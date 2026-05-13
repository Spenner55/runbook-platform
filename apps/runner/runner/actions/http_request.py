"""Handler stub for the http_request action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError

logger = logging.getLogger(__name__)


class HttpRequestHandler:
    """Stub — HTTP execution will be wired in a later phase."""

    def validate(self, params: dict[str, Any]) -> None:
        if not params.get("url"):
            raise ActionValidationError("http_request requires a non-empty 'url' param")

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        url = ctx.step.action_snapshot.params.get("url", "") if ctx.step.action_snapshot else ""
        logger.info(
            "http_request stub: step %s/%s url=%r (not yet executed)",
            ctx.step.position,
            ctx.step.name,
            url,
        )
        return ActionResult(status="succeeded", exit_code=0)
