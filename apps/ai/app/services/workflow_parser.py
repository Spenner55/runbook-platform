"""
Workflow candidate parser.

Routes to the LLM-backed parser when AI_USE_LLM_PARSER=true (and
OPENAI_API_KEY is set), otherwise uses the deterministic regex parser.

Does NOT persist anything — returns a candidate structure only.
Version assignment and persistence are Django's responsibility.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.core.config import settings
from app.prompts.parse import PARSE_SYSTEM_PROMPT, build_parse_user_prompt
from app.schemas.workflow_parse import (
    ParseRunbookRequest,
    ParseRunbookResponse,
    WorkflowCandidateStep,
)


class _LLMParseOutput(BaseModel):
    workflow_title: str
    steps: list[WorkflowCandidateStep]
    warnings: list[str] = []


def parse_runbook_to_candidate(request: ParseRunbookRequest) -> ParseRunbookResponse:
    if settings.AI_USE_LLM_PARSER:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "AI_USE_LLM_PARSER=true but OPENAI_API_KEY is not set. "
                "Set OPENAI_API_KEY in your environment before enabling LLM parsing."
            )
        return _llm_parse(request)

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


def _llm_parse(request: ParseRunbookRequest) -> ParseRunbookResponse:
    from app.services.llm_client import LLMClient

    client = LLMClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.AI_PARSE_MODEL or "gpt-4o",
    )
    user_prompt = build_parse_user_prompt(
        title=request.runbook.title,
        raw_content=request.runbook.raw_content,
    )
    try:
        output = client.complete_structured(
            PARSE_SYSTEM_PROMPT, user_prompt, _LLMParseOutput
        )
    except ValueError as exc:
        raise ValueError(f"LLM parse failed: {exc}") from exc
    except Exception as exc:
        raise ValueError(f"LLM parse returned invalid output: {exc}") from exc

    return ParseRunbookResponse(
        request_id=request.request_id,
        workflow_title=output.workflow_title or request.runbook.title,
        steps=output.steps,
        warnings=output.warnings,
    )
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
