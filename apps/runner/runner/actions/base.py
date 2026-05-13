"""Base types for the typed action dispatch system."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from runner.artifact_uploader import ArtifactUploader
    from runner.client import ApiClient
    from runner.schemas import ClaimedExecution, ClaimedStep, RunnerSettings


class ActionValidationError(Exception):
    """Raised by ActionHandler.validate() when action params are structurally invalid."""


@dataclass(frozen=True)
class ActionExecutionContext:
    execution: ClaimedExecution
    step: ClaimedStep
    claim_token: UUID
    client: ApiClient
    uploader: ArtifactUploader
    cancellation_event: threading.Event
    settings: RunnerSettings | None = None


@dataclass(frozen=True)
class ActionResult:
    status: Literal["succeeded", "failed"]
    exit_code: int | None = None
    error_message: str = ""
    failure_kind: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


@runtime_checkable
class ActionHandler(Protocol):
    def validate(self, params: dict[str, Any]) -> None:
        """Validate action params. Raise ActionValidationError if invalid."""
        ...

    def execute(self, ctx: ActionExecutionContext) -> ActionResult:
        """Execute the action stub and return a result."""
        ...
