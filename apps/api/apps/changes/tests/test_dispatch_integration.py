"""Dispatch integration tests — preflight gate and target lock acquisition.

Covers:
- make_dispatchable runs fresh preflight automatically if none exists
- make_dispatchable reuses a fresh PASSED preflight check
- make_dispatchable re-runs stale (expired) preflight
- Dispatch blocked when preflight FAILS (freeze rule, target lock conflict)
- Dispatch blocked when ChangeWindow is SCHEDULED (not yet open)
- Dispatch blocked when ChangeWindow is EXPIRED (never started)
- schedule_or_make_dispatchable transitions to SCHEDULED when scheduled_for is future
- Stale PASSED preflight reruns when expired; new failing conditions block dispatch
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
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeWindow,
    DispatchEligibilityCheck,
    FreezeRule,
    TargetLock,
)
from apps.common.exceptions import DomainConflictError
from apps.runners.models import RunnerPool, TargetConnectivityRoute
from apps.runners.scheduling import schedule_execution_claim
from apps.runners.tests.conftest import make_runner

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
        ApprovalRequest.objects.filter(pk=change.approval_request_id).update(
            status="approved"
        )
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=ChangeRecord.Status.APPROVED, approved_at=timezone.now()
    )
    change.refresh_from_db()
    return change


def _make_pool(org, key="prod-pool", *, max_concurrent_executions=2):
    return RunnerPool.objects.create(
        organization=org,
        key=key,
        name=key,
        environment="production",
        status=RunnerPool.Status.ACTIVE,
        max_concurrent_executions=max_concurrent_executions,
        capabilities=["action.shell_command", "action.http_request"],
    )


def _make_route(org, pool, *, target_type="server", pattern="*"):
    return TargetConnectivityRoute.objects.create(
        organization=org,
        pool=pool,
        environment="production",
        target_type=target_type,
        normalized_identifier_pattern=pattern,
        is_active=True,
    )


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
    check = DispatchEligibilityCheck.objects.filter(
        change_record=approved_change
    ).first()
    assert check is not None
    assert check.result == DispatchEligibilityCheck.Result.PASSED


@pytest.mark.django_db
def test_make_dispatchable_reuses_fresh_passed_preflight(approved_change):
    """Existing fresh PASSED check is reused — no duplicate check created."""
    actor = _system_actor()
    # Phase 11.3: preflight now checks for a verification plan. Ensure one
    # exists before running the manual preflight so it passes.
    change_services.ensure_verification_plan(change=approved_change, actor=actor)
    existing = change_services.run_dispatch_preflight(
        change=approved_change, actor=actor
    )

    change_services.make_dispatchable(change=approved_change, actor=actor)

    checks = list(
        DispatchEligibilityCheck.objects.filter(change_record=approved_change)
    )
    assert len(checks) == 1
    assert checks[0].pk == existing.pk


@pytest.mark.django_db
def test_make_dispatchable_reruns_expired_preflight(approved_change):
    """Stale (expired) PASSED check is not reused — a fresh one is run."""
    actor = _system_actor()
    existing = change_services.run_dispatch_preflight(
        change=approved_change, actor=actor
    )
    # Expire the check
    DispatchEligibilityCheck.objects.filter(pk=existing.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    change_services.make_dispatchable(change=approved_change, actor=actor)

    checks = list(
        DispatchEligibilityCheck.objects.filter(change_record=approved_change)
    )
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
def test_make_dispatchable_persists_matched_runner_pool_on_execution(
    approved_change, org
):
    pool = _make_pool(org, key="prod-routed")
    _make_route(org, pool)
    make_runner(pool, fingerprint="fp-dispatch-route")

    change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    binding = ChangeExecutionBinding.objects.get(change_record=approved_change)
    binding.execution.refresh_from_db()
    assert binding.execution.runner_pool_key == pool.key


@pytest.mark.django_db
def test_pool_disabled_after_dispatch_prevents_unclaimed_execution_claim(
    approved_change, org
):
    pool = _make_pool(org, key="prod-routed")
    _make_route(org, pool)
    runner = make_runner(pool, fingerprint="fp-disabled-after-dispatch")

    change_services.make_dispatchable(change=approved_change, actor=_system_actor())
    binding = ChangeExecutionBinding.objects.get(change_record=approved_change)

    pool.status = RunnerPool.Status.DISABLED
    pool.disabled_at = timezone.now()
    pool.save(update_fields=["status", "disabled_at", "updated_at"])

    with pytest.raises(Exception) as exc_info:
        schedule_execution_claim(runner)

    assert getattr(exc_info.value, "code", "") == "pool_not_active"
    binding.execution.refresh_from_db()
    assert binding.execution.status == "queued"


@pytest.mark.django_db
def test_cross_pool_target_change_fails_dispatch_preflight(
    org, operation_profile, published_workflow
):
    draft = change_services.create_change_record(
        organization=org,
        operation_profile_key=operation_profile.key,
        workflow_id=str(published_workflow.id),
        title="Cross-pool Change",
        summary="",
        justification="Needed",
        requested_inputs={"key": "value"},
        targets=[
            {
                "target_type": "server",
                "target_identifier": "prod-server-01",
                "environment": "production",
            },
            {
                "target_type": "server",
                "target_identifier": "prod-server-02",
                "environment": "production",
            },
        ],
        actor=_system_actor(),
    )
    approved_change = _approved_change(draft)
    pool_a = _make_pool(org, key="prod-a")
    pool_b = _make_pool(org, key="prod-b")
    _make_route(org, pool_a, pattern="prod-server-01")
    _make_route(org, pool_b, pattern="prod-server-02")
    make_runner(pool_a, fingerprint="fp-cross-a")
    make_runner(pool_b, fingerprint="fp-cross-b")

    check = change_services.run_dispatch_preflight(
        change=approved_change, actor=_system_actor()
    )
    assert check.runner_pool_ok is False
    assert check.runner_pool_reason == "multi_pool_unsupported"

    with pytest.raises(DomainConflictError) as exc_info:
        change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    assert exc_info.value.code == "dispatch_preflight_failed"


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
    assert (
        TargetLock.objects.filter(
            change_record=change, status=TargetLock.Status.ACTIVE
        ).count()
        == 1
    )


# ---------------------------------------------------------------------------
# Window-blocked dispatch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_make_dispatchable_blocked_when_window_scheduled(approved_change, org):
    """SCHEDULED window (future) blocks dispatch via preflight window check."""
    now = timezone.now()
    ChangeWindow.objects.create(
        organization=org,
        change_record=approved_change,
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(hours=4),
        status=ChangeWindow.Status.SCHEDULED,
    )

    with pytest.raises(DomainConflictError) as exc_info:
        change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    assert exc_info.value.code == "dispatch_preflight_failed"
    approved_change.refresh_from_db()
    assert approved_change.status == ChangeRecord.Status.APPROVED
    assert not ChangeExecutionBinding.objects.filter(
        change_record=approved_change
    ).exists()


@pytest.mark.django_db
def test_make_dispatchable_blocked_when_window_expired(approved_change, org):
    """EXPIRED window (past, change never started) blocks dispatch — never-started guard."""
    now = timezone.now()
    ChangeWindow.objects.create(
        organization=org,
        change_record=approved_change,
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
        status=ChangeWindow.Status.EXPIRED,
    )

    with pytest.raises(DomainConflictError) as exc_info:
        change_services.make_dispatchable(change=approved_change, actor=_system_actor())

    assert exc_info.value.code == "dispatch_preflight_failed"
    approved_change.refresh_from_db()
    assert approved_change.status == ChangeRecord.Status.APPROVED
    assert not ChangeExecutionBinding.objects.filter(
        change_record=approved_change
    ).exists()


# ---------------------------------------------------------------------------
# schedule_or_make_dispatchable — future scheduled_for → SCHEDULED
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_schedule_or_make_dispatchable_goes_to_scheduled_with_future_scheduled_for(
    org, operation_profile, published_workflow
):
    """When scheduled_for is in the future the change goes to SCHEDULED, not DISPATCHABLE."""
    from apps.approvals.models import ApprovalRequest

    actor = _system_actor()
    now = timezone.now()
    change = change_services.create_change_record(
        organization=org,
        operation_profile_key="prod-maintenance",
        workflow_id=str(published_workflow.id),
        title="Scheduled Change",
        summary="",
        justification="Needed",
        requested_inputs={"key": "value"},
        scheduled_for=now + timedelta(hours=2),
        targets=[
            {
                "target_type": "server",
                "target_identifier": "srv-sched-01",
                "environment": "production",
            }
        ],
        actor=actor,
    )
    change = change_services.submit_change_record(change=change, actor=actor)
    if change.approval_request_id:
        ApprovalRequest.objects.filter(pk=change.approval_request_id).update(
            status="approved"
        )
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=ChangeRecord.Status.APPROVED, approved_at=now
    )
    change.refresh_from_db()

    change_services.schedule_or_make_dispatchable(change=change, actor=actor)

    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.SCHEDULED
    assert not ChangeExecutionBinding.objects.filter(change_record=change).exists()
    assert not TargetLock.objects.filter(change_record=change).exists()


# ---------------------------------------------------------------------------
# Stale preflight is re-run; new failing conditions block dispatch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_stale_passed_preflight_reruns_when_conditions_change_and_fails(
    approved_change, org
):
    """Expired PASSED preflight is discarded; re-run fails when a freeze is added."""
    actor = _system_actor()

    # Phase 11.3: preflight now checks for a verification plan; create it first.
    change_services.ensure_verification_plan(change=approved_change, actor=actor)

    # 1. Run preflight — passes.
    existing = change_services.run_dispatch_preflight(
        change=approved_change, actor=actor
    )
    assert existing.result == DispatchEligibilityCheck.Result.PASSED

    # 2. Expire the check so make_dispatchable must re-run it.
    DispatchEligibilityCheck.objects.filter(pk=existing.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    # 3. Add a BLOCK freeze rule after the original check passed.
    now = timezone.now()
    FreezeRule.objects.create(
        organization=org,
        name="Post-preflight freeze",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=2),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
        is_active=True,
    )

    # 4. make_dispatchable re-runs preflight → new check fails → dispatch blocked.
    # The new check is created inside the atomic block and rolled back with the
    # DomainConflictError, so we cannot observe it after the fact. What matters
    # is that the stale PASSED check did NOT allow dispatch to proceed.
    with pytest.raises(DomainConflictError) as exc_info:
        change_services.make_dispatchable(change=approved_change, actor=actor)

    assert exc_info.value.code == "dispatch_preflight_failed"
    approved_change.refresh_from_db()
    # Change is still APPROVED — the expired PASSED preflight did not bypass the gate.
    assert approved_change.status == ChangeRecord.Status.APPROVED
    # No binding or locks were created (transaction rolled back cleanly).
    assert not ChangeExecutionBinding.objects.filter(
        change_record=approved_change
    ).exists()
    assert not TargetLock.objects.filter(change_record=approved_change).exists()

    # Verify the stale check was not used by confirming that running a fresh preflight
    # now returns a FAILED result (freeze rule is still active).
    fresh_check = change_services.run_dispatch_preflight(
        change=approved_change, actor=actor
    )
    assert fresh_check.result == DispatchEligibilityCheck.Result.FAILED
    assert fresh_check.freeze_conflicts_ok is False
