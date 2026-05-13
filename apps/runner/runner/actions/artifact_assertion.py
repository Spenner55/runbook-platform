"""Handler for the artifact_assertion action type (pilot.v1)."""

from __future__ import annotations

import logging
from typing import Any

from runner.actions.base import ActionExecutionContext, ActionResult, ActionValidationError

logger = logging.getLogger(__name__)


class ArtifactAssertionHandler:
    """Validate declared artifact metadata for a given artifact_key.

    Checks only metadata declared on the step — never reads arbitrary filesystem paths.
    """

    def validate(self, params: dict[str, Any]) -> None:
        if not params.get("artifact_key"):
            raise ActionValidationError(
                "artifact_assertion requires a non-empty 'artifact_key' param"
            )
        expected_kind = params.get("expected_kind")
        if expected_kind is not None and not isinstance(expected_kind, str):
            raise ActionValidationError(
                "artifact_assertion 'expected_kind' must be a string when present"
            )
        expected_mime = params.get("expected_mime_type")
        if expected_mime is not None and not isinstance(expected_mime, str):
            raise ActionValidationError(
                "artifact_assertion 'expected_mime_type' must be a string when present"
            )

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        params = ctx.step.action_snapshot.params if ctx.step.action_snapshot else {}
        artifact_key = params.get("artifact_key", "")

        declared = {decl.key: decl for decl in ctx.step.artifacts}

        if artifact_key not in declared:
            return ActionResult(
                status="failed",
                exit_code=1,
                error_message=(
                    f"Artifact {artifact_key!r} is not declared on this step. "
                    f"Declared keys: {sorted(declared)}"
                ),
                failure_kind="artifact_not_declared",
            )

        decl = declared[artifact_key]

        expected_kind = params.get("expected_kind")
        if expected_kind and decl.kind and decl.kind != expected_kind:
            return ActionResult(
                status="failed",
                exit_code=1,
                error_message=(
                    f"Artifact {artifact_key!r} has kind {decl.kind!r}, "
                    f"expected {expected_kind!r}"
                ),
                failure_kind="artifact_metadata_mismatch",
            )

        expected_mime = params.get("expected_mime_type")
        if expected_mime and decl.mime_type and decl.mime_type != expected_mime:
            return ActionResult(
                status="failed",
                exit_code=1,
                error_message=(
                    f"Artifact {artifact_key!r} has mime_type {decl.mime_type!r}, "
                    f"expected {expected_mime!r}"
                ),
                failure_kind="artifact_metadata_mismatch",
            )

        logger.info(
            "artifact_assertion: step %d/%s artifact_key=%r — declared and metadata valid",
            ctx.step.position,
            ctx.step.name,
            artifact_key,
        )
        return ActionResult(status="succeeded", exit_code=0)
