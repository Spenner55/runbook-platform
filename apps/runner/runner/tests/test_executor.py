"""Unit tests for runner.executor — API client is mocked throughout."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from runner.executor import Executor
from runner.schemas import ClaimedExecution, ClaimedStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_step(position: int, command: str = "") -> ClaimedStep:
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="manual",
        risk_level="low",
        command=command,
        requires_approval=False,
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
        claim_token=uuid4(),
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@patch("runner.executor.time.sleep")
def test_successful_execution_calls_complete_succeeded(mock_sleep):
    client = MagicMock()
    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2)])

    executor.run(execution)

    client.complete_execution.assert_called_once()
    _, _, outcome = client.complete_execution.call_args.args
    assert outcome == "succeeded"


@patch("runner.executor.time.sleep")
def test_steps_execute_in_position_order(mock_sleep):
    client = MagicMock()
    executor = Executor(client)
    # Pass steps intentionally out of order
    steps = [make_step(3), make_step(1), make_step(2)]
    execution = make_execution(steps)
    step_by_id = {s.id: s for s in steps}

    executor.run(execution)

    # Collect step IDs that were marked "running", in call order
    running_step_ids = [
        c.args[1]
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "running"
    ]
    running_positions = [step_by_id[sid].position for sid in running_step_ids]
    assert running_positions == sorted(running_positions)


@patch("runner.executor.time.sleep")
def test_fail_step_marker_triggers_failure_path(mock_sleep):
    client = MagicMock()
    executor = Executor(client)
    execution = make_execution([make_step(1, command="FAIL_STEP")])

    executor.run(execution)

    # Step should have been marked failed
    failed_calls = [
        c for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1

    # Execution outcome should be failed
    _, _, outcome = client.complete_execution.call_args.args
    assert outcome == "failed"


@patch("runner.executor.time.sleep")
def test_failure_stops_subsequent_steps(mock_sleep):
    client = MagicMock()
    executor = Executor(client)
    execution = make_execution([
        make_step(1, command="FAIL_STEP"),
        make_step(2),
        make_step(3),
    ])

    executor.run(execution)

    # Only step 1 should have been started (marked running)
    running_calls = [
        c for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "running"
    ]
    assert len(running_calls) == 1


@patch("runner.executor.time.sleep")
def test_complete_execution_called_exactly_once(mock_sleep):
    client = MagicMock()
    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2), make_step(3)])

    executor.run(execution)

    client.complete_execution.assert_called_once()


@patch("runner.executor.time.sleep")
def test_each_step_marked_running_then_succeeded(mock_sleep):
    client = MagicMock()
    executor = Executor(client)
    steps = [make_step(1), make_step(2)]
    execution = make_execution(steps)

    executor.run(execution)

    for step in steps:
        running = [
            c for c in client.update_step.call_args_list
            if c.args[1] == step.id and c.kwargs.get("status") == "running"
        ]
        succeeded = [
            c for c in client.update_step.call_args_list
            if c.args[1] == step.id and c.kwargs.get("status") == "succeeded"
        ]
        assert len(running) == 1, f"step {step.position} not marked running"
        assert len(succeeded) == 1, f"step {step.position} not marked succeeded"
