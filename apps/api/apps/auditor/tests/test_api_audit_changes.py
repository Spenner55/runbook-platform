import pytest
from django.utils import timezone

from apps.approvals.models import ApprovalDecision, ApprovalRequest
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
from apps.changes.models import (
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    OperationProfile,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
)
from apps.evidence.models import EvidenceBundle, EvidenceBundleItem
from apps.executions.models import Execution
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


def _set_audit_dates(change, *, submitted_at=None, created_at=None):
    updates = {}
    if submitted_at is not None:
        updates["submitted_at"] = submitted_at
    else:
        updates["submitted_at"] = None
    if created_at is not None:
        updates["created_at"] = created_at
    ChangeRecord.objects.filter(pk=change.pk).update(**updates)
    change.refresh_from_db()
    return change


def _approve_change(change, *, approver=None, label=""):
    request = ApprovalRequest.objects.create(
        organization=change.organization,
        subject_type=ApprovalRequest.SubjectType.CHANGE_RECORD,
        subject_id=change.id,
        status=ApprovalRequest.Status.APPROVED,
        requested_by_runner_id="runner-a",
        requested_at=timezone.now(),
        resolved_at=timezone.now(),
    )
    ApprovalDecision.objects.create(
        approval_request=request,
        decision=ApprovalDecision.Decision.APPROVED,
        source_type=ApprovalDecision.SourceType.HUMAN,
        decided_by_user=approver,
        decided_by_label=label,
        decided_at=timezone.now(),
    )
    ChangeRecord.objects.filter(pk=change.pk).update(
        approval_request=request,
        approved_at=timezone.now(),
    )
    change.refresh_from_db()
    return request


def _bind_runner(change, *, runner_id):
    execution = Execution.objects.create(
        organization=change.organization,
        workflow=change.workflow,
        workflow_version=change.workflow.version,
        workflow_snapshot={"name": change.workflow.name},
        status=Execution.Status.CLAIMED,
        claimed_by_runner_id=runner_id,
        claimed_at=timezone.now(),
    )
    ChangeExecutionBinding.objects.create(
        organization=change.organization,
        change_record=change,
        execution=execution,
        operation_profile_key=change.operation_profile.key,
        requested_inputs_sha256=change.requested_inputs_sha256 or "0" * 64,
        dispatch_token_nonce=f"nonce-{change.id}",
        dispatch_token_hash="hash",
        dispatch_token_expires_at=timezone.now() + timezone.timedelta(minutes=10),
        reserved_at=timezone.now(),
        bound_at=timezone.now(),
        bound_by_runner_id=runner_id,
    )


def _add_user_verification(change, *, user):
    plan = VerificationPlan.objects.create(
        organization=change.organization,
        change_record=change,
        operation_profile=change.operation_profile,
        mode=VerificationPlan.Mode.MANUAL,
        status=VerificationPlan.Status.ACTIVE,
        generated_from_profile_sha256="1" * 64,
    )
    check = VerificationCheck.objects.create(
        organization=change.organization,
        plan=plan,
        change_record=change,
        position=1,
        key=f"manual-{change.id}",
        name="Manual verification",
        check_type=VerificationCheck.CheckType.MANUAL_ATTESTATION,
        verification_key="manual.operator",
    )
    return VerificationResult.objects.create(
        organization=change.organization,
        change_record=change,
        plan=plan,
        verification_check=check,
        source=VerificationResult.Source.USER,
        outcome=VerificationResult.Outcome.PASSED,
        validation_status=VerificationResult.ValidationStatus.ACCEPTED,
        submitted_by=user,
    )


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
def test_auditor_search_filters_by_approver_and_executor(org, api_client_for_org):
    auditor = _user("api-filter-auditor@example.com")
    approver = _user("approval-filter@example.com")
    executor = _user("executor-filter@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    Membership.objects.create(organization=org, user=approver, role=MembershipRole.OPERATOR)
    Membership.objects.create(organization=org, user=executor, role=MembershipRole.OPERATOR)
    approved = _change(org, title="Approved by user", target="payments-prod")
    runner_executed = _change(org, title="Executed by runner", target="search-prod")
    user_executed = _change(org, title="Executed by user", target="ledger-prod")
    _approve_change(approved, approver=approver)
    _bind_runner(runner_executed, runner_id="runner-prod-7")
    _add_user_verification(user_executed, user=executor)
    AuditorAccessGrant.objects.create(organization=org, user=auditor, scope={"all": True})

    approver_response = client.get("/api/v1/audit/changes/", {"approver": "approval-filter"})
    runner_response = client.get("/api/v1/audit/changes/", {"executor": "runner-prod-7"})
    user_response = client.get("/api/v1/audit/changes/", {"executor": "executor-filter"})

    assert approver_response.status_code == 200
    assert [row["id"] for row in approver_response.data["results"]] == [str(approved.id)]
    assert runner_response.status_code == 200
    assert [row["id"] for row in runner_response.data["results"]] == [
        str(runner_executed.id)
    ]
    assert user_response.status_code == 200
    assert [row["id"] for row in user_response.data["results"]] == [str(user_executed.id)]


@pytest.mark.django_db
def test_auditor_search_approver_executor_filters_do_not_widen_grant_scope(
    org, api_client_for_org
):
    auditor = _user("api-filter-scoped-auditor@example.com")
    approver = _user("approver-out-of-scope@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    Membership.objects.create(organization=org, user=approver, role=MembershipRole.OPERATOR)
    _approve_change(_change(org, title="Out of scope", target="search-prod"), approver=approver)
    AuditorAccessGrant.objects.create(
        organization=org,
        user=auditor,
        scope={"target_ids": ["payments-prod"]},
    )

    response = client.get("/api/v1/audit/changes/", {"approver": "approver-out-of-scope"})

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert response.data["results"] == []


@pytest.mark.django_db
def test_auditor_search_date_filters_use_submitted_at_with_created_at_fallback(
    org, api_client_for_org
):
    auditor = _user("api-date-auditor@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)
    window_start = timezone.datetime(2026, 5, 2, tzinfo=timezone.get_current_timezone())
    window_end = timezone.datetime(2026, 5, 3, tzinfo=timezone.get_current_timezone())
    submitted_inside = _set_audit_dates(
        _change(org, title="Submitted inside", target="payments-prod"),
        submitted_at=window_start,
        created_at=window_start - timezone.timedelta(days=30),
    )
    fallback_inside = _set_audit_dates(
        _change(org, title="Fallback inside", target="search-prod"),
        submitted_at=None,
        created_at=window_start + timezone.timedelta(hours=1),
    )
    _set_audit_dates(
        _change(org, title="Submitted outside", target="ledger-prod"),
        submitted_at=window_start - timezone.timedelta(seconds=1),
        created_at=window_start + timezone.timedelta(hours=2),
    )
    _set_audit_dates(
        _change(org, title="Fallback outside", target="billing-prod"),
        submitted_at=None,
        created_at=window_end + timezone.timedelta(seconds=1),
    )
    AuditorAccessGrant.objects.create(organization=org, user=auditor, scope={"all": True})

    response = client.get(
        "/api/v1/audit/changes/",
        {"start_date": window_start.isoformat(), "end_date": window_end.isoformat()},
    )

    assert response.status_code == 200
    assert response.data["meta"]["date_basis"] == "submitted_at_with_created_at_fallback"
    assert {row["id"] for row in response.data["results"]} == {
        str(submitted_inside.id),
        str(fallback_inside.id),
    }
    basis_by_id = {row["id"]: row["audit_date_basis"] for row in response.data["results"]}
    assert basis_by_id[str(submitted_inside.id)] == "submitted_at"
    assert basis_by_id[str(fallback_inside.id)] == "created_at"


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


@pytest.mark.django_db
def test_admin_can_use_blueprint_alias_for_auditor_grants(org, api_client_for_org):
    admin = _user("api-admin-alias@example.com")
    auditor = _user("api-alias-auditor@example.com")
    Membership.objects.create(organization=org, user=auditor, role=MembershipRole.VIEWER)
    client = api_client_for_org(org, role=MembershipRole.ADMIN, user=admin)

    create_response = client.post(
        "/api/v1/auditor-access-grants/",
        {"user_id": str(auditor.id), "scope": {"all": True}},
        format="json",
    )
    list_response = client.get("/api/v1/auditor-access-grants/")

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.data["results"]] == [
        create_response.data["id"]
    ]


@pytest.mark.django_db
def test_auditor_grant_alias_enforces_same_permissions(org, api_client_for_org):
    auditor = _user("api-alias-denied-auditor@example.com")
    client = api_client_for_org(org, role=MembershipRole.VIEWER, user=auditor)

    list_response = client.get("/api/v1/auditor-access-grants/")
    create_response = client.post(
        "/api/v1/auditor-access-grants/",
        {"user_id": str(auditor.id), "scope": {"all": True}},
        format="json",
    )

    assert list_response.status_code == 403
    assert create_response.status_code == 403


@pytest.mark.django_db
def test_admin_cannot_create_auditor_grant_for_non_member(org, api_client_for_org):
    admin = _user("api-admin-non-member@example.com")
    outsider = _user("api-outsider@example.com")
    client = api_client_for_org(org, role=MembershipRole.ADMIN, user=admin)

    response = client.post(
        "/api/v1/audit/access-grants/",
        {"user_id": str(outsider.id), "scope": {"all": True}},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["errors"][0]["code"] == "auditor_user_not_organization_member"


@pytest.mark.django_db
def test_admin_cannot_create_auditor_grant_for_member_of_different_org(
    org, api_client_for_org
):
    admin = _user("api-admin-other-member@example.com")
    other_org = org.__class__.objects.create(name="Other Org", slug="other-grants")
    other_member = _user("api-other-member@example.com")
    Membership.objects.create(
        organization=other_org,
        user=other_member,
        role=MembershipRole.VIEWER,
    )
    client = api_client_for_org(org, role=MembershipRole.ADMIN, user=admin)

    response = client.post(
        "/api/v1/audit/access-grants/",
        {"user_id": str(other_member.id), "scope": {"all": True}},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["errors"][0]["code"] == "auditor_user_not_organization_member"
