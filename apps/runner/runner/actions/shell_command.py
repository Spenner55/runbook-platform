"""Handler stub for the shell_command action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError

logger = logging.getLogger(__name__)


class ShellCommandHandler:
    """Stub — full sandboxed execution will be wired in a later phase."""

    def validate(self, params: dict[str, Any]) -> None:
        if not params.get("command"):
            raise ActionValidationError("shell_command requires a non-empty 'command' param")

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        command = ctx.step.action_snapshot.params.get("command", "") if ctx.step.action_snapshot else ""
        logger.info(
            "shell_command stub: step %s/%s command=%r (not yet executed)",
            ctx.step.position,
            ctx.step.name,
            command,
        )
        return ActionResult(status="succeeded", exit_code=0)
