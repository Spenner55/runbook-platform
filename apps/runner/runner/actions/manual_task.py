"""Handler for the manual_task action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError

logger = logging.getLogger(__name__)


class ManualTaskHandler:
    """Manual tasks require human completion. Runner acknowledges after the operator confirms."""

    def validate(self, params: dict[str, Any]) -> None:
        instructions = params.get("instructions")
        if instructions is not None and not isinstance(instructions, str):
            raise ActionValidationError(
                "manual_task 'instructions' must be a string when present"
            )

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        params = ctx.step.action_snapshot.params if ctx.step.action_snapshot else {}
        instructions = params.get("instructions", "")
        logger.info(
            "manual_task: step %d/%s acknowledged%s",
            ctx.step.position,
            ctx.step.name,
            f" — instructions present ({len(instructions)} chars)" if instructions else "",
        )
        return ActionResult(status="succeeded", exit_code=0)
