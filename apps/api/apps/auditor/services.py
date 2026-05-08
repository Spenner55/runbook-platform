from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService
from apps.auditor.coverage import recompute_control_coverage
from apps.auditor.external_clients import get_refresh_client
from apps.auditor.models import (
    AuditorAccessGrant,
    AuditorGrantStatus,
    ExternalChangeReference,
    ExternalReferenceType,
    ExternalSystem,
    ServiceCatalogEntry,
    SnapshotSource,
    SnapshotStatus,
    canonical_json_sha256,
    sanitize_external_snapshot,
)
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.evidence.models import EvidenceBundle


def create_service_catalog_entry(
    *,
    organization,
    service_key: str,
    name: str,
    actor: AuditActor | None = None,
    created_by=None,
    **fields,
) -> ServiceCatalogEntry:
    try:
        service = ServiceCatalogEntry.objects.create(
            organization=organization,
            service_key=service_key,
            name=name,
            created_by=created_by,
            updated_by=created_by,
            **fields,
        )
    except IntegrityError as exc:
        raise DomainConflictError(
            code="service_catalog_entry_exists",
            detail="A service catalog entry with this key already exists.",
            attr="service_key",
        ) from exc
    _emit(
        organization_id=organization.id,
        actor=actor,
        event_type="service_catalog_entry.created",
        object_type=AuditEvent.ObjectType.SERVICE_CATALOG_ENTRY,
        object_id=service.id,
        metadata={"service_key": service.service_key},
    )
    return service


def update_service_catalog_entry(
    *,
    service: ServiceCatalogEntry,
    actor: AuditActor | None = None,
    updated_by=None,
    **fields,
) -> ServiceCatalogEntry:
    allowed_fields = {
        "name",
        "description",
        "owner_team",
        "business_owner",
        "criticality",
        "environment",
        "target_patterns",
        "metadata",
        "is_active",
    }
    for field, value in fields.items():
        if field not in allowed_fields:
            raise DomainValidationError(
                code="unsupported_service_field",
                detail=f"Unsupported service catalog field: {field}.",
                attr=field,
            )
        setattr(service, field, value)
    service.updated_by = updated_by
    service.save()
    _emit(
        organization_id=service.organization_id,
        actor=actor,
        event_type="service_catalog_entry.updated",
        object_type=AuditEvent.ObjectType.SERVICE_CATALOG_ENTRY,
        object_id=service.id,
        metadata={"service_key": service.service_key},
    )
    return service


def list_service_catalog_entries(*, organization, include_inactive: bool = False):
    from apps.auditor.selectors import service_catalog_queryset

    return service_catalog_queryset(
        organization=organization,
        include_inactive=include_inactive,
    )


@transaction.atomic
def link_external_change_reference(
    *,
    change_record,
    system: str,
    reference_type: str,
    external_id: str,
    snapshot: dict | None = None,
    actor: AuditActor | None = None,
    linked_by=None,
    external_key: str = "",
    display_label: str = "",
    external_url: str = "",
    notes: str = "",
    snapshot_source: str = SnapshotSource.MANUAL,
) -> ExternalChangeReference:
    if system not in ExternalSystem.values:
        raise DomainValidationError(
            code="unsupported_external_system",
            detail="Unsupported external reference system.",
            attr="system",
        )
    if reference_type not in ExternalReferenceType.values:
        raise DomainValidationError(
            code="unsupported_external_reference_type",
            detail="Unsupported external reference type.",
            attr="reference_type",
        )
    display_label = display_label or external_key or external_id
    if ExternalChangeReference.objects.filter(
        organization=change_record.organization,
        change_record=change_record,
        system=system,
        reference_type=reference_type,
        external_id=external_id,
    ).exists():
        raise DomainConflictError(
            code="external_reference_exists",
            detail="This external reference is already linked to the change.",
            attr="external_id",
        )
    try:
        reference = ExternalChangeReference.objects.create(
            organization=change_record.organization,
            change_record=change_record,
            system=system,
            reference_type=reference_type,
            external_id=external_id,
            external_key=external_key,
            display_label=display_label,
            external_url=external_url,
            snapshot=snapshot or {},
            snapshot_source=snapshot_source,
            snapshot_status=SnapshotStatus.CURRENT,
            snapshot_taken_at=timezone.now() if snapshot else None,
            linked_by=linked_by,
            notes=notes,
        )
    except IntegrityError as exc:
        raise DomainConflictError(
            code="external_reference_exists",
            detail="This external reference is already linked to the change.",
            attr="external_id",
        ) from exc
    except ValidationError as exc:
        raise DomainValidationError(
            code="invalid_external_reference",
            detail="External reference is invalid.",
            attr=_validation_attr(exc),
        ) from exc

    _emit(
        organization_id=reference.organization_id,
        actor=actor,
        event_type="external_change_reference.linked",
        object_type=AuditEvent.ObjectType.EXTERNAL_CHANGE_REFERENCE,
        object_id=reference.id,
        metadata={
            "change_record_id": str(change_record.id),
            "system": reference.system,
            "reference_type": reference.reference_type,
            "external_key": reference.external_key,
            "snapshot_sha256": reference.snapshot_sha256,
        },
    )
    return reference


@transaction.atomic
def refresh_external_change_reference(
    *,
    reference: ExternalChangeReference,
    actor: AuditActor | None = None,
    refreshed_by=None,
    client=None,
) -> ExternalChangeReference:
    client = client or get_refresh_client(system=reference.system)
    reference.last_refresh_attempted_at = timezone.now()
    try:
        refreshed = client.fetch_snapshot(reference=reference)
        reference.snapshot = sanitize_external_snapshot(refreshed.snapshot)
        reference.snapshot_sha256 = canonical_json_sha256(reference.snapshot)
        reference.snapshot_source = SnapshotSource.API_REFRESH
        reference.snapshot_status = SnapshotStatus.CURRENT
        reference.snapshot_taken_at = timezone.now()
        reference.last_refresh_error_code = ""
        if refreshed.external_key:
            reference.external_key = refreshed.external_key
        if refreshed.external_url:
            reference.external_url = refreshed.external_url
        if refreshed.display_label:
            reference.display_label = refreshed.display_label
        reference.save()
    except Exception as exc:
        reference.snapshot_status = SnapshotStatus.REFRESH_FAILED
        reference.last_refresh_error_code = type(exc).__name__[:64]
        reference.save()
        raise

    _emit(
        organization_id=reference.organization_id,
        actor=actor,
        event_type="external_change_reference.refreshed",
        object_type=AuditEvent.ObjectType.EXTERNAL_CHANGE_REFERENCE,
        object_id=reference.id,
        metadata={
            "system": reference.system,
            "reference_type": reference.reference_type,
            "snapshot_sha256": reference.snapshot_sha256,
        },
    )
    return reference


def create_auditor_access_grant(
    *,
    organization,
    user,
    scope: dict,
    actor: AuditActor | None = None,
    created_by=None,
    reason: str = "",
    starts_at=None,
    expires_at=None,
) -> AuditorAccessGrant:
    grant = AuditorAccessGrant.objects.create(
        organization=organization,
        user=user,
        scope=scope,
        reason=reason,
        starts_at=starts_at,
        expires_at=expires_at,
        created_by=created_by,
    )
    _emit(
        organization_id=organization.id,
        actor=actor,
        event_type="auditor_access_grant.created",
        object_type=AuditEvent.ObjectType.AUDITOR_ACCESS_GRANT,
        object_id=grant.id,
        metadata={"scope_keys": sorted(scope.keys())},
    )
    return grant


def revoke_auditor_access_grant(
    *,
    grant: AuditorAccessGrant,
    actor: AuditActor | None = None,
    revoked_by=None,
) -> AuditorAccessGrant:
    grant.status = AuditorGrantStatus.REVOKED
    grant.revoked_at = timezone.now()
    grant.revoked_by = revoked_by
    grant.save()
    _emit(
        organization_id=grant.organization_id,
        actor=actor,
        event_type="auditor_access_grant.revoked",
        object_type=AuditEvent.ObjectType.AUDITOR_ACCESS_GRANT,
        object_id=grant.id,
        metadata={"scope_keys": sorted(grant.scope.keys())},
    )
    return grant


def recompute_change_control_coverage(
    *,
    change_record,
    mapping_profile,
    evidence_bundle=None,
    computed_by=None,
    actor: AuditActor | None = None,
):
    bundle = evidence_bundle or _latest_sealed_bundle(change_record=change_record)
    if bundle is None:
        raise DomainValidationError(
            code="sealed_bundle_required",
            detail="Control coverage requires a sealed evidence bundle.",
            attr="evidence_bundle",
        )
    if bundle.change_record_id != change_record.id:
        raise DomainValidationError(
            code="bundle_change_mismatch",
            detail="Evidence bundle must belong to the selected change.",
            attr="evidence_bundle",
        )
    coverages = recompute_control_coverage(
        evidence_bundle=bundle,
        mapping_profile=mapping_profile,
        computed_by=computed_by,
    )
    _emit(
        organization_id=change_record.organization_id,
        actor=actor,
        event_type="control_coverage.recomputed",
        object_type=AuditEvent.ObjectType.CHANGE_CONTROL_COVERAGE,
        object_id=change_record.id,
        metadata={
            "change_record_id": str(change_record.id),
            "evidence_bundle_id": str(bundle.id),
            "mapping_profile_id": str(mapping_profile.id),
            "coverage_count": len(coverages),
            "fingerprints": [
                coverage.coverage_fingerprint_sha256 for coverage in coverages
            ],
        },
    )
    return coverages


def _latest_sealed_bundle(*, change_record):
    return (
        EvidenceBundle.objects.filter(
            organization=change_record.organization,
            change_record=change_record,
            status=EvidenceBundle.Status.SEALED,
        )
        .order_by("-version", "-created_at")
        .first()
    )


def _emit(*, actor: AuditActor | None, **kwargs):
    if actor is None:
        return None
    return AuditService.emit(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        **kwargs,
    )


def _validation_attr(exc: ValidationError) -> str | None:
    if hasattr(exc, "message_dict"):
        return next(iter(exc.message_dict), None)
    return None
