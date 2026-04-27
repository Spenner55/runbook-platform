# API Contracts

This document summarizes the current API surface and separates implemented behavior from planned or deferred behavior.

## Namespaces

| Namespace | Status | Audience |
| --- | --- | --- |
| `/api/v1/` | Implemented | Public product API used by React. |
| `/api/v1/internal/` | Implemented | Runner-only internal API. |
| `/health/` | Implemented | Django health check, intentionally outside versioning. |
| FastAPI `/health` | Implemented | AI service health check. |
| FastAPI `/parse/runbook` | Implemented | Django-to-AI advisory parsing. |
| FastAPI `/enrich/workflow` | Partially implemented placeholder | Mounted route returns placeholder response; no Django integration. |
| FastAPI `/summarize/failure` | Partially implemented placeholder | Mounted route returns placeholder response; no Django integration. |

## Implemented Public Django API

All paths below are under `/api/v1/`.

### Organizations

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/organizations/` | List organizations. |
| `POST` | `/organizations/` | Create organization. |
| `GET` | `/organizations/{id}/` | Retrieve organization. |

Create request:

```json
{
  "name": "Acme Corp",
  "slug": "acme"
}
```

Response fields: `id`, `name`, `slug`, `created_at`, `updated_at`.

### Runbooks

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/runbooks/` | List runbooks. |
| `POST` | `/runbooks/` | Create runbook. |
| `GET` | `/runbooks/{id}/` | Retrieve runbook. |
| `POST` | `/runbooks/{id}/mark-ready/` | Transition `draft -> ready`. |
| `POST` | `/runbooks/{id}/archive/` | Transition `draft/ready -> archived`. |

Create request:

```json
{
  "organization_id": "<uuid>",
  "title": "Deploy Service",
  "slug": "deploy-service",
  "raw_content": "1. Verify prerequisites\n2. Deploy"
}
```

List response fields: `id`, `title`, `slug`, `status`, `organization_id`, `created_at`, `updated_at`.

Detail response adds `raw_content`.

Status values: `draft`, `ready`, `archived`.

### Workflows

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/workflows/` | List workflows. |
| `POST` | `/workflows/` | Create draft workflow from a runbook through the AI parse boundary. |
| `GET` | `/workflows/{id}/` | Retrieve workflow. |
| `POST` | `/workflows/{id}/publish/` | Transition `draft -> published`; supersedes published sibling workflows for the same runbook. |
| `POST` | `/workflows/{id}/archive/` | Transition `draft/superseded -> archived`. |

Create request:

```json
{
  "runbook_id": "<uuid>"
}
```

List response fields: `id`, `name`, `version`, `status`, `definition_schema_version`, `runbook_id`, `organization_id`, `created_at`, `updated_at`.

Detail response adds `definition`.

Status values: `draft`, `published`, `superseded`, `archived`.

### Executions

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/executions/` | List executions. |
| `POST` | `/executions/` | Create queued execution from a published workflow. |
| `GET` | `/executions/{id}/` | Retrieve execution with materialized steps. |
| `POST` | `/executions/{id}/cancel/` | Transition queued execution to `cancelled`. |

Create request:

```json
{
  "workflow_id": "<uuid>"
}
```

List response fields: `id`, `status`, `workflow_id`, `organization_id`, `workflow_version`, `claimed_by_runner_id`, `claimed_at`, `last_heartbeat_at`, `started_at`, `finished_at`, `created_at`, `updated_at`.

Detail response adds `workflow_snapshot`, `claim_token_present`, and `steps`.

Step fields: `id`, `position`, `step_key`, `name`, `step_type`, `risk_level`, `command`, `requires_approval`, `status`, `started_at`, `finished_at`, `exit_code`, `error_message`.

Execution status values: `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`.

Step status values: `pending`, `running`, `succeeded`, `failed`, `skipped`.

## Implemented Internal Runner API

All paths below are under `/api/v1/internal/`.

### Claim Next

`POST /executions/claim-next/`

Request:

```json
{
  "runner_id": "runner-dev",
  "runner_version": "0.1.0",
  "requested_at": "2026-04-27T00:00:00Z"
}
```

Response with work:

```json
{
  "execution": {
    "id": "<uuid>",
    "status": "claimed",
    "workflow_id": "<uuid>",
    "organization_id": "<uuid>",
    "workflow_version": 1,
    "workflow_snapshot": {"name": "Deploy", "steps": []},
    "claimed_by_runner_id": "runner-dev",
    "claimed_at": "<iso8601>",
    "last_heartbeat_at": "<iso8601>",
    "steps": []
  },
  "claim_token": "<uuid>",
  "poll_after_seconds": 5
}
```

Response with no work:

```json
{
  "execution": null,
  "poll_after_seconds": 5
}
```

### Heartbeat

`POST /executions/{execution_id}/heartbeat/`

Request:

```json
{
  "runner_id": "runner-dev",
  "claim_token": "<uuid>",
  "observed_status": "running",
  "sent_at": "<iso8601>"
}
```

Response:

```json
{
  "execution_id": "<uuid>",
  "status": "running",
  "last_heartbeat_at": "<iso8601>"
}
```

### Step Update

`POST /executions/{execution_id}/steps/{step_id}/update/`

Allowed service transitions:

- `pending -> running`
- `running -> succeeded`
- `running -> failed`

Request:

```json
{
  "runner_id": "runner-dev",
  "claim_token": "<uuid>",
  "status": "succeeded",
  "started_at": "<iso8601>",
  "finished_at": "<iso8601>",
  "exit_code": 0,
  "error_message": ""
}
```

Response:

```json
{
  "execution_id": "<uuid>",
  "step": {
    "id": "<uuid>",
    "position": 1,
    "step_key": "step-1",
    "name": "Verify prerequisites",
    "step_type": "manual_task",
    "risk_level": "medium",
    "command": "",
    "requires_approval": false,
    "status": "succeeded",
    "started_at": "<iso8601>",
    "finished_at": "<iso8601>",
    "exit_code": 0,
    "error_message": ""
  },
  "execution_status": "running"
}
```

The serializer currently accepts `skipped`, but the service layer does not allow a transition to `skipped`.

### Complete Execution

`POST /executions/{execution_id}/complete/`

Request:

```json
{
  "runner_id": "runner-dev",
  "claim_token": "<uuid>",
  "final_status": "succeeded",
  "finished_at": "<iso8601>",
  "error_message": ""
}
```

Response:

```json
{
  "id": "<uuid>",
  "status": "succeeded",
  "finished_at": "<iso8601>"
}
```

## Implemented FastAPI AI API

### Health

`GET /health`

Response:

```json
{
  "status": "ok",
  "service": "ai"
}
```

### Parse Runbook

`POST /parse/runbook`

Request:

```json
{
  "request_id": "<uuid>",
  "runbook": {
    "id": "<runbook-id-or-slug>",
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

## Error Envelope

Django uses `apps.common.api_errors.custom_exception_handler` to normalize DRF and domain errors:

```json
{
  "errors": [
    {
      "code": "invalid_state_transition",
      "detail": "Cannot publish workflow with status 'published', expected 'draft'.",
      "attr": null
    }
  ]
}
```

Domain exception status mapping:

| Exception | HTTP |
| --- | --- |
| `DomainValidationError` | 400 |
| `InvalidWorkflowDefinitionError` | 400 |
| `DomainConflictError` | 409 |
| `ConcurrencyConflictError` | 409 |
| `InvalidStateTransitionError` | 409 |
| `ExternalDependencyError` | 503 |

## Planned By Blueprint

These are not implemented unless later code proves otherwise:

- Auth endpoints under `/api/v1/auth/...`.
- Membership endpoints.
- Approval endpoints.
- Policy endpoints.
- Audit event endpoints.
- Artifact endpoints.
- Integration endpoints.
- Execution event streaming endpoint.
- Richer AI endpoints beyond the current placeholder `enrich` and `summarize` routes.
- Production health/readiness/metrics endpoints beyond current simple health checks.

## Deferred

- Public API pagination strategy.
- OpenAPI/schema generation.
- Auth and permissions.
- Runner token authentication.
- SSE/websocket live updates.
- Queue-backed execution dispatch.

## Rules For Adding Endpoints

- Add public product endpoints under `/api/v1/`.
- Add runner-only endpoints under `/api/v1/internal/`.
- Keep health endpoints separate and documented.
- Use serializers for request validation and response shape.
- Put business logic and transactions in services.
- Add tests for service behavior and API contracts.
- Update this document and the relevant frontend/runner docs.
- Mark planned endpoints as planned until code exists.

## Public Vs Internal Rules

- Public endpoints are for browser/product clients and future external API consumers.
- Internal endpoints are for runner processes and should use dedicated serializers/views.
- Internal endpoints must validate runner ownership for claimed execution mutations.
- Public endpoints must not expose raw `claim_token` values.

## Authentication And Authorization

Current state: deferred. DRF is configured with `AllowAny`, and internal endpoint isolation is structural rather than authenticated. Phase 10.7 plans auth and runner-token hardening.
