"""
Execution summarization service.

Produces a human-readable summary of a completed workflow execution.

When AI_USE_LLM_PARSER=false (default), applies deterministic template-based logic.
When AI_USE_LLM_PARSER=true (and OPENAI_API_KEY is set), calls the LLM.
"""

from __future__ import annotations

import json

from app.core.config import settings
from app.prompts.summarize import SUMMARIZE_SYSTEM_PROMPT, build_summarize_user_prompt
from app.schemas.workflow_summarize import (
    ExecutionSummarizeRequest,
    ExecutionSummarizeResponse,
)


def summarize_execution_result(request: ExecutionSummarizeRequest) -> ExecutionSummarizeResponse:
    if settings.AI_USE_LLM_PARSER and settings.OPENAI_API_KEY:
        return _llm_summarize(request)
    return _deterministic_summarize(request)


def _deterministic_summarize(request: ExecutionSummarizeRequest) -> ExecutionSummarizeResponse:
    total = len(request.steps)
    succeeded = [s for s in request.steps if s.status == "succeeded"]
    failed = [s for s in request.steps if s.status == "failed"]

    if request.status == "succeeded":
        summary = (
            f"Execution of '{request.workflow_title}' completed successfully. "
            f"All {total} step(s) succeeded."
        )
    elif request.status == "failed":
        summary = (
            f"Execution of '{request.workflow_title}' failed. "
            f"{len(failed)} of {total} step(s) did not complete successfully."
        )
    else:
        summary = (
            f"Execution of '{request.workflow_title}' ended with status: {request.status}. "
            f"{len(succeeded)} of {total} step(s) succeeded."
        )

    key_outcomes: list[str] = []
    for step in failed:
        msg = f"Step '{step.name}' failed"
        if step.output:
            msg += f": {step.output}"
        key_outcomes.append(msg)
    for step in succeeded:
        if step.output:
            key_outcomes.append(f"Step '{step.name}': {step.output}")

    return ExecutionSummarizeResponse(
        request_id=request.request_id,
        summary=summary,
        key_outcomes=key_outcomes[:5],
    )


def _llm_summarize(request: ExecutionSummarizeRequest) -> ExecutionSummarizeResponse:
    from app.services.llm_client import LLMClient

    client = LLMClient(
        api_key=settings.OPENAI_API_KEY,
        model=settings.AI_PARSE_MODEL or "gpt-4o",
    )
    steps_lines = []
    for step in request.steps:
        line = f"- {step.name} [{step.status}]"
        if step.output:
            line += f": {step.output}"
        steps_lines.append(line)
    steps_text = "\n".join(steps_lines) or "(no steps)"

    user_prompt = build_summarize_user_prompt(
        workflow_title=request.workflow_title,
        status=request.status,
        steps_text=steps_text,
    )
    try:
        raw = client.complete(SUMMARIZE_SYSTEM_PROMPT, user_prompt)
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"LLM summarize returned invalid output: {exc}") from exc

    return ExecutionSummarizeResponse(
        request_id=request.request_id,
        summary=data.get("summary", ""),
        key_outcomes=data.get("key_outcomes", []),
    )
