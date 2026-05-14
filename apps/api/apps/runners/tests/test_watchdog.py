"""Tests for runner-level watchdog: liveness, lease expiry, and idempotency."""

import threading
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.common.exceptions import InvalidStateTransitionError
from apps.executions.models import Execution
from apps.executions.services import recover_stuck_executions
from apps.runners.models import ExecutionLease, Runner
from apps.runners.services import mark_stale_runners_offline, update_runner_heartbeat
from apps.runners.tests.conftest import make_runner


def _make_stale_runner(pool, *, seconds_ago: int = 200, status=Runner.Status.ACTIVE):
    runner = make_runner(pool, status=status)
    stale_at = timezone.now() - timedelta(seconds=seconds_ago)
    Runner.objects.filter(pk=runner.pk).update(
        last_heartbeat_at=stale_at,
        last_seen_at=stale_at,
    )
    return Runner.objects.get(pk=runner.pk)


def _make_fresh_runner(pool, *, seconds_ago: int = 5):
    runner = make_runner(pool)
    fresh_at = timezone.now() - timedelta(seconds=seconds_ago)
    Runner.objects.filter(pk=runner.pk).update(
        last_heartbeat_at=fresh_at,
        last_seen_at=fresh_at,
    )
    return Runner.objects.get(pk=runner.pk)


# ---------------------------------------------------------------------------
# Runner offline marking
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_stale_runner_marked_offline(pool):
    runner = _make_stale_runner(pool, seconds_ago=200)

    offline_ids = mark_stale_runners_offline(offline_threshold_seconds=120)

    assert str(runner.id) in offline_ids
    runner.refresh_from_db()
    assert runner.status == Runner.Status.OFFLINE


@pytest.mark.django_db(transaction=True)
def test_stale_draining_runner_marked_offline(pool):
    runner = _make_stale_runner(pool, seconds_ago=200, status=Runner.Status.DRAINING)

    offline_ids = mark_stale_runners_offline(offline_threshold_seconds=120)

    assert str(runner.id) in offline_ids
    runner.refresh_from_db()
    assert runner.status == Runner.Status.OFFLINE


@pytest.mark.django_db(transaction=True)
def test_fresh_runner_not_marked_offline(pool):
    runner = _make_fresh_runner(pool, seconds_ago=5)

    offline_ids = mark_stale_runners_offline(offline_threshold_seconds=120)

    assert str(runner.id) not in offline_ids
    runner.refresh_from_db()
    assert runner.status == Runner.Status.ACTIVE


@pytest.mark.django_db(transaction=True)
def test_already_offline_runner_not_processed_again(pool):
    """Calling the watchdog twice is idempotent: second sweep returns empty."""
    runner = _make_stale_runner(pool, seconds_ago=200)

    first = mark_stale_runners_offline(offline_threshold_seconds=120)
    second = mark_stale_runners_offline(offline_threshold_seconds=120)

    assert str(runner.id) in first
    assert str(runner.id) not in second
    runner.refresh_from_db()
    assert runner.status == Runner.Status.OFFLINE


@pytest.mark.django_db(transaction=True)
def test_mark_stale_runners_idempotent_concurrent(pool):
    """Two concurrent sweeps must mark each runner offline exactly once."""
    runner = _make_stale_runner(pool, seconds_ago=200)

    results: list[list[str]] = [[], []]
    barrier = threading.Barrier(2)

    def run(index: int) -> None:
        barrier.wait()
        results[index] = mark_stale_runners_offline(offline_threshold_seconds=120)

    t1 = threading.Thread(target=run, args=(0,))
    t2 = threading.Thread(target=run, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    all_marked = results[0] + results[1]
    assert all_marked.count(str(runner.id)) == 1, (
        "Runner must be marked offline exactly once across concurrent sweeps"
    )


@pytest.mark.django_db(transaction=True)
def test_mark_stale_runners_emits_audit_event(pool):
    runner = _make_stale_runner(pool, seconds_ago=200)

    mark_stale_runners_offline(offline_threshold_seconds=120)

    assert AuditEvent.objects.filter(
        event_type="runner.went_offline",
        object_id=runner.id,
    ).exists()


# ---------------------------------------------------------------------------
# Stale runner rejects heartbeat (lease expired)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_offline_runner_heartbeat_rejected(pool):
    """An OFFLINE runner cannot update its heartbeat; it must re-register."""
    runner = make_runner(pool, status=Runner.Status.OFFLINE)

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        update_runner_heartbeat(runner=runner)

    assert exc_info.value.code == "runner_lease_expired"
    runner.refresh_from_db()
    assert runner.status == Runner.Status.OFFLINE
    assert runner.last_heartbeat_at is not None  # unchanged


@pytest.mark.django_db
def test_active_runner_heartbeat_accepted(pool):
    runner = make_runner(pool, status=Runner.Status.ACTIVE)

    updated = update_runner_heartbeat(runner=runner)

    assert updated.status == Runner.Status.ACTIVE
    assert updated.last_heartbeat_at is not None


@pytest.mark.django_db
def test_draining_runner_heartbeat_accepted(pool):
    """A draining runner that is still alive must be able to heartbeat."""
    runner = make_runner(pool, status=Runner.Status.DRAINING)

    updated = update_runner_heartbeat(runner=runner)

    assert updated.status == Runner.Status.DRAINING


# ---------------------------------------------------------------------------
# Execution liveness (separate from runner liveness)
# ---------------------------------------------------------------------------


def _published_workflow(org):
    from apps.runbooks import services as rb_services
    from apps.workflows import services as wf_services
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    rb = rb_services.create_runbook(
        organization=org,
        title="Watchdog WF",
        slug=f"watchdog-wf-{org.slug}",
        raw_content="step one",
    )
    wf = wf_services.create_workflow(
        runbook=rb, transform_client=StubWorkflowTransformClient()
    )
    return wf_services.publish_workflow(workflow=wf)


def _make_stale_claimed_execution(wf, *, seconds_ago: int = 400):
    from apps.executions.services import create_execution

    execution = create_execution(workflow=wf, _from_change_service=True)
    stale_at = timezone.now() - timedelta(seconds=seconds_ago)
    Execution.objects.filter(pk=execution.pk).update(
        status=Execution.Status.CLAIMED,
        claimed_by_runner_id="runner-dead",
        claimed_at=stale_at,
        last_heartbeat_at=stale_at,
    )
    return Execution.objects.get(pk=execution.pk)


@pytest.mark.django_db(transaction=True)
def test_stale_execution_recovered_independently_of_runner(org, pool):
    """Runner can be alive while execution heartbeat is stale; execution must be recovered."""
    runner = _make_fresh_runner(pool)  # runner is alive
    assert runner.status == Runner.Status.ACTIVE

    wf = _published_workflow(org)
    execution = _make_stale_claimed_execution(wf, seconds_ago=400)

    recovered = recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.FAILED
    runner.refresh_from_db()
    assert runner.status == Runner.Status.ACTIVE  # runner unaffected


@pytest.mark.django_db(transaction=True)
def test_active_healthy_execution_not_recovered(org, pool):
    """An execution with a recent heartbeat must not be touched by the watchdog."""
    wf = _published_workflow(org)
    execution = _make_stale_claimed_execution(wf, seconds_ago=10)  # very recent

    recovered = recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) not in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.CLAIMED


# ---------------------------------------------------------------------------
# Target lock idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_execution_lease_expired_exactly_once_on_watchdog(org, pool):
    """Stale execution recovery expires the ExecutionLease exactly once."""
    from apps.executions.services import create_execution
    from apps.runners.scheduling import schedule_execution_claim

    runner = make_runner(pool)
    wf = _published_workflow(org)
    # Create a fresh queued execution so the runner can claim it
    create_execution(workflow=wf, _from_change_service=True)

    result = schedule_execution_claim(runner)
    assert result is not None
    execution = result["execution"]

    # Verify lease was created
    lease = ExecutionLease.objects.get(execution=execution)
    assert lease.status == ExecutionLease.Status.ACTIVE

    # Backdate both execution and lease heartbeat to appear stale
    stale_at = timezone.now() - timedelta(seconds=700)
    Execution.objects.filter(pk=execution.pk).update(last_heartbeat_at=stale_at)
    ExecutionLease.objects.filter(execution=execution).update(
        last_heartbeat_at=stale_at
    )

    first = recover_stuck_executions(stuck_threshold_seconds=300)
    assert str(execution.id) in first

    lease.refresh_from_db()
    assert lease.status == ExecutionLease.Status.EXPIRED
    first_released_at = lease.released_at

    # Second sweep must be a no-op for both execution and lease
    second = recover_stuck_executions(stuck_threshold_seconds=300)
    assert str(execution.id) not in second

    lease.refresh_from_db()
    assert lease.status == ExecutionLease.Status.EXPIRED
    assert lease.released_at == first_released_at


# ---------------------------------------------------------------------------
# Drain safety
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_draining_runner_execution_recovered_when_stale(org, pool):
    """A DRAINING runner's stale execution must still be recovered by the watchdog."""
    runner = _make_stale_runner(pool, seconds_ago=200, status=Runner.Status.DRAINING)

    wf = _published_workflow(org)
    execution = _make_stale_claimed_execution(wf, seconds_ago=400)

    recovered = recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.FAILED
    # runner drain status is unchanged (watchdog doesn't depend on runner status)
    runner.refresh_from_db()
    assert runner.status == Runner.Status.DRAINING  # not yet swept by runner watchdog


@pytest.mark.django_db(transaction=True)
def test_draining_runner_fresh_execution_not_recovered(org):
    """Draining status alone does not cause a healthy execution to be failed."""
    from apps.runners.models import RunnerPool

    pool = RunnerPool.objects.create(
        organization=org,
        key="drain-pool",
        name="Drain Pool",
        status=RunnerPool.Status.DRAINING,
        drain_requested_at=timezone.now(),
    )
    runner = make_runner(pool, status=Runner.Status.DRAINING)

    wf = _published_workflow(org)
    execution = _make_stale_claimed_execution(wf, seconds_ago=10)

    recovered = recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) not in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.CLAIMED
    _ = runner  # referenced for clarity


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_management_command_marks_stale_runners(pool):
    from io import StringIO

    from django.core.management import call_command

    _make_stale_runner(pool, seconds_ago=200)

    out = StringIO()
    call_command(
        "check_stuck_executions",
        runner_offline_seconds=120,
        stdout=out,
    )

    assert "Marked" in out.getvalue() and "offline" in out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_management_command_runner_watchdog_skip(pool):
    from io import StringIO

    from django.core.management import call_command

    _make_stale_runner(pool, seconds_ago=200)

    out = StringIO()
    call_command(
        "check_stuck_executions",
        skip_runner_watchdog=True,
        stdout=out,
    )

    assert "Runner watchdog skipped" in out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_management_command_no_stale_runners(pool):
    from io import StringIO

    from django.core.management import call_command

    _make_fresh_runner(pool)

    out = StringIO()
    call_command(
        "check_stuck_executions",
        runner_offline_seconds=120,
        stdout=out,
    )

    assert "No stale runners found" in out.getvalue()
