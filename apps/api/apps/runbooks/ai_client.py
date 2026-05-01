"""
Django-side HTTP client for the internal AI service.

Responsibilities:
- Build URLs and timeouts from Django settings.
- POST to FastAPI /parse/runbook.
- Validate the response shape at the service boundary.
- Translate transport/HTTP errors into narrow internal exceptions.

Nothing here persists data. FastAPI is a dependency, not a source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from django.conf import settings

# ---------------------------------------------------------------------------
# Internal exceptions
# ---------------------------------------------------------------------------


class AiServiceUnavailableError(Exception):
    """AI service could not be reached (connection refused, DNS failure, etc.)."""


class AiServiceTimeoutError(Exception):
    """AI service did not respond within the configured timeout."""


class AiServiceBadResponseError(Exception):
    """AI service returned a non-200 status or non-JSON body."""


class AiServiceContractError(Exception):
    """AI service returned JSON that does not match the expected shape."""


# ---------------------------------------------------------------------------
# Local result types
# ---------------------------------------------------------------------------


@dataclass
class WorkflowCandidateStep:
    step_key: str
    name: str
    step_type: str
    risk_level: str
    requires_approval: bool
    command: str | None = None


@dataclass
class WorkflowCandidate:
    request_id: str
    workflow_title: str
    steps: list[WorkflowCandidateStep]
    warnings: list[str] = field(default_factory=list)


@dataclass
class WorkflowEnrichmentStep:
    step_key: str
    risk_level: str
    requires_approval: bool


@dataclass
class WorkflowEnrichment:
    request_id: str
    steps: list[WorkflowEnrichmentStep]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExecutionSummary:
    request_id: str
    summary: str
    key_outcomes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def _request_headers(request_id: str) -> dict[str, str]:
    return {"X-Request-ID": request_id}


class RunbookAiClient:
    """
    Thin synchronous HTTP client for the internal AI parse service.

    Use `from_settings()` in production code.
    Pass a custom `transport` (e.g. httpx.MockTransport) in tests.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout: httpx.Timeout,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @classmethod
    def from_settings(cls) -> RunbookAiClient:
        return cls(
            base_url=settings.AI_BASE_URL,
            timeout=httpx.Timeout(
                connect=settings.AI_CONNECT_TIMEOUT_SECONDS,
                read=settings.AI_READ_TIMEOUT_SECONDS,
                write=settings.AI_WRITE_TIMEOUT_SECONDS,
                pool=settings.AI_POOL_TIMEOUT_SECONDS,
            ),
        )

    def parse_runbook_to_workflow_candidate(
        self,
        *,
        request_id: str,
        runbook_id: str,
        runbook_title: str,
        raw_content: str,
    ) -> WorkflowCandidate:
        """
        Call the AI service to convert a runbook into a workflow candidate.

        Must be called OUTSIDE any DB transaction so no connection is held
        open while waiting on the network.
        """
        url = f"{self._base_url}/parse/runbook"
        payload = {
            "request_id": request_id,
            "runbook": {
                "id": runbook_id,
                "title": runbook_title,
                "raw_content": raw_content,
            },
        }

        try:
            response = self._client.post(
                url, json=payload, headers=_request_headers(request_id)
            )
        except httpx.ConnectError as exc:
            raise AiServiceUnavailableError(
                f"AI service unreachable at {url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AiServiceTimeoutError(
                f"AI service timed out at {url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise AiServiceUnavailableError(
                f"AI service request failed: {exc}"
            ) from exc

        if response.status_code != 200:
            raise AiServiceBadResponseError(
                f"AI service returned HTTP {response.status_code} for {url}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise AiServiceBadResponseError(
                "AI service returned a non-JSON body"
            ) from exc

        return _validate_and_map_candidate(data)

    def enrich_workflow_candidate(
        self,
        *,
        request_id: str,
        workflow_title: str,
        steps: list[WorkflowCandidateStep],
        raw_content: str | None = None,
    ) -> WorkflowEnrichment:
        """
        Call the AI service to enrich parsed steps with risk and approval metadata.
        """
        url = f"{self._base_url}/enrich/workflow"
        payload = {
            "request_id": request_id,
            "workflow_title": workflow_title,
            "steps": [
                {
                    "step_key": s.step_key,
                    "name": s.name,
                    "step_type": s.step_type,
                    "risk_level": s.risk_level,
                    "requires_approval": s.requires_approval,
                    **({"command": s.command} if s.command is not None else {}),
                }
                for s in steps
            ],
            **({"raw_content": raw_content} if raw_content is not None else {}),
        }

        try:
            response = self._client.post(
                url, json=payload, headers=_request_headers(request_id)
            )
        except httpx.ConnectError as exc:
            raise AiServiceUnavailableError(
                f"AI service unreachable at {url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AiServiceTimeoutError(
                f"AI service timed out at {url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise AiServiceUnavailableError(
                f"AI service request failed: {exc}"
            ) from exc

        if response.status_code != 200:
            raise AiServiceBadResponseError(
                f"AI service returned HTTP {response.status_code} for {url}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise AiServiceBadResponseError(
                "AI service returned a non-JSON body"
            ) from exc

        return _validate_and_map_enrichment(data)

    def summarize_execution(
        self,
        *,
        request_id: str,
        execution_id: str,
        workflow_title: str,
        status: str,
        steps: list[dict],
    ) -> ExecutionSummary:
        """
        Call the AI service to summarize a completed execution.
        """
        url = f"{self._base_url}/summarize/execution"
        payload = {
            "request_id": request_id,
            "execution_id": execution_id,
            "workflow_title": workflow_title,
            "status": status,
            "steps": steps,
        }

        try:
            response = self._client.post(
                url, json=payload, headers=_request_headers(request_id)
            )
        except httpx.ConnectError as exc:
            raise AiServiceUnavailableError(
                f"AI service unreachable at {url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AiServiceTimeoutError(
                f"AI service timed out at {url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise AiServiceUnavailableError(
                f"AI service request failed: {exc}"
            ) from exc

        if response.status_code != 200:
            raise AiServiceBadResponseError(
                f"AI service returned HTTP {response.status_code} for {url}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise AiServiceBadResponseError(
                "AI service returned a non-JSON body"
            ) from exc

        return _validate_and_map_summary(data)

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Response validation / mapping
# ---------------------------------------------------------------------------


def _validate_and_map_summary(data: object) -> ExecutionSummary:
    """Validate raw summary response and return a typed ExecutionSummary."""
    if not isinstance(data, dict):
        raise AiServiceContractError("AI summary response is not a JSON object")

    summary = data.get("summary", "")
    if not isinstance(summary, str):
        raise AiServiceContractError("AI summary response 'summary' must be a string")

    key_outcomes = data.get("key_outcomes", [])
    return ExecutionSummary(
        request_id=data.get("request_id", ""),
        summary=summary,
        key_outcomes=key_outcomes if isinstance(key_outcomes, list) else [],
    )


def _validate_and_map_candidate(data: object) -> WorkflowCandidate:
    """Validate raw response dict and return a typed WorkflowCandidate."""
    if not isinstance(data, dict):
        raise AiServiceContractError("AI response is not a JSON object")

    workflow_title = data.get("workflow_title", "")
    if not workflow_title:
        raise AiServiceContractError("AI response missing 'workflow_title'")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise AiServiceContractError("AI response 'steps' must be a non-empty list")

    steps: list[WorkflowCandidateStep] = []
    seen_keys: set[str] = set()

    for i, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise AiServiceContractError(f"Step {i} is not a JSON object")

        step_key = raw_step.get("step_key")
        name = raw_step.get("name")
        step_type = raw_step.get("step_type")
        risk_level = raw_step.get("risk_level")
        requires_approval = raw_step.get("requires_approval", False)

        if not step_key:
            raise AiServiceContractError(f"Step {i} missing 'step_key'")
        if not name:
            raise AiServiceContractError(f"Step {i} missing 'name'")
        if not step_type:
            raise AiServiceContractError(f"Step {i} missing 'step_type'")
        if not risk_level:
            raise AiServiceContractError(f"Step {i} missing 'risk_level'")
        if not isinstance(requires_approval, bool):
            raise AiServiceContractError(
                f"Step {i} field 'requires_approval' must be a boolean"
            )
        if step_key in seen_keys:
            raise AiServiceContractError(f"Duplicate step_key: '{step_key}'")

        command = raw_step.get("command")
        seen_keys.add(step_key)
        steps.append(
            WorkflowCandidateStep(
                step_key=step_key,
                name=name,
                step_type=step_type,
                risk_level=risk_level,
                requires_approval=requires_approval,
                command=command if isinstance(command, str) else None,
            )
        )

    warnings = data.get("warnings", [])
    return WorkflowCandidate(
        request_id=data.get("request_id", ""),
        workflow_title=workflow_title,
        steps=steps,
        warnings=warnings if isinstance(warnings, list) else [],
    )


def _validate_and_map_enrichment(data: object) -> WorkflowEnrichment:
    """Validate raw enrich response dict and return typed enrichment data."""
    if not isinstance(data, dict):
        raise AiServiceContractError("AI enrich response is not a JSON object")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise AiServiceContractError(
            "AI enrich response 'steps' must be a non-empty list"
        )

    steps: list[WorkflowEnrichmentStep] = []
    seen_keys: set[str] = set()

    for i, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise AiServiceContractError(f"Enrich step {i} is not a JSON object")

        step_key = raw_step.get("step_key")
        risk_level = raw_step.get("risk_level")
        requires_approval = raw_step.get("requires_approval")

        if not step_key:
            raise AiServiceContractError(f"Enrich step {i} missing 'step_key'")
        if step_key in seen_keys:
            raise AiServiceContractError(f"Duplicate enrich step_key: '{step_key}'")
        if not isinstance(risk_level, str) or not risk_level:
            raise AiServiceContractError(f"Enrich step {i} missing 'risk_level'")
        if not isinstance(requires_approval, bool):
            raise AiServiceContractError(
                f"Enrich step {i} field 'requires_approval' must be a boolean"
            )

        seen_keys.add(step_key)
        steps.append(
            WorkflowEnrichmentStep(
                step_key=step_key,
                risk_level=risk_level,
                requires_approval=requires_approval,
            )
        )

    warnings = data.get("warnings", [])
    return WorkflowEnrichment(
        request_id=data.get("request_id", ""),
        steps=steps,
        warnings=warnings if isinstance(warnings, list) else [],
    )
