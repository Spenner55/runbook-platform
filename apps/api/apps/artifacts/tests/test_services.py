import io

import pytest

from apps.artifacts import services as artifact_services
from apps.artifacts.models import Artifact
from apps.audit.models import AuditEvent
from apps.common.exceptions import DomainValidationError, PayloadTooLargeError


def _make_file(content: bytes, name: str = "stdout.txt"):
    f = io.BytesIO(content)
    f.name = name
    f.size = len(content)
    f.chunks = lambda: [content]
    return f


@pytest.mark.django_db
def test_create_from_runner_upload_success(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    content = b"step output\n"
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(content),
    )

    assert artifact.id is not None
    assert artifact.kind == "stdout"
    assert artifact.name == "stdout.txt"
    assert artifact.size_bytes == len(content)
    assert len(artifact.checksum_sha256) == 64
    assert artifact.upload_status == Artifact.UploadStatus.AVAILABLE
    assert "claim_token" not in artifact.storage_key
    assert str(org.id) in artifact.storage_key
    assert str(claimed_execution.id) in artifact.storage_key
    assert str(artifact.id) in artifact.storage_key


@pytest.mark.django_db
def test_create_uploads_file_to_storage(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    import os

    content = b"real bytes here\n"
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="out.txt",
        file_obj=_make_file(content),
    )

    from apps.artifacts.storage import ArtifactStorage

    storage = ArtifactStorage()
    assert storage.exists(artifact.storage_key)
    with storage.open(artifact.storage_key) as f:
        assert f.read() == content


@pytest.mark.django_db
def test_create_emits_audit_event(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    content = b"audit test\n"
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(content),
    )

    events = AuditEvent.objects.filter(event_type="artifact.uploaded", object_id=artifact.id)
    assert events.count() == 1
    event = events.first()
    assert event.actor_type == AuditEvent.ActorType.RUNNER
    assert "storage_key" not in event.metadata
    assert "claim_token" not in event.metadata
    assert event.metadata["kind"] == "stdout"


@pytest.mark.django_db
def test_create_rejects_wrong_runner_id(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    from apps.common.exceptions import InvalidStateTransitionError

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="wrong-runner",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"x"),
        )
    assert exc_info.value.code == "runner_ownership_mismatch"


@pytest.mark.django_db
def test_create_rejects_wrong_claim_token(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    from apps.common.exceptions import InvalidStateTransitionError

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token="00000000-0000-0000-0000-000000000000",
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"x"),
        )
    assert exc_info.value.code == "claim_token_mismatch"


@pytest.mark.django_db
def test_create_rejects_step_mismatch(
    org, claimed_execution, claim_token, artifact_media_root, published_workflow
):
    # Create a second execution and use its step with the first execution
    from apps.executions import services as exec_services

    second_execution = exec_services.create_execution(workflow=published_workflow)
    result2 = exec_services.claim_next_execution(runner_id="runner-2")
    second_step = result2["execution"].steps.first()

    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=second_step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"x"),
        )
    assert exc_info.value.code == "artifact_step_mismatch"


@pytest.mark.django_db
def test_create_rejects_invalid_kind(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="invalid-kind",
            name="stdout.txt",
            file_obj=_make_file(b"x"),
        )
    assert exc_info.value.code == "artifact_invalid_kind"


@pytest.mark.django_db
def test_create_rejects_oversize_file(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_MAX_UPLOAD_BYTES = 10
    big_content = b"x" * 11
    f = _make_file(big_content)

    with pytest.raises(PayloadTooLargeError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="big.txt",
            file_obj=f,
        )
    assert exc_info.value.code == "artifact_too_large"


@pytest.mark.django_db
def test_create_accepts_file_at_size_limit(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_MAX_UPLOAD_BYTES = 10
    content = b"x" * 10
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="limit.txt",
        file_obj=_make_file(content),
    )
    assert artifact.size_bytes == 10


@pytest.mark.django_db
def test_create_rejects_checksum_mismatch(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"hello"),
            declared_checksum_sha256="a" * 64,
        )
    assert exc_info.value.code == "checksum_mismatch"


@pytest.mark.django_db
def test_create_accepts_correct_checksum(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    import hashlib

    content = b"checksum test"
    expected = hashlib.sha256(content).hexdigest()
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(content),
        declared_checksum_sha256=expected,
    )
    assert artifact.checksum_sha256 == expected


@pytest.mark.django_db
def test_storage_key_contains_artifact_uuid(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(b"data"),
    )
    assert str(artifact.id) in artifact.storage_key


@pytest.mark.django_db
def test_sanitizes_unsafe_filename(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="file",
        name="../../../etc/passwd",
        file_obj=_make_file(b"evil"),
    )
    assert "/" not in artifact.name
    assert "\\" not in artifact.name
    assert ".." not in artifact.name


@pytest.mark.django_db
def test_list_for_execution(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(b"out"),
    )
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stderr",
        name="stderr.txt",
        file_obj=_make_file(b"err"),
    )

    total, artifacts = artifact_services.list_for_execution(execution=claimed_execution)
    assert total == 2
    kinds = {a.kind for a in artifacts}
    assert "stdout" in kinds
    assert "stderr" in kinds


@pytest.mark.django_db
def test_list_for_execution_filter_by_kind(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(b"out"),
    )
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stderr",
        name="stderr.txt",
        file_obj=_make_file(b"err"),
    )

    total, artifacts = artifact_services.list_for_execution(
        execution=claimed_execution, kind="stdout"
    )
    assert total == 1
    assert artifacts[0].kind == "stdout"


@pytest.mark.django_db
def test_create_download_url(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    artifact = artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(b"data"),
    )

    from apps.audit.services import AuditActor, AuditEvent

    actor = AuditActor(
        actor_type=AuditEvent.ActorType.UNKNOWN,
        actor_id="",
        actor_label="test-user",
    )
    result = artifact_services.create_download_url(artifact=artifact, actor=actor)

    assert "download_url" in result
    assert "expires_at" in result
    assert result["method"] == "GET"
    assert result["filename"] == "stdout.txt"
    assert "storage_key" not in result

    events = AuditEvent.objects.filter(event_type="artifact.download_url_created", object_id=artifact.id)
    assert events.count() == 1
    assert "expires_at" in events.first().metadata
    assert "download_url" not in events.first().metadata


@pytest.mark.django_db
def test_execution_quota_enforced(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION = 20
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="a.txt",
        file_obj=_make_file(b"x" * 15),
    )
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stderr",
            name="b.txt",
            file_obj=_make_file(b"x" * 10),
        )
    assert exc_info.value.code == "artifact_execution_quota_exceeded"
