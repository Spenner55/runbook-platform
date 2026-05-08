import pytest
from django.utils import timezone

from apps.auditor.models import (
    AuditorAccessGrant,
    ControlCoverageStatus,
    ControlMappingProfile,
    ControlStandard,
    ExternalReferenceType,
    ExternalSystem,
    ServiceCatalogEntry,
)
from apps.auditor.services import link_external_change_reference
from apps.changes.models import ChangeRecord, ChangeTarget, OperationProfile
from apps.evidence.models import EvidenceBundle, EvidenceBundleItem
from apps.organizations.models import Membership, MembershipRole
from apps.runbooks.models import Runbook
from apps.users.models import User
from apps.workflows.models import Workflow


def _user(email):
    return User.objects.create_user(email=email, password="s3cr3tpass!")


def _change(org, *, title, status="closed", risk="high", target="payments-prod"):
    runbook = Runbook.objects.create(
        organization=org,
        title=f"{title} runbook",
        slug=f"{org.slug}-{title.lower().replace(' ', '-')}",
        raw_content="Deploy safely",
    )
    workflow = Workflow.objects.create(
        organization=org,
        runbook=runbook,
        name=f"{title} workflow",
        version=1,
        status=Workflow.Status.PUBLISHED,
    )
    profile = OperationProfile.objects.create(
        organization=org,
        key=f"{title.lower().replace(' ', '-')}-profile",
        name=f"{title} profile",
        risk_level=risk,
    )
    change = ChangeRecord.objects.create(
        organization=org,
        operation_profile=profile,
        workflow=workflow,
        title=title,
        summary="Production maintenance",
        justification="Required",
    )
    ChangeTarget.objects.create(
        organization=org,
        change_record=change,
        position=1,
        target_type="service",
        target_identifier=target,
        normalized_identifier=target,
        display_name=target,
        environment="production",
        metadata={"service_key": target.replace("-prod", "-api")},
    )
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=status,
        closed_at=timezone.now() if status == "closed" else None,
        submitted_at=timezone.now(),
    )
    change.refresh_from_db()
    return change


def _sealed_bundle(change):
    now = timezone.now()
    bundle = EvidenceBundle.objects.create(
        organization=change.organization,
        change_record=change,
        version=1,
        status=EvidenceBundle.Status.COMPILING,
        completeness_status=EvidenceBundle.CompletenessStatus.COMPLETE,
        source_cutoff_at=now,
        manifest={"items": [{"canonical_path": "request/change_record.json"}]},
        manifest_sha256="a" * 64,
        content_sha256="b" * 64,
        content_size_bytes=128,
        storage_key=f"evidence/{change.organization_id}/{change.id}/bundle.zip",
    )
    EvidenceBundleItem.objects.create(
        organization=change.organization,
        bundle=bundle,
        item_type=EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
        item_key="change",
        canonical_path="request/change_record.json",
        position=1,
        present=True,
        valid=True,
    )
    bundle.status = EvidenceBundle.Status.SEALED
    bundle.sealed_at = now
    bundle.save()
    return bundle


@pytest.mark.django_db
def test_auditor_search_is_grant_scoped_and_filterable(org, api_client_for_org):
    auditor = _user("api-auditor@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="payments-api",
        name="Payments API",
        target_patterns=["payments-prod"],
    )
    allowed = _change(org, title="Payments closed", target="payments-prod")
    _change(org, title="Search closed", target="search-prod")
    AuditorAccessGrant.objects.create(
        organization=org,
        user=auditor,
        scope={"service_keys": ["payments-api"], "statuses": ["closed"]},
    )

    response = client.get("/api/v1/audit/changes/", {"service": "payments-api"})

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == str(allowed.id)

    response = client.get("/api/v1/audit/changes/", {"service": "search-api"})

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert response.data["results"] == []


@pytest.mark.django_db
def test_auditor_detail_returns_projection_snapshots_bundle_and_coverage(
    org, api_client_for_org
):
    auditor = _user("api-detail-auditor@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    change = _change(org, title="Audited change", target="payments-prod")
    bundle = _sealed_bundle(change)
    profile = ControlMappingProfile.objects.create(
        organization=org,
        key="soc2",
        name="SOC 2",
        standard=ControlStandard.SOC2,
        mapping_rules=[
            {
                "control_id": "CC8.1",
                "required_sections": ["request"],
                "required_item_types": ["change_snapshot"],
            }
        ],
    )
    from apps.auditor.services import recompute_change_control_coverage

    recompute_change_control_coverage(
        change_record=change,
        evidence_bundle=bundle,
        mapping_profile=profile,
    )
    link_external_change_reference(
        change_record=change,
        system=ExternalSystem.JIRA,
        reference_type=ExternalReferenceType.TICKET,
        external_id="10001",
        external_key="PROJ-123",
        snapshot={"title": "Ticket"},
    )
    AuditorAccessGrant.objects.create(organization=org, user=auditor, scope={"all": True})

    response = client.get(f"/api/v1/audit/changes/{change.id}/")

    assert response.status_code == 200
    assert response.data["id"] == str(change.id)
    assert response.data["bundle"]["status"] == EvidenceBundle.Status.SEALED
    assert response.data["external_references"][0]["snapshot"] == {"title": "Ticket"}
    assert response.data["control_coverage"][0]["coverage_status"] == (
        ControlCoverageStatus.COVERED
    )


@pytest.mark.django_db
def test_auditor_detail_returns_404_outside_grant_scope(org, api_client_for_org):
    auditor = _user("api-denied-auditor@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    change = _change(org, title="Denied change", target="search-prod")
    AuditorAccessGrant.objects.create(
        organization=org,
        user=auditor,
        scope={"target_ids": ["payments-prod"]},
    )

    response = client.get(f"/api/v1/audit/changes/{change.id}/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_auditor_cannot_mutate_admin_operator_resources(org, api_client_for_org):
    auditor = _user("api-readonly-auditor@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    AuditorAccessGrant.objects.create(organization=org, user=auditor, scope={"all": True})
    change = _change(org, title="Readonly change", target="payments-prod")

    service_response = client.post(
        "/api/v1/audit/service-catalog/",
        {"service_key": "payments-api", "name": "Payments API"},
        format="json",
    )
    grant_response = client.post(
        "/api/v1/audit/access-grants/",
        {"user_id": str(auditor.id), "scope": {"all": True}},
        format="json",
    )
    reference_response = client.post(
        f"/api/v1/changes/{change.id}/external-references/",
        {
            "system": ExternalSystem.JIRA,
            "reference_type": ExternalReferenceType.TICKET,
            "external_id": "10001",
        },
        format="json",
    )

    assert service_response.status_code == 403
    assert grant_response.status_code == 403
    assert reference_response.status_code == 403


@pytest.mark.django_db
def test_admin_can_create_and_revoke_auditor_grant(org, api_client_for_org):
    admin = _user("api-admin@example.com")
    auditor = _user("api-new-auditor@example.com")
    Membership.objects.create(organization=org, user=auditor, role=MembershipRole.VIEWER)
    client = api_client_for_org(org, role=MembershipRole.ADMIN, user=admin)

    response = client.post(
        "/api/v1/audit/access-grants/",
        {
            "user_id": str(auditor.id),
            "scope": {"statuses": ["closed"]},
            "reason": "annual audit",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == "active"

    revoke_response = client.post(
        f"/api/v1/audit/access-grants/{response.data['id']}/revoke/"
    )

    assert revoke_response.status_code == 200
    assert revoke_response.data["status"] == "revoked"
