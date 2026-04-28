"""
Artifact service layer.

All storage writes, quota checks, checksum computation, audit emission,
and download URL generation live here. Views and serializers delegate here.
"""

import hashlib
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models, transaction
from django.utils import timezone

from apps.artifacts.models import Artifact
from apps.artifacts.storage import ArtifactStorage
from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService
from apps.common.exceptions import DomainValidationError, ExternalDependencyError, PayloadTooLargeError
from apps.executions.models import Execution, ExecutionStep
from apps.executions.services import _validate_runner_ownership

_SAFE_FILENAME_RE = re.compile(r"[^\w.\-]")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_SAFE_NAME_LENGTH = 200


def _sanitize_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = name.replace(" ", "_")
    name = name.replace("/", "").replace("\\", "")
    name = name.lstrip(".")
    name = _SAFE_FILENAME_RE.sub("_", name)
    return (name or "artifact")[:_MAX_SAFE_NAME_LENGTH]


def _generate_storage_key(
    organization_id,
    execution_id,
    step_id,
    artifact_id,
    safe_name: str,
) -> str:
    step_segment = str(step_id) if step_id else "execution"
    return (
        f"artifacts/org/{organization_id}"
        f"/execution/{execution_id}"
        f"/step/{step_segment}"
        f"/artifact/{artifact_id}"
        f"/{safe_name}"
    )


def _compute_sha256(file_obj) -> str:
    h = hashlib.sha256()
    file_obj.seek(0)
    for chunk in file_obj.chunks():
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()


def _check_runner_daily_quota(runner_id: str, size_bytes: int) -> None:
    today = timezone.now().date().isoformat()
    cache_key = f"artifact_daily_bytes_{runner_id}_{today}"
    current = cache.get(cache_key, 0)
    limit = settings.ARTIFACT_DAILY_BYTES_PER_RUNNER
    if current + size_bytes > limit:
        raise DomainValidationError(
            code="artifact_runner_daily_quota_exceeded",
            detail=f"Upload would exceed runner daily quota of {limit} bytes.",
        )


def _increment_runner_daily_quota(runner_id: str, size_bytes: int) -> None:
    today = timezone.now().date().isoformat()
    cache_key = f"artifact_daily_bytes_{runner_id}_{today}"
    ttl = 48 * 3600
    try:
        cache.incr(cache_key, size_bytes)
    except ValueError:
        cache.set(cache_key, size_bytes, ttl)


def _check_execution_quota(execution: Execution, size_bytes: int) -> None:
    existing = (
        Artifact.objects.filter(
            execution=execution,
            upload_status=Artifact.UploadStatus.AVAILABLE,
        ).aggregate(total=models.Sum("size_bytes"))["total"]
        or 0
    )
    limit = settings.ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION
    if existing + size_bytes > limit:
        raise DomainValidationError(
            code="artifact_execution_quota_exceeded",
            detail=f"Upload would exceed per-execution quota of {limit} bytes.",
        )


def _check_step_artifact_count(step) -> None:
    if step is None:
        return
    count = Artifact.objects.filter(
        step=step, upload_status=Artifact.UploadStatus.AVAILABLE
    ).count()
    limit = settings.ARTIFACT_MAX_ARTIFACTS_PER_STEP
    if count >= limit:
        raise DomainValidationError(
            code="artifact_step_count_exceeded",
            detail=f"Step already has {limit} artifacts.",
        )


def _normalize_mime_type(kind: str, declared: str) -> str:
    if kind in ("stdout", "stderr"):
        return "text/plain; charset=utf-8"
    if kind == "report":
        return declared or "application/json"
    return declared or "application/octet-stream"


def create_from_runner_upload(
    *,
    execution: Execution,
    step,
    runner_id: str,
    claim_token: str,
    kind: str,
    name: str,
    file_obj,
    declared_mime_type: str = "",
    declared_checksum_sha256: str = "",
    metadata: dict | None = None,
) -> Artifact:
    """
    Canonical upload sequence (§5.6):
      1. Validate inputs (fail fast, no I/O)
      2. Write to storage
      3. Create DB row in transaction; on DB failure attempt storage delete
    """
    _validate_runner_ownership(execution, runner_id, claim_token)

    if step is not None and str(step.execution_id) != str(execution.id):
        raise DomainValidationError(
            code="artifact_step_mismatch",
            detail="Step does not belong to the given execution.",
        )

    if kind not in Artifact.Kind.values:
        raise DomainValidationError(
            code="artifact_invalid_kind",
            detail=f"Invalid kind '{kind}'. Allowed: {', '.join(Artifact.Kind.values)}.",
        )

    if file_obj is None:
        raise DomainValidationError(
            code="artifact_file_required",
            detail="No file was provided.",
        )

    size_bytes = file_obj.size
    if size_bytes > settings.ARTIFACT_MAX_UPLOAD_BYTES:
        raise PayloadTooLargeError(
            code="artifact_too_large",
            detail=(
                f"File size {size_bytes} bytes exceeds maximum "
                f"{settings.ARTIFACT_MAX_UPLOAD_BYTES} bytes."
            ),
        )

    _check_runner_daily_quota(runner_id, size_bytes)
    _check_execution_quota(execution, size_bytes)
    _check_step_artifact_count(step)

    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise DomainValidationError(
            code="artifact_invalid_metadata",
            detail="Metadata must be a JSON object.",
        )

    safe_name = _sanitize_filename(name) or f"{kind}.bin"
    mime_type = _normalize_mime_type(kind, declared_mime_type)

    artifact_id = uuid.uuid4()
    storage_key = _generate_storage_key(
        organization_id=execution.organization_id,
        execution_id=execution.id,
        step_id=step.id if step else None,
        artifact_id=artifact_id,
        safe_name=safe_name,
    )

    computed_checksum = _compute_sha256(file_obj)

    if declared_checksum_sha256:
        if not _CHECKSUM_RE.match(declared_checksum_sha256):
            raise DomainValidationError(
                code="artifact_invalid_checksum",
                detail="checksum_sha256 must be exactly 64 lowercase hex characters.",
            )
        if declared_checksum_sha256 != computed_checksum:
            raise DomainValidationError(
                code="checksum_mismatch",
                detail="Provided checksum_sha256 does not match computed checksum.",
            )

    storage = ArtifactStorage()
    try:
        storage.save(storage_key, file_obj)
    except Exception as exc:
        raise ExternalDependencyError(
            code="artifact_storage_failed",
            detail="Failed to write artifact to storage.",
        ) from exc

    now = timezone.now()
    try:
        with transaction.atomic():
            artifact = Artifact.objects.create(
                id=artifact_id,
                organization=execution.organization,
                execution=execution,
                step=step,
                kind=kind,
                name=safe_name,
                original_name=name[:255],
                mime_type=mime_type,
                size_bytes=size_bytes,
                checksum_sha256=computed_checksum,
                storage_key=storage_key,
                uploaded_by_runner_id=runner_id,
                upload_status=Artifact.UploadStatus.AVAILABLE,
                uploaded_at=now,
                content_disposition=Artifact.ContentDisposition.ATTACHMENT,
                metadata=metadata,
            )
    except Exception:
        try:
            storage.delete(storage_key)
        except Exception:
            pass
        raise

    try:
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=AuditEvent.ActorType.RUNNER,
            actor_id=runner_id,
            actor_label=runner_id,
            event_type="artifact.uploaded",
            object_type=AuditEvent.ObjectType.ARTIFACT,
            object_id=artifact.id,
            metadata={
                "execution_id": str(execution.id),
                "step_id": str(step.id) if step else None,
                "kind": kind,
                "name": safe_name,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "checksum_sha256": computed_checksum,
            },
        )
    except Exception:
        pass

    _increment_runner_daily_quota(runner_id, size_bytes)

    return artifact


def list_for_execution(
    *,
    execution: Execution,
    step_id=None,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list]:
    qs = Artifact.objects.filter(
        execution=execution,
        upload_status=Artifact.UploadStatus.AVAILABLE,
    )
    if step_id is not None:
        qs = qs.filter(step_id=step_id)
    if kind is not None:
        qs = qs.filter(kind=kind)
    total = qs.count()
    return total, list(qs[offset : offset + limit])


def create_download_url(*, artifact: Artifact, actor: AuditActor) -> dict:
    """
    Emit an audit event and return a time-limited download descriptor.

    Local dev returns a URL pointing to the Django streaming endpoint.
    Production S3 would return a presigned URL here.
    """
    ttl = settings.ARTIFACT_DOWNLOAD_URL_TTL_SECONDS
    now = timezone.now()
    expires_at = now + timedelta(seconds=ttl)

    download_url = f"/api/v1/artifacts/{artifact.id}/content/"

    try:
        AuditService.emit(
            organization_id=artifact.organization_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            actor_label=actor.actor_label,
            event_type="artifact.download_url_created",
            object_type=AuditEvent.ObjectType.ARTIFACT,
            object_id=artifact.id,
            metadata={
                "execution_id": str(artifact.execution_id),
                "step_id": str(artifact.step_id) if artifact.step_id else None,
                "artifact_id": str(artifact.id),
                "kind": artifact.kind,
                "name": artifact.name,
                "expires_at": expires_at.isoformat(),
            },
        )
    except Exception:
        pass

    return {
        "artifact_id": str(artifact.id),
        "download_url": download_url,
        "expires_at": expires_at.isoformat(),
        "method": "GET",
        "content_disposition": artifact.content_disposition,
        "filename": artifact.name,
    }
