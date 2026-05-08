import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService, system_actor
from apps.auditor.models import (
    AuditorAccessGrant,
    AuditorGrantStatus,
    ChangeControlCoverage,
    ControlCoverageStatus,
    ControlMappingProfile,
    ControlStandard,
    ExternalChangeReference,
    ExternalReferenceType,
    ExternalSystem,
    ServiceCatalogEntry,
)
from apps.auditor.services import (
    create_control_mapping_profile,
    create_service_catalog_entry,
    update_control_mapping_profile,
    update_service_catalog_entry,
)
from apps.changes.models import ChangeRecord, OperationProfile
from apps.evidence.models import EvidenceBundle
from apps.organizations.models import Organization
from apps.runbooks.models import Runbook
from apps.users.models import User
from apps.workflows.models import Workflow


def _user(email="auditor@example.com"):
    return User.objects.create_user(email=email, password="s3cr3tpass!")


def _org(slug="auditor-org"):
    return Organization.objects.create(name=slug, slug=slug)


def _change(organization, *, title="Audited change"):
    runbook = Runbook.objects.create(
        organization=organization,
        title=f"{title} runbook",
        slug=f"{organization.slug}-{title.lower().replace(' ', '-')}",
        raw_content="Deploy safely",
    )
    workflow = Workflow.objects.create(
        organization=organization,
        runbook=runbook,
        name=f"{title} workflow",
        version=1,
        status=Workflow.Status.PUBLISHED,
    )
    profile = OperationProfile.objects.create(
        organization=organization,
        key=f"{organization.slug}-prod-change",
        name="Production change",
        risk_level="high",
    )
    return ChangeRecord.objects.create(
        organization=organization,
        operation_profile=profile,
        workflow=workflow,
        title=title,
        summary="Production maintenance",
        justification="Required",
    )


def _sealed_bundle(change):
    now = timezone.now()
    return EvidenceBundle.objects.create(
        organization=change.organization,
        change_record=change,
        version=1,
        status=EvidenceBundle.Status.SEALED,
        completeness_status=EvidenceBundle.CompletenessStatus.COMPLETE,
        source_cutoff_at=now,
        sealed_at=now,
        manifest_sha256="a" * 64,
        content_sha256="b" * 64,
        content_size_bytes=128,
        storage_key=f"evidence/{change.organization_id}/{change.id}/bundle.zip",
    )


def _mapping_profile(organization):
    return ControlMappingProfile.objects.create(
        organization=organization,
        key="soc2-change-controls",
        name="SOC 2 change controls",
        standard=ControlStandard.SOC2,
        mapping_rules=[
            {
                "control_id": "CC8.1",
                "control_title": "Change authorization",
                "required_sections": ["request", "approval"],
            }
        ],
    )


@pytest.mark.django_db
def test_external_reference_sanitizes_snapshot_and_hashes(org):
    change = _change(org)
    reference = ExternalChangeReference.objects.create(
        organization=org,
        change_record=change,
        system=ExternalSystem.JIRA,
        reference_type=ExternalReferenceType.TICKET,
        external_id="10001",
        external_key="PROJ-123",
        display_label="Jira PROJ-123",
        external_url="https://jira.example.com/browse/PROJ-123",
        snapshot={
            "title": "Production change ticket",
            "authorization": "Bearer secret",
            "source_fields": {
                "state": "Done",
                "api_token": "secret",
            },
        },
    )

    assert reference.snapshot == {
        "title": "Production change ticket",
        "source_fields": {"state": "Done"},
    }
    assert len(reference.snapshot_sha256) == 64
    assert reference.snapshot_taken_at is not None


@pytest.mark.django_db
def test_external_reference_rejects_cross_org_change(org):
    other_org = _org("other-auditor-org")
    change = _change(other_org, title="Other change")

    with pytest.raises(ValidationError):
        ExternalChangeReference.objects.create(
            organization=org,
            change_record=change,
            system=ExternalSystem.JIRA,
            reference_type=ExternalReferenceType.TICKET,
            external_id="10001",
            display_label="Jira PROJ-123",
        )


@pytest.mark.django_db
def test_external_reference_rejects_credential_bearing_url(org):
    change = _change(org)

    with pytest.raises(ValidationError):
        ExternalChangeReference.objects.create(
            organization=org,
            change_record=change,
            system=ExternalSystem.JIRA,
            reference_type=ExternalReferenceType.TICKET,
            external_id="10001",
            display_label="Jira PROJ-123",
            external_url="https://user:password@jira.example.com/browse/PROJ-123",
        )


@pytest.mark.django_db
def test_external_reference_unique_per_change_system_type_and_id(org):
    change = _change(org)
    kwargs = {
        "organization": org,
        "change_record": change,
        "system": ExternalSystem.SERVICENOW,
        "reference_type": ExternalReferenceType.TICKET,
        "external_id": "CHG001",
        "display_label": "CHG001",
    }
    ExternalChangeReference.objects.create(**kwargs)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ExternalChangeReference.objects.create(**kwargs)


@pytest.mark.django_db
def test_service_catalog_entry_constraints_and_validation(org):
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="payments-api",
        name="Payments API",
        target_patterns=["server:prod-api-01"],
        metadata={"tier": "critical"},
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ServiceCatalogEntry.objects.create(
                organization=org,
                service_key="payments-api",
                name="Duplicate",
            )

    with pytest.raises(ValidationError):
        ServiceCatalogEntry.objects.create(
            organization=org,
            service_key="unsafe-pattern",
            name="Unsafe Pattern",
            target_patterns=[{"query": "https://cmdb.example.com/search"}],
        )


@pytest.mark.django_db
def test_service_catalog_entry_create_update_deactivate_emit_audit_events(org):
    actor = system_actor("service catalog audit test")

    service = create_service_catalog_entry(
        organization=org,
        service_key="checkout-api",
        name="Checkout API",
        actor=actor,
    )
    update_service_catalog_entry(
        service=service,
        actor=actor,
        owner_team="platform",
    )
    update_service_catalog_entry(
        service=service,
        actor=actor,
        is_active=False,
    )

    events = list(
        AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.SERVICE_CATALOG_ENTRY,
            object_id=service.id,
        ).order_by("occurred_at")
    )

    assert [event.event_type for event in events] == [
        "service_catalog_entry.created",
        "service_catalog_entry.updated",
        "service_catalog_entry.deactivated",
    ]
    assert all(event.metadata == {"service_key": "checkout-api"} for event in events)


@pytest.mark.django_db
def test_control_mapping_profile_enforces_standard_and_active_uniqueness(org):
    _mapping_profile(org)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ControlMappingProfile.objects.create(
                organization=org,
                key="soc2-change-controls",
                name="Duplicate active SOC 2 profile",
                standard=ControlStandard.SOC2,
                version=2,
                mapping_rules=[{"control_id": "CC8.2"}],
            )

    with pytest.raises(ValidationError):
        ControlMappingProfile.objects.create(
            organization=org,
            key="bad-rules",
            name="Bad Rules",
            standard=ControlStandard.SOC2,
            mapping_rules=[{"control_id": "CC8.1", "python": "lambda x: x"}],
        )


@pytest.mark.django_db
def test_control_mapping_profile_create_update_deactivate_emit_audit_events(org):
    actor = system_actor("control mapping audit test")

    profile = create_control_mapping_profile(
        organization=org,
        key="iso-change-controls",
        name="ISO change controls",
        standard=ControlStandard.ISO27001,
        version=1,
        mapping_rules=[{"control_id": "A.8.32"}],
        actor=actor,
    )
    update_control_mapping_profile(
        profile=profile,
        actor=actor,
        description="Updated profile",
    )
    update_control_mapping_profile(
        profile=profile,
        actor=actor,
        is_active=False,
    )

    events = list(
        AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.CONTROL_MAPPING_PROFILE,
            object_id=profile.id,
        ).order_by("occurred_at")
    )

    assert [event.event_type for event in events] == [
        "control_mapping_profile.created",
        "control_mapping_profile.updated",
        "control_mapping_profile.deactivated",
    ]
    assert all(
        event.metadata == {
            "key": "iso-change-controls",
            "standard": ControlStandard.ISO27001,
            "version": 1,
            "mapping_rule_count": 1,
        }
        for event in events
    )


@pytest.mark.django_db
def test_change_control_coverage_requires_same_org_sealed_bundle_and_matching_profile(
    org,
):
    change = _change(org)
    bundle = _sealed_bundle(change)
    profile = _mapping_profile(org)

    coverage = ChangeControlCoverage.objects.create(
        organization=org,
        change_record=change,
        evidence_bundle=bundle,
        mapping_profile=profile,
        standard=ControlStandard.SOC2,
        control_id="CC8.1",
        control_title="Change authorization",
        coverage_status=ControlCoverageStatus.COVERED,
        matched_sections=["request", "approval"],
        missing_sections=[],
        evidence_paths=["change/change_record.json"],
        coverage_fingerprint_sha256="c" * 64,
    )

    assert str(coverage) == "CC8.1 [covered]"


@pytest.mark.django_db
def test_change_control_coverage_rejects_unsealed_bundle(org):
    change = _change(org)
    bundle = EvidenceBundle.objects.create(
        organization=org,
        change_record=change,
        version=1,
        source_cutoff_at=timezone.now(),
    )
    profile = _mapping_profile(org)

    with pytest.raises(ValidationError):
        ChangeControlCoverage.objects.create(
            organization=org,
            change_record=change,
            evidence_bundle=bundle,
            mapping_profile=profile,
            standard=ControlStandard.SOC2,
            control_id="CC8.1",
            coverage_status=ControlCoverageStatus.NOT_COVERED,
            coverage_fingerprint_sha256="c" * 64,
        )


@pytest.mark.django_db
def test_auditor_grant_scope_is_read_only_and_explicit(org):
    user = _user()
    grant = AuditorAccessGrant.objects.create(
        organization=org,
        user=user,
        scope={
            "service_keys": ["payments-api"],
            "statuses": ["closed", "verified"],
            "include_exceptions": False,
        },
        reason="External audit sample",
    )

    assert grant.status == AuditorGrantStatus.ACTIVE

    with pytest.raises(ValidationError):
        AuditorAccessGrant.objects.create(
            organization=org,
            user=user,
            scope={"service_keys": []},
        )

    with pytest.raises(ValidationError):
        AuditorAccessGrant.objects.create(
            organization=org,
            user=user,
            scope={"can_approve": True, "service_keys": ["payments-api"]},
        )


@pytest.mark.django_db
def test_revoked_auditor_grant_requires_revoked_at(org):
    user = _user()

    with pytest.raises(ValidationError):
        AuditorAccessGrant.objects.create(
            organization=org,
            user=user,
            status=AuditorGrantStatus.REVOKED,
            scope={"all": True},
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "object_type,event_type",
    [
        (
            AuditEvent.ObjectType.EXTERNAL_CHANGE_REFERENCE,
            "external_change_reference.linked",
        ),
        (
            AuditEvent.ObjectType.SERVICE_CATALOG_ENTRY,
            "service_catalog_entry.created",
        ),
        (
            AuditEvent.ObjectType.CONTROL_MAPPING_PROFILE,
            "control_mapping_profile.created",
        ),
        (
            AuditEvent.ObjectType.CHANGE_CONTROL_COVERAGE,
            "control_coverage.recomputed",
        ),
        (
            AuditEvent.ObjectType.AUDITOR_ACCESS_GRANT,
            "auditor_access_grant.created",
        ),
    ],
)
def test_audit_service_accepts_auditor_object_types(org, object_type, event_type):
    actor = system_actor("auditor model test")

    event = AuditService.emit(
        organization_id=org.id,
        actor_type=actor.actor_type,
        actor_label=actor.actor_label,
        event_type=event_type,
        object_type=object_type,
        object_id=org.id,
        metadata={"scope_summary": "soc2"},
    )

    assert event.object_type == object_type
