import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.artifacts.models import Artifact


@pytest.mark.django_db
def test_artifact_inherits_uuid_pk(org, claimed_execution, step):
    artifact = Artifact.objects.create(
        organization=org,
        execution=claimed_execution,
        step=step,
        kind=Artifact.Kind.STDOUT,
        name="stdout.txt",
        mime_type="text/plain; charset=utf-8",
        size_bytes=42,
        checksum_sha256="a" * 64,
        storage_key=f"artifacts/org/{org.id}/execution/{claimed_execution.id}/step/{step.id}/artifact/test-uuid/stdout.txt",
        uploaded_by_runner_id="runner-test",
        uploaded_at=timezone.now(),
    )
    assert artifact.pk is not None
    assert len(str(artifact.pk)) == 36


@pytest.mark.django_db
def test_artifact_kind_choices():
    assert "stdout" in Artifact.Kind.values
    assert "stderr" in Artifact.Kind.values
    assert "file" in Artifact.Kind.values
    assert "report" in Artifact.Kind.values
    assert "diagnostic" in Artifact.Kind.values


@pytest.mark.django_db
def test_artifact_storage_key_unique(org, claimed_execution, step):
    key = f"artifacts/org/{org.id}/execution/{claimed_execution.id}/step/{step.id}/artifact/dup/stdout.txt"
    Artifact.objects.create(
        organization=org,
        execution=claimed_execution,
        step=step,
        kind=Artifact.Kind.STDOUT,
        name="stdout.txt",
        mime_type="text/plain; charset=utf-8",
        size_bytes=42,
        checksum_sha256="a" * 64,
        storage_key=key,
        uploaded_by_runner_id="runner-test",
        uploaded_at=timezone.now(),
    )
    with pytest.raises(IntegrityError):
        Artifact.objects.create(
            organization=org,
            execution=claimed_execution,
            step=step,
            kind=Artifact.Kind.STDOUT,
            name="stdout.txt",
            mime_type="text/plain; charset=utf-8",
            size_bytes=42,
            checksum_sha256="b" * 64,
            storage_key=key,
            uploaded_by_runner_id="runner-test",
            uploaded_at=timezone.now(),
        )


@pytest.mark.django_db
def test_artifact_str(org, claimed_execution, step):
    artifact = Artifact.objects.create(
        organization=org,
        execution=claimed_execution,
        step=step,
        kind=Artifact.Kind.STDERR,
        name="stderr.txt",
        mime_type="text/plain; charset=utf-8",
        size_bytes=10,
        checksum_sha256="c" * 64,
        storage_key=f"artifacts/org/{org.id}/execution/{claimed_execution.id}/step/{step.id}/artifact/str-test/stderr.txt",
        uploaded_by_runner_id="runner-test",
        uploaded_at=timezone.now(),
    )
    assert "stderr.txt" in str(artifact)
    assert "stderr" in str(artifact)


def test_artifact_has_no_db_file_bytes_field():
    field_names = {f.name for f in Artifact._meta.get_fields()}
    assert "content" not in field_names
    assert "file_content" not in field_names
    assert "file_bytes" not in field_names
    assert "storage_key" in field_names
    assert "checksum_sha256" in field_names
