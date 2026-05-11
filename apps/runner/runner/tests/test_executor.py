"""Unit tests for runner.executor — API client is mocked throughout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from runner.executor import Executor
from runner.sandbox.base import CapturedStream, SandboxResult
from runner.executor import _HeartbeatThread
from runner.schemas import (
    ApprovalStatusResponse,
    BreakglassSessionFacts,
    ClaimedExecution,
    ClaimedStep,
    HeartbeatResponse,
    RunnerSettings,
    StepStartResponse,
    VerificationResultResponse,
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


def make_change_execution(steps: list[ClaimedStep]) -> ClaimedExecution:
    return ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=steps,
        change_record_id=uuid4(),
        dispatch_token="dispatch-token",
        requested_inputs_sha256="a" * 64,
        operation_profile_key="prod-maintenance",
        verification_plan_id=uuid4(),
        verification_keys=[
            {
                "check_key": "runner-health-check",
                "verification_key": "postdeploy.health.ok",
                "step_key": "step-1",
                "check_type": "runner_step",
            }
        ],
    )


def make_breakglass_change_execution(steps: list[ClaimedStep]) -> ClaimedExecution:
    execution = make_change_execution(steps)
    now = datetime.now(tz=UTC)
    execution.breakglass = BreakglassSessionFacts(
        breakglass_session_id=uuid4(),
        scope_sha256="a" * 64,
        scope_summary="actions=continue_running gates=policy_override targets=1",
        started_at=now,
        expires_at=now + timedelta(minutes=30),
        review_due_at=now + timedelta(hours=24),
    )
    return execution


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


def test_resumed_execution_skips_completed_steps():
    client = make_client()
    executor = Executor(client)
    completed = make_step(1)
    completed.status = "succeeded"
    pending = make_step(2)
    execution = make_execution([completed, pending])

    run_execution(executor, execution)

    client.start_step.assert_called_once()
    assert client.start_step.call_args.args[1] == pending.id
    client.complete_execution.assert_called_once()
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


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


def test_executor_emits_verification_fact_when_step_metadata_exists():
    client = make_client()
    client.submit_verification_result.return_value = VerificationResultResponse(
        result_id=uuid4(),
        check_id=uuid4(),
        validation_status="accepted",
        check_status="passed",
        plan_status="satisfied",
        change_status="verified",
        accepted=True,
    )

    executor = Executor(client)
    execution = make_change_execution([make_step(1)])
    run_execution(executor, execution)

    client.submit_verification_result.assert_called_once()
    call = client.submit_verification_result.call_args
    assert call.args[0] == execution.change_record_id
    assert call.args[1] == execution.id
    assert call.kwargs["check_key"] == "runner-health-check"
    assert call.kwargs["outcome"] == "passed"
    assert call.kwargs["verification_key"] == "postdeploy.health.ok"
    assert call.kwargs["step_key"] == "step-1"
    assert call.kwargs["observed_value"]["exit_code"] == 0


def test_executor_observes_breakglass_session_for_change_execution():
    client = make_client()
    executor = Executor(client)
    execution = make_breakglass_change_execution([make_step(1)])
    claim_token = uuid4()

    executor.run(execution, claim_token)

    client.breakglass_heartbeat.assert_called_once_with(
        execution.change_record_id,
        claim_token,
        execution.breakglass.breakglass_session_id,
        execution.breakglass.scope_sha256,
    )


def test_executor_skips_verification_callback_without_metadata():
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_step(1)])

    run_execution(executor, execution)

    client.submit_verification_result.assert_not_called()


def test_executor_does_not_treat_callback_response_as_final_authority():
    client = make_client()
    client.submit_verification_result.return_value = VerificationResultResponse(
        result_id=uuid4(),
        check_id=uuid4(),
        validation_status="accepted",
        check_status="passed",
        plan_status="satisfied",
        change_status="verified",
        accepted=True,
    )

    executor = Executor(client)
    execution = make_change_execution([make_step(1)])
    run_execution(executor, execution)

    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"
    assert not hasattr(client, "close_change") or client.close_change.call_count == 0


# ---------------------------------------------------------------------------
# Sandboxed execution tests
# ---------------------------------------------------------------------------


def _empty_stream(content: bytes = b"") -> CapturedStream:
    return CapturedStream(
        content=content,
        truncated=False,
        original_size_bytes=len(content),
        captured_size_bytes=len(content),
    )


def make_sandbox_result(
    *,
    exit_code: int = 0,
    timed_out: bool = False,
    cancelled: bool = False,
    failure_kind: str = "",
    error_message: str = "",
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> SandboxResult:
    now = datetime.now(tz=UTC)
    return SandboxResult(
        provider="local_process",
        sandbox_run_id="test-run-1",
        started_at=now,
        finished_at=now,
        exit_code=exit_code,
        timed_out=timed_out,
        cancelled=cancelled,
        failure_kind=failure_kind,
        error_message=error_message,
        stdout=_empty_stream(stdout),
        stderr=_empty_stream(stderr),
        artifacts=[],
        metadata={},
    )


def make_mock_provider(result: SandboxResult) -> MagicMock:
    provider = MagicMock()
    provider.name = "local_process"
    provider.validate.return_value = None
    provider.execute.return_value = result
    provider.cleanup.return_value = None
    return provider


def make_sandboxed_settings(workspace_root: str) -> RunnerSettings:
    return RunnerSettings(
        api_base_url="http://api:8000",
        runner_id="test-runner",
        registration_token="test-token-secret",
        execution_mode="sandboxed",
        sandbox_provider="local_process",
        sandbox_workspace_root=workspace_root,
    )


def make_command_step(
    position: int,
    command: str = "echo hello",
    *,
    step_snapshot: dict | None = None,
) -> ClaimedStep:
    snapshot = step_snapshot if step_snapshot is not None else {"id": f"step-{position}", "command": command}
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="command",
        risk_level="low",
        command=command,
        status="pending",
        step_snapshot=snapshot,
    )


def make_unsupported_step(position: int) -> ClaimedStep:
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="manual",
        risk_level="low",
        command="",
        status="pending",
    )


def test_sandboxed_start_gate_called_before_execution(tmp_path):
    """start_step must be called before provider.execute in sandboxed mode."""
    call_order = []
    client = MagicMock()
    client.start_step.side_effect = lambda *a, **kw: (
        call_order.append("start_step") or _run_response()
    )
    mock_provider = make_mock_provider(make_sandbox_result(stdout=b"ok\n"))
    mock_provider.execute.side_effect = lambda *a, **kw: (
        call_order.append("execute") or make_sandbox_result(stdout=b"ok\n")
    )

    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1)])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    assert "start_step" in call_order
    assert "execute" in call_order
    assert call_order.index("start_step") < call_order.index("execute")


def test_sandboxed_blocked_step_not_executed(tmp_path):
    """Blocked step must not call provider.execute."""
    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="running",
        step={"id": str(uuid4()), "status": "failed"},
        runner_action="blocked",
        poll_after_seconds=0,
    )
    mock_provider = make_mock_provider(make_sandbox_result())
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1)])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    mock_provider.execute.assert_not_called()
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_sandboxed_approval_path_works(tmp_path):
    """Approval gate still works in sandboxed mode; command runs after approval."""
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
        execution_status="running",
        step_id=uuid4(),
        step_status="running",
        approval_request=None,
        runner_action="run",
        poll_after_seconds=0,
    )
    mock_provider = make_mock_provider(make_sandbox_result(stdout=b"approved\n"))
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    step = make_command_step(1, "echo approved")
    step = ClaimedStep(
        **{**step.model_dump(), "requires_approval": True}
    )
    execution = make_execution([step])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    mock_provider.execute.assert_called_once()
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_sandboxed_successful_real_command(tmp_path):
    """A real `echo` command in sandboxed mode should succeed with exit_code=0."""
    client = make_client()
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "echo hello")])

    run_execution(executor, execution)

    succeeded_calls = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded_calls) == 1
    assert succeeded_calls[0].kwargs.get("exit_code") == 0
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_sandboxed_nonzero_command_fails_with_exit_code(tmp_path):
    """A command that exits non-zero must report status=failed with the correct exit_code."""
    client = make_client()
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "exit 42")])

    run_execution(executor, execution)

    failed_calls = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("exit_code") == 42
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_sandboxed_timeout_fails_with_failure_kind_timeout(tmp_path):
    """A timed-out step must report status=failed and failure_kind=timeout."""
    client = make_client()
    mock_provider = make_mock_provider(
        make_sandbox_result(timed_out=True, exit_code=None, failure_kind="timeout")
    )
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "sleep 9999")])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    failed_calls = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("failure_kind") == "timeout"
    assert failed_calls[0].kwargs.get("timed_out") is True
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_sandboxed_unsupported_step_type_fails_closed(tmp_path):
    """A step with an unsupported step_type must fail without calling provider.execute."""
    client = make_client()
    mock_provider = make_mock_provider(make_sandbox_result())
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_unsupported_step(1)])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    mock_provider.execute.assert_not_called()
    failed_calls = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("failure_kind") == "unsupported_step_type"
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_sandboxed_stdout_stderr_uploaded_before_terminal_update(tmp_path):
    """stdout/stderr artifacts must be uploaded before update_step is called."""
    call_order = []
    client = make_client()
    client.upload_artifact.side_effect = lambda *a, **kw: (
        call_order.append("upload") or MagicMock()
    )
    client.update_step.side_effect = lambda *a, **kw: (
        call_order.append("update_step") or MagicMock()
    )
    mock_provider = make_mock_provider(
        make_sandbox_result(stdout=b"hello\n", stderr=b"warning\n")
    )
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1)])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    assert "upload" in call_order
    assert "update_step" in call_order
    assert call_order.index("upload") < call_order.index("update_step")


def test_sandboxed_artifact_upload_failure_does_not_rerun_command(tmp_path):
    """Upload failure must not cause the command to be re-executed."""
    import httpx

    client = make_client()
    client.upload_artifact.side_effect = httpx.ConnectError("storage down")
    mock_provider = make_mock_provider(make_sandbox_result(stdout=b"done\n"))
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1)])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    # Command ran exactly once despite upload failure
    assert mock_provider.execute.call_count == 1
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


# ---------------------------------------------------------------------------
# Cancellation token tests
# ---------------------------------------------------------------------------


def _heartbeat_cancel_response(reason: str = "user requested") -> HeartbeatResponse:
    return HeartbeatResponse(
        execution_id=uuid4(),
        status="running",
        cancel_requested=True,
        cancel_reason=reason,
    )


def _heartbeat_ok_response() -> HeartbeatResponse:
    return HeartbeatResponse(
        execution_id=uuid4(),
        status="running",
        cancel_requested=False,
        cancel_reason="",
    )


def test_heartbeat_cancel_response_flips_cancellation_token():
    """A heartbeat response with cancel_requested=True must set the cancellation event."""
    import threading

    client = MagicMock()
    client.heartbeat.return_value = _heartbeat_cancel_response("operator stop")
    cancellation_event = threading.Event()

    thread = _HeartbeatThread(
        client,
        uuid4(),
        uuid4(),
        interval=0.01,
        cancellation_event=cancellation_event,
    )
    thread.start()
    cancellation_event.wait(timeout=1.0)
    thread.stop()
    thread.join(timeout=2.0)

    assert cancellation_event.is_set()
    assert thread.cancel_reason == "operator stop"


def test_heartbeat_no_cancel_does_not_set_token():
    """A normal heartbeat response must not set the cancellation event."""
    import threading

    client = MagicMock()
    client.heartbeat.return_value = _heartbeat_ok_response()
    cancellation_event = threading.Event()

    thread = _HeartbeatThread(
        client,
        uuid4(),
        uuid4(),
        interval=0.01,
        cancellation_event=cancellation_event,
    )
    thread.start()
    # Let it fire a couple of heartbeats
    import time as _time
    _time.sleep(0.05)
    thread.stop()
    thread.join(timeout=2.0)

    assert not cancellation_event.is_set()


def test_cancellation_before_step_prevents_execution():
    """If cancellation is set before the step loop runs, no steps execute."""
    import threading

    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2)])

    original_run = executor.run

    def run_with_pre_cancel(exec_, token):
        # Inject cancellation into the shared event before steps start.
        # We do this by patching _HeartbeatThread to immediately set the event.
        original_init = _HeartbeatThread.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self._cancellation_event.set()

        with patch.object(_HeartbeatThread, "__init__", patched_init):
            executor.run(exec_, token)

    run_with_pre_cancel(execution, uuid4())

    client.start_step.assert_not_called()
    client.complete_execution.assert_called_once()
    assert client.complete_execution.call_args.kwargs["final_status"] == "cancelled"


def test_cancellation_does_not_execute_later_steps():
    """After step 1 completes, cancellation set at that point must prevent step 2 from running."""
    import threading

    cancellation_holder: list[threading.Event] = []

    original_hb_init = _HeartbeatThread.__init__

    def patched_hb_init(self, *args, **kwargs):
        original_hb_init(self, *args, **kwargs)
        cancellation_holder.append(self._cancellation_event)

    client = make_client()

    # Set cancellation after step 1's update_step is called (simulates heartbeat firing)
    original_update_step = client.update_step

    def update_step_and_cancel(*args, **kwargs):
        if cancellation_holder:
            cancellation_holder[0].set()
        return MagicMock()

    client.update_step.side_effect = update_step_and_cancel

    executor = Executor(client)
    execution = make_execution([make_step(1), make_step(2)])

    with patch.object(_HeartbeatThread, "__init__", patched_hb_init):
        run_execution(executor, execution)

    # Step 1 ran; step 2 must have been skipped
    assert client.start_step.call_count == 1
    final_status = client.complete_execution.call_args.kwargs["final_status"]
    assert final_status == "cancelled"


def test_cancelled_sandbox_result_reported_to_django(tmp_path):
    """When provider returns cancelled=True, update_step must be called with cancelled=True."""
    client = make_client()
    mock_provider = make_mock_provider(
        make_sandbox_result(cancelled=True, exit_code=None, error_message="Step was cancelled")
    )
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1)])

    with patch("runner.executor.get_provider", return_value=mock_provider):
        run_execution(executor, execution)

    failed_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("cancelled") is True
    assert failed_calls[0].kwargs.get("failure_kind") == "cancelled"


def test_cancellation_during_approval_wait_stops_execution():
    """Cancellation set during approval wait must abort the wait and complete as cancelled."""
    import threading as _threading

    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="claimed",
        step={"id": str(uuid4()), "status": "waiting_for_approval"},
        runner_action="wait_for_approval",
        poll_after_seconds=0,
    )

    cancellation_holder: list[_threading.Event] = []

    original_hb_init = _HeartbeatThread.__init__

    def patched_hb_init(self, *args, **kwargs):
        original_hb_init(self, *args, **kwargs)
        cancellation_holder.append(self._cancellation_event)

    # We need to set cancellation AFTER the first time.sleep in _wait_for_approval runs.
    # mock_sleep patches time.sleep to a no-op, so we patch it to also set cancellation.
    sleep_call_count = {"n": 0}

    def cancel_on_second_sleep(seconds):
        sleep_call_count["n"] += 1
        if sleep_call_count["n"] >= 1 and cancellation_holder:
            cancellation_holder[0].set()

    with patch.object(_HeartbeatThread, "__init__", patched_hb_init):
        with patch("runner.executor.time.sleep", cancel_on_second_sleep):
            executor = Executor(client)
            execution = make_execution([make_step(1, requires_approval=True), make_step(2)])
            executor.run(execution, uuid4())

    # Approval polling must not have been called (cancellation arrived before first poll)
    client.get_step_approval_status.assert_not_called()
    # Step 2 must not have started
    assert client.start_step.call_count == 1
    final_status = client.complete_execution.call_args.kwargs["final_status"]
    assert final_status == "cancelled"


# ---------------------------------------------------------------------------
# End-to-end: real sandbox + real commands, mocked ApiClient
# ---------------------------------------------------------------------------


def test_e2e_real_stdout_content_passed_to_upload(tmp_path):
    """Real printf command — stdout bytes must reach upload_artifact."""
    captured_uploads: list[bytes] = []

    client = make_client()

    def capture_upload(execution_id, step_id, claim_token, *, file_obj=None, **kwargs):
        data = file_obj.read() if file_obj is not None else b""
        captured_uploads.append(data)
        return MagicMock(id=uuid4(), checksum_sha256="abc", size_bytes=len(data))

    client.upload_artifact.side_effect = capture_upload
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "printf 'hello\\n'")])

    run_execution(executor, execution)

    succeeded_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded_calls) == 1
    assert succeeded_calls[0].kwargs.get("exit_code") == 0

    # stdout content must have been uploaded
    assert any(b"hello" in data for data in captured_uploads), (
        f"Expected 'hello' in uploaded artifact content, got: {captured_uploads!r}"
    )


def test_e2e_nonzero_exit_reports_correct_code(tmp_path):
    """Real exit 7 — executor must report exit_code=7 to update_step."""
    client = make_client()
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "exit 7")])

    run_execution(executor, execution)

    failed_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("exit_code") == 7
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_e2e_real_timeout_reports_timed_out(tmp_path):
    """Real sleep 30 with 1-second timeout — must report timed_out=True and failure_kind=timeout."""
    client = make_client()
    settings = RunnerSettings(
        api_base_url="http://api:8000",
        runner_id="test-runner",
        registration_token="test-token-secret",
        execution_mode="sandboxed",
        sandbox_provider="local_process",
        sandbox_workspace_root=str(tmp_path),
        sandbox_default_timeout_seconds=1,
    )
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "sleep 30")])

    run_execution(executor, execution)

    failed_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("timed_out") is True
    assert failed_calls[0].kwargs.get("failure_kind") == "timeout"
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_e2e_sandbox_metadata_propagated_to_update_step(tmp_path):
    """sandbox_provider and sandbox_run_id from SandboxResult must reach update_step."""
    client = make_client()
    settings = make_sandboxed_settings(str(tmp_path))
    executor = Executor(client, settings)
    execution = make_execution([make_command_step(1, "echo meta")])

    run_execution(executor, execution)

    succeeded_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded_calls) == 1
    assert succeeded_calls[0].kwargs.get("sandbox_provider") == "local_process"
    assert succeeded_calls[0].kwargs.get("sandbox_run_id", "") != ""


def test_e2e_step_snapshot_timeout_overrides_default(tmp_path):
    """timeoutSeconds in step_snapshot must be used instead of the runner default."""
    client = make_client()
    # Runner default is 300s; step requests 1s — sleep 30 must time out quickly.
    settings = RunnerSettings(
        api_base_url="http://api:8000",
        runner_id="test-runner",
        registration_token="test-token-secret",
        execution_mode="sandboxed",
        sandbox_provider="local_process",
        sandbox_workspace_root=str(tmp_path),
        sandbox_default_timeout_seconds=300,
    )
    executor = Executor(client, settings)
    execution = make_execution(
        [make_command_step(1, "sleep 30", step_snapshot={"id": "step-1", "timeoutSeconds": 1})]
    )

    run_execution(executor, execution)

    failed_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("timed_out") is True
    assert failed_calls[0].kwargs.get("failure_kind") == "timeout"


def test_e2e_step_snapshot_timeout_clamped_to_runner_default(tmp_path):
    """A step requesting a timeout above the runner max must be clamped down."""
    client = make_client()
    settings = RunnerSettings(
        api_base_url="http://api:8000",
        runner_id="test-runner",
        registration_token="test-token-secret",
        execution_mode="sandboxed",
        sandbox_provider="local_process",
        sandbox_workspace_root=str(tmp_path),
        sandbox_default_timeout_seconds=2,
    )
    executor = Executor(client, settings)
    # Step requests 9999s but runner caps at 2s; sleep 30 must time out quickly.
    execution = make_execution(
        [make_command_step(1, "sleep 30", step_snapshot={"id": "step-1", "timeoutSeconds": 9999})]
    )

    run_execution(executor, execution)

    failed_calls = [
        c for c in client.update_step.call_args_list if c.kwargs.get("status") == "failed"
    ]
    assert len(failed_calls) == 1
    assert failed_calls[0].kwargs.get("timed_out") is True
