# REST API v1

All public product endpoints are versioned under `/api/v1/`. The Django health endpoint lives outside versioning at `/health/`.

For implemented/partial/planned/deferred status across all APIs, see [API contracts](../architecture/api-contracts.md).

## Design Principles

- Views are transport adapters.
- Business logic and transactions live in service modules.
- Serializers validate requests and shape responses.
- State transitions use explicit `POST` actions.
- Errors are normalized to `{"errors": [...]}` by `apps.common.api_errors.custom_exception_handler`.

## Organizations

Base path: `/api/v1/organizations/`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/organizations/` | List organizations. |
| `POST` | `/api/v1/organizations/` | Create organization. |
| `GET` | `/api/v1/organizations/{id}/` | Retrieve organization. |

Create payload:

```json
{
  "name": "Acme Corp",
  "slug": "acme"
}
```

Response fields: `id`, `name`, `slug`, `created_at`, `updated_at`.

## Runbooks

Base path: `/api/v1/runbooks/`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/runbooks/` | List runbooks. |
| `POST` | `/api/v1/runbooks/` | Create runbook. |
| `GET` | `/api/v1/runbooks/{id}/` | Retrieve runbook. |
| `POST` | `/api/v1/runbooks/{id}/mark-ready/` | Transition draft runbook to ready. |
| `POST` | `/api/v1/runbooks/{id}/archive/` | Archive a draft or ready runbook. |

Create payload:

```json
{
  "organization_id": "<uuid>",
  "title": "Deploy Service",
  "slug": "deploy-service",
  "raw_content": "1. Verify prerequisites"
}
```

Status values: `draft`, `ready`, `archived`.

## Workflows

Base path: `/api/v1/workflows/`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/workflows/` | List workflows. |
| `POST` | `/api/v1/workflows/` | Create draft workflow from a runbook through the AI parse boundary. |
| `GET` | `/api/v1/workflows/{id}/` | Retrieve workflow. |
| `POST` | `/api/v1/workflows/{id}/publish/` | Publish draft workflow and supersede currently published sibling workflows. |
| `POST` | `/api/v1/workflows/{id}/archive/` | Archive a draft or superseded workflow. |

Create payload:

```json
{
  "runbook_id": "<uuid>"
}
```

Status values: `draft`, `published`, `superseded`, `archived`.

## Executions

Base path: `/api/v1/executions/`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/executions/` | List executions. |
| `POST` | `/api/v1/executions/` | Create queued execution from a published workflow. |
| `GET` | `/api/v1/executions/{id}/` | Retrieve execution with materialized steps. |
| `POST` | `/api/v1/executions/{id}/cancel/` | Cancel a queued execution. |

Create payload:

```json
{
  "workflow_id": "<uuid>"
}
```

Execution status values: `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`.

Step status values: `pending`, `running`, `succeeded`, `failed`, `skipped`.

## Error Responses

Shape:

```json
{
  "errors": [
    {
      "code": "invalid_state_transition",
      "detail": "Cannot cancel execution with status 'running', expected 'queued'.",
      "attr": null
    }
  ]
}
```

See [API contracts](../architecture/api-contracts.md#error-envelope) for status mapping.
