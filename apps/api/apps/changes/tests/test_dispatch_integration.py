"""Dispatch integration tests — preflight gate and target lock acquisition.

Covers:
- make_dispatchable runs fresh preflight automatically if none exists
- make_dispatchable reuses a fresh PASSED preflight check
- make_dispatchable re-runs stale (expired) preflight
- Dispatch blocked when preflight FAILS (freeze rule, target lock conflict)
- TargetLock rows created for all targets on successful dispatch
- Concurrent dispatch blocked by target lock uniqueness constraint
- Rollback: locks not persisted when dispatch fails partway through
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import (
    ChangeRecord,
    DispatchEligibilityCheck,
    FreezeRule,
    TargetLock,
)
from apps.common.exceptions import DomainConflictError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _approved_change(draft_change):
    """Submit and force-approve a change without calling make_dispatchable."""
    from apps.approvals.models import ApprovalRequest

    actor = _system_actor()
    change = change_services.submit_change_record(change=draft_change, actor=actor)
    if change.approval_request_id:
        ApprovalRequest.objects.filter(pk=change.approval_request_id).update(status="approved")
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=ChangeRecord.Status.APPROVED, approved_at=timezone.now()
    )
    change.refresh_from_db()
    return change


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_change(draft_change):
    return _approved_change(draft_change)


@pytest.fixture
def second_draft_change(org, operation_profile, published_workflow):
    """A second draft change targeting the same prod-server-01 as draft_change."""
    actor = _system_actor()
    return change_services.create_change_record(
        organization=org,
        operation_profile_key="prod-maintenance",
        workflow_id=str(published_workflow.id),
        title="Second Change",
        summary="",
        justification="Needed",
        requested_inputs={"key": "value"},
        targets=[
            {
                "target_type": "server",
                "target_identifier": "prod-server-01",
                "environment": "production",
            }
        ],
        actor=actor,
    )


@pytest.fixture
def second_approved_change(second_draft_change):
    return _approved_change(second_draft_change)


# ---------------------------------------------------------------------------
# Preflight gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_make_dispatchable_runs_preflight_if_none_exists(approved_change):
    """No prior preflight → make_dispatchable creates one automatically."""
    assert not DispatchEligibilityCheck.objects.filter(
        change_record=approved_change
    ).exists()

    change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    approved_change.refresh_from_db()
    assert approved_change.status == ChangeRecord.Status.DISPATCHABLE
    check = DispatchEligibilityCheck.objects.filter(change_record=approved_change).first()
    assert check is not None
    assert check.result == DispatchEligibilityCheck.Result.PASSED


@pytest.mark.django_db
def test_make_dispatchable_reuses_fresh_passed_preflight(approved_change):
    """Existing fresh PASSED check is reused — no duplicate check created."""
    actor = _system_actor()
    existing = change_services.run_dispatch_preflight(change=approved_change, actor=actor)

    change_services.make_dispatchable(change=approved_change, actor=actor)

    checks = list(DispatchEligibilityCheck.objects.filter(change_record=approved_change))
    assert len(checks) == 1
    assert checks[0].pk == existing.pk


@pytest.mark.django_db
def test_make_dispatchable_reruns_expired_preflight(approved_change):
    """Stale (expired) PASSED check is not reused — a fresh one is run."""
    actor = _system_actor()
    existing = change_services.run_dispatch_preflight(change=approved_change, actor=actor)
    # Expire the check
    DispatchEligibilityCheck.objects.filter(pk=existing.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    change_services.make_dispatchable(change=approved_change, actor=actor)

    checks = list(DispatchEligibilityCheck.objects.filter(change_record=approved_change))
    assert len(checks) == 2
    fresh = max(checks, key=lambda c: c.checked_at)
    assert fresh.result == DispatchEligibilityCheck.Result.PASSED


@pytest.mark.django_db
def test_make_dispatchable_blocked_when_preflight_fails(approved_change, org):
    """Active freeze rule causes preflight to fail → DomainConflictError raised."""
    now = timezone.now()
    FreezeRule.objects.create(
        organization=org,
        name="prod-freeze",
        is_active=True,
        behavior=FreezeRule.Behavior.BLOCK,
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=1),
    )

    with pytest.raises(DomainConflictError) as exc_info:
        change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    assert exc_info.value.code == "dispatch_preflight_failed"
    approved_change.refresh_from_db()
    assert approved_change.status == ChangeRecord.Status.APPROVED


# ---------------------------------------------------------------------------
# Target lock acquisition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_make_dispatchable_creates_target_locks(approved_change):
    """Successful dispatch creates ACTIVE TargetLock for each target."""
    assert not TargetLock.objects.filter(change_record=approved_change).exists()

    change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    locks = list(TargetLock.objects.filter(change_record=approved_change))
    assert len(locks) == 1
    lock = locks[0]
    assert lock.status == TargetLock.Status.ACTIVE
    assert lock.target_type == "server"
    assert lock.normalized_identifier == "prod-server-01"
    assert lock.execution_id is not None


@pytest.mark.django_db
def test_target_lock_linked_to_execution(approved_change):
    """Target lock execution FK matches the execution created for the change."""
    change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    approved_change.refresh_from_db()
    binding = approved_change.execution_binding
    lock = TargetLock.objects.get(change_record=approved_change)
    assert lock.execution_id == binding.execution_id


@pytest.mark.django_db
def test_target_lock_audit_event_emitted(approved_change):
    """change.target_lock_acquired audit event is emitted for each lock."""
    change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    lock_events = AuditEvent.objects.filter(event_type="change.target_lock_acquired")
    assert lock_events.count() == 1
    event = lock_events.first()
    assert event.metadata["target_type"] == "server"
    assert event.metadata["target_identifier"] == "prod-server-01"


# ---------------------------------------------------------------------------
# Concurrency: second dispatch blocked
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_concurrent_dispatch_blocked_by_target_lock(
    approved_change, second_approved_change
):
    """Two changes targeting the same target — second dispatch is blocked by lock."""
    actor = _system_actor()

    change_services.make_dispatchable(change=approved_change, actor=actor)

    with pytest.raises(DomainConflictError) as exc_info:
        change_services.make_dispatchable(change=second_approved_change, actor=actor)

    assert exc_info.value.code in (
        "dispatch_preflight_failed",
        "target_lock_conflict",
    )
    second_approved_change.refresh_from_db()
    assert second_approved_change.status == ChangeRecord.Status.APPROVED
    assert not TargetLock.objects.filter(change_record=second_approved_change).exists()


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_locks_rolled_back_if_execution_creation_fails(approved_change):
    """If execution creation raises, no locks are persisted (atomic rollback)."""
    from apps.executions import services as execution_services

    actor = _system_actor()

    with patch.object(
        execution_services, "create_execution", side_effect=RuntimeError("db failure")
    ):
        with pytest.raises(RuntimeError):
            change_services.make_dispatchable(change=approved_change, actor=actor)

    assert not TargetLock.objects.filter(change_record=approved_change).exists()
    approved_change.refresh_from_db()
    assert approved_change.status == ChangeRecord.Status.APPROVED


@pytest.mark.django_db
def test_dispatch_rolled_back_on_lock_conflict(approved_change, second_approved_change):
    """Partial-lock conflict rolls back execution creation too."""
    actor = _system_actor()

    # Lock the target manually so second change hits the conflict path.
    now = timezone.now()
    target = approved_change.targets.first()
    TargetLock.objects.create(
        organization=approved_change.organization,
        change_record=approved_change,
        execution=None,
        change_target=target,
        target_type=target.target_type,
        target_identifier=target.target_identifier,
        normalized_identifier=target.normalized_identifier,
        status=TargetLock.Status.ACTIVE,
        acquired_at=now,
    )

    from apps.executions.models import Execution

    before_count = Execution.objects.count()

    with pytest.raises(DomainConflictError):
        change_services.make_dispatchable(change=second_approved_change, actor=actor)

    # No orphaned execution left behind.
    assert Execution.objects.count() == before_count
    assert not TargetLock.objects.filter(change_record=second_approved_change).exists()


# ---------------------------------------------------------------------------
# API integration: submit + preflight + dispatch via approval flow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_without_approval_dispatches_with_locks(
    org, operation_profile, published_workflow
):
    """No-approval profile: submit triggers auto-dispatch including lock acquisition."""
    operation_profile.requires_approval = False
    operation_profile.save()

    actor = _system_actor()
    change = change_services.create_change_record(
        organization=org,
        operation_profile_key="prod-maintenance",
        workflow_id=str(published_workflow.id),
        title="Auto Dispatch",
        summary="",
        justification="urgent",
        requested_inputs={"key": "v"},
        targets=[
            {
                "target_type": "server",
                "target_identifier": "srv-auto",
                "environment": "production",
            }
        ],
        actor=actor,
    )
    change_services.submit_change_record(change=change, actor=actor)
    change.refresh_from_db()

    assert change.status == ChangeRecord.Status.DISPATCHABLE
    assert TargetLock.objects.filter(
        change_record=change, status=TargetLock.Status.ACTIVE
    ).count() == 1
