"""
Workflow-owned boundary for the internal AI service.

Contains:
- WorkflowTransformClient  Protocol that all transform clients must satisfy
- StubWorkflowTransformClient  deterministic local implementation (tests / fallback)
- HttpWorkflowTransformClient  production implementation backed by RunbookAiClient
- Re-exports of AI error types for use by views
"""

from __future__ import annotations

import re
import uuid
from typing import Protocol

from apps.runbooks.ai_client import (  # noqa: F401
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
    RunbookAiClient,
    WorkflowCandidate,
    WorkflowCandidateStep,
    WorkflowEnrichment,
)

__all__ = [
    # Protocol
    "WorkflowTransformClient",
    # Implementations
    "StubWorkflowTransformClient",
    "HttpWorkflowTransformClient",
    # AI error types (used by views)
    "AiServiceBadResponseError",
    "AiServiceContractError",
    "AiServiceTimeoutError",
    "AiServiceUnavailableError",
    # Result types
    "WorkflowCandidate",
    "WorkflowCandidateStep",
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
# HTTP implementation — production path
# ---------------------------------------------------------------------------


class HttpWorkflowTransformClient:
    """
    WorkflowTransformClient backed by the real AI parse service.

    Bridges the transform_runbook protocol (title/slug/content) to the
    RunbookAiClient interface (request_id/runbook_id/title/content).
    Uses runbook_slug as the trace runbook_id sent to FastAPI.
    """

    def __init__(self, *, ai_client: RunbookAiClient) -> None:
        self._ai_client = ai_client

    @classmethod
    def from_settings(cls) -> HttpWorkflowTransformClient:
        return cls(ai_client=RunbookAiClient.from_settings())

    def transform_runbook(
        self,
        *,
        runbook_title: str,
        runbook_slug: str,
        raw_content: str,
    ) -> WorkflowCandidate:
        request_id = str(uuid.uuid4())
        parsed = self._ai_client.parse_runbook_to_workflow_candidate(
            request_id=request_id,
            runbook_id=runbook_slug,
            runbook_title=runbook_title,
            raw_content=raw_content,
        )
        enrichment = self._ai_client.enrich_workflow_candidate(
            request_id=request_id,
            workflow_title=parsed.workflow_title,
            steps=parsed.steps,
            raw_content=raw_content,
        )
        return _merge_enrichment(parsed, enrichment)


# ---------------------------------------------------------------------------
# Deterministic stub implementation — used in tests and as fallback
# ---------------------------------------------------------------------------


class StubWorkflowTransformClient:
    """
    Local, deterministic stand-in for the AI transform boundary.

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
                    command=command,
                )
            )

        return WorkflowCandidate(
            request_id="stub",
            workflow_title=runbook_title,
            steps=steps,
        )

    @staticmethod
    def _extract_candidates(raw_content: str) -> list[tuple[str, str | None]]:
        lines = raw_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        candidates: list[tuple[str, str | None]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue

            stripped = _LIST_MARKER_RE.sub("", stripped).strip()
            if not stripped:
                continue

            run_match = _RUN_PREFIX_RE.match(stripped)
            if run_match:
                command = stripped[run_match.end() :].strip()
                display = f"run: {command}" if command else stripped
                candidates.append((display, command or None))
            else:
                candidates.append((stripped, None))

        return candidates


def _merge_enrichment(
    parsed: WorkflowCandidate, enrichment: WorkflowEnrichment
) -> WorkflowCandidate:
    """Merge enrich-owned fields into parse-owned workflow structure by step key."""
    parsed_keys = [step.step_key for step in parsed.steps]
    enrich_keys = [step.step_key for step in enrichment.steps]

    if len(enrich_keys) != len(set(enrich_keys)):
        raise AiServiceContractError("AI enrich response contains duplicate step keys")

    missing = sorted(set(parsed_keys) - set(enrich_keys))
    extra = sorted(set(enrich_keys) - set(parsed_keys))
    if missing:
        raise AiServiceContractError(
            f"AI enrich response missing step keys: {', '.join(missing)}"
        )
    if extra:
        raise AiServiceContractError(
            f"AI enrich response returned unknown step keys: {', '.join(extra)}"
        )

    enrichment_by_key = {step.step_key: step for step in enrichment.steps}
    merged_steps = []
    for step in parsed.steps:
        enriched = enrichment_by_key[step.step_key]
        merged_steps.append(
            WorkflowCandidateStep(
                step_key=step.step_key,
                name=step.name,
                step_type=step.step_type,
                risk_level=enriched.risk_level,
                requires_approval=enriched.requires_approval,
                command=step.command,
            )
        )

    return WorkflowCandidate(
        request_id=parsed.request_id,
        workflow_title=parsed.workflow_title,
        steps=merged_steps,
        warnings=[*parsed.warnings, *enrichment.warnings],
    )
