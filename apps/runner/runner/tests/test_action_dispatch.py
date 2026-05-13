"""Tests for the typed action dispatch skeleton (v2 action_snapshot path)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from runner.actions.base import (
    ActionResult,
    ActionValidationError,
)
from runner.actions.registry import ACTION_REGISTRY, ActionRegistry
from runner.executor import Executor
from runner.schemas import (
    ActionSnapshot,
    ClaimedExecution,
    ClaimedStep,
    StepStartResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def make_v1_step(position: int = 1) -> ClaimedStep:
    """A v1 step has no action_snapshot."""
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="manual",
        risk_level="low",
        status="pending",
    )


def make_v2_step(
    position: int = 1,
    action_type: str = "manual_task",
    version: str = "pilot.v1",
    params: dict[str, Any] | None = None,
) -> ClaimedStep:
    """A v2 step carries an action_snapshot."""
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="action",
        risk_level="low",
        status="pending",
        action_snapshot=ActionSnapshot(
            type=action_type,
            version=version,
            params=params or {},
        ),
    )


def _run_response() -> StepStartResponse:
    return StepStartResponse(
        execution_id=uuid4(),
        execution_status="running",
        step={"id": str(uuid4()), "status": "running"},
        runner_action="run",
        poll_after_seconds=0,
    )


def make_client() -> MagicMock:
    client = MagicMock()
    client.start_step.return_value = _run_response()
    return client


def run_execution(executor: Executor, execution: ClaimedExecution) -> None:
    executor.run(execution, uuid4())


def make_mock_handler(
    validate_raises: ActionValidationError | None = None,
    result: ActionResult | None = None,
) -> MagicMock:
    handler = MagicMock()
    if validate_raises is not None:
        handler.validate.side_effect = validate_raises
    else:
        handler.validate.return_value = None
    handler.execute.return_value = result or ActionResult(status="succeeded", exit_code=0)
    return handler


def registry_with(action_type: str, version: str, handler) -> ActionRegistry:
    r = ActionRegistry()
    r.register(action_type, version, handler)
    return r


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_sleep(monkeypatch):
    monkeypatch.setattr("runner.executor.time.sleep", lambda _: None)


# ---------------------------------------------------------------------------
# 1. v1 compatibility — steps without action_snapshot use the old path
# ---------------------------------------------------------------------------


def test_v1_step_routes_to_simulated_path():
    """A step with no action_snapshot must use the existing simulated execution path."""
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_v1_step(1)])

    run_execution(executor, execution)

    succeeded = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded) == 1
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_v1_step_does_not_invoke_action_registry():
    """The action registry must not be consulted for v1 steps."""
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_v1_step(1)])

    with patch("runner.executor.ACTION_REGISTRY") as mock_registry:
        run_execution(executor, execution)

    mock_registry.lookup.assert_not_called()


# ---------------------------------------------------------------------------
# 2. v2 known action — handler resolved and executed
# ---------------------------------------------------------------------------


def test_v2_known_action_resolves_and_executes_handler():
    """A v2 step with a registered (type, version) must call handler.execute."""
    client = make_client()
    handler = make_mock_handler()
    registry = registry_with("manual_task", "pilot.v1", handler)
    executor = Executor(client)
    execution = make_execution([make_v2_step(1, "manual_task", "pilot.v1")])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    handler.execute.assert_called_once()
    succeeded = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded) == 1
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_v2_known_action_validate_called_with_params():
    """handler.validate must be called with the snapshot's params dict."""
    client = make_client()
    handler = make_mock_handler()
    registry = registry_with("shell_command", "pilot.v1", handler)
    executor = Executor(client)
    params = {"command": "echo hello"}
    execution = make_execution([make_v2_step(1, "shell_command", "pilot.v1", params)])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    handler.validate.assert_called_once_with(params)


def test_v2_shell_command_dispatch_uses_sandbox_provider(tmp_path):
    client = make_client()
    settings = MagicMock()
    settings.sandbox_allow_shell = False
    settings.sandbox_workspace_root = str(tmp_path)
    settings.sandbox_provider = "local_process"
    settings.sandbox_default_timeout_seconds = 300
    settings.sandbox_stdout_max_bytes = 1024
    settings.sandbox_stderr_max_bytes = 1024
    settings.sandbox_artifact_max_bytes = 1024
    settings.sandbox_max_artifacts_per_step = 10
    settings.sandbox_allowed_env_names = []
    settings.sandbox_allowed_env_prefixes = []
    settings.sandbox_cleanup_policy = "always"
    executor = Executor(client, settings=settings)
    step = make_v2_step(
        1,
        "shell_command",
        "pilot.v1",
        params={"command": "printf pilot-b"},
    )
    execution = make_execution([step])

    result = MagicMock()
    result.exit_code = 0
    result.timed_out = False
    result.cancelled = False
    result.failure_kind = ""
    result.error_message = ""
    result.stdout.content = b"pilot-b"
    result.stderr.content = b""
    result.artifacts = []
    result.provider = "local_process"
    result.sandbox_run_id = "sandbox-1"
    result.started_at = None
    result.finished_at = None
    provider = MagicMock()
    provider.validate.return_value = None
    provider.execute.return_value = result

    with patch("runner.actions.shell_command.get_provider", return_value=provider):
        run_execution(executor, execution)

    provider.validate.assert_called_once()
    provider.execute.assert_called_once()
    succeeded = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded) == 1
    assert client.complete_execution.call_args.kwargs["final_status"] == "succeeded"


def test_v2_failed_handler_result_reports_failed():
    """If handler.execute returns status=failed, update_step must reflect failed."""
    client = make_client()
    handler = make_mock_handler(
        result=ActionResult(
            status="failed",
            exit_code=1,
            error_message="stub failure",
            failure_kind="stub_error",
        )
    )
    registry = registry_with("manual_task", "pilot.v1", handler)
    executor = Executor(client)
    execution = make_execution([make_v2_step(1)])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    failed = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed) == 1
    assert failed[0].kwargs.get("failure_kind") == "stub_error"
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


# ---------------------------------------------------------------------------
# 3. Unknown type — fails closed
# ---------------------------------------------------------------------------


def test_v2_unknown_type_fails_closed():
    """A v2 step whose type is not registered must fail with unsupported_action_contract."""
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_v2_step(1, action_type="nonexistent_type", version="pilot.v1")])

    with patch("runner.executor.ACTION_REGISTRY", ActionRegistry()):
        run_execution(executor, execution)

    failed = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed) == 1
    assert failed[0].kwargs.get("failure_kind") == "unsupported_action_contract"
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_v2_unknown_type_does_not_call_update_succeeded():
    """No succeeded update must be emitted when the action type is unknown."""
    client = make_client()
    executor = Executor(client)
    execution = make_execution([make_v2_step(1, action_type="does_not_exist", version="pilot.v1")])

    with patch("runner.executor.ACTION_REGISTRY", ActionRegistry()):
        run_execution(executor, execution)

    succeeded = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "succeeded"
    ]
    assert len(succeeded) == 0


# ---------------------------------------------------------------------------
# 4. Unknown version — fails closed
# ---------------------------------------------------------------------------


def test_v2_unknown_version_fails_closed():
    """A v2 step whose version is not registered must fail with unsupported_action_contract."""
    client = make_client()
    # Register the type under a different version only.
    registry = ActionRegistry()
    registry.register("manual_task", "pilot.v1", make_mock_handler())
    executor = Executor(client)
    execution = make_execution([make_v2_step(1, action_type="manual_task", version="pilot.v99")])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    failed = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed) == 1
    assert failed[0].kwargs.get("failure_kind") == "unsupported_action_contract"
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


# ---------------------------------------------------------------------------
# 5. Validation failure — action_input_invalid
# ---------------------------------------------------------------------------


def test_v2_validate_failure_reports_action_input_invalid():
    """ActionValidationError from handler.validate must produce failure_kind=action_input_invalid."""
    client = make_client()
    handler = make_mock_handler(
        validate_raises=ActionValidationError("command is required")
    )
    registry = registry_with("shell_command", "pilot.v1", handler)
    executor = Executor(client)
    execution = make_execution([make_v2_step(1, "shell_command", "pilot.v1", params={})])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    failed = [
        c
        for c in client.update_step.call_args_list
        if c.kwargs.get("status") == "failed"
    ]
    assert len(failed) == 1
    assert failed[0].kwargs.get("failure_kind") == "action_input_invalid"
    assert "command is required" in (failed[0].kwargs.get("error_message") or "")
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


def test_v2_validate_failure_does_not_call_execute():
    """handler.execute must not be called when validate raises."""
    client = make_client()
    handler = make_mock_handler(
        validate_raises=ActionValidationError("url is required")
    )
    registry = registry_with("http_request", "pilot.v1", handler)
    executor = Executor(client)
    execution = make_execution([make_v2_step(1, "http_request", "pilot.v1", params={})])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    handler.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Step-start gate remains before real side effects
# ---------------------------------------------------------------------------


def test_v2_start_gate_called_before_handler_execute():
    """start_step must be called before handler.execute for v2 steps."""
    call_order: list[str] = []
    client = make_client()
    client.start_step.side_effect = lambda *a, **kw: (
        call_order.append("start_step") or _run_response()
    )

    handler = MagicMock()
    handler.validate.return_value = None
    handler.execute.side_effect = lambda ctx: (
        call_order.append("execute") or ActionResult(status="succeeded", exit_code=0)
    )
    registry = registry_with("manual_task", "pilot.v1", handler)
    executor = Executor(client)
    execution = make_execution([make_v2_step(1)])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    assert "start_step" in call_order
    assert "execute" in call_order
    assert call_order.index("start_step") < call_order.index("execute")


def test_v2_blocked_start_prevents_execute():
    """If start_step returns runner_action=blocked, handler.execute must not be called."""
    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=uuid4(),
        execution_status="running",
        step={"id": str(uuid4()), "status": "failed"},
        runner_action="blocked",
        poll_after_seconds=0,
    )
    handler = make_mock_handler()
    registry = registry_with("manual_task", "pilot.v1", handler)
    executor = Executor(client)
    execution = make_execution([make_v2_step(1)])

    with patch("runner.executor.ACTION_REGISTRY", registry):
        run_execution(executor, execution)

    handler.execute.assert_not_called()
    assert client.complete_execution.call_args.kwargs["final_status"] == "failed"


# ---------------------------------------------------------------------------
# Registry unit tests
# ---------------------------------------------------------------------------


def test_registry_lookup_returns_none_for_unknown_key():
    r = ActionRegistry()
    assert r.lookup("no_such_type", "no_such_version") is None


def test_registry_lookup_returns_handler_for_registered_key():
    r = ActionRegistry()
    handler = make_mock_handler()
    r.register("my_type", "v1", handler)
    assert r.lookup("my_type", "v1") is handler


def test_registry_type_version_are_independent_keys():
    """Same type with different versions are separate registry entries."""
    r = ActionRegistry()
    h1 = make_mock_handler()
    h2 = make_mock_handler()
    r.register("shell_command", "pilot.v1", h1)
    r.register("shell_command", "pilot.v2", h2)
    assert r.lookup("shell_command", "pilot.v1") is h1
    assert r.lookup("shell_command", "pilot.v2") is h2
    assert r.lookup("shell_command", "pilot.v3") is None


def test_global_registry_contains_all_pilot_v1_handlers():
    """All five pilot.v1 handlers must be present in the module-level ACTION_REGISTRY."""
    expected = [
        ("manual_task", "pilot.v1"),
        ("approval_gate", "pilot.v1"),
        ("shell_command", "pilot.v1"),
        ("http_request", "pilot.v1"),
        ("artifact_assertion", "pilot.v1"),
    ]
    for action_type, version in expected:
        assert ACTION_REGISTRY.lookup(action_type, version) is not None, (
            f"Expected handler for ({action_type!r}, {version!r}) in ACTION_REGISTRY"
        )


# ---------------------------------------------------------------------------
# Individual handler validation tests
# ---------------------------------------------------------------------------


def test_shell_command_validate_requires_command():
    from runner.actions.shell_command import ShellCommandHandler

    h = ShellCommandHandler()
    with pytest.raises(ActionValidationError):
        h.validate({})
    h.validate({"commandMode": "shell", "command": "echo hi"})


def test_http_request_validate_requires_url():
    from runner.actions.http_request import HttpRequestHandler

    h = HttpRequestHandler()
    with pytest.raises(ActionValidationError):
        h.validate({})
    h.validate({"url": "https://example.com"})


def test_artifact_assertion_validate_requires_artifact_key():
    from runner.actions.artifact_assertion import ArtifactAssertionHandler

    h = ArtifactAssertionHandler()
    with pytest.raises(ActionValidationError):
        h.validate({})
    h.validate({"artifact_key": "my-artifact"})


def test_manual_task_validate_accepts_empty_params():
    from runner.actions.manual_task import ManualTaskHandler

    ManualTaskHandler().validate({})


def test_approval_gate_validate_accepts_empty_params():
    from runner.actions.approval_gate import ApprovalGateHandler

    ApprovalGateHandler().validate({})
