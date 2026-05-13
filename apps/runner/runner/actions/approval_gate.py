"""Handler stub for the approval_gate action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult

logger = logging.getLogger(__name__)


class ApprovalGateHandler:
    """Stub — approval gate side effects are managed by Django; runner acknowledges."""

    def validate(self, params: dict[str, Any]) -> None:
        pass

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        logger.info(
            "approval_gate stub: step %s/%s acknowledged",
            ctx.step.position,
            ctx.step.name,
        )
        return ActionResult(status="succeeded", exit_code=0)
