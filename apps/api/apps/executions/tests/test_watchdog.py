import threading
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.approvals.models import ApprovalRequest
from apps.audit.models import AuditEvent
from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Watchdog Test",
        slug="watchdog-test",
        raw_content="Step one\nStep two",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


def _make_stale_claimed(published_workflow, *, seconds_ago: int = 400):
    """Create an execution that is claimed with a stale heartbeat."""
    execution = services.create_execution(workflow=published_workflow)
    stale_at = timezone.now() - timedelta(seconds=seconds_ago)
    Execution.objects.filter(pk=execution.pk).update(
        status=Execution.Status.CLAIMED,
        claimed_by_runner_id="runner-dead",
        claimed_at=stale_at,
        last_heartbeat_at=stale_at,
    )
    return Execution.objects.get(pk=execution.pk)


def _make_stale_running(published_workflow, *, seconds_ago: int = 400):
    """Create an execution that is running with a stale heartbeat and one running step."""
    execution = services.create_execution(workflow=published_workflow)
    stale_at = timezone.now() - timedelta(seconds=seconds_ago)
    Execution.objects.filter(pk=execution.pk).update(
        status=Execution.Status.RUNNING,
        claimed_by_runner_id="runner-dead",
        claimed_at=stale_at,
        started_at=stale_at,
        last_heartbeat_at=stale_at,
    )
    step = execution.steps.order_by("position").first()
    ExecutionStep.objects.filter(pk=step.pk).update(
        status=ExecutionStep.Status.RUNNING,
        started_at=stale_at,
    )
    return Execution.objects.get(pk=execution.pk)


def _make_expired_approval(published_workflow):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-approval")
    step = claimed["steps"][0]
    step.requires_approval = True
    step.step_snapshot = {**step.step_snapshot, "requiresApproval": True}
    step.save(update_fields=["requires_approval", "step_snapshot", "updated_at"])
    approval_request, _ = approval_services.request_step_approval(
        execution=claimed["execution"],
        step=step,
        runner_id="runner-approval",
        claim_token=claimed["claim_token"],
    )
    approval_request.expires_at = timezone.now() - timedelta(seconds=1)
    approval_request.save(update_fields=["expires_at", "updated_at"])
    return approval_request


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_stale_claimed_execution_becomes_failed(published_workflow):
    execution = _make_stale_claimed(published_workflow)

    recovered = services.recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.FAILED
    assert execution.finished_at is not None


@pytest.mark.django_db(transaction=True)
def test_stale_running_execution_becomes_failed(published_workflow):
    execution = _make_stale_running(published_workflow)

    recovered = services.recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.FAILED


@pytest.mark.django_db(transaction=True)
def test_running_step_becomes_failed(published_workflow):
    execution = _make_stale_running(published_workflow)

    services.recover_stuck_executions(stuck_threshold_seconds=300)

    failed_steps = execution.steps.filter(status=ExecutionStep.Status.FAILED)
    assert failed_steps.exists()
    step = failed_steps.first()
    assert "watchdog" in step.error_message
    assert step.finished_at is not None


@pytest.mark.django_db(transaction=True)
def test_fresh_heartbeat_execution_is_not_changed(published_workflow):
    """An execution with a recent heartbeat must not be recovered."""
    execution = services.create_execution(workflow=published_workflow)
    recent_at = timezone.now() - timedelta(seconds=10)
    Execution.objects.filter(pk=execution.pk).update(
        status=Execution.Status.CLAIMED,
        claimed_by_runner_id="runner-alive",
        claimed_at=recent_at,
        last_heartbeat_at=recent_at,
    )

    recovered = services.recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) not in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.CLAIMED


@pytest.mark.django_db(transaction=True)
def test_queued_execution_is_not_changed(published_workflow):
    """Queued executions (no heartbeat) are not touched by the watchdog."""
    execution = services.create_execution(workflow=published_workflow)

    recovered = services.recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) not in recovered
    execution.refresh_from_db()
    assert execution.status == Execution.Status.QUEUED


@pytest.mark.django_db(transaction=True)
def test_recover_is_idempotent(published_workflow):
    """Calling recover twice does not change an already-failed execution."""
    execution = _make_stale_claimed(published_workflow)

    first = services.recover_stuck_executions(stuck_threshold_seconds=300)
    second = services.recover_stuck_executions(stuck_threshold_seconds=300)

    assert str(execution.id) in first
    assert str(execution.id) not in second
    execution.refresh_from_db()
    assert execution.status == Execution.Status.FAILED


@pytest.mark.django_db(transaction=True)
def test_concurrent_watchdog_calls_do_not_double_process(published_workflow):
    """
    Two threads invoking recover_stuck_executions concurrently must recover
    each stuck execution exactly once.
    """
    execution = _make_stale_claimed(published_workflow)

    results: list[list[str]] = [[], []]
    barrier = threading.Barrier(2)

    def run(index: int) -> None:
        barrier.wait()
        results[index] = services.recover_stuck_executions(stuck_threshold_seconds=300)

    t1 = threading.Thread(target=run, args=(0,))
    t2 = threading.Thread(target=run, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    all_recovered = results[0] + results[1]
    assert all_recovered.count(str(execution.id)) == 1, (
        "Execution must be recovered exactly once across concurrent calls"
    )


# ---------------------------------------------------------------------------
# Management command tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_management_command_reports_recovered(published_workflow):
    from io import StringIO

    from django.core.management import call_command

    _make_stale_claimed(published_workflow)

    out = StringIO()
    call_command("check_stuck_executions", threshold_seconds=300, stdout=out)

    assert "Recovered" in out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_management_command_reports_none_when_clean(published_workflow):
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command("check_stuck_executions", threshold_seconds=300, stdout=out)

    assert "No stuck executions found" in out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_management_command_idempotent(published_workflow):
    from io import StringIO

    from django.core.management import call_command

    _make_stale_claimed(published_workflow)

    out1 = StringIO()
    call_command("check_stuck_executions", threshold_seconds=300, stdout=out1)

    out2 = StringIO()
    call_command("check_stuck_executions", threshold_seconds=300, stdout=out2)

    assert "Recovered" in out1.getvalue()
    assert "No stuck executions found" in out2.getvalue()


@pytest.mark.django_db(transaction=True)
def test_management_command_recovers_expired_approval(published_workflow):
    from io import StringIO

    from django.core.management import call_command

    approval_request = _make_expired_approval(published_workflow)

    out = StringIO()
    call_command("check_stuck_executions", threshold_seconds=300, stdout=out)

    assert "Recovered 1 expired approval(s)" in out.getvalue()
    approval_request.refresh_from_db()
    approval_request.execution.refresh_from_db()
    approval_request.step.refresh_from_db()
    assert approval_request.status == ApprovalRequest.Status.TIMED_OUT
    assert approval_request.execution.status == Execution.Status.FAILED
    assert approval_request.step.status == ExecutionStep.Status.FAILED
    assert AuditEvent.objects.filter(event_type="execution.approval_timeout").exists()


@pytest.mark.django_db(transaction=True)
def test_management_command_skip_expired_approvals(published_workflow):
    from io import StringIO

    from django.core.management import call_command

    approval_request = _make_expired_approval(published_workflow)

    out = StringIO()
    call_command(
        "check_stuck_executions",
        threshold_seconds=300,
        skip_expired_approvals=True,
        stdout=out,
    )

    assert "Expired approval recovery skipped" in out.getvalue()
    approval_request.refresh_from_db()
    assert approval_request.status == ApprovalRequest.Status.PENDING
