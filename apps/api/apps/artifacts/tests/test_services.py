import io
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.artifacts import services as artifact_services
from apps.artifacts.models import Artifact
from apps.artifacts.storage import ArtifactStorage
from apps.audit.models import AuditEvent
from apps.common.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    PayloadTooLargeError,
)


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

    events = AuditEvent.objects.filter(
        event_type="artifact.uploaded", object_id=artifact.id
    )
    assert events.count() == 1
    event = events.first()
    assert event.actor_type == AuditEvent.ActorType.RUNNER
    assert "storage_key" not in event.metadata
    assert "claim_token" not in event.metadata
    assert event.metadata["kind"] == "stdout"


@pytest.mark.django_db
def test_create_from_runner_upload_triggers_notify(
    org,
    claimed_execution,
    claim_token,
    step,
    artifact_media_root,
    django_capture_on_commit_callbacks,
):
    with patch("apps.artifacts.services.IntegrationService.notify") as notify:
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            artifact = artifact_services.create_from_runner_upload(
                execution=claimed_execution,
                step=step,
                runner_id="runner-test",
                claim_token=claim_token,
                kind="stdout",
                name="stdout.txt",
                file_obj=_make_file(b"artifact notify\n"),
            )

    assert len(callbacks) == 1
    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["event_type"] == "artifact.uploaded"
    assert kwargs["organization"] == artifact.organization
    assert kwargs["context"]["event_type"] == "artifact.uploaded"
    assert kwargs["context"]["artifact_id"] == str(artifact.id)
    assert kwargs["context"]["execution_id"] == str(claimed_execution.id)
    assert kwargs["context"]["step_id"] == str(step.id)


@pytest.mark.django_db
def test_notify_failure_does_not_fail_artifact_upload(
    org,
    claimed_execution,
    claim_token,
    step,
    artifact_media_root,
    django_capture_on_commit_callbacks,
):
    with patch(
        "apps.artifacts.services.IntegrationService.notify",
        side_effect=RuntimeError("dispatch unavailable"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            artifact = artifact_services.create_from_runner_upload(
                execution=claimed_execution,
                step=step,
                runner_id="runner-test",
                claim_token=claim_token,
                kind="stdout",
                name="stdout.txt",
                file_obj=_make_file(b"artifact notify failure\n"),
            )

    artifact.refresh_from_db()
    assert artifact.upload_status == Artifact.UploadStatus.AVAILABLE


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

    exec_services.create_execution(workflow=published_workflow)
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
def test_create_requires_checksum_when_setting_enabled(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_REQUIRE_CHECKSUM = True
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"data"),
        )
    assert exc_info.value.code == "artifact_checksum_required"


@pytest.mark.django_db
def test_create_rejects_disallowed_mime_type(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_ALLOWED_MIME_TYPES = ["application/json"]
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="file",
            name="output.txt",
            declared_mime_type="text/plain",
            file_obj=_make_file(b"data"),
        )
    assert exc_info.value.code == "artifact_mime_type_not_allowed"


@pytest.mark.django_db
def test_create_rejects_oversize_metadata(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_MAX_METADATA_BYTES = 10
    with pytest.raises(PayloadTooLargeError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"data"),
            metadata={"message": "too large"},
        )
    assert exc_info.value.code == "artifact_metadata_too_large"


@pytest.mark.django_db
def test_create_rejects_terminal_execution(
    org, claimed_execution, claim_token, step, artifact_media_root
):
    claimed_execution.status = "succeeded"
    claimed_execution.save(update_fields=["status"])

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"data"),
        )
    assert exc_info.value.code == "artifact_execution_terminal"


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

    events = AuditEvent.objects.filter(
        event_type="artifact.download_url_created", object_id=artifact.id
    )
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


@pytest.mark.django_db
def test_runner_daily_quota_enforced(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_DAILY_BYTES_PER_RUNNER = 5
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="a.txt",
        file_obj=_make_file(b"12345"),
    )
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stderr",
            name="b.txt",
            file_obj=_make_file(b"1"),
        )
    assert exc_info.value.code == "artifact_runner_daily_quota_exceeded"


@pytest.mark.django_db
def test_step_artifact_count_enforced(
    org, claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_MAX_ARTIFACTS_PER_STEP = 1
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="a.txt",
        file_obj=_make_file(b"a"),
    )
    with pytest.raises(DomainValidationError) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stderr",
            name="b.txt",
            file_obj=_make_file(b"b"),
        )
    assert exc_info.value.code == "artifact_step_count_exceeded"


@pytest.mark.django_db
def test_audit_failure_rolls_back_upload_and_deletes_storage(
    org, claimed_execution, claim_token, step, artifact_media_root, monkeypatch
):
    before = Artifact.objects.count()

    def fail_emit(**kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr(artifact_services.AuditService, "emit", fail_emit)

    with pytest.raises(RuntimeError):
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"data"),
        )

    assert Artifact.objects.count() == before
    assert not list(Path(artifact_media_root).rglob("*.*"))


@pytest.mark.django_db
def test_storage_write_failure_does_not_create_artifact(
    org, claimed_execution, claim_token, step, artifact_media_root, monkeypatch
):
    before = Artifact.objects.count()

    def fail_save(self, storage_key, file_obj):
        raise OSError("storage down")

    monkeypatch.setattr(ArtifactStorage, "save", fail_save)

    with pytest.raises(Exception) as exc_info:
        artifact_services.create_from_runner_upload(
            execution=claimed_execution,
            step=step,
            runner_id="runner-test",
            claim_token=claim_token,
            kind="stdout",
            name="stdout.txt",
            file_obj=_make_file(b"data"),
        )

    assert exc_info.value.code == "artifact_storage_failed"
    assert Artifact.objects.count() == before


def test_storage_rejects_path_escape(artifact_media_root):
    storage = ArtifactStorage()
    with pytest.raises(Exception):
        storage.local_path("../outside.txt")
