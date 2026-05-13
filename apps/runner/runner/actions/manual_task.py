"""Handler stub for the manual_task action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult

logger = logging.getLogger(__name__)


class ManualTaskHandler:
    """Stub — manual tasks require human intervention and are always considered complete."""

    def validate(self, params: dict[str, Any]) -> None:
        pass

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        logger.info(
            "manual_task stub: step %s/%s acknowledged",
            ctx.step.position,
            ctx.step.name,
        )
        return ActionResult(status="succeeded", exit_code=0)
