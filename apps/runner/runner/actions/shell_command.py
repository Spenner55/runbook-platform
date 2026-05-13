"""Handler for the shell_command action type (pilot.v1)."""

from __future__ import annotations

import logging
import os
import shlex
from pathlib import Path
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError
from runner.sandbox import (
    ArtifactSpec,
    SandboxError,
    SandboxExecutionSpec,
    SandboxLimits,
    SandboxValidationError,
    get_provider,
)
from runner.sandbox.workspace import WorkspaceManager
from runner.schemas import ArtifactDeclaration

logger = logging.getLogger(__name__)

_ALLOWED_MODES = frozenset({"argv", "shell"})
_MAX_ARGV_ITEMS = 256
_MAX_WORKING_DIR_LENGTH = 512


class ShellCommandHandler:
    """Execute a sandboxed shell command via the configured sandbox provider."""

    def validate(self, params: dict[str, Any]) -> None:
        mode = _command_mode(params)
        if mode not in _ALLOWED_MODES:
            raise ActionValidationError(
                f"shell_command 'commandMode' must be one of {sorted(_ALLOWED_MODES)}, "
                f"got {mode!r}"
            )

        if mode == "argv":
            argv = params.get("argv")
            if not argv or not isinstance(argv, list):
                raise ActionValidationError(
                    "shell_command commandMode=argv requires a non-empty 'argv' list"
                )
            if len(argv) > _MAX_ARGV_ITEMS:
                raise ActionValidationError(
                    f"shell_command 'argv' exceeds maximum of {_MAX_ARGV_ITEMS} items"
                )
            if not all(isinstance(a, str) for a in argv):
                raise ActionValidationError(
                    "shell_command 'argv' entries must all be strings"
                )

        elif mode == "shell":
            command = params.get("command")
            if not command or not isinstance(command, str):
                raise ActionValidationError(
                    "shell_command commandMode=shell requires a non-empty 'command' string"
                )

        working_dir = _working_directory(params)
        if working_dir is not None:
            if not isinstance(working_dir, str):
                raise ActionValidationError(
                    "shell_command 'workingDirectory' must be a string when present"
                )
            if os.path.isabs(working_dir):
                raise ActionValidationError(
                    "shell_command 'workingDirectory' must be relative, not absolute"
                )
            if ".." in Path(working_dir).parts:
                raise ActionValidationError(
                    "shell_command 'workingDirectory' must not contain '..'"
                )
            if len(working_dir) > _MAX_WORKING_DIR_LENGTH:
                raise ActionValidationError(
                    "shell_command 'workingDirectory' exceeds maximum length"
                )

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        settings = ctx.settings
        if settings is None:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message="shell_command requires runner settings (sandbox configuration unavailable)",
                failure_kind="sandbox_setup_failed",
            )

        params = ctx.step.action_snapshot.params if ctx.step.action_snapshot else {}
        mode = _command_mode(params)

        if mode == "shell" and "commandMode" in params and not settings.sandbox_allow_shell:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=(
                    "shell_command commandMode=shell is not permitted - "
                    "set RUNNER_SANDBOX_ALLOW_SHELL=true to enable"
                ),
                failure_kind="policy_blocked",
            )

        if ctx.execution.execution_mode == "dry_run":
            logger.info(
                "shell_command: step %d/%s dry_run - validating sandbox inputs without live execution",
                ctx.step.position,
                ctx.step.name,
            )
            return ActionResult(status="succeeded", exit_code=0)

        working_dir = _working_directory(params)
        if mode == "argv":
            argv = params.get("argv", [])
            cmd_str = shlex.join(str(a) for a in argv)
        else:
            cmd_str = params.get("command", "")

        script = (
            f"cd {shlex.quote(working_dir)}\n{cmd_str}" if working_dir else cmd_str
        )

        env = _build_env(settings)

        wm = WorkspaceManager(Path(settings.sandbox_workspace_root))
        try:
            ws_path = wm.build_workspace_path(
                ctx.execution.id,
                ctx.step.position,
                ctx.step.step_key,
                ctx.step.id,
            )
        except SandboxValidationError as exc:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=f"Failed to build workspace path: {exc}",
                failure_kind="sandbox_setup_failed",
            )

        timeout_seconds = settings.sandbox_default_timeout_seconds
        if ctx.step.timeout_seconds and ctx.step.timeout_seconds > 0:
            timeout_seconds = min(ctx.step.timeout_seconds, settings.sandbox_default_timeout_seconds)

        limits = SandboxLimits(
            timeout_seconds=timeout_seconds,
            stdout_max_bytes=settings.sandbox_stdout_max_bytes,
            stderr_max_bytes=settings.sandbox_stderr_max_bytes,
            artifact_max_bytes=settings.sandbox_artifact_max_bytes,
            max_artifacts=settings.sandbox_max_artifacts_per_step,
        )

        try:
            artifact_specs = _build_artifact_specs(ctx.step.artifacts)
        except ActionValidationError as exc:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=str(exc),
                failure_kind="action_input_invalid",
            )

        spec = SandboxExecutionSpec(
            execution_id=ctx.execution.id,
            step_id=ctx.step.id,
            step_key=ctx.step.step_key,
            step_type="shell_command",
            command=[script],
            display_command=script[:256],
            workspace_root=ws_path,
            environment=env,
            limits=limits,
            artifact_specs=artifact_specs,
        )

        provider = get_provider(settings.sandbox_provider)

        try:
            provider.validate(spec)
        except SandboxValidationError as exc:
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=str(exc),
                failure_kind="sandbox_setup_failed",
            )

        result = None
        try:
            result = provider.execute(spec, ctx.cancellation_event)
        except SandboxError as exc:
            logger.error(
                "shell_command: sandbox error for step %d/%s: %s",
                ctx.step.position,
                ctx.step.name,
                exc,
            )
            provider.cleanup(spec, None)
            return ActionResult(
                status="failed",
                exit_code=None,
                error_message=str(exc),
                failure_kind="sandbox_setup_failed",
            )

        snapshot = ctx.step.action_snapshot
        action_type = snapshot.type if snapshot else ""
        action_version = snapshot.version if snapshot else ""

        ctx.uploader.upload_stdout(
            ctx.step.id,
            result.stdout.content,
            action_type=action_type,
            action_version=action_version,
            step_key=ctx.step.step_key,
        )
        ctx.uploader.upload_stderr(
            ctx.step.id,
            result.stderr.content,
            action_type=action_type,
            action_version=action_version,
            step_key=ctx.step.step_key,
        )

        for collected in result.artifacts:
            ctx.uploader.upload_file(
                ctx.step.id,
                collected,
                sandbox_provider=result.provider,
                sandbox_run_id=result.sandbox_run_id,
                step_key=ctx.step.step_key,
                declaration_key=collected.spec.declaration_key,
                action_type=action_type,
                action_version=action_version,
            )

        step_failed = (
            result.timed_out
            or result.cancelled
            or bool(result.failure_kind)
            or (result.exit_code is not None and result.exit_code != 0)
        )
        cleanup_policy = settings.sandbox_cleanup_policy
        if cleanup_policy == "always" or (cleanup_policy == "on_success" and not step_failed):
            provider.cleanup(spec, result)

        if result.timed_out:
            return ActionResult(
                status="failed",
                exit_code=result.exit_code,
                error_message=result.error_message or f"Step timed out after {timeout_seconds}s",
                failure_kind="timeout",
                started_at=result.started_at,
                finished_at=result.finished_at,
            )
        if result.cancelled:
            return ActionResult(
                status="failed",
                exit_code=result.exit_code,
                error_message=result.error_message or "Step was cancelled",
                failure_kind="cancelled",
                started_at=result.started_at,
                finished_at=result.finished_at,
            )
        if result.failure_kind:
            failure_kind = _normalize_sandbox_failure_kind(
                result.failure_kind, result.error_message
            )
            return ActionResult(
                status="failed",
                exit_code=result.exit_code,
                error_message=result.error_message,
                failure_kind=failure_kind,
                started_at=result.started_at,
                finished_at=result.finished_at,
            )
        if result.exit_code is not None and result.exit_code != 0:
            return ActionResult(
                status="failed",
                exit_code=result.exit_code,
                error_message=f"Command exited with code {result.exit_code}",
                failure_kind="action_failed",
                started_at=result.started_at,
                finished_at=result.finished_at,
            )
        return ActionResult(
            status="succeeded",
            exit_code=result.exit_code,
            started_at=result.started_at,
            finished_at=result.finished_at,
        )


def _command_mode(params: dict[str, Any]) -> str:
    if "commandMode" in params:
        return params.get("commandMode")
    if params.get("argv"):
        return "argv"
    if params.get("command"):
        return "shell"
    return ""


def _working_directory(params: dict[str, Any]) -> str | None:
    if "workingDirectory" in params:
        return params.get("workingDirectory")
    return params.get("working_directory")


def _normalize_sandbox_failure_kind(kind: str, message: str = "") -> str:
    if kind in {
        "timeout",
        "action_input_invalid",
        "required_artifact_missing",
        "sandbox_setup_failed",
    }:
        return kind
    if kind in {"spawn_error", "sandbox_error", "validation_error"}:
        return "sandbox_setup_failed"
    if kind == "artifact_error":
        return (
            "required_artifact_missing"
            if "required artifact" in message.lower()
            else "action_input_invalid"
        )
    return "action_failed"


def _build_env(settings: Any) -> dict[str, str]:
    allowed_names = set(settings.sandbox_allowed_env_names)
    allowed_prefixes = tuple(settings.sandbox_allowed_env_prefixes)
    return {
        k: v
        for k, v in os.environ.items()
        if k in allowed_names or (allowed_prefixes and k.startswith(allowed_prefixes))
    }


def _build_artifact_specs(declarations: list[ArtifactDeclaration]) -> list[ArtifactSpec]:
    specs = []
    for decl in declarations:
        if not decl.path:
            continue
        # Catch unsafe paths at declaration-validation time → action_input_invalid
        if os.path.isabs(decl.path):
            raise ActionValidationError(
                f"Artifact declaration '{decl.key}' has an absolute path: {decl.path!r}"
            )
        if ".." in Path(decl.path).parts:
            raise ActionValidationError(
                f"Artifact declaration '{decl.key}' contains '..': {decl.path!r}"
            )
        specs.append(
            ArtifactSpec(
                name=decl.name or decl.key,
                path=decl.path,
                kind=decl.kind or "file",
                mime_type=decl.mime_type,
                required=decl.required,
                declaration_key=decl.key,
            )
        )
    return specs
