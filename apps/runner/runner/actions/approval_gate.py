"""Handler for the approval_gate action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import (
    ActionExecutionContext,
    ActionResult,
    ActionValidationError,
)

logger = logging.getLogger(__name__)


class ApprovalGateHandler:
    """Approval side effects are managed by Django. Runner acknowledges after approval is granted."""

    def validate(self, params: dict[str, Any]) -> None:
        approvers = params.get("approvers")
        if approvers is not None and not isinstance(approvers, list):
            raise ActionValidationError(
                "approval_gate 'approvers' must be a list when present"
            )
        timeout = params.get("approval_timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, (int, float)) or timeout <= 0
        ):
            raise ActionValidationError(
                "approval_gate 'approval_timeout_seconds' must be a positive number when present"
            )

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        logger.info(
            "approval_gate: step %d/%s — approval already granted by Django gate, acknowledging",
            ctx.step.position,
            ctx.step.name,
        )
        return ActionResult(status="succeeded", exit_code=0)
