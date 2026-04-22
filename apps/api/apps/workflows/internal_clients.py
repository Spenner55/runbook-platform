"""
Workflow-owned boundary for the internal AI service.

Contains:
- WorkflowTransformClient  Protocol that all transform clients must satisfy
- StubWorkflowTransformClient  deterministic local implementation for Phase 03
- Re-exports of AI error types and the HTTP client callable for use by views
  and future HttpWorkflowTransformClient implementations

Swap path:
    # Phase 03
    client = StubWorkflowTransformClient()
    # Phase N+
    client = HttpWorkflowTransformClient(base_url=settings.AI_BASE_URL)
"""
from __future__ import annotations

import re
from typing import Protocol

from apps.runbooks.ai_client import (  # noqa: F401
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
    WorkflowCandidate,
    WorkflowCandidateStep,
    parse_runbook_to_workflow_candidate,
)

__all__ = [
    # Protocol
    "WorkflowTransformClient",
    # Stub
    "StubWorkflowTransformClient",
    # AI error types (used by views)
    "AiServiceBadResponseError",
    "AiServiceContractError",
    "AiServiceTimeoutError",
    "AiServiceUnavailableError",
    # Result types
    "WorkflowCandidate",
    "WorkflowCandidateStep",
    # HTTP callable (kept for HttpWorkflowTransformClient wiring later)
    "parse_runbook_to_workflow_candidate",
]

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

_LIST_MARKER_RE = re.compile(r"^(?:\d+[.)]\s+|[-*]\s+)")
_RUN_PREFIX_RE = re.compile(r"^run:\s*", re.IGNORECASE)


class WorkflowTransformClient(Protocol):
    def transform_runbook(
        self,
        *,
        runbook_title: str,
        runbook_slug: str,
        raw_content: str,
    ) -> WorkflowCandidate:
        """Return a WorkflowCandidate derived from the given runbook fields."""
        ...


# ---------------------------------------------------------------------------
# Deterministic stub implementation
# ---------------------------------------------------------------------------

class StubWorkflowTransformClient:
    """
    Local, deterministic stand-in for the future AI transform boundary.

    Algorithm (pure, no I/O, no randomness):
    1. Normalize line endings.
    2. Strip each line; drop blank lines.
    3. Drop Markdown headings (lines whose first non-space char is #).
    4. Remove leading list markers (-, *, 1., 2) …).
    5. For lines starting with "run:" extract command → step_type=shell_command.
    6. Build one step per remaining candidate line.
    7. If nothing remains, produce one fallback step from the runbook title.
    8. Assign step keys step-001, step-002, … (zero-padded to 3 digits).
    """

    def transform_runbook(
        self,
        *,
        runbook_title: str,
        runbook_slug: str,
        raw_content: str,
    ) -> WorkflowCandidate:
        candidates = self._extract_candidates(raw_content)
        if not candidates:
            candidates = [(runbook_title.strip() or "Run procedure", None)]

        steps = []
        for idx, (text, command) in enumerate(candidates, start=1):
            step_key = f"step-{idx:03d}"
            step_type = "shell_command" if command is not None else "manual_task"
            steps.append(
                WorkflowCandidateStep(
                    step_key=step_key,
                    name=text[:255],
                    step_type=step_type,
                    risk_level="medium",
                    requires_approval=False,
                )
            )

        return WorkflowCandidate(
            request_id="stub",
            workflow_title=runbook_title,
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_candidates(raw_content: str) -> list[tuple[str, str | None]]:
        """
        Return a list of (display_text, command_or_None) tuples.
        Order matches source order; output is fully determined by input.
        """
        lines = raw_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        candidates: list[tuple[str, str | None]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue

            # Remove leading list markers.
            stripped = _LIST_MARKER_RE.sub("", stripped).strip()
            if not stripped:
                continue

            # Detect run: prefix.
            run_match = _RUN_PREFIX_RE.match(stripped)
            if run_match:
                command = stripped[run_match.end():].strip()
                display = f"run: {command}" if command else stripped
                candidates.append((display, command or None))
            else:
                candidates.append((stripped, None))

        return candidates
