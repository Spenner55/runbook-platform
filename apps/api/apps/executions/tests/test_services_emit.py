"""
Milestone 3: verify execution_event_bus.emit() is called at the correct
state-transition points in services.py.

All tests are synchronous (pytest-django TestCase style). The real emit() is
a no-op in sync test environments (no ASGI loop), so we patch it to a
MagicMock to inspect call arguments without needing an event loop.
"""
from unittest.mock import patch

import pytest

from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient

_EMIT_PATH = "apps.executions.services.execution_event_bus.emit"

RUNNER_ID = "test-runner-1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Emit Test Runbook",
        slug="emit-test",
        raw_content="Step one\nStep two",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def queued_execution(published_workflow):
    return services.create_execution(workflow=published_workflow)


@pytest.fixture
def claimed_execution(queued_execution):
    result = services.claim_next_execution(runner_id=RUNNER_ID)
    assert result is not None
    return result  # dict with 'execution', 'steps', 'claim_token'


# ---------------------------------------------------------------------------
# claim_next_execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_next_emits_status_changed(queued_execution):
    with patch(_EMIT_PATH) as mock_emit:
        result = services.claim_next_execution(runner_id=RUNNER_ID)

    assert result is not None
    assert mock_emit.call_count == 1
    exec_id, event = mock_emit.call_args[0]
    assert exec_id == str(result["execution"].id)
    assert event.event_type == "execution.status_changed"
    assert event.data["status"] == Execution.Status.CLAIMED
    assert event.data["started_at"] is None
    assert event.data["finished_at"] is None


@pytest.mark.django_db
def test_claim_next_empty_queue_does_not_emit():
    """No queued executions → no emit."""
    with patch(_EMIT_PATH) as mock_emit:
        result = services.claim_next_execution(runner_id=RUNNER_ID)

    assert result is None
    mock_emit.assert_not_called()


# ---------------------------------------------------------------------------
# update_execution_step
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_step_emits_step_status_changed(claimed_execution):
    execution = claimed_execution["execution"]
    step = claimed_execution["steps"][0]
    claim_token = claimed_execution["claim_token"]

    with patch(_EMIT_PATH) as mock_emit:
        services.update_execution_step(
            execution=execution,
            step_id=str(step.id),
            runner_id=RUNNER_ID,
            claim_token=claim_token,
            new_status=ExecutionStep.Status.RUNNING,
        )

    # At minimum one call with step.status_changed
    step_calls = [
        c for c in mock_emit.call_args_list if c[0][1].event_type == "step.status_changed"
    ]
    assert len(step_calls) == 1
    _, event = step_calls[0][0]
    assert event.data["step_id"] == str(step.id)
    assert event.data["status"] == ExecutionStep.Status.RUNNING
    assert event.data["execution_id"] == str(execution.id)


@pytest.mark.django_db
def test_update_step_emits_execution_running_on_first_step(claimed_execution):
    """First step going RUNNING must emit both step.status_changed AND execution.status_changed."""
    execution = claimed_execution["execution"]
    step = claimed_execution["steps"][0]
    claim_token = claimed_execution["claim_token"]

    with patch(_EMIT_PATH) as mock_emit:
        services.update_execution_step(
            execution=execution,
            step_id=str(step.id),
            runner_id=RUNNER_ID,
            claim_token=claim_token,
            new_status=ExecutionStep.Status.RUNNING,
        )

    event_types = [c[0][1].event_type for c in mock_emit.call_args_list]
    assert "step.status_changed" in event_types
    assert "execution.status_changed" in event_types

    exec_events = [c for c in mock_emit.call_args_list if c[0][1].event_type == "execution.status_changed"]
    assert len(exec_events) == 1
    _, ev = exec_events[0][0]
    assert ev.data["status"] == Execution.Status.RUNNING


@pytest.mark.django_db
def test_update_step_does_not_emit_execution_running_on_subsequent_step(claimed_execution):
    """Second step going RUNNING must emit only step.status_changed (execution already RUNNING)."""
    execution = claimed_execution["execution"]
    steps = claimed_execution["steps"]
    claim_token = claimed_execution["claim_token"]

    # Start step 1 (triggers CLAIMED→RUNNING)
    services.update_execution_step(
        execution=execution,
        step_id=str(steps[0].id),
        runner_id=RUNNER_ID,
        claim_token=claim_token,
        new_status=ExecutionStep.Status.RUNNING,
    )
    # Complete step 1
    services.update_execution_step(
        execution=execution,
        step_id=str(steps[0].id),
        runner_id=RUNNER_ID,
        claim_token=claim_token,
        new_status=ExecutionStep.Status.SUCCEEDED,
    )

    with patch(_EMIT_PATH) as mock_emit:
        services.update_execution_step(
            execution=execution,
            step_id=str(steps[1].id),
            runner_id=RUNNER_ID,
            claim_token=claim_token,
            new_status=ExecutionStep.Status.RUNNING,
        )

    event_types = [c[0][1].event_type for c in mock_emit.call_args_list]
    assert event_types == ["step.status_changed"]


# ---------------------------------------------------------------------------
# complete_execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_complete_execution_emits_status_and_closed(claimed_execution):
    execution = claimed_execution["execution"]
    claim_token = claimed_execution["claim_token"]

    with patch(_EMIT_PATH) as mock_emit:
        services.complete_execution(
            execution=execution,
            runner_id=RUNNER_ID,
            claim_token=claim_token,
            outcome=Execution.Status.SUCCEEDED,
        )

    event_types = [c[0][1].event_type for c in mock_emit.call_args_list]
    assert "execution.status_changed" in event_types
    assert "stream.closed" in event_types

    status_event = next(c[0][1] for c in mock_emit.call_args_list if c[0][1].event_type == "execution.status_changed")
    assert status_event.data["status"] == Execution.Status.SUCCEEDED

    closed_event = next(c[0][1] for c in mock_emit.call_args_list if c[0][1].event_type == "stream.closed")
    assert closed_event.data["final_status"] == Execution.Status.SUCCEEDED
    assert closed_event.data["reason"] == "terminal_state"


@pytest.mark.django_db
def test_complete_execution_failed_emits_status_and_closed(claimed_execution):
    execution = claimed_execution["execution"]
    claim_token = claimed_execution["claim_token"]

    with patch(_EMIT_PATH) as mock_emit:
        services.complete_execution(
            execution=execution,
            runner_id=RUNNER_ID,
            claim_token=claim_token,
            outcome=Execution.Status.FAILED,
        )

    event_types = [c[0][1].event_type for c in mock_emit.call_args_list]
    assert "execution.status_changed" in event_types
    assert "stream.closed" in event_types

    status_event = next(c[0][1] for c in mock_emit.call_args_list if c[0][1].event_type == "execution.status_changed")
    assert status_event.data["status"] == Execution.Status.FAILED


# ---------------------------------------------------------------------------
# cancel_execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cancel_execution_emits_status_and_closed(queued_execution):
    with patch(_EMIT_PATH) as mock_emit:
        services.cancel_execution(execution=queued_execution)

    event_types = [c[0][1].event_type for c in mock_emit.call_args_list]
    assert "execution.status_changed" in event_types
    assert "stream.closed" in event_types

    status_event = next(c[0][1] for c in mock_emit.call_args_list if c[0][1].event_type == "execution.status_changed")
    assert status_event.data["status"] == Execution.Status.CANCELLED

    closed_event = next(c[0][1] for c in mock_emit.call_args_list if c[0][1].event_type == "stream.closed")
    assert closed_event.data["final_status"] == Execution.Status.CANCELLED
    assert closed_event.data["reason"] == "terminal_state"


# ---------------------------------------------------------------------------
# heartbeat_execution — must NOT emit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_emit_not_called_on_heartbeat(claimed_execution):
    execution = claimed_execution["execution"]
    claim_token = claimed_execution["claim_token"]

    with patch(_EMIT_PATH) as mock_emit:
        services.heartbeat_execution(
            execution=execution,
            runner_id=RUNNER_ID,
            claim_token=claim_token,
        )

    mock_emit.assert_not_called()
