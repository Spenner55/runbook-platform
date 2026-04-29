"""
Workflow enrichment service.

Adds risk classification and approval requirements to parsed workflow steps.

When AI_USE_LLM_PARSER=false (default), applies deterministic keyword-based rules.
When AI_USE_LLM_PARSER=true (and OPENAI_API_KEY is set), calls the LLM.
"""

from __future__ import annotations

import json

from app.core.config import settings
from app.prompts.enrich import ENRICH_SYSTEM_PROMPT, build_enrich_user_prompt
from app.schemas.workflow_enrich import WorkflowEnrichRequest, WorkflowEnrichResponse
from app.schemas.workflow_parse import WorkflowCandidateStep

_CRITICAL_KEYWORDS = {
    "delete",
    "drop",
    "truncate",
    "failover",
    "destroy",
    "wipe",
    "purge",
}
_HIGH_KEYWORDS = {
    "deploy",
    "migration",
    "migrate",
    "restart",
    "reboot",
    "scale",
    "upgrade",
    "rollback",
}
_LOW_KEYWORDS = {
    "check",
    "verify",
    "read",
    "list",
    "view",
    "health",
    "monitor",
    "describe",
    "show",
    "validate",
}


def enrich_workflow_candidate(request: WorkflowEnrichRequest) -> WorkflowEnrichResponse:
    if settings.AI_USE_LLM_PARSER and settings.OPENAI_API_KEY:
        return _llm_enrich(request)
    return _deterministic_enrich(request)


def _deterministic_enrich(request: WorkflowEnrichRequest) -> WorkflowEnrichResponse:
    enriched: list[WorkflowCandidateStep] = []
    for step in request.steps:
        risk, approval = _classify_risk(step)
        enriched.append(
            step.model_copy(update={"risk_level": risk, "requires_approval": approval})
        )
    return WorkflowEnrichResponse(
        request_id=request.request_id,
        steps=enriched,
        warnings=[],
    )


def _classify_risk(step: WorkflowCandidateStep) -> tuple[str, bool]:
    text = step.name.lower() + " " + (step.command or "").lower()
    if any(kw in text for kw in _CRITICAL_KEYWORDS):
        return "critical", True
    if any(kw in text for kw in _HIGH_KEYWORDS):
        return "high", True
    if any(kw in text for kw in _LOW_KEYWORDS):
        return "low", False
    if step.step_type == "approval":
        return "medium", True
    return "medium", False


def _llm_enrich(request: WorkflowEnrichRequest) -> WorkflowEnrichResponse:
    from app.services.llm_client import LLMClient

    client = LLMClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.AI_PARSE_MODEL or "gpt-4o",
    )
    steps_json = json.dumps([s.model_dump() for s in request.steps], indent=2)
    user_prompt = build_enrich_user_prompt(
        workflow_title=request.workflow_title,
        steps_json=steps_json,
    )
    try:
        raw = client.complete(ENRICH_SYSTEM_PROMPT, user_prompt)
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"LLM enrich returned invalid output: {exc}") from exc

    try:
        steps = [WorkflowCandidateStep(**s) for s in data.get("steps", [])]
    except Exception as exc:
        raise ValueError(f"LLM enrich output failed schema validation: {exc}") from exc

    return WorkflowEnrichResponse(
        request_id=request.request_id,
        steps=steps,
        warnings=data.get("warnings", []),
    )
