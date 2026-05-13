"""Handler stub for the artifact_assertion action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError

logger = logging.getLogger(__name__)


class ArtifactAssertionHandler:
    """Stub — artifact assertion checks will be wired in a later phase."""

    def validate(self, params: dict[str, Any]) -> None:
        if not params.get("artifact_key"):
            raise ActionValidationError(
                "artifact_assertion requires a non-empty 'artifact_key' param"
            )

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        key = ctx.step.action_snapshot.params.get("artifact_key", "") if ctx.step.action_snapshot else ""
        logger.info(
            "artifact_assertion stub: step %s/%s artifact_key=%r (not yet checked)",
            ctx.step.position,
            ctx.step.name,
            key,
        )
        return ActionResult(status="succeeded", exit_code=0)
