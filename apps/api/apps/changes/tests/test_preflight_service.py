"""Dispatch preflight service tests.

Covers: eligible, ineligible, stale, conflict, window, freeze, target-lock,
actor-authorization, API endpoints (POST run / GET latest).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import (
    ChangeException,
    ChangeRecord,
    ChangeWindow,
    DispatchEligibilityCheck,
    FreezeRule,
    TargetLock,
)
from apps.organizations.models import Membership, MembershipRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now():
    return timezone.now()


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _user_actor(user_id=None):
    """Return a SYSTEM actor that passes actor_authorized_ok without needing a real DB user."""
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test-user")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_change(draft_change):
    """Submitted change forced to APPROVED status with a valid approval_request record."""
    from apps.approvals.models import ApprovalRequest

    actor = _system_actor()
    change = change_services.submit_change_record(change=draft_change, actor=actor)
    # Approve the ApprovalRequest directly so the preflight approval check passes.
    if change.approval_request_id:
        ApprovalRequest.objects.filter(pk=change.approval_request_id).update(
            status="approved"
        )
    # Force the change status to APPROVED without calling make_dispatchable.
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=ChangeRecord.Status.APPROVED, approved_at=_now()
    )
    change.refresh_from_db()
    change_services.ensure_verification_plan(change=change, actor=actor, activate=True)
    return change


@pytest.fixture
def dispatchable_change(draft_change):
    """Change in DISPATCHABLE status via the proper approval → dispatch flow."""
    from apps.approvals import services as approval_services

    actor = _system_actor()
    change = change_services.submit_change_record(change=draft_change, actor=actor)
    ar = change.approval_request
    approval_services.decide_approval(
        approval_request=ar, decision="approved", actor=actor
    )
    change.refresh_from_db()
    return change


# ---------------------------------------------------------------------------
# Service: eligible (all checks pass)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_passes_for_approved_change(approved_change):
    actor = _user_actor()
    check = change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    assert check.result == DispatchEligibilityCheck.Result.PASSED
    assert check.approved_status_ok is True
    assert check.policy_pass_ok is True
    assert check.window_open_ok is True
    assert check.freeze_conflicts_ok is True
    assert check.target_locks_ok is True
    assert check.actor_authorized_ok is True
    assert check.conflicts == []
    assert len(check.checks) == 7
    check_names = [c["name"] for c in check.checks]
    assert check_names == [
        "approved_status",
        "policy_pass",
        "window_open",
        "freeze_conflicts",
        "target_locks",
        "actor_authorized",
        "verification_plan",
    ]


@pytest.mark.django_db
def test_preflight_persisted_as_immutable_snapshot(approved_change):
    actor = _user_actor()
    check = change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    assert check.pk is not None
    assert check.checked_at is not None
    assert check.expires_at > check.checked_at
    assert check.input_snapshot_sha256 == approved_change.request_snapshot_sha256


@pytest.mark.django_db
def test_preflight_snapshot_immutable(approved_change):
    actor = _user_actor()
    check = change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError, match="immutable"):
        check.result = DispatchEligibilityCheck.Result.FAILED
        check.save()


@pytest.mark.django_db
def test_preflight_ttl_set(approved_change):
    actor = _user_actor()
    before = _now()
    check = change_services.run_dispatch_preflight(change=approved_change, actor=actor)
    after = _now()

    assert check.expires_at >= before + timedelta(seconds=299)
    assert check.expires_at <= after + timedelta(seconds=301)


# ---------------------------------------------------------------------------
# Service: ineligible statuses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_fails_for_draft_change(draft_change):
    actor = _user_actor()
    check = change_services.run_dispatch_preflight(change=draft_change, actor=actor)

    assert check.result == DispatchEligibilityCheck.Result.FAILED
    assert check.approved_status_ok is False
    status_check = next(c for c in check.checks if c["name"] == "approved_status")
    assert "draft" in status_check["detail"]


@pytest.mark.django_db
def test_preflight_fails_for_pending_approval_change(draft_change, operation_profile):
    actor = _system_actor()
    change = change_services.submit_change_record(change=draft_change, actor=actor)
    assert change.status == ChangeRecord.Status.PENDING_APPROVAL

    user_actor = _user_actor()
    check = change_services.run_dispatch_preflight(change=change, actor=user_actor)

    assert check.result == DispatchEligibilityCheck.Result.FAILED
    assert check.approved_status_ok is False


@pytest.mark.django_db
def test_preflight_fails_for_closed_change(approved_change):
    approved_change.status = ChangeRecord.Status.CLOSED
    approved_change.closed_at = _now()
    approved_change.save(update_fields=["status", "closed_at", "updated_at"])

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.result == DispatchEligibilityCheck.Result.FAILED
    assert check.approved_status_ok is False


@pytest.mark.django_db
def test_preflight_passes_for_dispatchable_change(dispatchable_change):
    check = change_services.run_dispatch_preflight(
        change=dispatchable_change, actor=_user_actor()
    )
    assert check.approved_status_ok is True
    assert check.result == DispatchEligibilityCheck.Result.PASSED


# ---------------------------------------------------------------------------
# Service: window check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_passes_when_no_window(approved_change):
    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    window_check = next(c for c in check.checks if c["name"] == "window_open")
    assert window_check["ok"] is True
    assert "No change window" in window_check["detail"]
    assert check.window_snapshot_sha256 == ""


@pytest.mark.django_db
def test_preflight_passes_when_window_open(approved_change, org):
    now = _now()
    ChangeWindow.objects.create(
        organization=org,
        change_record=approved_change,
        starts_at=now - timedelta(minutes=30),
        ends_at=now + timedelta(hours=1),
        status=ChangeWindow.Status.OPEN,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.window_open_ok is True
    assert check.window_snapshot_sha256 != ""


@pytest.mark.django_db
def test_preflight_fails_when_window_scheduled(approved_change, org):
    now = _now()
    ChangeWindow.objects.create(
        organization=org,
        change_record=approved_change,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=4),
        status=ChangeWindow.Status.SCHEDULED,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.window_open_ok is False
    assert check.result == DispatchEligibilityCheck.Result.FAILED
    window_check = next(c for c in check.checks if c["name"] == "window_open")
    assert "scheduled" in window_check["detail"]


@pytest.mark.django_db
def test_preflight_fails_when_window_expired(approved_change, org):
    now = _now()
    ChangeWindow.objects.create(
        organization=org,
        change_record=approved_change,
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
        status=ChangeWindow.Status.EXPIRED,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.window_open_ok is False
    assert check.result == DispatchEligibilityCheck.Result.FAILED


# ---------------------------------------------------------------------------
# Service: freeze rule conflicts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_fails_when_block_freeze_active(approved_change, org):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Release Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=True,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is False
    assert check.result == DispatchEligibilityCheck.Result.FAILED
    freeze_conflicts = [c for c in check.conflicts if c["type"] == "freeze_rule"]
    assert len(freeze_conflicts) == 1
    assert freeze_conflicts[0]["behavior"] == FreezeRule.Behavior.BLOCK


@pytest.mark.django_db
def test_preflight_fails_when_allow_with_exception_no_reference(approved_change, org):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Exception Freeze",
        behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=True,
        is_active=True,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is False
    freeze_conflicts = [c for c in check.conflicts if c["type"] == "freeze_rule"]
    assert any(
        c["behavior"] == FreezeRule.Behavior.ALLOW_WITH_EXCEPTION
        for c in freeze_conflicts
    )


@pytest.mark.django_db
def test_preflight_fails_when_only_legacy_exception_reference_provided(approved_change, org):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Exception Freeze",
        behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=True,
        is_active=True,
    )
    # Provide freeze exception reference on the change
    approved_change.freeze_exception_reference = "CAB-2024-001"
    approved_change.freeze_exception_reason = "Emergency maintenance"
    approved_change.save(
        update_fields=[
            "freeze_exception_reference",
            "freeze_exception_reason",
            "updated_at",
        ]
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is False


@pytest.mark.django_db
def test_preflight_passes_when_approved_freeze_override_exception_matches_scope(
    approved_change, org
):
    now = _now()
    rule = FreezeRule.objects.create(
        organization=org,
        name="Exception Freeze",
        behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=True,
        is_active=True,
    )
    ChangeException.objects.create(
        organization=org,
        change_record=approved_change,
        exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
        status=ChangeException.Status.APPROVED,
        reason="Approved emergency freeze override",
        scope_json={
            "freeze_rule_id": str(rule.id),
            "target_ids": [
                str(tid)
                for tid in approved_change.targets.values_list("id", flat=True)
            ],
        },
        requested_at=now - timedelta(minutes=5),
        approved_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is True


@pytest.mark.django_db
def test_preflight_passes_when_freeze_inactive(approved_change, org):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Inactive Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=2),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=False,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is True


@pytest.mark.django_db
def test_preflight_freeze_scoped_to_different_target_type_does_not_conflict(
    approved_change, org
):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="DB Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.TARGET_TYPE,
        target_type="database",  # change targets "server", not "database"
        requires_exception_reference=False,
        is_active=True,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is True


@pytest.mark.django_db
def test_preflight_freeze_scoped_to_matching_target_type_conflicts(
    approved_change, org
):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Server Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.TARGET_TYPE,
        target_type="server",  # matches the change target
        requires_exception_reference=False,
        is_active=True,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is False


@pytest.mark.django_db
def test_block_freeze_wins_over_allow_with_exception_freeze(approved_change, org):
    """BLOCK freeze blocks dispatch even when change satisfies an AWE freeze's exception."""
    now = _now()
    # AWE freeze — change has an exception reference, so this one would pass on its own.
    FreezeRule.objects.create(
        organization=org,
        name="AWE Freeze",
        behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=True,
        is_active=True,
    )
    # BLOCK freeze — unconditional; exception reference must not help.
    FreezeRule.objects.create(
        organization=org,
        name="Block Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=True,
    )
    # Provide the exception reference (satisfies AWE, must not satisfy BLOCK).
    approved_change.freeze_exception_reference = "CAB-2024-999"
    approved_change.freeze_exception_reason = "Approved emergency"
    approved_change.save(
        update_fields=[
            "freeze_exception_reference",
            "freeze_exception_reason",
            "updated_at",
        ]
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )

    assert check.freeze_conflicts_ok is False
    assert check.result == DispatchEligibilityCheck.Result.FAILED
    # The BLOCK freeze must appear in conflicts.
    block_conflicts = [
        c
        for c in check.conflicts
        if c["type"] == "freeze_rule" and c["behavior"] == FreezeRule.Behavior.BLOCK
    ]
    assert len(block_conflicts) == 1
    assert block_conflicts[0]["name"] == "Block Freeze"


@pytest.mark.django_db
def test_preflight_expired_freeze_rule_does_not_conflict(approved_change, org):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Past Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=4),
        ends_at=now - timedelta(hours=1),  # already ended
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=True,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.freeze_conflicts_ok is True


# ---------------------------------------------------------------------------
# Service: target lock conflicts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_passes_when_no_active_locks(approved_change):
    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.target_locks_ok is True


@pytest.mark.django_db
def test_preflight_fails_when_conflicting_active_lock(
    approved_change, org, org_factory
):
    org_factory("other-org-lock")
    # Create a second change record in the same org (for another change)
    second_change = ChangeRecord.objects.create(
        organization=org,
        operation_profile=approved_change.operation_profile,
        workflow=approved_change.workflow,
        title="Other Change",
        summary="",
        justification="",
        status=ChangeRecord.Status.RUNNING,
    )

    TargetLock.objects.create(
        organization=org,
        change_record=second_change,
        target_type="server",
        target_identifier="prod-server-01",
        normalized_identifier="prod-server-01",
        status=TargetLock.Status.ACTIVE,
        acquired_at=_now(),
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.target_locks_ok is False
    assert check.result == DispatchEligibilityCheck.Result.FAILED
    lock_conflicts = [c for c in check.conflicts if c["type"] == "target_lock"]
    assert len(lock_conflicts) == 1
    assert lock_conflicts[0]["target_type"] == "server"
    assert lock_conflicts[0]["change_record_id"] == str(second_change.id)


@pytest.mark.django_db
def test_preflight_own_active_lock_does_not_conflict(approved_change, org):
    TargetLock.objects.create(
        organization=org,
        change_record=approved_change,
        target_type="server",
        target_identifier="prod-server-01",
        normalized_identifier="prod-server-01",
        status=TargetLock.Status.ACTIVE,
        acquired_at=_now(),
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.target_locks_ok is True


@pytest.mark.django_db
def test_preflight_released_lock_does_not_conflict(approved_change, org, org_factory):
    second_change = ChangeRecord.objects.create(
        organization=org,
        operation_profile=approved_change.operation_profile,
        workflow=approved_change.workflow,
        title="Other Change",
        summary="",
        justification="",
        status=ChangeRecord.Status.CLOSED,
    )
    TargetLock.objects.create(
        organization=org,
        change_record=second_change,
        target_type="server",
        target_identifier="prod-server-01",
        normalized_identifier="prod-server-01",
        status=TargetLock.Status.RELEASED,  # already released
        acquired_at=_now() - timedelta(hours=1),
        released_at=_now(),
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.target_locks_ok is True


# ---------------------------------------------------------------------------
# Service: actor authorization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_fails_when_no_actor(approved_change):
    check = change_services.run_dispatch_preflight(change=approved_change, actor=None)
    assert check.actor_authorized_ok is False
    assert check.result == DispatchEligibilityCheck.Result.FAILED


@pytest.mark.django_db
def test_preflight_passes_with_system_actor(approved_change):
    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_system_actor()
    )
    assert check.actor_authorized_ok is True


# ---------------------------------------------------------------------------
# Service: stale check detection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_is_not_stale_immediately_after_creation(approved_change):
    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert timezone.now() <= check.expires_at


@pytest.mark.django_db
def test_preflight_stale_when_expires_at_in_past(approved_change):
    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    # Force expires_at into the past via DB update to bypass immutability guard
    DispatchEligibilityCheck.objects.filter(pk=check.pk).update(
        expires_at=timezone.now() - timedelta(minutes=10)
    )
    check.refresh_from_db()
    assert timezone.now() > check.expires_at


# ---------------------------------------------------------------------------
# Service: multiple checks, latest selector
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_latest_preflight_returns_most_recent(approved_change):
    actor = _user_actor()
    change_services.run_dispatch_preflight(change=approved_change, actor=actor)
    second = change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    from apps.changes import selectors

    latest = selectors.get_latest_dispatch_preflight(
        change_id=approved_change.id, organization=approved_change.organization
    )
    assert latest.pk == second.pk


@pytest.mark.django_db
def test_latest_preflight_returns_none_when_no_checks(approved_change):
    from apps.changes import selectors

    result = selectors.get_latest_dispatch_preflight(
        change_id=approved_change.id, organization=approved_change.organization
    )
    assert result is None


# ---------------------------------------------------------------------------
# Service: audit event emitted
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_preflight_emits_audit_event(approved_change):
    from apps.audit.models import AuditEvent

    actor = _user_actor()
    check = change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    event = AuditEvent.objects.filter(
        event_type="change.preflight_checked",
        object_id=check.id,
    ).first()
    assert event is not None
    assert event.metadata["result"] == DispatchEligibilityCheck.Result.PASSED
    assert event.metadata["change_record_id"] == str(approved_change.id)


# ---------------------------------------------------------------------------
# Service: all checks run even when early ones fail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_all_checks_run_when_status_fails(draft_change, org):
    """All preflight checks should appear in the result even when status fails."""
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Release Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=True,
    )

    check = change_services.run_dispatch_preflight(
        change=draft_change, actor=_user_actor()
    )
    assert check.result == DispatchEligibilityCheck.Result.FAILED
    assert len(check.checks) == 7


# ---------------------------------------------------------------------------
# API: POST preflight (run)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_preflight_run_returns_201(approved_change, api_client, org, org_user):
    Membership.objects.create(
        organization=org, user=org_user, role=MembershipRole.OPERATOR
    )
    api_client.force_authenticate(user=org_user)

    url = f"/api/v1/changes/{approved_change.id}/preflight/"
    response = api_client.post(
        url,
        data={},
        content_type="application/json",
        HTTP_X_ORGANIZATION_ID=str(org.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["result"] in (
        DispatchEligibilityCheck.Result.PASSED,
        DispatchEligibilityCheck.Result.FAILED,
    )
    assert "checks" in data
    assert "conflicts" in data
    assert "is_stale" in data


@pytest.mark.django_db
def test_api_preflight_run_requires_operator_role(
    approved_change, api_client, org, org_user
):
    Membership.objects.create(
        organization=org, user=org_user, role=MembershipRole.VIEWER
    )
    api_client.force_authenticate(user=org_user)

    url = f"/api/v1/changes/{approved_change.id}/preflight/"
    response = api_client.post(
        url,
        data={},
        content_type="application/json",
        HTTP_X_ORGANIZATION_ID=str(org.id),
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_api_preflight_run_404_for_unknown_change(api_client, org, org_user):
    import uuid

    Membership.objects.create(
        organization=org, user=org_user, role=MembershipRole.OPERATOR
    )
    api_client.force_authenticate(user=org_user)

    url = f"/api/v1/changes/{uuid.uuid4()}/preflight/"
    response = api_client.post(
        url,
        data={},
        content_type="application/json",
        HTTP_X_ORGANIZATION_ID=str(org.id),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# API: GET preflight latest
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_preflight_latest_returns_most_recent(
    approved_change, api_client, org, org_user
):
    Membership.objects.create(
        organization=org, user=org_user, role=MembershipRole.VIEWER
    )
    actor = _user_actor()
    change_services.run_dispatch_preflight(change=approved_change, actor=actor)
    change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    api_client.force_authenticate(user=org_user)
    url = f"/api/v1/changes/{approved_change.id}/preflight/latest/"
    response = api_client.get(url, HTTP_X_ORGANIZATION_ID=str(org.id))
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "is_stale" in data


@pytest.mark.django_db
def test_api_preflight_latest_404_when_none_exist(
    approved_change, api_client, org, org_user
):
    Membership.objects.create(
        organization=org, user=org_user, role=MembershipRole.VIEWER
    )
    api_client.force_authenticate(user=org_user)
    url = f"/api/v1/changes/{approved_change.id}/preflight/latest/"
    response = api_client.get(url, HTTP_X_ORGANIZATION_ID=str(org.id))
    assert response.status_code == 404


@pytest.mark.django_db
def test_api_preflight_latest_requires_org_member(approved_change, api_client, org):
    from apps.users.models import User

    other_user = User.objects.create_user(
        email="outsider@example.com", password="pass1234!"
    )
    api_client.force_authenticate(user=other_user)
    url = f"/api/v1/changes/{approved_change.id}/preflight/latest/"
    response = api_client.get(url, HTTP_X_ORGANIZATION_ID=str(org.id))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Service: conflict structure correctness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_conflicts_include_freeze_rule_and_target_lock(
    approved_change, org, org_factory
):
    now = _now()
    FreezeRule.objects.create(
        organization=org,
        name="Prod Freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=True,
    )
    second_change = ChangeRecord.objects.create(
        organization=org,
        operation_profile=approved_change.operation_profile,
        workflow=approved_change.workflow,
        title="Other Change",
        summary="",
        justification="",
        status=ChangeRecord.Status.RUNNING,
    )
    TargetLock.objects.create(
        organization=org,
        change_record=second_change,
        target_type="server",
        target_identifier="prod-server-01",
        normalized_identifier="prod-server-01",
        status=TargetLock.Status.ACTIVE,
        acquired_at=now,
    )

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_user_actor()
    )
    assert check.result == DispatchEligibilityCheck.Result.FAILED

    conflict_types = {c["type"] for c in check.conflicts}
    assert "freeze_rule" in conflict_types
    assert "target_lock" in conflict_types

    freeze_conflict = next(c for c in check.conflicts if c["type"] == "freeze_rule")
    assert "id" in freeze_conflict
    assert "name" in freeze_conflict
    assert "behavior" in freeze_conflict

    lock_conflict = next(c for c in check.conflicts if c["type"] == "target_lock")
    assert "id" in lock_conflict
    assert "target_type" in lock_conflict
    assert "acquired_at" in lock_conflict
