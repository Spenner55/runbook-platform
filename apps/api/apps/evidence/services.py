import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.core.exceptions import (
    ObjectDoesNotExist,
    SuspiciousFileOperation,
    ValidationError,
)
from django.db import transaction
from django.db.models import Max, Q
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.changes.models import (
    ChangeClosure,
    ChangeRecord,
    VerificationResult,
)
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.evidence import selectors
from apps.evidence.models import (
    EvidenceBundle,
    EvidenceBundleItem,
    EvidenceExport,
    EvidenceRedactionPolicy,
    EvidenceRetentionPolicy,
    LegalHold,
)
from apps.evidence.storage import EvidenceStorage


def assert_bundle_mutable(bundle) -> None:
    if bundle.has_sealed_content:
        raise ValidationError(
            "Sealed evidence bundles are immutable.",
            code="evidence_bundle_immutable",
        )


SCHEMA_VERSION = "1"
ZIP_FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_EXTERNAL_ATTR = 0o100644 << 16
ZIP_COMPRESSION = zipfile.ZIP_STORED
DOWNLOAD_TOKEN_SALT = "evidence.bundle.download"

CANONICAL_REQUIRED_PATHS = {
    "change/change_record.json": EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
    "change/targets.json": EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
    "controls/approvals.json": EvidenceBundleItem.ItemType.APPROVAL,
    "controls/policy_decisions.json": EvidenceBundleItem.ItemType.POLICY_DECISION,
    "execution/execution.json": EvidenceBundleItem.ItemType.EXECUTION,
    "verification/plan.json": EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
    "verification/results.json": EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
    "audit/audit_trail.ndjson": EvidenceBundleItem.ItemType.AUDIT_EVENT,
    "artifacts/index.json": EvidenceBundleItem.ItemType.ARTIFACT,
    "exceptions/exceptions.json": EvidenceBundleItem.ItemType.EXCEPTION,
    "exports/export_receipt.json": EvidenceBundleItem.ItemType.EXPORT_RECEIPT,
}


@dataclass(frozen=True)
class _Section:
    item_type: str
    item_key: str
    canonical_path: str
    payload: dict | list
    required: bool = True
    present: bool = True
    valid: bool = True
    missing_reason: str = ""
    validation_errors: tuple[dict, ...] = ()
    source_type: str = ""
    source_id: str = ""
    source_updated_at: datetime | None = None
    source_metadata: dict | None = None


@dataclass(frozen=True)
class _PackageEntry:
    path: str
    content: bytes
    media_type: str
    item_type: str
    item_key: str = ""
    required: bool = True
    source_refs: tuple[dict, ...] = ()


def create_evidence_bundle_for_change(
    *,
    change_record,
    created_by=None,
    actor: AuditActor | None = None,
) -> EvidenceBundle:
    """Materialize a deterministic evidence bundle projection for a closed change."""

    with transaction.atomic():
        change = (
            ChangeRecord.objects.select_for_update()
            .select_related("operation_profile", "workflow")
            .get(pk=change_record.pk)
        )
        if change.status != ChangeRecord.Status.CLOSED:
            raise ValidationError(
                "Evidence bundles can only be materialized for closed changes.",
                code="evidence_change_not_closed",
            )

        compiled_at = timezone.now()
        source_cutoff_at = compiled_at
        latest_version = (
            EvidenceBundle.objects.select_for_update()
            .filter(change_record=change)
            .aggregate(max_version=Max("version"))["max_version"]
            or 0
        )
        previous_bundle = (
            EvidenceBundle.objects.filter(change_record=change)
            .order_by("-version", "-created_at")
            .first()
        )
        bundle = EvidenceBundle.objects.create(
            organization=change.organization,
            change_record=change,
            version=latest_version + 1,
            status=EvidenceBundle.Status.COMPILING,
            completeness_status=EvidenceBundle.CompletenessStatus.INCOMPLETE,
            source_cutoff_at=source_cutoff_at,
            compiled_at=compiled_at,
            previous_bundle=previous_bundle,
            created_by=created_by,
        )

        _materialize_items(bundle=bundle, change=change)

        bundle.refresh_from_db()
        _emit_bundle_materialized(bundle=bundle, actor=actor)
        return bundle


def materialize_evidence_bundle(*args, **kwargs) -> EvidenceBundle:
    return create_evidence_bundle_for_change(*args, **kwargs)


def create_evidence_bundle(*args, **kwargs) -> EvidenceBundle:
    return create_evidence_bundle_for_change(*args, **kwargs)


def seal_bundle(
    bundle: EvidenceBundle,
    actor: AuditActor | None = None,
    *,
    sealed_by=None,
    storage: EvidenceStorage | None = None,
) -> EvidenceBundle:
    """Seal a complete evidence bundle into an immutable deterministic ZIP."""

    storage = storage or EvidenceStorage()
    storage_key = ""
    wrote_storage = False
    try:
        with transaction.atomic():
            locked_bundle = (
                EvidenceBundle.objects.select_for_update()
                .select_related("change_record", "organization")
                .get(pk=bundle.pk)
            )
            list(
                EvidenceBundleItem.objects.select_for_update().filter(
                    bundle=locked_bundle
                )
            )
            if locked_bundle.status != EvidenceBundle.Status.COMPILING:
                raise DomainValidationError(
                    code="evidence_bundle_not_compiling",
                    detail="Only compiling evidence bundles can be sealed.",
                )
            if (
                locked_bundle.completeness_status
                != EvidenceBundle.CompletenessStatus.COMPLETE
            ):
                raise DomainValidationError(
                    code="evidence_bundle_not_complete",
                    detail="Only complete evidence bundles can be sealed.",
                )
            _assert_no_missing_or_invalid_items(locked_bundle)

            locked_bundle.sealed_at = timezone.now()
            locked_bundle.sealed_by = sealed_by
            locked_bundle.save(update_fields=["sealed_at", "sealed_by", "updated_at"])

            package = build_sealed_bundle_package(locked_bundle, storage=storage)
            storage_key = _sealed_bundle_storage_key(locked_bundle)
            storage.save_bytes(storage_key, package["zip_bytes"])
            wrote_storage = True

            retention_policy = _resolve_default_retention_policy(
                locked_bundle.organization
            )
            retention_expires_at = None
            if retention_policy is not None:
                retention_expires_at = locked_bundle.sealed_at + timedelta(
                    days=retention_policy.sealed_bundle_retention_days
                )

            locked_bundle.manifest = _normalize(package["manifest"])
            locked_bundle.manifest_sha256 = package["manifest_sha256"]
            locked_bundle.payload_checksums_sha256 = package["payload_checksums_sha256"]
            locked_bundle.content_sha256 = package["content_sha256"]
            locked_bundle.content_size_bytes = package["content_size_bytes"]
            locked_bundle.storage_key = storage_key
            locked_bundle.mime_type = "application/zip"
            locked_bundle.status = EvidenceBundle.Status.SEALED
            if retention_policy is not None:
                locked_bundle.retention_policy = retention_policy
                locked_bundle.retention_expires_at = retention_expires_at
            locked_bundle.save(
                update_fields=[
                    "manifest",
                    "manifest_sha256",
                    "payload_checksums_sha256",
                    "content_sha256",
                    "content_size_bytes",
                    "storage_key",
                    "mime_type",
                    "status",
                    "retention_policy",
                    "retention_expires_at",
                    "updated_at",
                ]
            )

            transaction.on_commit(
                lambda: _emit_bundle_sealed(bundle_id=locked_bundle.id, actor=actor)
            )
            return locked_bundle
    except Exception as exc:
        if wrote_storage and storage_key:
            storage.delete(storage_key)
        if isinstance(exc, DomainValidationError) and exc.code in {
            "artifact_storage_missing",
            "artifact_checksum_mismatch",
        }:
            invalidated = invalidate_bundle(
                bundle,
                reason=exc.code,
                actor=actor,
                invalidated_by=sealed_by,
            )
            invalidated.completeness_status = EvidenceBundle.CompletenessStatus.INVALID
            invalidated.save(update_fields=["completeness_status", "updated_at"])
        raise


def seal_evidence_bundle(*args, **kwargs) -> EvidenceBundle:
    return seal_bundle(*args, **kwargs)


def invalidate_bundle(
    bundle: EvidenceBundle,
    *,
    reason: str,
    actor: AuditActor | None = None,
    invalidated_by=None,
) -> EvidenceBundle:
    """Invalidate a compiling or sealed bundle without rewriting sealed bytes."""

    if not reason:
        raise DomainValidationError(
            code="evidence_invalidation_reason_required",
            detail="Invalidation reason is required.",
        )

    with transaction.atomic():
        locked_bundle = EvidenceBundle.objects.select_for_update().get(pk=bundle.pk)
        if locked_bundle.status == EvidenceBundle.Status.INVALIDATED:
            return locked_bundle
        if locked_bundle.status not in [
            EvidenceBundle.Status.COMPILING,
            EvidenceBundle.Status.SEALED,
        ]:
            raise DomainValidationError(
                code="invalid_evidence_bundle_transition",
                detail="Evidence bundle status cannot be invalidated.",
            )
        previous_status = locked_bundle.status
        locked_bundle.status = EvidenceBundle.Status.INVALIDATED
        locked_bundle.invalidated_at = timezone.now()
        locked_bundle.invalidation_reason = reason[:128]
        locked_bundle.invalidated_by = invalidated_by
        locked_bundle.save(
            update_fields=[
                "status",
                "invalidated_at",
                "invalidation_reason",
                "invalidated_by",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda: _emit_bundle_invalidated(
                bundle_id=locked_bundle.id,
                previous_status=previous_status,
                actor=actor,
            )
        )
        return locked_bundle


def create_bundle_download_url(
    *,
    bundle: EvidenceBundle,
    actor: AuditActor,
    storage: EvidenceStorage | None = None,
) -> dict:
    """Return a time-limited local download descriptor for a sealed bundle."""

    storage = storage or EvidenceStorage()
    bundle = EvidenceBundle.objects.get(pk=bundle.pk)
    if bundle.status != EvidenceBundle.Status.SEALED:
        raise DomainValidationError(
            code="evidence_bundle_not_sealed",
            detail="Only sealed evidence bundles can be downloaded.",
        )
    if bundle.storage_deleted_at is not None or not bundle.storage_key:
        raise DomainValidationError(
            code="evidence_bundle_storage_missing",
            detail="Evidence bundle storage is not available.",
        )
    if not storage.exists(bundle.storage_key):
        raise DomainValidationError(
            code="evidence_bundle_storage_missing",
            detail="Evidence bundle storage is not available.",
        )

    ttl = settings.ARTIFACT_DOWNLOAD_URL_TTL_SECONDS
    expires_at = timezone.now() + timedelta(seconds=ttl)
    token = create_bundle_download_token(bundle=bundle, expires_at=expires_at)
    query = urlencode({"organization_id": str(bundle.organization_id), "token": token})
    download_url = f"/api/v1/evidence-bundles/{bundle.id}/content/?{query}"
    filename = f"evidence-bundle-{bundle.change_record_id}-v{bundle.version}.zip"

    AuditService.emit(
        organization_id=bundle.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_bundle.downloaded",
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        metadata={
            "change_record_id": str(bundle.change_record_id),
            "version": bundle.version,
            "manifest_sha256": bundle.manifest_sha256,
            "content_sha256": bundle.content_sha256,
            "content_size_bytes": bundle.content_size_bytes,
            "expires_at": expires_at.isoformat(),
        },
    )

    return {
        "bundle_id": str(bundle.id),
        "download_url": download_url,
        "expires_at": expires_at.isoformat(),
        "method": "GET",
        "content_disposition": "attachment",
        "filename": filename,
        "content_sha256": bundle.content_sha256,
        "content_size_bytes": bundle.content_size_bytes,
    }


def create_bundle_download_token(*, bundle: EvidenceBundle, expires_at) -> str:
    return signing.dumps(
        {
            "bundle_id": str(bundle.id),
            "organization_id": str(bundle.organization_id),
            "expires_at": expires_at.isoformat(),
            "content_sha256": bundle.content_sha256,
        },
        salt=DOWNLOAD_TOKEN_SALT,
    )


def validate_bundle_download_token(*, bundle: EvidenceBundle, token: str) -> None:
    try:
        payload = signing.loads(token, salt=DOWNLOAD_TOKEN_SALT)
    except signing.BadSignature as exc:
        raise DomainValidationError(
            code="evidence_bundle_download_token_invalid",
            detail="Evidence bundle download token is invalid.",
        ) from exc

    if payload.get("bundle_id") != str(bundle.id) or payload.get(
        "organization_id"
    ) != str(bundle.organization_id):
        raise DomainValidationError(
            code="evidence_bundle_download_token_invalid",
            detail="Evidence bundle download token does not match this bundle.",
        )
    if payload.get("content_sha256") != bundle.content_sha256:
        raise DomainValidationError(
            code="evidence_bundle_download_token_invalid",
            detail="Evidence bundle download token does not match current content.",
        )

    expires_at_raw = payload.get("expires_at")
    try:
        expires_at = timezone.datetime.fromisoformat(expires_at_raw)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(
            code="evidence_bundle_download_token_invalid",
            detail="Evidence bundle download token expiry is invalid.",
        ) from exc
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, UTC)
    if expires_at <= timezone.now():
        raise DomainValidationError(
            code="evidence_bundle_download_token_expired",
            detail="Evidence bundle download token has expired.",
        )


def build_sealed_bundle_package(
    bundle: EvidenceBundle,
    *,
    storage: EvidenceStorage | None = None,
) -> dict:
    """Build deterministic sealed bundle bytes without writing storage or status."""

    storage = storage or EvidenceStorage()
    bundle = EvidenceBundle.objects.select_related("change_record", "organization").get(
        pk=bundle.pk
    )
    if bundle.sealed_at is None:
        raise DomainValidationError(
            code="evidence_bundle_sealed_at_required",
            detail="sealed_at must be persisted before package generation.",
        )

    payload_entries = _payload_entries_for_bundle(bundle, storage=storage)
    bundle = _refresh_bundle_source_snapshot_from_items(bundle)
    manifest = _manifest_for_bundle(bundle, payload_entries)
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha256 = sha256_hexdigest(manifest_bytes)

    entries_by_path = {entry.path: entry.content for entry in payload_entries}
    entries_by_path["manifest.json"] = manifest_bytes
    checksums_bytes = canonical_checksums_bytes(entries_by_path)
    entries_by_path["checksums.sha256"] = checksums_bytes

    payload_checksums_bytes = canonical_checksums_bytes(
        {entry.path: entry.content for entry in payload_entries}
    )
    payload_checksums_sha256 = sha256_hexdigest(payload_checksums_bytes)
    zip_bytes = deterministic_zip_bytes(entries_by_path)
    content_sha256 = sha256_hexdigest(zip_bytes)

    return {
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_sha256": manifest_sha256,
        "checksums_bytes": checksums_bytes,
        "payload_checksums_sha256": payload_checksums_sha256,
        "zip_bytes": zip_bytes,
        "content_sha256": content_sha256,
        "content_size_bytes": len(zip_bytes),
    }


def canonical_checksums_bytes(entries_by_path: dict[str, bytes]) -> bytes:
    lines = []
    for path in sorted(entries_by_path):
        if path == "checksums.sha256":
            continue
        _validate_zip_path(path)
        lines.append(f"{sha256_hexdigest(entries_by_path[path])}  {path}")
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def deterministic_zip_bytes(entries_by_path: dict[str, bytes]) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(
        archive,
        "w",
        compression=ZIP_COMPRESSION,
        allowZip64=True,
        strict_timestamps=True,
    ) as zip_file:
        zip_file.comment = b""
        for path in sorted(entries_by_path):
            _validate_zip_path(path)
            info = zipfile.ZipInfo(path, date_time=ZIP_FIXED_DATE_TIME)
            info.compress_type = ZIP_COMPRESSION
            info.create_system = 3
            info.external_attr = ZIP_FILE_EXTERNAL_ATTR
            zip_file.writestr(info, entries_by_path[path])
    return archive.getvalue()


def _assert_no_missing_or_invalid_items(bundle: EvidenceBundle) -> None:
    missing_required = bundle.items.filter(required=True, present=False).exists()
    invalid_items = bundle.items.filter(valid=False).exists()
    if missing_required:
        raise DomainValidationError(
            code="evidence_bundle_missing_required_items",
            detail="Evidence bundle has missing required items.",
        )
    if invalid_items:
        raise DomainValidationError(
            code="evidence_bundle_invalid_items",
            detail="Evidence bundle has invalid items.",
        )


def _payload_entries_for_bundle(
    bundle: EvidenceBundle,
    *,
    storage: EvidenceStorage,
) -> list[_PackageEntry]:
    sections = _source_sections_for_bundle(bundle)
    entries_by_path: dict[str, _PackageEntry] = {}

    for section in sections:
        content = (
            canonical_ndjson_bytes(section.payload)
            if section.canonical_path.endswith(".ndjson")
            else canonical_json_bytes(section.payload)
        )
        item = (
            EvidenceBundleItem.objects.filter(
                bundle=bundle,
                item_type=section.item_type,
                item_key=section.item_key,
            )
            .order_by("position", "id")
            .first()
        )
        if item is not None:
            _sync_compiling_item_content(item, content)
        entries_by_path[section.canonical_path] = _PackageEntry(
            path=section.canonical_path,
            content=content,
            media_type="application/x-ndjson"
            if section.canonical_path.endswith(".ndjson")
            else "application/json",
            item_type=section.item_type,
            item_key=section.item_key,
            required=section.required,
            source_refs=_source_refs_for_path(bundle, section.canonical_path),
        )

    for path, item_type in CANONICAL_REQUIRED_PATHS.items():
        if path not in entries_by_path:
            content = b"" if path.endswith(".ndjson") else canonical_json_bytes({})
            entries_by_path[path] = _PackageEntry(
                path=path,
                content=content,
                media_type="application/x-ndjson"
                if path.endswith(".ndjson")
                else "application/json",
                item_type=item_type,
                required=True,
                source_refs=_source_refs_for_path(bundle, path),
            )

    artifact_items = (
        EvidenceBundleItem.objects.select_related("artifact")
        .filter(bundle=bundle, item_type=EvidenceBundleItem.ItemType.ARTIFACT)
        .exclude(artifact__isnull=True)
        .order_by("canonical_path", "item_key", "id")
    )
    for item in artifact_items:
        if item.canonical_path == "artifacts/index.json":
            continue
        artifact = item.artifact
        if not storage.exists(artifact.storage_key):
            _invalidate_for_artifact_defect(
                bundle,
                reason="artifact_storage_missing",
                detail=f"Artifact storage bytes are missing for {artifact.id}.",
            )
        artifact_bytes = storage.read_bytes(artifact.storage_key)
        artifact_sha256 = sha256_hexdigest(artifact_bytes)
        if artifact_sha256 != artifact.checksum_sha256:
            _invalidate_for_artifact_defect(
                bundle,
                reason="artifact_checksum_mismatch",
                detail=f"Artifact checksum mismatch for {artifact.id}.",
            )
        _sync_compiling_item_content(item, artifact_bytes)
        entries_by_path[item.canonical_path] = _PackageEntry(
            path=item.canonical_path,
            content=artifact_bytes,
            media_type=item.mime_type or artifact.mime_type,
            item_type=item.item_type,
            item_key=item.item_key,
            required=item.required,
            source_refs=_source_refs_for_item(item),
        )

    return [entries_by_path[path] for path in sorted(entries_by_path)]


def _source_sections_for_bundle(bundle: EvidenceBundle) -> list[_Section]:
    change = ChangeRecord.objects.select_related("operation_profile", "workflow").get(
        pk=bundle.change_record_id
    )
    targets = list(selectors.change_targets_for_bundle(change))
    verification_plan = selectors.verification_plan_for_bundle(change)
    verification_checks = list(selectors.verification_checks_for_bundle(change))
    verification_results = list(selectors.verification_results_for_bundle(change))
    closure = selectors.closure_for_bundle(change)
    exceptions = list(selectors.exceptions_for_bundle(change))
    breakglass_sessions = list(selectors.breakglass_sessions_for_bundle(change))
    retro_reviews = list(selectors.retro_reviews_for_bundle(change))
    execution_binding = selectors.execution_binding_for_bundle(change)
    execution = execution_binding.execution if execution_binding is not None else None
    execution_steps = (
        list(execution.steps.order_by("position", "created_at", "id"))
        if execution is not None
        else []
    )
    approvals = list(
        selectors.approval_requests_for_bundle(
            change,
            exceptions=exceptions,
            execution=execution,
        )
    )
    policy_evaluations = list(
        selectors.policy_evaluations_for_bundle(
            change,
            exceptions=exceptions,
            execution=execution,
        )
    )
    artifacts = list(
        selectors.artifacts_for_bundle(
            change,
            execution=execution,
            verification_results=verification_results,
            exceptions=exceptions,
        )
    )
    related_object_ids = _related_object_ids(
        change=change,
        targets=targets,
        execution_binding=execution_binding,
        execution=execution,
        execution_steps=execution_steps,
        approvals=approvals,
        policy_evaluations=policy_evaluations,
        verification_plan=verification_plan,
        verification_checks=verification_checks,
        verification_results=verification_results,
        closure=closure,
        exceptions=exceptions,
        breakglass_sessions=breakglass_sessions,
        retro_reviews=retro_reviews,
        artifacts=artifacts,
    )
    audit_events = list(
        selectors.audit_events_for_bundle(
            change,
            related_object_ids=related_object_ids,
            source_cutoff_at=bundle.source_cutoff_at,
        )
    )

    sections = [
        _change_snapshot_section(bundle, change, targets),
        _targets_section(bundle, change, targets),
        _approvals_section(bundle, change, approvals),
        _policy_decisions_section(bundle, change, policy_evaluations),
        _execution_section(
            bundle, change, execution_binding, execution, execution_steps
        ),
        _audit_section(bundle, change, audit_events),
        _artifacts_section(bundle, change, artifacts),
        _verification_plan_section(
            bundle,
            change,
            verification_plan,
            verification_checks,
        ),
        _verification_results_section(
            bundle,
            change,
            verification_plan,
            verification_checks,
            verification_results,
        ),
        _closure_section(bundle, change, closure),
        _exceptions_section(
            bundle,
            change,
            exceptions,
            breakglass_sessions,
            retro_reviews,
            force=True,
        ),
        _export_receipt_section(bundle, change),
    ]
    external_reference_section = _external_references_section(
        bundle,
        change,
        verification_results,
        verification_checks,
        retro_reviews,
    )
    if external_reference_section is not None:
        sections.append(external_reference_section)
    return sections


def _manifest_for_bundle(
    bundle: EvidenceBundle,
    payload_entries: list[_PackageEntry],
) -> dict:
    entries = [
        {
            "path": entry.path,
            "item_type": entry.item_type,
            "item_key": entry.item_key,
            "media_type": entry.media_type,
            "size_bytes": len(entry.content),
            "sha256": sha256_hexdigest(entry.content),
            "required": entry.required,
            "source_refs": list(entry.source_refs),
        }
        for entry in payload_entries
    ]
    entries.sort(key=lambda item: (item["path"], item["item_type"], item["item_key"]))
    change = bundle.change_record
    return {
        "manifest_schema_version": SCHEMA_VERSION,
        "package_type": "sealed_bundle",
        "bundle": {
            "id": bundle.id,
            "version": bundle.version,
            "status": EvidenceBundle.Status.SEALED,
            "completeness_status": bundle.completeness_status,
            "compiled_at": bundle.compiled_at,
            "sealed_at": bundle.sealed_at,
        },
        "change": {
            "id": change.id,
            "status": change.status,
            "request_snapshot_sha256": change.request_snapshot_sha256,
            "requested_inputs_sha256": change.requested_inputs_sha256,
        },
        "source": {
            "source_snapshot_sha256": bundle.source_snapshot_sha256,
            "source_cutoff_at": bundle.source_cutoff_at,
            "source_high_watermark": bundle.source_high_watermark,
        },
        "algorithms": {
            "content_hash": "sha256",
            "manifest_hash": "sha256",
            "payload_checksums_hash": "sha256",
            "zip_method": "zip-stored",
        },
        "entries": entries,
    }


def _sync_compiling_item_content(item: EvidenceBundleItem, content: bytes) -> None:
    content_sha256 = sha256_hexdigest(content)
    content_size_bytes = len(content)
    if (
        item.content_sha256 == content_sha256
        and item.content_size_bytes == content_size_bytes
    ):
        return
    item.content_sha256 = content_sha256
    item.content_size_bytes = content_size_bytes
    item.save(update_fields=["content_sha256", "content_size_bytes", "updated_at"])


def _refresh_bundle_source_snapshot_from_items(
    bundle: EvidenceBundle,
) -> EvidenceBundle:
    items = list(
        EvidenceBundleItem.objects.filter(bundle=bundle).order_by(
            "position", "item_type", "item_key"
        )
    )
    completeness_report, completeness_status = _completeness_from_items(items)
    snapshot_payload = [_snapshot_item_payload(item) for item in items]
    source_snapshot_sha256 = sha256_hexdigest(canonical_json_bytes(snapshot_payload))
    if (
        bundle.completeness_report == completeness_report
        and bundle.completeness_status == completeness_status
        and bundle.source_snapshot_sha256 == source_snapshot_sha256
    ):
        return bundle
    bundle.completeness_report = completeness_report
    bundle.completeness_status = completeness_status
    bundle.source_snapshot_sha256 = source_snapshot_sha256
    bundle.save(
        update_fields=[
            "completeness_report",
            "completeness_status",
            "source_snapshot_sha256",
            "updated_at",
        ]
    )
    return bundle


def _snapshot_item_payload(item: EvidenceBundleItem) -> dict:
    return {
        "item_type": item.item_type,
        "item_key": item.item_key,
        "canonical_path": item.canonical_path,
        "json_pointer": item.json_pointer,
        "position": item.position,
        "required": item.required,
        "present": item.present,
        "valid": item.valid,
        "missing_reason": item.missing_reason,
        "validation_errors": item.validation_errors,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "source_updated_at": item.source_updated_at,
        "content_sha256": item.content_sha256,
        "content_size_bytes": item.content_size_bytes,
    }


def _source_refs_for_path(
    bundle: EvidenceBundle,
    path: str,
) -> tuple[dict, ...]:
    refs = []
    for item in EvidenceBundleItem.objects.filter(
        bundle=bundle, canonical_path=path
    ).order_by("position", "item_type", "item_key", "id"):
        refs.extend(_source_refs_for_item(item))
    return tuple(refs)


def _source_refs_for_item(item: EvidenceBundleItem) -> tuple[dict, ...]:
    if not item.source_type and not item.source_id:
        return ()
    return (
        {
            "source_type": item.source_type,
            "source_id": item.source_id,
            "json_pointer": item.json_pointer,
        },
    )


def _sealed_bundle_storage_key(bundle: EvidenceBundle) -> str:
    return (
        f"evidence/org/{bundle.organization_id}/change/{bundle.change_record_id}/"
        f"bundle/{bundle.id}/v{bundle.version}/sealed.zip"
    )


def _validate_zip_path(path: str) -> None:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise SuspiciousFileOperation("Invalid evidence ZIP entry path.")


def _invalidate_for_artifact_defect(
    bundle: EvidenceBundle,
    *,
    reason: str,
    detail: str,
) -> None:
    raise DomainValidationError(code=reason, detail=detail)


def _materialize_items(*, bundle: EvidenceBundle, change: ChangeRecord) -> None:
    assert_bundle_mutable(bundle)

    targets = list(selectors.change_targets_for_bundle(change))
    verification_plan = selectors.verification_plan_for_bundle(change)
    verification_checks = list(selectors.verification_checks_for_bundle(change))
    verification_results = list(selectors.verification_results_for_bundle(change))
    closure = selectors.closure_for_bundle(change)
    exceptions = list(selectors.exceptions_for_bundle(change))
    breakglass_sessions = list(selectors.breakglass_sessions_for_bundle(change))
    retro_reviews = list(selectors.retro_reviews_for_bundle(change))
    execution_binding = selectors.execution_binding_for_bundle(change)
    execution = execution_binding.execution if execution_binding is not None else None
    execution_steps = (
        list(execution.steps.order_by("position", "created_at", "id"))
        if execution is not None
        else []
    )
    approvals = list(
        selectors.approval_requests_for_bundle(
            change,
            exceptions=exceptions,
            execution=execution,
        )
    )
    policy_evaluations = list(
        selectors.policy_evaluations_for_bundle(
            change,
            exceptions=exceptions,
            execution=execution,
        )
    )
    artifacts = list(
        selectors.artifacts_for_bundle(
            change,
            execution=execution,
            verification_results=verification_results,
            exceptions=exceptions,
        )
    )

    related_object_ids = _related_object_ids(
        change=change,
        targets=targets,
        execution_binding=execution_binding,
        execution=execution,
        execution_steps=execution_steps,
        approvals=approvals,
        policy_evaluations=policy_evaluations,
        verification_plan=verification_plan,
        verification_checks=verification_checks,
        verification_results=verification_results,
        closure=closure,
        exceptions=exceptions,
        breakglass_sessions=breakglass_sessions,
        retro_reviews=retro_reviews,
        artifacts=artifacts,
    )
    audit_events = list(
        selectors.audit_events_for_bundle(
            change,
            related_object_ids=related_object_ids,
            source_cutoff_at=bundle.source_cutoff_at,
        )
    )

    sections = [
        _change_snapshot_section(bundle, change, targets),
        _targets_section(bundle, change, targets),
        _approvals_section(bundle, change, approvals),
        _policy_decisions_section(bundle, change, policy_evaluations),
        _execution_section(
            bundle, change, execution_binding, execution, execution_steps
        ),
        _audit_section(bundle, change, audit_events),
        _artifacts_section(bundle, change, artifacts),
        _verification_plan_section(
            bundle,
            change,
            verification_plan,
            verification_checks,
        ),
        _verification_results_section(
            bundle,
            change,
            verification_plan,
            verification_checks,
            verification_results,
        ),
        _closure_section(bundle, change, closure),
        _export_receipt_section(bundle, change),
    ]
    exception_section = _exceptions_section(
        bundle,
        change,
        exceptions,
        breakglass_sessions,
        retro_reviews,
        force=True,
    )
    sections.append(exception_section)
    external_reference_section = _external_references_section(
        bundle,
        change,
        verification_results,
        verification_checks,
        retro_reviews,
    )
    if external_reference_section is not None:
        sections.append(external_reference_section)

    position = 0
    for section in sections:
        position += 1
        _create_section_item(bundle, section, position=position)

    for event_position, event in enumerate(audit_events, start=1):
        position += 1
        _create_audit_event_item(
            bundle, event, position=position, event_position=event_position
        )

    for artifact in artifacts:
        position += 1
        _create_artifact_item(bundle, change, artifact, position=position)

    _create_missing_verification_items(
        bundle=bundle,
        verification_checks=verification_checks,
        verification_results=verification_results,
        start_position=position,
    )

    _finalize_bundle_materialization(bundle, audit_events)


def _section_payload(bundle: EvidenceBundle, change: ChangeRecord, *, items):
    return {
        "schema_version": SCHEMA_VERSION,
        "organization_id": change.organization_id,
        "change_record_id": change.id,
        "bundle_id": bundle.id,
        "bundle_version": bundle.version,
        "generated_at": bundle.compiled_at,
        "items": items,
    }


def _change_snapshot_section(bundle, change, targets):
    item = {
        "id": change.id,
        "status": change.status,
        "title": change.title,
        "summary": change.summary,
        "justification": change.justification,
        "requested_by_id": change.requested_by_id,
        "submitted_by_id": change.submitted_by_id,
        "operation_profile_id": change.operation_profile_id,
        "operation_profile_key_snapshot": change.operation_profile_key_snapshot,
        "workflow_id": change.workflow_id,
        "workflow_version_snapshot": change.workflow_version_snapshot,
        "workflow_definition_sha256": change.workflow_definition_sha256,
        "requested_inputs_sha256": change.requested_inputs_sha256,
        "request_snapshot_sha256": change.request_snapshot_sha256,
        "approval_request_id": change.approval_request_id,
        "policy_evaluation_id": change.policy_evaluation_id,
        "policy_decision_snapshot": change.policy_decision_snapshot,
        "scheduled_for": change.scheduled_for,
        "submitted_at": change.submitted_at,
        "approved_at": change.approved_at,
        "dispatchable_at": change.dispatchable_at,
        "running_at": change.running_at,
        "verification_pending_at": change.verification_pending_at,
        "verification_failed_at": change.verification_failed_at,
        "verified_at": change.verified_at,
        "closed_at": change.closed_at,
        "terminal_reason": change.terminal_reason,
        "is_emergency": change.is_emergency,
        "emergency_declared_by_id": change.emergency_declared_by_id,
        "emergency_declared_at": change.emergency_declared_at,
        "emergency_reason_sha256": _hash_text(change.emergency_reason),
        "retro_review_required": change.retro_review_required,
        "retro_review_due_at": change.retro_review_due_at,
        "retro_review_blocking_status": change.retro_review_blocking_status,
        "freeze_exception_reference": change.freeze_exception_reference,
        "freeze_exception_recorded_by_id": change.freeze_exception_recorded_by_id,
        "freeze_exception_recorded_at": change.freeze_exception_recorded_at,
        "target_count": len(targets),
        "targets": [_serialize_target(target) for target in targets],
        "created_at": change.created_at,
        "updated_at": change.updated_at,
    }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
        item_key="change_snapshot",
        canonical_path="change/change_record.json",
        payload=_section_payload(bundle, change, items=[item]),
        source_type="changes.ChangeRecord",
        source_id=str(change.id),
        source_updated_at=change.updated_at,
        source_metadata={"status": change.status, "target_count": len(targets)},
    )


def _targets_section(bundle, change, targets):
    items = [_serialize_target(target) for target in targets]
    return _Section(
        item_type=EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
        item_key="targets",
        canonical_path="change/targets.json",
        payload=_section_payload(bundle, change, items=items),
        source_metadata={"target_count": len(items)},
    )


def _approvals_section(bundle, change, approvals):
    items = []
    for approval in approvals:
        decision = _approval_decision_for(approval)
        items.append(
            {
                "id": approval.id,
                "subject_type": approval.subject_type,
                "subject_id": approval.subject_id,
                "execution_id": approval.execution_id,
                "step_id": approval.step_id,
                "status": approval.status,
                "requested_by_runner_id": approval.requested_by_runner_id,
                "requested_at": approval.requested_at,
                "timeout_seconds": approval.timeout_seconds,
                "expires_at": approval.expires_at,
                "resolved_at": approval.resolved_at,
                "decision": _serialize_approval_decision(decision),
                "created_at": approval.created_at,
                "updated_at": approval.updated_at,
            }
        )
    return _Section(
        item_type=EvidenceBundleItem.ItemType.APPROVAL,
        item_key="approvals",
        canonical_path="controls/approvals.json",
        payload=_section_payload(bundle, change, items=items),
        source_metadata={"approval_count": len(items)},
    )


def _policy_decisions_section(bundle, change, policy_evaluations):
    items = []
    for evaluation in policy_evaluations:
        items.append(
            {
                "id": evaluation.id,
                "execution_id": evaluation.execution_id,
                "step_id": evaluation.step_id,
                "policy_id": evaluation.policy_id,
                "rule_id": evaluation.rule_id,
                "matched": evaluation.matched,
                "outcome": evaluation.outcome,
                "effective_outcome": evaluation.effective_outcome,
                "decision_source": evaluation.decision_source,
                "condition_type": evaluation.condition_type,
                "condition_params_snapshot": evaluation.condition_params_snapshot,
                "context_snapshot": evaluation.context_snapshot,
                "reason": evaluation.reason,
                "error_code": evaluation.error_code,
                "error_message": evaluation.error_message,
                "evaluated_at": evaluation.evaluated_at,
                "created_at": evaluation.created_at,
                "updated_at": evaluation.updated_at,
            }
        )
    return _Section(
        item_type=EvidenceBundleItem.ItemType.POLICY_DECISION,
        item_key="policy_decisions",
        canonical_path="controls/policy_decisions.json",
        payload=_section_payload(bundle, change, items=items),
        source_metadata={"policy_evaluation_count": len(items)},
    )


def _execution_section(bundle, change, binding, execution, steps):
    present = execution is not None
    missing_reason = "" if present else "missing_execution"
    item = None
    if execution is not None:
        item = {
            "binding": _serialize_binding(binding),
            "execution": {
                "id": execution.id,
                "workflow_id": execution.workflow_id,
                "workflow_version": execution.workflow_version,
                "status": execution.status,
                "started_at": execution.started_at,
                "finished_at": execution.finished_at,
                "claimed_by_runner_id": execution.claimed_by_runner_id,
                "claimed_at": execution.claimed_at,
                "last_heartbeat_at": execution.last_heartbeat_at,
                "created_at": execution.created_at,
                "updated_at": execution.updated_at,
            },
            "steps": [_serialize_execution_step(step) for step in steps],
        }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXECUTION,
        item_key="execution",
        canonical_path="execution/execution.json",
        payload=_section_payload(bundle, change, items=[] if item is None else [item]),
        present=present,
        missing_reason=missing_reason,
        source_type="executions.Execution" if execution is not None else "",
        source_id=str(execution.id) if execution is not None else "",
        source_updated_at=execution.updated_at if execution is not None else None,
        source_metadata={
            "step_count": len(steps),
            "status": getattr(execution, "status", None),
        },
    )


def _audit_section(bundle, change, audit_events):
    events = [_serialize_audit_event(event) for event in audit_events]
    return _Section(
        item_type=EvidenceBundleItem.ItemType.AUDIT_EVENT,
        item_key="audit_trail",
        canonical_path="audit/audit_trail.ndjson",
        payload=events,
        source_metadata={"audit_event_count": len(events)},
    )


def _artifacts_section(bundle, change, artifacts):
    items = []
    invalid_errors = []
    for artifact in artifacts:
        validation_errors = _artifact_validation_errors(change, artifact)
        invalid_errors.extend(validation_errors)
        items.append(
            {
                "id": artifact.id,
                "execution_id": artifact.execution_id,
                "step_id": artifact.step_id,
                "kind": artifact.kind,
                "name": artifact.name,
                "original_name": artifact.original_name,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
                "checksum_sha256": artifact.checksum_sha256,
                "storage_key": artifact.storage_key,
                "uploaded_by_runner_id": artifact.uploaded_by_runner_id,
                "upload_status": artifact.upload_status,
                "uploaded_at": artifact.uploaded_at,
                "content_disposition": artifact.content_disposition,
                "bundle_path": _artifact_bundle_path(artifact),
                "valid": not validation_errors,
                "validation_errors": validation_errors,
            }
        )
    return _Section(
        item_type=EvidenceBundleItem.ItemType.ARTIFACT,
        item_key="artifacts_index",
        canonical_path="artifacts/index.json",
        payload=_section_payload(bundle, change, items=items),
        valid=not invalid_errors,
        validation_errors=tuple(invalid_errors),
        source_metadata={"artifact_count": len(items)},
    )


def _verification_results_section(
    bundle,
    change,
    verification_plan,
    verification_checks,
    verification_results,
):
    items = {
        "plan": None,
        "checks": [
            _serialize_verification_check(check) for check in verification_checks
        ],
        "results": [
            _serialize_verification_result(result) for result in verification_results
        ],
    }
    if verification_plan is not None:
        items["plan"] = {
            "id": verification_plan.id,
            "mode": verification_plan.mode,
            "status": verification_plan.status,
            "generated_from_profile_sha256": verification_plan.generated_from_profile_sha256,
            "required_check_count": verification_plan.required_check_count,
            "optional_check_count": verification_plan.optional_check_count,
            "satisfied_required_count": verification_plan.satisfied_required_count,
            "failed_required_count": verification_plan.failed_required_count,
            "generated_at": verification_plan.generated_at,
            "activated_at": verification_plan.activated_at,
            "satisfied_at": verification_plan.satisfied_at,
            "failed_at": verification_plan.failed_at,
        }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
        item_key="verification_results",
        canonical_path="verification/results.json",
        payload=_section_payload(bundle, change, items=[items]),
        present=verification_plan is not None,
        missing_reason=""
        if verification_plan is not None
        else "missing_verification_plan",
        source_type="changes.VerificationPlan" if verification_plan is not None else "",
        source_id=str(verification_plan.id) if verification_plan is not None else "",
        source_updated_at=verification_plan.updated_at
        if verification_plan is not None
        else None,
        source_metadata={
            "required_check_count": len(
                [check for check in verification_checks if check.required]
            ),
            "result_count": len(verification_results),
        },
    )


def _verification_plan_section(bundle, change, verification_plan, verification_checks):
    items = {
        "plan": None,
        "checks": [
            _serialize_verification_check(check) for check in verification_checks
        ],
    }
    if verification_plan is not None:
        items["plan"] = {
            "id": verification_plan.id,
            "mode": verification_plan.mode,
            "status": verification_plan.status,
            "generated_from_profile_sha256": verification_plan.generated_from_profile_sha256,
            "required_check_count": verification_plan.required_check_count,
            "optional_check_count": verification_plan.optional_check_count,
            "satisfied_required_count": verification_plan.satisfied_required_count,
            "failed_required_count": verification_plan.failed_required_count,
            "generated_at": verification_plan.generated_at,
            "activated_at": verification_plan.activated_at,
            "satisfied_at": verification_plan.satisfied_at,
            "failed_at": verification_plan.failed_at,
        }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
        item_key="verification_plan",
        canonical_path="verification/plan.json",
        payload=_section_payload(bundle, change, items=[items]),
        present=verification_plan is not None,
        missing_reason=""
        if verification_plan is not None
        else "missing_verification_plan",
        source_type="changes.VerificationPlan" if verification_plan is not None else "",
        source_id=str(verification_plan.id) if verification_plan is not None else "",
        source_updated_at=verification_plan.updated_at
        if verification_plan is not None
        else None,
        source_metadata={
            "required_check_count": len(
                [check for check in verification_checks if check.required]
            ),
            "check_count": len(verification_checks),
        },
    )


def _closure_section(bundle, change, closure):
    present = closure is not None
    item = None if closure is None else _serialize_closure(closure)
    return _Section(
        item_type=EvidenceBundleItem.ItemType.CLOSURE,
        item_key="closure",
        canonical_path="closure/closure.json",
        payload=_section_payload(bundle, change, items=[] if item is None else [item]),
        present=present,
        missing_reason="" if present else "missing_closure",
        source_type="changes.ChangeClosure" if present else "",
        source_id=str(closure.id) if present else "",
        source_updated_at=closure.updated_at if present else None,
        source_metadata={"outcome": closure.outcome if present else None},
    )


def _exceptions_section(
    bundle,
    change,
    exceptions,
    breakglass_sessions,
    retro_reviews,
    *,
    force=False,
):
    if (
        not force
        and not exceptions
        and not breakglass_sessions
        and not retro_reviews
        and not change.is_emergency
    ):
        return None
    items = {
        "change_emergency": {
            "is_emergency": change.is_emergency,
            "emergency_declared_by_id": change.emergency_declared_by_id,
            "emergency_declared_at": change.emergency_declared_at,
            "retro_review_required": change.retro_review_required,
            "retro_review_due_at": change.retro_review_due_at,
            "retro_review_blocking_status": change.retro_review_blocking_status,
        },
        "exceptions": [_serialize_exception(exc) for exc in exceptions],
        "breakglass_sessions": [
            _serialize_breakglass(session) for session in breakglass_sessions
        ],
        "retro_reviews": [_serialize_retro_review(review) for review in retro_reviews],
    }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXCEPTION,
        item_key="exceptions",
        canonical_path="exceptions/exceptions.json",
        payload=_section_payload(bundle, change, items=[items]),
        required=False,
        source_metadata={
            "exception_count": len(exceptions),
            "breakglass_count": len(breakglass_sessions),
            "retro_review_count": len(retro_reviews),
        },
    )


def _export_receipt_section(bundle, change):
    receipt = {
        "receipt_type": "sealed_bundle",
        "export_id": None,
        "organization_id": change.organization_id,
        "change_record_id": change.id,
        "bundle_id": bundle.id,
        "bundle_version": bundle.version,
        "compiled_at": bundle.compiled_at,
        "sealed_at": bundle.sealed_at,
    }
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXPORT_RECEIPT,
        item_key="sealed_bundle_receipt",
        canonical_path="exports/export_receipt.json",
        payload=_section_payload(bundle, change, items=[receipt]),
        source_metadata={"receipt_type": "sealed_bundle"},
    )


def _external_references_section(
    bundle,
    change,
    verification_results,
    verification_checks,
    retro_reviews,
):
    references = []
    for result in verification_results:
        if result.external_reference:
            references.append(
                {
                    "source_type": "changes.VerificationResult",
                    "source_id": result.id,
                    "reference": result.external_reference,
                }
            )
    for check in verification_checks:
        if check.external_reference_config:
            references.append(
                {
                    "source_type": "changes.VerificationCheck",
                    "source_id": check.id,
                    "reference": check.external_reference_config,
                }
            )
    for review in retro_reviews:
        if review.remediation_reference:
            references.append(
                {
                    "source_type": "changes.RetroReview",
                    "source_id": review.id,
                    "reference": review.remediation_reference,
                }
            )
    if not references:
        return None
    references.sort(key=lambda item: (item["source_type"], str(item["source_id"])))
    return _Section(
        item_type=EvidenceBundleItem.ItemType.EXTERNAL_REFERENCE,
        item_key="external_references",
        canonical_path="references/external_references.json",
        payload=_section_payload(bundle, change, items=references),
        required=False,
        source_metadata={"external_reference_count": len(references)},
    )


def _create_section_item(
    bundle, section: _Section, *, position: int
) -> EvidenceBundleItem:
    payload_bytes = (
        canonical_ndjson_bytes(section.payload)
        if section.canonical_path.endswith(".ndjson")
        else canonical_json_bytes(section.payload)
    )
    return EvidenceBundleItem.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        item_type=section.item_type,
        item_key=section.item_key,
        canonical_path=section.canonical_path,
        position=position,
        required=section.required,
        present=section.present,
        valid=section.valid,
        missing_reason=section.missing_reason,
        validation_errors=list(section.validation_errors),
        source_type=section.source_type,
        source_id=section.source_id,
        source_updated_at=section.source_updated_at,
        source_metadata=section.source_metadata or {},
        content_sha256=sha256_hexdigest(payload_bytes),
        content_size_bytes=len(payload_bytes),
        mime_type="application/x-ndjson"
        if section.canonical_path.endswith(".ndjson")
        else "application/json",
    )


def _create_audit_event_item(bundle, event, *, position: int, event_position: int):
    payload_bytes = canonical_json_bytes(_serialize_audit_event(event))
    return EvidenceBundleItem.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        item_type=EvidenceBundleItem.ItemType.AUDIT_EVENT,
        item_key=f"audit_event:{event.id}",
        canonical_path="audit/audit_trail.ndjson",
        json_pointer=f"/events/{event_position - 1}",
        position=position,
        required=True,
        present=True,
        valid=True,
        source_type="audit.AuditEvent",
        source_id=str(event.id),
        source_updated_at=event.updated_at,
        source_metadata={
            "event_type": event.event_type,
            "object_type": event.object_type,
            "object_id": str(event.object_id),
            "occurred_at": _normalize(event.occurred_at),
            "event_position": event_position,
        },
        content_sha256=sha256_hexdigest(payload_bytes),
        content_size_bytes=len(payload_bytes),
        mime_type="application/json",
    )


def _create_artifact_item(bundle, change, artifact, *, position: int):
    validation_errors = _artifact_validation_errors(change, artifact)
    return EvidenceBundleItem.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        item_type=EvidenceBundleItem.ItemType.ARTIFACT,
        item_key=f"artifact:{artifact.id}",
        canonical_path=_artifact_bundle_path(artifact),
        position=position,
        required=True,
        present=True,
        valid=not validation_errors,
        validation_errors=validation_errors,
        source_type="artifacts.Artifact",
        source_id=str(artifact.id),
        source_updated_at=artifact.updated_at,
        source_metadata={
            "name": artifact.name,
            "kind": artifact.kind,
            "checksum_sha256": artifact.checksum_sha256,
            "upload_status": artifact.upload_status,
        },
        artifact=artifact
        if artifact.organization_id == bundle.organization_id
        else None,
        content_sha256=artifact.checksum_sha256
        if _checksum_is_valid(artifact.checksum_sha256)
        else "",
        content_size_bytes=artifact.size_bytes,
        mime_type=artifact.mime_type,
    )


def _create_missing_verification_items(
    *,
    bundle,
    verification_checks,
    verification_results,
    start_position,
) -> None:
    accepted_result_check_ids = {
        result.verification_check_id
        for result in verification_results
        if result.validation_status == VerificationResult.ValidationStatus.ACCEPTED
    }
    position = start_position
    for check in verification_checks:
        if not check.required or check.id in accepted_result_check_ids:
            continue
        position += 1
        EvidenceBundleItem.objects.create(
            organization=bundle.organization,
            bundle=bundle,
            item_type=EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
            item_key=f"missing_verification_result:{check.id}",
            canonical_path="verification/results.json",
            json_pointer=f"/missing_required/{check.key}",
            position=position,
            required=True,
            present=False,
            valid=True,
            missing_reason="missing_required_verification_result",
            source_type="changes.VerificationCheck",
            source_id=str(check.id),
            source_updated_at=check.updated_at,
            source_metadata={"check_key": check.key, "check_type": check.check_type},
            content_sha256=sha256_hexdigest(
                canonical_json_bytes({"missing": str(check.id)})
            ),
            content_size_bytes=len(canonical_json_bytes({"missing": str(check.id)})),
            mime_type="application/json",
        )


def _finalize_bundle_materialization(bundle, audit_events) -> None:
    items = list(
        EvidenceBundleItem.objects.filter(bundle=bundle).order_by(
            "position", "item_type", "item_key"
        )
    )
    completeness_report, completeness_status = _completeness_from_items(items)
    snapshot_payload = [_snapshot_item_payload(item) for item in items]
    audit_high_watermark = {}
    if audit_events:
        last_event = audit_events[-1]
        audit_high_watermark = {
            "occurred_at": _normalize(last_event.occurred_at),
            "created_at": _normalize(last_event.created_at),
            "id": str(last_event.id),
        }
    bundle.completeness_report = completeness_report
    bundle.completeness_status = completeness_status
    bundle.source_snapshot_sha256 = sha256_hexdigest(
        canonical_json_bytes(snapshot_payload)
    )
    bundle.source_high_watermark = {"audit": audit_high_watermark}
    bundle.save(
        update_fields=[
            "completeness_report",
            "completeness_status",
            "source_snapshot_sha256",
            "source_high_watermark",
            "updated_at",
        ]
    )


def _completeness_from_items(items):
    sections = []
    missing_required = []
    invalid_items = []
    for item in items:
        report_item = {
            "item_type": item.item_type,
            "item_key": item.item_key,
            "canonical_path": item.canonical_path,
            "json_pointer": item.json_pointer,
            "position": item.position,
            "required": item.required,
            "present": item.present,
            "valid": item.valid,
            "missing_reason": item.missing_reason,
            "validation_errors": item.validation_errors,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "content_sha256": item.content_sha256,
        }
        sections.append(report_item)
        if item.required and not item.present:
            missing_required.append(report_item)
        if not item.valid:
            invalid_items.append(report_item)

    if invalid_items:
        status = EvidenceBundle.CompletenessStatus.INVALID
    elif missing_required:
        status = EvidenceBundle.CompletenessStatus.INCOMPLETE
    else:
        status = EvidenceBundle.CompletenessStatus.COMPLETE
    return (
        {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "summary": {
                "total_items": len(items),
                "missing_required_count": len(missing_required),
                "invalid_count": len(invalid_items),
            },
            "missing_required": missing_required,
            "invalid": invalid_items,
            "sections": sections,
        },
        status,
    )


def _emit_bundle_materialized(*, bundle, actor: AuditActor | None) -> None:
    actor = actor or system_actor("Evidence materialization")
    AuditService.emit(
        organization_id=bundle.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_bundle.materialized",
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        metadata={
            "change_record_id": str(bundle.change_record_id),
            "version": bundle.version,
            "completeness_status": bundle.completeness_status,
            "item_count": bundle.items.count(),
            "source_snapshot_sha256": bundle.source_snapshot_sha256,
        },
    )


def _emit_bundle_sealed(*, bundle_id, actor: AuditActor | None) -> None:
    bundle = EvidenceBundle.objects.get(pk=bundle_id)
    actor = actor or system_actor("Evidence sealing")
    AuditService.emit(
        organization_id=bundle.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_bundle.sealed",
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        metadata={
            "change_record_id": str(bundle.change_record_id),
            "version": bundle.version,
            "manifest_sha256": bundle.manifest_sha256,
            "content_sha256": bundle.content_sha256,
            "content_size_bytes": bundle.content_size_bytes,
        },
    )


def _emit_bundle_invalidated(
    *,
    bundle_id,
    previous_status: str,
    actor: AuditActor | None,
) -> None:
    bundle = EvidenceBundle.objects.get(pk=bundle_id)
    actor = actor or system_actor("Evidence invalidation")
    AuditService.emit(
        organization_id=bundle.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_bundle.invalidated",
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        metadata={
            "change_record_id": str(bundle.change_record_id),
            "version": bundle.version,
            "previous_status": previous_status,
            "invalidation_reason": bundle.invalidation_reason,
        },
    )


def _related_object_ids(**sources):
    ids = {sources["change"].id}
    for key, value in sources.items():
        if key == "change" or value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for obj in values:
            if obj is not None:
                ids.add(obj.id)
            decision = _approval_decision_for(obj)
            if decision is not None:
                ids.add(decision.id)
    return ids


def _serialize_target(target):
    return {
        "id": target.id,
        "position": target.position,
        "target_type": target.target_type,
        "target_identifier": target.target_identifier,
        "normalized_identifier": target.normalized_identifier,
        "display_name": target.display_name,
        "environment": target.environment,
        "metadata": target.metadata,
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


def _serialize_approval_decision(decision):
    if decision is None:
        return None
    return {
        "id": decision.id,
        "decision": decision.decision,
        "source_type": decision.source_type,
        "decided_by_user_id": decision.decided_by_user_id,
        "decided_by_label": decision.decided_by_label,
        "decided_by_label_source": decision.decided_by_label_source,
        "notes_sha256": _hash_text(decision.notes),
        "decided_at": decision.decided_at,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
    }


def _approval_decision_for(approval):
    try:
        return approval.decision
    except (AttributeError, ObjectDoesNotExist):
        return None


def _serialize_binding(binding):
    if binding is None:
        return None
    return {
        "id": binding.id,
        "operation_profile_key": binding.operation_profile_key,
        "requested_inputs_sha256": binding.requested_inputs_sha256,
        "dispatch_token_expires_at": binding.dispatch_token_expires_at,
        "reserved_at": binding.reserved_at,
        "bound_at": binding.bound_at,
        "bound_by_runner_id": binding.bound_by_runner_id,
        "execution_accepted_at": binding.execution_accepted_at,
        "execution_started_at": binding.execution_started_at,
        "execution_finished_at": binding.execution_finished_at,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def _serialize_execution_step(step):
    return {
        "id": step.id,
        "position": step.position,
        "step_key": step.step_key,
        "name": step.name,
        "step_type": step.step_type,
        "risk_level": step.risk_level,
        "requires_approval": step.requires_approval,
        "status": step.status,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "exit_code": step.exit_code,
        "error_message": step.error_message,
        "created_at": step.created_at,
        "updated_at": step.updated_at,
    }


def _serialize_verification_check(check):
    return {
        "id": check.id,
        "position": check.position,
        "key": check.key,
        "name": check.name,
        "description": check.description,
        "check_type": check.check_type,
        "required": check.required,
        "status": check.status,
        "verification_key": check.verification_key,
        "source_step_key": check.source_step_key,
        "artifact_kind": check.artifact_kind,
        "artifact_name_pattern": check.artifact_name_pattern,
        "expected_checksum_sha256": check.expected_checksum_sha256,
        "external_reference_config": check.external_reference_config,
        "last_result_id": check.last_result_id,
        "satisfied_at": check.satisfied_at,
        "failed_at": check.failed_at,
        "created_at": check.created_at,
        "updated_at": check.updated_at,
    }


def _serialize_verification_result(result):
    return {
        "id": result.id,
        "verification_check_id": result.verification_check_id,
        "source": result.source,
        "outcome": result.outcome,
        "validation_status": result.validation_status,
        "submitted_by_id": result.submitted_by_id,
        "runner_id": result.runner_id,
        "verification_key": result.verification_key,
        "artifact_id": result.artifact_id,
        "artifact_checksum_sha256": result.artifact_checksum_sha256,
        "external_reference": result.external_reference,
        "manual_attestation_sha256": _hash_text(result.manual_attestation_text),
        "observed_value": result.observed_value,
        "validation_errors": result.validation_errors,
        "submitted_at": result.submitted_at,
        "validated_at": result.validated_at,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
    }


def _serialize_closure(closure: ChangeClosure):
    return {
        "id": closure.id,
        "outcome": closure.outcome,
        "closed_by_id": closure.closed_by_id,
        "independent_reviewer_id": closure.independent_reviewer_id,
        "summary": closure.summary,
        "verification_plan_id": closure.verification_plan_id,
        "verification_summary": closure.verification_summary,
        "execution_summary": closure.execution_summary,
        "closed_at": closure.closed_at,
        "created_at": closure.created_at,
        "updated_at": closure.updated_at,
    }


def _serialize_exception(exc):
    return {
        "id": exc.id,
        "exception_type": exc.exception_type,
        "status": exc.status,
        "reason_sha256": _hash_text(exc.reason),
        "scope_sha256": sha256_hexdigest(canonical_json_bytes(exc.scope_json)),
        "requested_by_id": exc.requested_by_id,
        "requested_at": exc.requested_at,
        "approval_request_id": exc.approval_request_id,
        "approved_by_id": exc.approved_by_id,
        "approved_at": exc.approved_at,
        "rejected_at": exc.rejected_at,
        "expires_at": exc.expires_at,
        "resolved_at": exc.resolved_at,
        "resolution_note_sha256": _hash_text(exc.resolution_note),
        "policy_evaluation_id": exc.policy_evaluation_id,
        "verification_check_id": exc.verification_check_id,
        "artifact_id": exc.artifact_id,
        "created_at": exc.created_at,
        "updated_at": exc.updated_at,
    }


def _serialize_breakglass(session):
    return {
        "id": session.id,
        "status": session.status,
        "scope_sha256": session.scope_sha256,
        "reason_sha256": _hash_text(session.reason),
        "activated_by_id": session.activated_by_id,
        "started_at": session.started_at,
        "expires_at": session.expires_at,
        "ended_at": session.ended_at,
        "ended_by_id": session.ended_by_id,
        "end_reason": session.end_reason,
        "review_due_at": session.review_due_at,
        "review_status": session.review_status,
        "last_heartbeat_at": session.last_heartbeat_at,
        "activation_ip_hash": session.activation_ip_hash,
        "activation_user_agent": session.activation_user_agent,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def _serialize_retro_review(review):
    return {
        "id": review.id,
        "breakglass_session_id": review.breakglass_session_id,
        "change_exception_id": review.change_exception_id,
        "status": review.status,
        "disposition": review.disposition,
        "reviewed_by_id": review.reviewed_by_id,
        "reviewed_at": review.reviewed_at,
        "due_at": review.due_at,
        "summary_sha256": _hash_text(review.summary),
        "remediation_required": review.remediation_required,
        "remediation_reference": review.remediation_reference,
        "control_failure_category": review.control_failure_category,
        "evidence_sha256": sha256_hexdigest(canonical_json_bytes(review.evidence_json)),
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


def _serialize_audit_event(event):
    return {
        "id": event.id,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "actor_label": event.actor_label,
        "event_type": event.event_type,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "organization_id": event.organization_id,
        "metadata": event.metadata,
        "occurred_at": event.occurred_at,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def _artifact_validation_errors(change, artifact):
    errors = []
    if artifact.organization_id != change.organization_id:
        errors.append(
            {
                "code": "cross_org_artifact_reference",
                "artifact_id": str(artifact.id),
                "artifact_organization_id": str(artifact.organization_id),
                "expected_organization_id": str(change.organization_id),
            }
        )
    if artifact.execution.organization_id != change.organization_id:
        errors.append(
            {
                "code": "cross_org_artifact_execution",
                "artifact_id": str(artifact.id),
                "execution_id": str(artifact.execution_id),
            }
        )
    if not _checksum_is_valid(artifact.checksum_sha256):
        errors.append(
            {
                "code": "invalid_artifact_checksum",
                "artifact_id": str(artifact.id),
            }
        )
    if artifact.upload_status != artifact.UploadStatus.AVAILABLE:
        errors.append(
            {
                "code": "artifact_unavailable",
                "artifact_id": str(artifact.id),
                "upload_status": artifact.upload_status,
            }
        )
    return errors


def _artifact_bundle_path(artifact):
    safe_name = "".join(
        char if char.isalnum() or char in {".", "-", "_"} else "_"
        for char in artifact.name
    ).strip("._")
    if not safe_name:
        safe_name = "artifact"
    return f"artifacts/files/{artifact.id}/{safe_name}"


def _checksum_is_valid(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def _hash_text(value: str) -> str:
    if not value:
        return ""
    return sha256_hexdigest(str(value).encode("utf-8"))


def sha256_hexdigest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value) -> bytes:
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_ndjson_bytes(values) -> bytes:
    lines = [canonical_json_bytes(value).decode("utf-8") for value in values]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _normalize(value):
    if isinstance(value, dict):
        return {
            str(key): _normalize(value[key]) for key in sorted(value.keys(), key=str)
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, UTC)
        value = value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "pk") and hasattr(value, "_meta"):
        return _normalize(model_to_dict(value))
    return value


# ---------------------------------------------------------------------------
# EvidenceRedactionPolicy service helpers
# ---------------------------------------------------------------------------


def compute_redaction_policy_sha256(rules: list) -> str:
    """Compute canonical SHA-256 of a redaction policy rule list."""
    return sha256_hexdigest(canonical_json_bytes(rules))


# ---------------------------------------------------------------------------
# Export creation
# ---------------------------------------------------------------------------


def create_export(
    bundle: EvidenceBundle,
    *,
    redaction_policy: EvidenceRedactionPolicy | None = None,
    actor: AuditActor | None = None,
    requested_by=None,
    storage: EvidenceStorage | None = None,
) -> EvidenceExport:
    """Create a derived export ZIP from a sealed bundle."""
    storage = storage or EvidenceStorage()

    bundle = EvidenceBundle.objects.select_related(
        "change_record", "organization", "retention_policy"
    ).get(pk=bundle.pk)
    if bundle.status != EvidenceBundle.Status.SEALED:
        raise DomainValidationError(
            code="bundle_not_sealed",
            detail="Only sealed evidence bundles can be exported.",
        )
    if bundle.storage_deleted_at is not None or not bundle.storage_key:
        raise DomainValidationError(
            code="bundle_storage_missing",
            detail="Sealed bundle storage is not available.",
        )
    if not storage.exists(bundle.storage_key):
        raise DomainValidationError(
            code="bundle_storage_missing",
            detail="Sealed bundle storage is not available.",
        )

    bundle_bytes = storage.read_bytes(bundle.storage_key)
    if sha256_hexdigest(bundle_bytes) != bundle.content_sha256:
        raise DomainValidationError(
            code="bundle_checksum_mismatch",
            detail="Sealed bundle checksum does not match stored bytes.",
        )

    if redaction_policy is not None:
        if not redaction_policy.is_active:
            raise DomainValidationError(
                code="redaction_policy_inactive",
                detail="Redaction policy is not active.",
            )
        if redaction_policy.organization_id != bundle.organization_id:
            raise DomainValidationError(
                code="redaction_policy_invalid",
                detail="Redaction policy does not belong to this organization.",
            )

    requested_at = timezone.now()
    export = EvidenceExport.objects.create(
        organization=bundle.organization,
        bundle=bundle,
        redaction_policy=redaction_policy,
        status=EvidenceExport.Status.CREATING,
        requested_by=requested_by,
        requested_at=requested_at,
        source_manifest_sha256=bundle.manifest_sha256,
        source_bundle_content_sha256=bundle.content_sha256,
    )

    storage_key = ""
    wrote_storage = False
    try:
        source_entries = _load_zip_entries(bundle_bytes)
        export_entries, redaction_summary = _apply_redaction_policy(
            source_entries,
            policy=redaction_policy,
        )

        receipt = _build_export_receipt(
            bundle=bundle,
            export=export,
            redaction_policy=redaction_policy,
            redaction_summary=redaction_summary,
        )
        receipt_bytes = canonical_json_bytes(receipt)
        receipt_sha256 = sha256_hexdigest(receipt_bytes)
        export_entries["exports/export_receipt.json"] = receipt_bytes

        export_manifest = _build_export_manifest(
            bundle=bundle,
            export=export,
            entries_by_path=export_entries,
            redaction_summary=redaction_summary,
            receipt_sha256=receipt_sha256,
        )
        manifest_bytes = canonical_json_bytes(export_manifest)
        manifest_sha256 = sha256_hexdigest(manifest_bytes)
        export_entries["manifest.json"] = manifest_bytes
        checksums_bytes = canonical_checksums_bytes(export_entries)
        export_entries["checksums.sha256"] = checksums_bytes

        zip_bytes = deterministic_zip_bytes(export_entries)
        content_sha256 = sha256_hexdigest(zip_bytes)
        content_size_bytes = len(zip_bytes)

        storage_key = _export_storage_key(export)
        storage.save_bytes(storage_key, zip_bytes)
        wrote_storage = True

        ready_at = timezone.now()
        expires_at = ready_at + timedelta(days=_export_retention_days(bundle))

        export.status = EvidenceExport.Status.READY
        export.ready_at = ready_at
        export.expires_at = expires_at
        export.storage_key = storage_key
        export.content_sha256 = content_sha256
        export.content_size_bytes = content_size_bytes
        export.manifest = _normalize(export_manifest)
        export.manifest_sha256 = manifest_sha256
        export.redaction_summary = redaction_summary
        export.receipt = _normalize(receipt)
        export.receipt_sha256 = receipt_sha256
        export.save()

        export_id = export.id
        transaction.on_commit(
            lambda: _emit_export_created(export_id=export_id, actor=actor)
        )
        return export
    except Exception as exc:
        if wrote_storage and storage_key:
            try:
                storage.delete(storage_key)
            except Exception:
                pass
        export.refresh_from_db()
        if export.status == EvidenceExport.Status.CREATING:
            EvidenceExport.objects.filter(pk=export.pk).update(
                status=EvidenceExport.Status.FAILED,
                failure_code=str(getattr(exc, "code", "export_failed"))[:128],
                failure_message=str(exc)[:500],
            )
        raise


def download_export(
    export: EvidenceExport,
    *,
    actor: AuditActor | None = None,
    storage: EvidenceStorage | None = None,
) -> bytes:
    """Return export ZIP bytes and emit a download audit event."""
    storage = storage or EvidenceStorage()
    export = EvidenceExport.objects.select_related("bundle", "organization").get(
        pk=export.pk
    )

    if export.status != EvidenceExport.Status.READY:
        raise DomainValidationError(
            code="export_not_ready",
            detail="Export is not ready for download.",
        )
    if export.storage_deleted_at is not None or not export.storage_key:
        raise DomainValidationError(
            code="export_storage_missing",
            detail="Export storage is not available.",
        )
    if export.expires_at is not None and export.expires_at <= timezone.now():
        raise DomainValidationError(
            code="export_expired",
            detail="Export has expired.",
        )
    if not storage.exists(export.storage_key):
        raise DomainValidationError(
            code="export_storage_missing",
            detail="Export storage is not available.",
        )

    export_bytes = storage.read_bytes(export.storage_key)

    actor = actor or system_actor("Evidence export download")
    AuditService.emit(
        organization_id=export.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_export.downloaded",
        object_type=AuditEvent.ObjectType.EVIDENCE_EXPORT,
        object_id=export.id,
        metadata={
            "bundle_id": str(export.bundle_id),
            "export_id": str(export.id),
            "content_sha256": export.content_sha256,
            "content_size_bytes": export.content_size_bytes,
        },
    )

    from django.db.models import F

    EvidenceExport.objects.filter(pk=export.pk).update(
        download_count=F("download_count") + 1,
        last_downloaded_at=timezone.now(),
    )

    return export_bytes


# ---------------------------------------------------------------------------
# Redaction pipeline
# ---------------------------------------------------------------------------


def _load_zip_entries(bundle_bytes: bytes) -> dict[str, bytes]:
    """Extract all ZIP entries as path -> bytes (excluding checksums.sha256)."""
    result = {}
    archive = io.BytesIO(bundle_bytes)
    with zipfile.ZipFile(archive, "r") as zf:
        for name in sorted(zf.namelist()):
            result[name] = zf.read(name)
    return result


def _apply_redaction_policy(
    source_entries: dict[str, bytes],
    *,
    policy: EvidenceRedactionPolicy | None,
) -> tuple[dict[str, bytes], dict]:
    """Apply redaction rules to a copy of source entries. Never mutates source."""
    if policy is None:
        return dict(source_entries), {
            "redacted": False,
            "policy_id": None,
            "policy_sha256": None,
            "rules_applied": 0,
            "omitted_paths": [],
            "transformed_paths": [],
            "redaction_counts": {},
        }

    entries = dict(source_entries)
    omitted_paths: list[dict] = []
    transformed_paths: list[dict] = []
    redaction_counts: dict[str, int] = {}

    for rule in policy.rules:
        action = rule.get("action", "")
        rule_id = rule.get("id", "")

        if action == "omit_path":
            path = rule.get("path", "")
            if path in entries and path not in ("manifest.json", "checksums.sha256"):
                del entries[path]
                omitted_paths.append({"path": path, "rule_id": rule_id})
                redaction_counts[action] = redaction_counts.get(action, 0) + 1

        elif action == "redact_json_pointer":
            path = rule.get("path", "")
            pointer = rule.get("pointer", "")
            if path in entries and path.endswith(".json"):
                try:
                    data = json.loads(entries[path].decode("utf-8"))
                    count = _apply_json_pointer_redaction(data, pointer)
                    if count > 0:
                        entries[path] = canonical_json_bytes(data)
                        transformed_paths.append(
                            {
                                "path": path,
                                "pointer": pointer,
                                "rule_id": rule_id,
                                "count": count,
                            }
                        )
                        redaction_counts[action] = (
                            redaction_counts.get(action, 0) + count
                        )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        elif action == "redact_ndjson_field":
            path = rule.get("path", "")
            field = rule.get("field", "")
            if path in entries and path.endswith(".ndjson"):
                try:
                    raw = entries[path].decode("utf-8")
                    count, new_bytes = _apply_ndjson_field_redaction(raw, field)
                    if count > 0:
                        entries[path] = new_bytes
                        transformed_paths.append(
                            {
                                "path": path,
                                "field": field,
                                "rule_id": rule_id,
                                "count": count,
                            }
                        )
                        redaction_counts[action] = (
                            redaction_counts.get(action, 0) + count
                        )
                except UnicodeDecodeError:
                    pass

        elif action == "artifact_metadata_only":
            keys_to_remove = [
                p for p in list(entries) if p.startswith("artifacts/files/")
            ]
            for p in keys_to_remove:
                del entries[p]
                omitted_paths.append(
                    {"path": p, "rule_id": rule_id, "reason": "artifact_metadata_only"}
                )
                redaction_counts[action] = redaction_counts.get(action, 0) + 1

        elif action == "replace_file_with_notice":
            path = rule.get("path", "")
            if path in entries and path not in ("manifest.json", "checksums.sha256"):
                original_sha256 = sha256_hexdigest(entries[path])
                notice = (
                    f"This file has been replaced by a redaction notice.\n"
                    f"source_path: {path}\n"
                    f"source_sha256: {original_sha256}\n"
                    f"redaction_policy_id: {policy.id}\n"
                    f"rule_id: {rule_id}\n"
                ).encode()
                entries[path] = notice
                transformed_paths.append(
                    {"path": path, "rule_id": rule_id, "replaced": True}
                )
                redaction_counts[action] = redaction_counts.get(action, 0) + 1

    redaction_summary = {
        "redacted": True,
        "policy_id": str(policy.id),
        "policy_sha256": policy.rules_sha256,
        "rules_applied": len(policy.rules),
        "omitted_paths": omitted_paths,
        "transformed_paths": transformed_paths,
        "redaction_counts": redaction_counts,
    }
    return entries, redaction_summary


def _apply_json_pointer_redaction(data, pointer: str) -> int:
    """Apply [REDACTED] at the given JSON Pointer (RFC 6901). Returns replacement count."""
    if not pointer or not pointer.startswith("/"):
        return 0
    parts = pointer.lstrip("/").split("/")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]

    def _redact(obj, keys):
        if not keys:
            return 0
        key = keys[0]
        remaining = keys[1:]
        if isinstance(obj, dict):
            if key in obj:
                if not remaining:
                    obj[key] = "[REDACTED]"
                    return 1
                return _redact(obj[key], remaining)
        elif isinstance(obj, list):
            try:
                idx = int(key)
                if 0 <= idx < len(obj):
                    if not remaining:
                        obj[idx] = "[REDACTED]"
                        return 1
                    return _redact(obj[idx], remaining)
            except ValueError:
                pass
        return 0

    return _redact(data, parts)


def _apply_ndjson_field_redaction(raw: str, field: str) -> tuple[int, bytes]:
    """Replace field in every NDJSON event. Preserves order. Returns (count, bytes)."""
    count = 0
    out_lines = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
            if isinstance(event, dict) and field in event:
                event[field] = "[REDACTED]"
                count += 1
            out_lines.append(canonical_json_bytes(event).decode("utf-8"))
        except json.JSONDecodeError:
            out_lines.append(stripped)
    result = "\n".join(out_lines)
    if out_lines:
        result += "\n"
    return count, result.encode("utf-8")


def _build_export_receipt(
    *, bundle, export, redaction_policy, redaction_summary
) -> dict:
    return {
        "receipt_schema_version": SCHEMA_VERSION,
        "receipt_type": "evidence_export",
        "export_id": export.id,
        "bundle_id": bundle.id,
        "bundle_version": bundle.version,
        "change_record_id": bundle.change_record_id,
        "organization_id": bundle.organization_id,
        "requested_by_user_id": export.requested_by_id,
        "requested_at": export.requested_at,
        "source_manifest_sha256": bundle.manifest_sha256,
        "source_bundle_content_sha256": bundle.content_sha256,
        "redaction_policy_id": str(redaction_policy.id) if redaction_policy else None,
        "redaction_policy_sha256": redaction_policy.rules_sha256
        if redaction_policy
        else None,
        "redaction_summary": redaction_summary,
    }


def _build_export_manifest(
    *,
    bundle,
    export,
    entries_by_path: dict[str, bytes],
    redaction_summary: dict,
    receipt_sha256: str,
) -> dict:
    entries = []
    for path in sorted(entries_by_path):
        if path in ("manifest.json", "checksums.sha256"):
            continue
        content = entries_by_path[path]
        if path.endswith(".ndjson"):
            media_type = "application/x-ndjson"
        elif path.endswith(".json"):
            media_type = "application/json"
        else:
            media_type = "application/octet-stream"
        entries.append(
            {
                "path": path,
                "media_type": media_type,
                "size_bytes": len(content),
                "sha256": sha256_hexdigest(content),
                "required": True,
                "source_refs": [],
                "redaction_state": "redacted"
                if redaction_summary["redacted"]
                else "original",
            }
        )
    return {
        "manifest_schema_version": SCHEMA_VERSION,
        "package_type": "evidence_export",
        "bundle": {
            "id": bundle.id,
            "version": bundle.version,
            "status": bundle.status,
            "manifest_sha256": bundle.manifest_sha256,
            "content_sha256": bundle.content_sha256,
        },
        "export": {
            "id": export.id,
            "requested_at": export.requested_at,
            "redaction_policy_id": str(export.redaction_policy_id)
            if export.redaction_policy_id
            else None,
        },
        "source": {
            "source_manifest_sha256": bundle.manifest_sha256,
            "source_bundle_content_sha256": bundle.content_sha256,
        },
        "redaction_summary": redaction_summary,
        "receipt_sha256": receipt_sha256,
        "algorithms": {
            "content_hash": "sha256",
            "manifest_hash": "sha256",
            "zip_method": "zip-stored",
        },
        "entries": entries,
    }


def _export_storage_key(export: EvidenceExport) -> str:
    bundle = export.bundle
    return (
        f"evidence/org/{bundle.organization_id}/change/{bundle.change_record_id}/"
        f"bundle/{bundle.id}/exports/{export.id}/export.zip"
    )


def _resolve_default_retention_policy(organization) -> EvidenceRetentionPolicy | None:
    return EvidenceRetentionPolicy.objects.filter(
        organization=organization,
        is_default=True,
        is_active=True,
    ).first()


def _bundle_retention_days(bundle: EvidenceBundle, *, invalidated: bool = False) -> int:
    policy = None
    if bundle.retention_policy_id and bundle.retention_policy is not None:
        policy = bundle.retention_policy
    if policy is None:
        policy = _resolve_default_retention_policy(bundle.organization)
    if policy is not None:
        return (
            policy.invalidated_bundle_retention_days
            if invalidated
            else policy.sealed_bundle_retention_days
        )
    return getattr(settings, "EVIDENCE_BUNDLE_RETENTION_DAYS", 2557)  # ~7 years


def _export_retention_days(bundle: EvidenceBundle) -> int:
    policy = None
    if bundle.retention_policy_id and bundle.retention_policy is not None:
        policy = bundle.retention_policy
    if policy is None:
        policy = _resolve_default_retention_policy(bundle.organization)
    if policy is not None:
        return policy.export_retention_days
    return getattr(settings, "EVIDENCE_EXPORT_RETENTION_DAYS", 30)


# ---------------------------------------------------------------------------
# Legal hold
# ---------------------------------------------------------------------------


def create_legal_hold(
    bundle: EvidenceBundle,
    *,
    reason: str,
    external_reference: str = "",
    actor: AuditActor | None = None,
    placed_by=None,
) -> LegalHold:
    """Place an active legal hold on a bundle and its source change."""
    if not reason or not reason.strip():
        raise DomainValidationError(
            code="legal_hold_reason_required",
            detail="Legal hold reason is required.",
        )

    with transaction.atomic():
        locked_bundle = (
            EvidenceBundle.objects.select_for_update()
            .select_related("change_record", "organization")
            .get(pk=bundle.pk)
        )
        existing = LegalHold.objects.filter(
            change_record=locked_bundle.change_record,
            evidence_bundle=locked_bundle,
            status=LegalHold.Status.ACTIVE,
        ).first()
        if existing:
            raise DomainConflictError(
                code="legal_hold_already_active",
                detail="An active legal hold already exists for this bundle.",
            )

        hold = LegalHold.objects.create(
            organization=locked_bundle.organization,
            change_record=locked_bundle.change_record,
            evidence_bundle=locked_bundle,
            status=LegalHold.Status.ACTIVE,
            reason=reason.strip(),
            external_reference=(external_reference or "").strip()[:512],
            placed_by=placed_by,
            placed_at=timezone.now(),
        )

        hold_id = hold.id
        transaction.on_commit(
            lambda: _emit_legal_hold_created(hold_id=hold_id, actor=actor)
        )
        return hold


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------


def _find_active_legal_hold(
    change_record, *, bundle=None, export=None
) -> LegalHold | None:
    """Return the first active legal hold covering the target, or None."""
    query = Q(change_record=change_record, status=LegalHold.Status.ACTIVE)
    if bundle is not None:
        query |= Q(evidence_bundle=bundle, status=LegalHold.Status.ACTIVE)
    if export is not None:
        query |= Q(evidence_export=export, status=LegalHold.Status.ACTIVE)
    return LegalHold.objects.filter(query).first()


def assert_no_active_legal_hold(change_record, *, bundle=None, export=None) -> None:
    """Raise DomainValidationError if any active legal hold covers the target."""
    hold = _find_active_legal_hold(change_record, bundle=bundle, export=export)
    if hold is not None:
        raise DomainValidationError(
            code="legal_hold_blocks_cleanup",
            detail=f"Active legal hold {hold.id} blocks cleanup.",
        )


def cleanup_expired_bundle_storage(
    bundle: EvidenceBundle,
    actor: AuditActor | None = None,
    now=None,
    storage: EvidenceStorage | None = None,
) -> EvidenceBundle:
    """Delete stored ZIP bytes for an expired bundle. Keeps DB row and hashes."""
    storage = storage or EvidenceStorage()
    now = now or timezone.now()

    blocking_hold_id = None
    try:
        with transaction.atomic():
            locked = (
                EvidenceBundle.objects.select_for_update()
                .select_related("change_record", "organization")
                .get(pk=bundle.pk)
            )
            if locked.storage_deleted_at is not None:
                return locked
            if locked.retention_expires_at is None or locked.retention_expires_at > now:
                raise DomainValidationError(
                    code="retention_not_expired",
                    detail="Bundle retention period has not expired.",
                )
            hold = _find_active_legal_hold(locked.change_record, bundle=locked)
            if hold is not None:
                blocking_hold_id = hold.id
                raise DomainValidationError(
                    code="legal_hold_blocks_cleanup",
                    detail=f"Active legal hold {hold.id} blocks cleanup.",
                )

            if locked.storage_key and storage.exists(locked.storage_key):
                storage.delete(locked.storage_key)

            locked.storage_deleted_at = now
            locked.storage_delete_reason = "retention_expired"
            locked.save(
                update_fields=[
                    "storage_deleted_at",
                    "storage_delete_reason",
                    "updated_at",
                ]
            )

            bundle_id = locked.id
            transaction.on_commit(
                lambda: _emit_bundle_retention_deleted(bundle_id=bundle_id, actor=actor)
            )
            return locked
    except DomainValidationError as exc:
        if exc.code == "legal_hold_blocks_cleanup" and blocking_hold_id is not None:
            _emit_retention_cleanup_blocked(
                hold_id=blocking_hold_id,
                target_type="evidence_bundle",
                target_id=str(bundle.pk),
                actor=actor,
            )
        raise


def cleanup_expired_export_storage(
    export: EvidenceExport,
    actor: AuditActor | None = None,
    now=None,
    storage: EvidenceStorage | None = None,
) -> EvidenceExport:
    """Delete stored ZIP bytes for an expired export. Keeps DB row and hashes."""
    storage = storage or EvidenceStorage()
    now = now or timezone.now()

    blocking_hold_id = None
    try:
        with transaction.atomic():
            locked = (
                EvidenceExport.objects.select_for_update()
                .select_related("bundle__change_record", "organization")
                .get(pk=export.pk)
            )
            if locked.storage_deleted_at is not None:
                return locked
            if locked.expires_at is None or locked.expires_at > now:
                raise DomainValidationError(
                    code="retention_not_expired",
                    detail="Export retention period has not expired.",
                )
            hold = _find_active_legal_hold(
                locked.bundle.change_record,
                bundle=locked.bundle,
                export=locked,
            )
            if hold is not None:
                blocking_hold_id = hold.id
                raise DomainValidationError(
                    code="legal_hold_blocks_cleanup",
                    detail=f"Active legal hold {hold.id} blocks cleanup.",
                )

            if locked.storage_key and storage.exists(locked.storage_key):
                storage.delete(locked.storage_key)

            locked.storage_deleted_at = now
            locked.save(update_fields=["storage_deleted_at", "updated_at"])

            export_id = locked.id
            transaction.on_commit(
                lambda: _emit_export_retention_deleted(export_id=export_id, actor=actor)
            )
            return locked
    except DomainValidationError as exc:
        if exc.code == "legal_hold_blocks_cleanup" and blocking_hold_id is not None:
            _emit_retention_cleanup_blocked(
                hold_id=blocking_hold_id,
                target_type="evidence_export",
                target_id=str(export.pk),
                actor=actor,
            )
        raise


def release_legal_hold(
    hold: LegalHold,
    *,
    released_by,
    release_reason: str,
    actor: AuditActor | None = None,
) -> LegalHold:
    """Release an active legal hold. Requires actor, timestamp, and nonblank reason."""
    if not release_reason or not release_reason.strip():
        raise DomainValidationError(
            code="release_reason_required",
            detail="A nonblank release reason is required.",
        )

    with transaction.atomic():
        locked = (
            LegalHold.objects.select_for_update()
            .select_related("organization", "change_record")
            .get(pk=hold.pk)
        )
        if locked.status != LegalHold.Status.ACTIVE:
            raise DomainValidationError(
                code="legal_hold_not_active",
                detail="Only active legal holds can be released.",
            )

        locked.status = LegalHold.Status.RELEASED
        locked.released_by = released_by
        locked.released_at = timezone.now()
        locked.release_reason = release_reason.strip()
        locked.save(
            update_fields=[
                "status",
                "released_by",
                "released_at",
                "release_reason",
                "updated_at",
            ]
        )

        hold_id = locked.id
        transaction.on_commit(
            lambda: _emit_legal_hold_released(hold_id=hold_id, actor=actor)
        )
        return locked


# ---------------------------------------------------------------------------
# Audit emitters for new event types
# ---------------------------------------------------------------------------


def _emit_export_created(*, export_id, actor: AuditActor | None) -> None:
    export = EvidenceExport.objects.select_related("bundle").get(pk=export_id)
    actor = actor or system_actor("Evidence export creation")
    AuditService.emit(
        organization_id=export.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_export.created",
        object_type=AuditEvent.ObjectType.EVIDENCE_EXPORT,
        object_id=export.id,
        metadata={
            "bundle_id": str(export.bundle_id),
            "redaction_policy_id": str(export.redaction_policy_id)
            if export.redaction_policy_id
            else None,
            "source_manifest_sha256": export.source_manifest_sha256,
            "content_sha256": export.content_sha256,
            "content_size_bytes": export.content_size_bytes,
            "redaction_counts": export.redaction_summary.get("redaction_counts", {}),
        },
    )


def _emit_legal_hold_created(*, hold_id, actor: AuditActor | None) -> None:
    hold = LegalHold.objects.select_related("change_record", "evidence_bundle").get(
        pk=hold_id
    )
    actor = actor or system_actor("Legal hold creation")
    AuditService.emit(
        organization_id=hold.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="legal_hold.created",
        object_type=AuditEvent.ObjectType.LEGAL_HOLD,
        object_id=hold.id,
        metadata={
            "change_record_id": str(hold.change_record_id),
            "evidence_bundle_id": str(hold.evidence_bundle_id)
            if hold.evidence_bundle_id
            else None,
            "external_reference_sha256": _hash_text(hold.external_reference),
        },
    )


def _emit_bundle_retention_deleted(*, bundle_id, actor: AuditActor | None) -> None:
    bundle = EvidenceBundle.objects.get(pk=bundle_id)
    actor = actor or system_actor("Retention cleanup")
    AuditService.emit(
        organization_id=bundle.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_bundle.retention_deleted",
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        metadata={
            "content_sha256": bundle.content_sha256,
            "retention_policy_id": str(bundle.retention_policy_id)
            if bundle.retention_policy_id
            else None,
        },
    )


def _emit_export_retention_deleted(*, export_id, actor: AuditActor | None) -> None:
    export = EvidenceExport.objects.get(pk=export_id)
    actor = actor or system_actor("Retention cleanup")
    AuditService.emit(
        organization_id=export.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence_export.retention_deleted",
        object_type=AuditEvent.ObjectType.EVIDENCE_EXPORT,
        object_id=export.id,
        metadata={
            "content_sha256": export.content_sha256,
        },
    )


def _emit_legal_hold_released(*, hold_id, actor: AuditActor | None) -> None:
    hold = LegalHold.objects.select_related("change_record").get(pk=hold_id)
    actor = actor or system_actor("Legal hold release")
    AuditService.emit(
        organization_id=hold.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="legal_hold.released",
        object_type=AuditEvent.ObjectType.LEGAL_HOLD,
        object_id=hold.id,
        metadata={
            "change_record_id": str(hold.change_record_id),
            "evidence_bundle_id": str(hold.evidence_bundle_id)
            if hold.evidence_bundle_id
            else None,
        },
    )


def _emit_retention_cleanup_blocked(
    *, hold_id, target_type: str, target_id: str, actor: AuditActor | None
) -> None:
    hold = LegalHold.objects.select_related("organization").get(pk=hold_id)
    actor = actor or system_actor("Retention cleanup")
    AuditService.emit(
        organization_id=hold.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="evidence.retention_cleanup_blocked",
        object_type=AuditEvent.ObjectType.LEGAL_HOLD,
        object_id=hold.id,
        metadata={
            "target_type": target_type,
            "target_id": target_id,
        },
    )
