"""
Deterministic workflow candidate parser.

Extracts a structured workflow candidate from raw runbook content.
Does NOT persist anything — returns a candidate structure only.
Version assignment and persistence are Django's responsibility.
"""

from __future__ import annotations

import re

from app.schemas.workflow_parse import (
    ParseRunbookRequest,
    ParseRunbookResponse,
    WorkflowCandidateStep,
)


def parse_runbook_to_candidate(request: ParseRunbookRequest) -> ParseRunbookResponse:
    warnings: list[str] = []
    steps = _extract_steps(request.runbook.raw_content, warnings)

    if not steps:
        steps = _default_steps(request.runbook.title)
        warnings.append(
            "No numbered steps detected in content; using default step structure."
        )

    return ParseRunbookResponse(
        request_id=request.request_id,
        workflow_title=request.runbook.title,
        steps=steps,
        warnings=warnings,
    )


def _extract_steps(
    raw_content: str,
    warnings: list[str],
) -> list[WorkflowCandidateStep]:
    """
    Extract steps from raw content by scanning for numbered list items.

    Matches patterns like:
      "1. Do something"
      "Step 1: Do something"
      "2) Do something"
    """
    if not raw_content.strip():
        return []

    steps: list[WorkflowCandidateStep] = []
    pattern = re.compile(
        r"^(?:step\s*)?\d+[\.\:\)]\s*(.+)",
        re.IGNORECASE,
    )

    for line in raw_content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = pattern.match(stripped)
        if m:
            name = m.group(1).strip()[:255]
            steps.append(
                WorkflowCandidateStep(
                    step_key=f"step-{len(steps) + 1}",
                    name=name,
                    step_type="manual_task",
                    risk_level="medium",
                    requires_approval=False,
                )
            )

    return steps


def _default_steps(title: str) -> list[WorkflowCandidateStep]:
    return [
        WorkflowCandidateStep(
            step_key="step-1",
            name="Verify prerequisites",
            step_type="manual_task",
            risk_level="low",
            requires_approval=False,
        ),
        WorkflowCandidateStep(
            step_key="step-2",
            name=f"Execute: {title}"[:255],
            step_type="manual_task",
            risk_level="medium",
            requires_approval=False,
        ),
    ]
