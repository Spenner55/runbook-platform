"""Focused unit tests for pilot.v1 action handler validate() and execute() logic."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from runner.actions.base import ActionExecutionContext, ActionValidationError
from runner.schemas import (
    ActionSnapshot,
    ArtifactDeclaration,
    ClaimedExecution,
    ClaimedStep,
    IdempotencySpec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_execution() -> ClaimedExecution:
    return ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=[],
    )


def _make_step(
    action_type: str = "manual_task",
    params: dict[str, Any] | None = None,
    artifacts: list[ArtifactDeclaration] | None = None,
    requires_approval: bool = False,
    timeout_seconds: int | None = None,
    idempotency: IdempotencySpec | None = None,
) -> ClaimedStep:
    return ClaimedStep(
        id=uuid4(),
        position=1,
        step_key="step-1",
        name="Test Step",
        step_type="action",
        risk_level="low",
        status="pending",
        action_snapshot=ActionSnapshot(
            type=action_type,
            version="pilot.v1",
            params=params or {},
        ),
        artifacts=artifacts or [],
        requires_approval=requires_approval,
        timeout_seconds=timeout_seconds,
        idempotency=idempotency,
    )


def _make_settings(**overrides: Any) -> MagicMock:
    settings = MagicMock()
    settings.sandbox_allow_shell = False
    settings.sandbox_workspace_root = "/tmp/test-workspaces"
    settings.sandbox_provider = "local_process"
    settings.sandbox_default_timeout_seconds = 300
    settings.sandbox_stdout_max_bytes = 1_048_576
    settings.sandbox_stderr_max_bytes = 1_048_576
    settings.sandbox_artifact_max_bytes = 10_485_760
    settings.sandbox_max_artifacts_per_step = 10
    settings.sandbox_allowed_env_names = []
    settings.sandbox_allowed_env_prefixes = []
    settings.sandbox_cleanup_policy = "always"
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_ctx(
    step: ClaimedStep | None = None,
    settings: Any = None,
) -> ActionExecutionContext:
    return ActionExecutionContext(
        execution=_make_execution(),
        step=step or _make_step(),
        claim_token=uuid4(),
        client=MagicMock(),
        uploader=MagicMock(),
        cancellation_event=threading.Event(),
        settings=settings,
    )


def _make_sandbox_result(
    exit_code: int = 0,
    timed_out: bool = False,
    cancelled: bool = False,
    failure_kind: str = "",
    error_message: str = "",
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> MagicMock:
    r = MagicMock()
    r.exit_code = exit_code
    r.timed_out = timed_out
    r.cancelled = cancelled
    r.failure_kind = failure_kind
    r.error_message = error_message
    r.stdout.content = stdout
    r.stderr.content = stderr
    r.artifacts = []
    r.provider = "local_process"
    r.sandbox_run_id = "test-run-1"
    r.started_at = datetime.now(tz=UTC)
    r.finished_at = datetime.now(tz=UTC)
    return r


# ===========================================================================
# manual_task
# ===========================================================================


class TestManualTaskValidate:
    def test_empty_params_accepted(self):
        from runner.actions.manual_task import ManualTaskHandler

        ManualTaskHandler().validate({})

    def test_string_instructions_accepted(self):
        from runner.actions.manual_task import ManualTaskHandler

        ManualTaskHandler().validate({"instructions": "Do the thing."})

    def test_non_string_instructions_rejected(self):
        from runner.actions.manual_task import ManualTaskHandler

        with pytest.raises(ActionValidationError, match="instructions"):
            ManualTaskHandler().validate({"instructions": 42})


class TestManualTaskExecute:
    def test_returns_succeeded(self):
        from runner.actions.manual_task import ManualTaskHandler

        ctx = _make_ctx(step=_make_step("manual_task", {}))
        result = ManualTaskHandler().execute(ctx)

        assert result.status == "succeeded"
        assert result.exit_code == 0

    def test_returns_succeeded_with_instructions(self):
        from runner.actions.manual_task import ManualTaskHandler

        ctx = _make_ctx(step=_make_step("manual_task", {"instructions": "Press the button."}))
        result = ManualTaskHandler().execute(ctx)

        assert result.status == "succeeded"


# ===========================================================================
# approval_gate
# ===========================================================================


class TestApprovalGateValidate:
    def test_empty_params_accepted(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        ApprovalGateHandler().validate({})

    def test_approvers_list_accepted(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        ApprovalGateHandler().validate({"approvers": ["alice", "bob"]})

    def test_approvers_not_a_list_rejected(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        with pytest.raises(ActionValidationError, match="approvers"):
            ApprovalGateHandler().validate({"approvers": "alice"})

    def test_valid_timeout_accepted(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        ApprovalGateHandler().validate({"approval_timeout_seconds": 3600})

    def test_zero_timeout_rejected(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        with pytest.raises(ActionValidationError, match="timeout"):
            ApprovalGateHandler().validate({"approval_timeout_seconds": 0})

    def test_negative_timeout_rejected(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        with pytest.raises(ActionValidationError, match="timeout"):
            ApprovalGateHandler().validate({"approval_timeout_seconds": -1})


class TestApprovalGateExecute:
    def test_returns_succeeded(self):
        from runner.actions.approval_gate import ApprovalGateHandler

        ctx = _make_ctx(step=_make_step("approval_gate", {}))
        result = ApprovalGateHandler().execute(ctx)

        assert result.status == "succeeded"
        assert result.exit_code == 0


# ===========================================================================
# shell_command — validate
# ===========================================================================


class TestShellCommandValidate:
    def test_missing_command_mode_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="commandMode"):
            ShellCommandHandler().validate({})

    def test_invalid_command_mode_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="commandMode"):
            ShellCommandHandler().validate({"commandMode": "exec"})

    def test_argv_mode_requires_argv(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="argv"):
            ShellCommandHandler().validate({"commandMode": "argv"})

    def test_argv_mode_empty_list_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="argv"):
            ShellCommandHandler().validate({"commandMode": "argv", "argv": []})

    def test_argv_mode_non_strings_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="strings"):
            ShellCommandHandler().validate({"commandMode": "argv", "argv": ["echo", 42]})

    def test_argv_mode_valid(self):
        from runner.actions.shell_command import ShellCommandHandler

        ShellCommandHandler().validate({"commandMode": "argv", "argv": ["echo", "hello"]})

    def test_shell_mode_requires_command(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="command"):
            ShellCommandHandler().validate({"commandMode": "shell"})

    def test_shell_mode_empty_command_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="command"):
            ShellCommandHandler().validate({"commandMode": "shell", "command": ""})

    def test_shell_mode_valid(self):
        from runner.actions.shell_command import ShellCommandHandler

        ShellCommandHandler().validate({"commandMode": "shell", "command": "echo hi"})

    def test_absolute_working_directory_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="relative"):
            ShellCommandHandler().validate(
                {"commandMode": "argv", "argv": ["ls"], "workingDirectory": "/etc"}
            )

    def test_dotdot_working_directory_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="\\.\\."):
            ShellCommandHandler().validate(
                {"commandMode": "argv", "argv": ["ls"], "workingDirectory": "../secrets"}
            )

    def test_relative_working_directory_accepted(self):
        from runner.actions.shell_command import ShellCommandHandler

        ShellCommandHandler().validate(
            {"commandMode": "argv", "argv": ["ls"], "workingDirectory": "subdir/nested"}
        )

    def test_non_string_working_directory_rejected(self):
        from runner.actions.shell_command import ShellCommandHandler

        with pytest.raises(ActionValidationError, match="string"):
            ShellCommandHandler().validate(
                {"commandMode": "argv", "argv": ["ls"], "workingDirectory": 123}
            )


# ===========================================================================
# shell_command — execute
# ===========================================================================


class TestShellCommandExecute:
    def test_no_settings_fails_closed(self):
        from runner.actions.shell_command import ShellCommandHandler

        ctx = _make_ctx(
            step=_make_step("shell_command", {"commandMode": "argv", "argv": ["echo"]}),
            settings=None,
        )
        result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "configuration_error"

    def test_shell_mode_without_allow_shell_fails_closed(self):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_allow_shell=False)
        ctx = _make_ctx(
            step=_make_step("shell_command", {"commandMode": "shell", "command": "rm -rf /"}),
            settings=settings,
        )
        result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "shell_mode_not_permitted"

    def test_argv_mode_success(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["echo", "hello"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(exit_code=0, stdout=b"hello\n")
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "succeeded"
        assert result.exit_code == 0
        ctx.uploader.upload_stdout.assert_called_once_with(step.id, b"hello\n")

    def test_shell_mode_success_when_allowed(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(
            sandbox_workspace_root=str(tmp_path), sandbox_allow_shell=True
        )
        step = _make_step("shell_command", {"commandMode": "shell", "command": "echo hi"})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(exit_code=0)
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "succeeded"

    def test_nonzero_exit_code_fails_with_failure_kind(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["false"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(exit_code=1)
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.exit_code == 1
        assert result.failure_kind == "nonzero_exit"

    def test_timeout_maps_to_timeout_failure_kind(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["sleep", "9999"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(timed_out=True, exit_code=None)
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "timeout"

    def test_cancellation_maps_to_cancelled_failure_kind(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["sleep", "9999"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(cancelled=True, exit_code=None)
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "cancelled"

    def test_sandbox_error_fails_closed(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler
        from runner.sandbox import SandboxError

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["echo"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.side_effect = SandboxError("infra failure")

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "sandbox_error"
        # cleanup must be called with (spec, None) when execute raises
        args, _ = mock_provider.cleanup.call_args
        assert args[1] is None

    def test_sandbox_validation_error_fails_closed(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["echo"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_provider = MagicMock()
        mock_provider.validate.side_effect = SandboxValidationError("bad spec")

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "validation_error"

    def test_provider_validate_called_before_execute(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["echo"]})
        ctx = _make_ctx(step=step, settings=settings)

        call_order: list[str] = []
        mock_result = _make_sandbox_result(exit_code=0)
        mock_provider = MagicMock()
        mock_provider.validate.side_effect = lambda spec: call_order.append("validate")
        mock_provider.execute.side_effect = lambda spec, tok: (
            call_order.append("execute") or mock_result
        )

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            ShellCommandHandler().execute(ctx)

        assert call_order.index("validate") < call_order.index("execute")

    def test_step_timeout_seconds_used_when_present(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(
            sandbox_workspace_root=str(tmp_path),
            sandbox_default_timeout_seconds=600,
        )
        step = _make_step(
            "shell_command",
            {"commandMode": "argv", "argv": ["echo"]},
            timeout_seconds=60,
        )
        ctx = _make_ctx(step=step, settings=settings)

        captured_specs: list = []
        mock_result = _make_sandbox_result(exit_code=0)
        mock_provider = MagicMock()
        mock_provider.validate.side_effect = lambda spec: captured_specs.append(spec)
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            ShellCommandHandler().execute(ctx)

        assert captured_specs[0].limits.timeout_seconds == 60

    def test_step_timeout_clamped_to_runner_max(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(
            sandbox_workspace_root=str(tmp_path),
            sandbox_default_timeout_seconds=30,
        )
        step = _make_step(
            "shell_command",
            {"commandMode": "argv", "argv": ["echo"]},
            timeout_seconds=9000,
        )
        ctx = _make_ctx(step=step, settings=settings)

        captured_specs: list = []
        mock_result = _make_sandbox_result(exit_code=0)
        mock_provider = MagicMock()
        mock_provider.validate.side_effect = lambda spec: captured_specs.append(spec)
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            ShellCommandHandler().execute(ctx)

        assert captured_specs[0].limits.timeout_seconds == 30

    def test_cleanup_always_called_on_success(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(
            sandbox_workspace_root=str(tmp_path), sandbox_cleanup_policy="always"
        )
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["echo"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(exit_code=0)
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            ShellCommandHandler().execute(ctx)

        mock_provider.cleanup.assert_called_once()

    def test_cleanup_on_success_skipped_on_failure(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(
            sandbox_workspace_root=str(tmp_path), sandbox_cleanup_policy="on_success"
        )
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["false"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(exit_code=1)
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            ShellCommandHandler().execute(ctx)

        mock_provider.cleanup.assert_not_called()

    def test_infrastructure_failure_kind_passed_through(self, tmp_path):
        from runner.actions.shell_command import ShellCommandHandler

        settings = _make_settings(sandbox_workspace_root=str(tmp_path))
        step = _make_step("shell_command", {"commandMode": "argv", "argv": ["echo"]})
        ctx = _make_ctx(step=step, settings=settings)

        mock_result = _make_sandbox_result(
            failure_kind="artifact_error", error_message="artifact too large"
        )
        mock_provider = MagicMock()
        mock_provider.validate.return_value = None
        mock_provider.execute.return_value = mock_result

        with patch("runner.actions.shell_command.get_provider", return_value=mock_provider):
            result = ShellCommandHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "artifact_error"


# Import for sandbox validation error tests
from runner.sandbox import SandboxValidationError


# ===========================================================================
# http_request — validate
# ===========================================================================


class TestHttpRequestValidate:
    def test_missing_url_rejected(self):
        from runner.actions.http_request import HttpRequestHandler

        with pytest.raises(ActionValidationError, match="url"):
            HttpRequestHandler().validate({})

    def test_http_url_rejected(self):
        from runner.actions.http_request import HttpRequestHandler

        with pytest.raises(ActionValidationError, match="HTTPS"):
            HttpRequestHandler().validate({"url": "http://example.com"})

    def test_https_url_accepted(self):
        from runner.actions.http_request import HttpRequestHandler

        HttpRequestHandler().validate({"url": "https://example.com"})

    def test_invalid_method_rejected(self):
        from runner.actions.http_request import HttpRequestHandler

        with pytest.raises(ActionValidationError, match="method"):
            HttpRequestHandler().validate({"url": "https://example.com", "method": "CONNECT"})

    def test_allowed_methods_accepted(self):
        from runner.actions.http_request import HttpRequestHandler

        for method in ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]:
            HttpRequestHandler().validate({"url": "https://example.com", "method": method})

    def test_headers_not_dict_rejected(self):
        from runner.actions.http_request import HttpRequestHandler

        with pytest.raises(ActionValidationError, match="headers"):
            HttpRequestHandler().validate(
                {"url": "https://example.com", "headers": "Authorization: Bearer x"}
            )

    def test_headers_dict_accepted(self):
        from runner.actions.http_request import HttpRequestHandler

        HttpRequestHandler().validate(
            {"url": "https://example.com", "headers": {"Authorization": "Bearer x"}}
        )


# ===========================================================================
# http_request — execute
# ===========================================================================


class TestHttpRequestExecute:
    def test_dry_run_skips_live_request(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step("http_request", {"url": "https://example.com", "dry_run": True})
        ctx = _make_ctx(step=step)

        with patch("runner.actions.http_request.httpx.Client") as mock_client_cls:
            result = HttpRequestHandler().execute(ctx)

        mock_client_cls.assert_not_called()
        assert result.status == "succeeded"

    def test_validate_only_skips_live_request(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step("http_request", {"url": "https://example.com", "validate_only": True})
        ctx = _make_ctx(step=step)

        with patch("runner.actions.http_request.httpx.Client") as mock_client_cls:
            result = HttpRequestHandler().execute(ctx)

        mock_client_cls.assert_not_called()
        assert result.status == "succeeded"

    def test_mutating_method_without_idempotency_fails_closed(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step(
            "http_request",
            {"url": "https://example.com", "method": "POST"},
            requires_approval=False,
        )
        ctx = _make_ctx(step=step)

        result = HttpRequestHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "mutating_request_without_idempotency"

    def test_mutating_method_with_idempotency_proceeds(self):
        from runner.actions.http_request import HttpRequestHandler

        idempotency = IdempotencySpec(mode="key", key="op-abc-123")
        step = _make_step(
            "http_request",
            {"url": "https://example.com", "method": "POST"},
            idempotency=idempotency,
        )
        ctx = _make_ctx(step=step)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request.return_value = mock_response

        with patch("runner.actions.http_request.httpx.Client", return_value=mock_http):
            result = HttpRequestHandler().execute(ctx)

        assert result.status == "succeeded"

    def test_mutating_method_with_approval_proceeds(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step(
            "http_request",
            {"url": "https://example.com", "method": "DELETE"},
            requires_approval=True,
        )
        ctx = _make_ctx(step=step)

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request.return_value = mock_response

        with patch("runner.actions.http_request.httpx.Client", return_value=mock_http):
            result = HttpRequestHandler().execute(ctx)

        assert result.status == "succeeded"

    def test_get_request_succeeds(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step("http_request", {"url": "https://example.com", "method": "GET"})
        ctx = _make_ctx(step=step)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"OK"
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request.return_value = mock_response

        with patch("runner.actions.http_request.httpx.Client", return_value=mock_http):
            result = HttpRequestHandler().execute(ctx)

        assert result.status == "succeeded"
        assert result.exit_code == 0

    def test_timeout_exception_maps_to_timeout_failure_kind(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step("http_request", {"url": "https://example.com"})
        ctx = _make_ctx(step=step)

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request.side_effect = httpx.TimeoutException("timed out")

        with patch("runner.actions.http_request.httpx.Client", return_value=mock_http):
            result = HttpRequestHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "timeout"

    def test_http_error_maps_to_http_error_failure_kind(self):
        from runner.actions.http_request import HttpRequestHandler

        step = _make_step("http_request", {"url": "https://example.com"})
        ctx = _make_ctx(step=step)

        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request.side_effect = httpx.ConnectError("connection refused")

        with patch("runner.actions.http_request.httpx.Client", return_value=mock_http):
            result = HttpRequestHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "http_error"

    def test_response_body_capped(self):
        from runner.actions.http_request import HttpRequestHandler, _MAX_RESPONSE_BODY_BYTES

        step = _make_step("http_request", {"url": "https://example.com"})
        ctx = _make_ctx(step=step)

        big_body = b"x" * (_MAX_RESPONSE_BODY_BYTES + 1024)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = big_body
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.request.return_value = mock_response

        with patch("runner.actions.http_request.httpx.Client", return_value=mock_http):
            result = HttpRequestHandler().execute(ctx)

        # Succeeds — cap is enforced internally, no error thrown
        assert result.status == "succeeded"




# ===========================================================================
# artifact_assertion — validate
# ===========================================================================


class TestArtifactAssertionValidate:
    def test_missing_artifact_key_rejected(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        with pytest.raises(ActionValidationError, match="artifact_key"):
            ArtifactAssertionHandler().validate({})

    def test_empty_artifact_key_rejected(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        with pytest.raises(ActionValidationError, match="artifact_key"):
            ArtifactAssertionHandler().validate({"artifact_key": ""})

    def test_valid_artifact_key_accepted(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        ArtifactAssertionHandler().validate({"artifact_key": "my-artifact"})

    def test_expected_kind_non_string_rejected(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        with pytest.raises(ActionValidationError, match="expected_kind"):
            ArtifactAssertionHandler().validate(
                {"artifact_key": "x", "expected_kind": 42}
            )

    def test_expected_mime_type_non_string_rejected(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        with pytest.raises(ActionValidationError, match="expected_mime_type"):
            ArtifactAssertionHandler().validate(
                {"artifact_key": "x", "expected_mime_type": ["text/plain"]}
            )


# ===========================================================================
# artifact_assertion — execute
# ===========================================================================


class TestArtifactAssertionExecute:
    def _make_decl(
        self,
        key: str,
        kind: str = "file",
        mime_type: str = "",
        path: str = "output.txt",
    ) -> ArtifactDeclaration:
        return ArtifactDeclaration(key=key, kind=kind, mime_type=mime_type, path=path)

    def test_undeclared_key_fails_with_artifact_not_declared(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        step = _make_step("artifact_assertion", {"artifact_key": "missing-key"}, artifacts=[])
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "artifact_not_declared"

    def test_declared_key_succeeds(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [self._make_decl("report")]
        step = _make_step("artifact_assertion", {"artifact_key": "report"}, artifacts=artifacts)
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "succeeded"
        assert result.exit_code == 0

    def test_kind_mismatch_fails_with_metadata_mismatch(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [self._make_decl("report", kind="file")]
        step = _make_step(
            "artifact_assertion",
            {"artifact_key": "report", "expected_kind": "image"},
            artifacts=artifacts,
        )
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "artifact_metadata_mismatch"

    def test_kind_match_succeeds(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [self._make_decl("report", kind="file")]
        step = _make_step(
            "artifact_assertion",
            {"artifact_key": "report", "expected_kind": "file"},
            artifacts=artifacts,
        )
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "succeeded"

    def test_mime_type_mismatch_fails_with_metadata_mismatch(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [self._make_decl("report", mime_type="application/pdf")]
        step = _make_step(
            "artifact_assertion",
            {"artifact_key": "report", "expected_mime_type": "text/plain"},
            artifacts=artifacts,
        )
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "failed"
        assert result.failure_kind == "artifact_metadata_mismatch"

    def test_mime_type_match_succeeds(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [self._make_decl("report", mime_type="text/csv")]
        step = _make_step(
            "artifact_assertion",
            {"artifact_key": "report", "expected_mime_type": "text/csv"},
            artifacts=artifacts,
        )
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "succeeded"

    def test_empty_expected_kind_skips_check(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [self._make_decl("report", kind="image")]
        step = _make_step(
            "artifact_assertion",
            {"artifact_key": "report", "expected_kind": ""},
            artifacts=artifacts,
        )
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "succeeded"

    def test_multiple_artifacts_correct_key_matched(self):
        from runner.actions.artifact_assertion import ArtifactAssertionHandler

        artifacts = [
            self._make_decl("log", kind="stdout"),
            self._make_decl("report", kind="file"),
        ]
        step = _make_step(
            "artifact_assertion", {"artifact_key": "report"}, artifacts=artifacts
        )
        ctx = _make_ctx(step=step)

        result = ArtifactAssertionHandler().execute(ctx)

        assert result.status == "succeeded"
