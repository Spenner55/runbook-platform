# AI Service Boundary

## Purpose

The FastAPI AI service is an advisory dependency used by Django. Today it deterministically parses runbook text into workflow candidates through `POST /parse/runbook`.

It does not own product state.

## Why It Is Advisory Only

AI output is untrusted derived data. Django must validate it before persistence because Django owns:

- Workflow version allocation.
- Workflow definition persistence.
- Tenant scoping.
- API contracts.
- State transitions.
- Error handling exposed to product clients.

FastAPI returns candidates; Django decides whether and how to persist.

## Allowed Django To AI Calls

Current allowed call:

- Django `RunbookAiClient` -> FastAPI `POST /parse/runbook`.

Allowed future calls, only after approved blueprint work:

- Workflow enrichment suggestions.
- Failure summaries.
- Safer provider-backed parsing.

All future calls must remain advisory and return bounded schemas.

## Disallowed Calls

- React frontend -> FastAPI.
- Runner -> FastAPI.
- FastAPI -> PostgreSQL.
- FastAPI -> runner.
- FastAPI persisting workflows, executions, approvals, artifacts, policies, or audit rows.

## Current AI Endpoints

| Method | Path | Status | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | Implemented | Returns AI process health plus OpenAI dependency status. |
| `POST` | `/parse/runbook` | Implemented | Parses raw runbook content into a workflow candidate. |
| `POST` | `/enrich/workflow` | Placeholder | Returns a static placeholder response; unused by Django. |
| `POST` | `/summarize/failure` | Placeholder | Returns a static placeholder response; unused by Django. |

## Parse Contract

Request:

```json
{
  "request_id": "<uuid>",
  "runbook": {
    "id": "<id-or-slug>",
    "title": "Deploy Service",
    "raw_content": "1. Verify prerequisites"
  }
}
```

Response:

```json
{
  "request_id": "<uuid>",
  "workflow_title": "Deploy Service",
  "steps": [
    {
      "step_key": "step-1",
      "name": "Verify prerequisites",
      "step_type": "manual_task",
      "risk_level": "medium",
      "requires_approval": false
    }
  ],
  "warnings": []
}
```

## Error And Timeout Expectations

Django-side client behavior:

- Connection failures become `AiServiceUnavailableError`.
- Timeout failures become `AiServiceTimeoutError`.
- Non-200 or non-JSON responses become `AiServiceBadResponseError`.
- Shape mismatches become `AiServiceContractError`.
- Workflow view maps these to `ExternalDependencyError` with HTTP 503.

The AI call should happen outside a database transaction.

## Health Contract

`GET /health` always reports AI service process health with HTTP 200 when the
FastAPI process can respond. Dependency degradation is informational for Django
detailed health checks and operator dashboards; it is not an ALB readiness
signal.

Response shape:

```json
{
  "status": "ok",
  "service": "ai",
  "checks": {
    "openai": {
      "status": "ok",
      "mode": "connectivity_checked",
      "detail": "OpenAI models endpoint reachable."
    }
  }
}
```

OpenAI status behavior:

- When `AI_USE_LLM_PARSER=false`, OpenAI is reported as `disabled` and the
  overall AI status remains `ok`.
- When LLM parsing is enabled without `OPENAI_API_KEY` or `AI_PARSE_MODEL`, the
  overall AI status is `degraded` and the OpenAI check reports
  `not_configured`.
- When LLM parsing is enabled and configured, health checks the non-generative
  OpenAI models endpoint with `AI_HEALTH_OPENAI_TIMEOUT_SECONDS`.
- Connectivity results are cached for `AI_HEALTH_OPENAI_CACHE_SECONDS` to avoid
  provider health-check amplification.
- Health must not call chat completions, structured completions, parsing,
  enrichment, or summarization code.

## Integration Rule For Workflow Parsing

Workflow parsing must flow through Django:

1. Frontend posts `runbook_id` to Django.
2. Django loads the runbook.
3. Django calls FastAPI parse.
4. Django validates candidate output.
5. Django maps the candidate to workflow definition.
6. Django persists workflow version and definition.

Do not move steps 4-6 into FastAPI.

## Planned AI Work

Blueprint-level only unless implemented later:

- Provider-backed richer parsing.
- Prompt templates and safety controls.
- Workflow enrichment.
- Failure summarization.
- Request correlation and observability.

These additions must keep FastAPI stateless and advisory.
