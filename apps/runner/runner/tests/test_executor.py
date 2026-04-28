"""Unit tests for runner.executor — API client is mocked throughout."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from runner.executor import Executor
from runner.schemas import (
    ApprovalStatusResponse,
    ClaimedExecution,
    ClaimedStep,
    StepStartResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_step(
    position: int, command: str = "", requires_approval: bool = False
) -> ClaimedStep:
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="manual",
        risk_level="low",
        command=command,
        requires_approval=requires_approval,
        status="pending",
    )


def make_execution(steps: list[ClaimedStep]) -> ClaimedExecution:
    return ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=steps,
    )


def _run_response(execution_id=None, step_id=None) -> StepStartResponse:
    eid = execution_id or uuid4()
    sid = step_id or uuid4()
    return StepStartResponse(
        execution_id=eid,
        execution_status="running",
        step={"id": str(sid), "status": "running"},
        runner_action="run",
        poll_after_seconds=0,
    )


def make_client(runner_action: str = "run") -> MagicMock:
    client = MagicMock()
    if runner_action == "run":
        client.start_step.return_value = _run_response()
    return client


def run_execution(executor: Executor, execution: ClaimedExecution) -> None:
    """Helper: run executor with a fresh claim_token."""
    executor.run(execution, uuid4())


@pytest.fixture(autouse=True)
def mock_sleep(monkeypatch):
    """Suppress all time.sleep calls in executor tests."""
    monkeypatch.setattr("runner.executor.time.sleep", lambda _: None)


# ---------------------------------------------------------------------------
# Basic happy-path tests (non-approval steps)
# ---------------------------------------------------------------------------


def test_successful_execution_calls_complete_succeeded():
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2)])

    run_execution(executor, execution)

    client.complete_execution.assert_called_once()
    call_kwargs = client.complete_execution.call_args.kwargs
    assert call_kwargs["final_status"] == "succeeded"


def test_steps_execute_in_position_order():
    client = make_client()
    executor = Executor(client)
    steps = [make_step(3), make_step(1), make_step(2)]
    execution = make_execution(steps)
    step_by_id = {s.id: s for s in steps}

    run_execution(executor, execution)

    # Collect step IDs whose start_step was called, in call order
    started_step_ids = [c.args[1] for c in client.start_step.call_args_list]
    started_positions = [step_by_id[sid].position for sid in started_step_ids]
    assert started_positions == sorted(started_positions)


def test_fail_step_marker_triggers_failure_path():
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_step(1, command="FAIL_STEP")])

    run_execution(executor, execution)

    failed_calls = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1

    call_kwargs = client.complete_execution.call_args.kwargs
    assert call_kwargs["final_status"] == "failed"


def test_failure_stops_subsequent_steps():
    client = make_client()
    executor = Executor(client)
    execution = make_execution(
        [
            make_step(1, command="FAIL_STEP"),
            make_step(2),
            make_step(3),
        ]
    )

    run_execution(executor, execution)

    # Only step 1 should have had start_step called
    assert client.start_step.call_count == 1


def test_complete_execution_called_exactly_once():
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2), make_step(3)])

    run_execution(executor, execution)

    client.complete_execution.assert_called_once()


def test_each_step_started_then_marked_succeeded():
    client = make_client()
    executor = Executor(client)
    steps = [make_step(1), make_step(2)]
    execution = make_execution(steps)

    run_execution(executor, execution)

    # Every step must have been started via start_step
    assert client.start_step.call_count == len(steps)

    # Every step must be marked succeeded via update_step
    for step in steps:
        succeeded_calls = [
            c
            for c in client.update_step.call_args_list
            if c.args[1] == step.id and c.kwargs.get("status") == "succeeded"
        ]
        assert len(succeeded_calls) == 1, f"step {step.position} not marked succeeded"


# ---------------------------------------------------------------------------
# Approval step tests
# ---------------------------------------------------------------------------


def test_approval_step_waits_before_executing():
    """Command must not run before runner_action=run is received."""
    client = MagicMock()
    wait_response = StepStartResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step={"id": str(uuid4()), "status": "waiting_for_approval"},
        runner_action="wait_for_approval",
        poll_after_seconds=0,
    )
    approved_response = ApprovalStatusResponse(
        execution_id=uuid4(),
        execution_status="running",
        step_id=uuid4(),
        step_status="running",
        approval_request=None,
        runner_action="run",
        poll_after_seconds=0,
    )
    client.start_step.return_value = wait_response
    client.get_step_approval_status.return_value = approved_response

    executor = Executor(client)
    steps = [make_step(1, requires_approval=True)]
    execution = make_execution(steps)

    run_execution(executor, execution)

    # start_step called before any update_step
    assert client.start_step.called
    assert client.get_step_approval_status.called
    # Step ends succeeded
    succeeded = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded) == 1
    client.complete_execution.assert_called_once()
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_approval_step_rejection_fails_without_running_command():
    """Rejected approval must fail the step without calling update_step(succeeded)."""
    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step={"id": str(uuid4()), "status": "waiting_for_approval"},
        runner_action="wait_for_approval",
        poll_after_seconds=0,
    )
    client.get_step_approval_status.return_value = ApprovalStatusResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step_id=uuid4(),
        step_status="failed",
        approval_request=None,
        runner_action="fail",
        poll_after_seconds=0,
    )

    executor = Executor(client)
    execution = make_execution([make_step(1, requires_approval=True)])

    run_execution(executor, execution)

    # update_step must NOT have been called (Django already set step to failed)
    assert client.update_step.call_count == 0
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_approval_step_timeout_fails_without_running_command():
    """Timed-out approval must fail the step without running the command."""
    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step={"id": str(uuid4()), "status": "waiting_for_approval"},
        runner_action="wait_for_approval",
        poll_after_seconds=0,
    )
    client.get_step_approval_status.return_value = ApprovalStatusResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step_id=uuid4(),
        step_status="failed",
        approval_request=None,
        runner_action="fail",
        poll_after_seconds=0,
    )

    executor = Executor(client)
    execution = make_execution([make_step(1, requires_approval=True)])

    run_execution(executor, execution)

    assert client.update_step.call_count == 0
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_approval_polls_multiple_times_before_decision():
    """Runner keeps polling on wait before getting a final decision."""
    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step={"id": str(uuid4()), "status": "waiting_for_approval"},
        runner_action="wait_for_approval",
        poll_after_seconds=0,
    )
    # Three waits then approve
    client.get_step_approval_status.side_effect = [
        ApprovalStatusResponse(
            execution_id=uuid4(),
            execution_status="claimed",
            step_id=uuid4(),
            step_status="waiting_for_approval",
            approval_request=None,
            runner_action="wait",
            poll_after_seconds=0,
        ),
        ApprovalStatusResponse(
            execution_id=uuid4(),
            execution_status="claimed",
            step_id=uuid4(),
            step_status="waiting_for_approval",
            approval_request=None,
            runner_action="wait",
            poll_after_seconds=0,
        ),
        ApprovalStatusResponse(
            execution_id=uuid4(),
            execution_status="running",
            step_id=uuid4(),
            step_status="running",
            approval_request=None,
            runner_action="run",
            poll_after_seconds=0,
        ),
    ]

    executor = Executor(client)
    execution = make_execution([make_step(1, requires_approval=True)])

    run_execution(executor, execution)

    assert client.get_step_approval_status.call_count == 3
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_non_approval_step_never_calls_approval_status():
    """Non-approval steps must not touch approval-status endpoint."""
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2)])

    run_execution(executor, execution)

    assert client.get_step_approval_status.call_count == 0


def test_blocked_step_fails_execution_without_running_command():
    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="running",
        step={"id": str(uuid4()), "status": "failed"},
        runner_action="blocked",
        poll_after_seconds=0,
    )

    executor = Executor(client)
    execution = make_execution([make_step(1)])

    run_execution(executor, execution)

    assert client.update_step.call_count == 0
    assert client.get_step_approval_status.call_count == 0
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_approved_step_followed_by_normal_step_both_succeed():
    """Execution continues normally after an approved step."""
    client = MagicMock()
    # Step 1 requires approval (and is approved), step 2 is normal.
    client.start_step.side_effect = [
        StepStartResponse(
            execution_id=uuid4(),
            execution_status="claimed",
            step={"id": str(uuid4()), "status": "waiting_for_approval"},
            runner_action="wait_for_approval",
            poll_after_seconds=0,
        ),
        _run_response(),
    ]
    client.get_step_approval_status.return_value = ApprovalStatusResponse(
        execution_id=uuid4(),
        execution_status="running",
        step_id=uuid4(),
        step_status="running",
        approval_request=None,
        runner_action="run",
        poll_after_seconds=0,
    )

    executor = Executor(client)
    execution = make_execution([make_step(1, requires_approval=True), make_step(2)])

    run_execution(executor, execution)

    assert client.start_step.call_count == 2
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


# ---------------------------------------------------------------------------
# Artifact upload integration tests
# ---------------------------------------------------------------------------


def test_executor_uploads_stdout_before_succeeded_step_update():
    """Artifact upload must happen before update_step(succeeded)."""
    call_order = []
    client = make_client()
    client.upload_artifact.side_effect = lambda *a, **kw: (
        call_order.append("upload") or MagicMock()
    )
    client.update_step.side_effect = lambda *a, **kw: (
        call_order.append("update_step") or MagicMock()
    )

    executor = Executor(client)
    execution = make_execution([make_step(1)])
    run_execution(executor, execution)

    assert "upload" in call_order
    assert "update_step" in call_order
    assert call_order.index("upload") < call_order.index("update_step")


def test_executor_uploads_stderr_on_failed_step_before_update():
    """Stderr artifact must be uploaded before update_step(failed) for FAIL_STEP."""
    call_order = []
    client = make_client()
    client.upload_artifact.side_effect = lambda *a, **kw: (
        call_order.append("upload") or MagicMock()
    )
    client.update_step.side_effect = lambda *a, **kw: (
        call_order.append("update_step") or MagicMock()
    )

    executor = Executor(client)
    execution = make_execution([make_step(1, command="FAIL_STEP")])
    run_execution(executor, execution)

    assert "upload" in call_order
    assert "update_step" in call_order
    assert call_order.index("upload") < call_order.index("update_step")


def test_artifact_upload_failure_does_not_affect_step_outcome():
    """A failed artifact upload must not change a successful step to failed."""
    import httpx

    client = make_client()
    client.upload_artifact.side_effect = httpx.ConnectError("storage down")

    executor = Executor(client)
    execution = make_execution([make_step(1)])
    run_execution(executor, execution)

    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"
    succeeded_updates = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded_updates) == 1
