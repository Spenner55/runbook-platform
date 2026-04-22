# REST API v1

All endpoints are versioned under `/api/v1/`. The health endpoint lives outside versioning at `/health/`.

## Design principles

- Views are transport-only. All business logic lives in `services.py`.
- Views never call `.save()` directly for core mutations — they call service functions.
- Serializers are split by intent: `Create`, `List`, and `Detail` variants exist where the shapes differ.
- State transitions (publish, cancel) use explicit `POST` actions, not `PATCH`.
- Validation errors surface naturally via DRF — no custom error envelope at this layer.

---

## Organizations

**Base path:** `/api/v1/organizations/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/organizations/` | List all organizations |
| POST | `/api/v1/organizations/` | Create an organization |
| GET | `/api/v1/organizations/{id}/` | Retrieve an organization |

### Create payload

```json
{
  "name": "Acme Corp",
  "slug": "acme"
}
```

### Response shape (create / detail / list item)

```json
{
  "id": "<uuid>",
  "name": "Acme Corp",
  "slug": "acme",
  "created_at": "<iso8601>",
  "updated_at": "<iso8601>"
}
```

### Service called

`organizations.services.create_organization(name, slug)`

---

## Runbooks

**Base path:** `/api/v1/runbooks/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/runbooks/` | List all runbooks |
| POST | `/api/v1/runbooks/` | Create a runbook |
| GET | `/api/v1/runbooks/{id}/` | Retrieve a runbook |

### Create payload

```json
{
  "organization_id": "<uuid>",
  "title": "Deploy Service",
  "slug": "deploy-service",
  "raw_content": "## Steps\n..."
}
```

### List item shape

```json
{
  "id": "<uuid>",
  "title": "Deploy Service",
  "slug": "deploy-service",
  "status": "draft",
  "organization_id": "<uuid>",
  "created_at": "<iso8601>"
}
```

### Detail shape (create response / retrieve)

Adds `raw_content` and `updated_at` to the list shape.

### Status values

`draft` | `ready` | `archived`

### Service called

`runbooks.services.create_runbook(organization, title, slug, raw_content)`

---

## Workflows

**Base path:** `/api/v1/workflows/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/workflows/` | List all workflows |
| POST | `/api/v1/workflows/` | Create a workflow from a runbook |
| GET | `/api/v1/workflows/{id}/` | Retrieve a workflow |
| POST | `/api/v1/workflows/{id}/publish/` | Transition draft → published |

### Create payload

```json
{
  "runbook_id": "<uuid>"
}
```

A new version number is assigned automatically (increments from the runbook's highest existing version, starting at 1). The initial `definition` is derived from the runbook.

### List item shape

```json
{
  "id": "<uuid>",
  "name": "Deploy Service",
  "version": 1,
  "status": "draft",
  "runbook_id": "<uuid>",
  "organization_id": "<uuid>",
  "created_at": "<iso8601>"
}
```

### Detail shape (create response / retrieve / action responses)

Adds `definition`, `definition_schema_version`, and `updated_at` to the list shape.

### Status values

`draft` | `published` | `superseded` | `archived`

### Publish action

`POST /api/v1/workflows/{id}/publish/`

- Transitions status from `draft` to `published`.
- Returns `400` if the workflow is not currently in `draft` status.
- Returns the full detail shape on success.

### Services called

- Create: `workflows.services.create_workflow_from_runbook(runbook)`
- Publish: `workflows.services.publish_workflow(workflow)`

---

## Executions

**Base path:** `/api/v1/executions/`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/executions/` | List all executions |
| POST | `/api/v1/executions/` | Create an execution from a workflow |
| GET | `/api/v1/executions/{id}/` | Retrieve an execution with steps |
| POST | `/api/v1/executions/{id}/cancel/` | Cancel a queued execution |

### Create payload

```json
{
  "workflow_id": "<uuid>"
}
```

The workflow must be in `published` status. On creation, all steps defined in the workflow are materialized as `ExecutionStep` records in `pending` status.

### List item shape

```json
{
  "id": "<uuid>",
  "status": "queued",
  "workflow_id": "<uuid>",
  "organization_id": "<uuid>",
  "workflow_version": 1,
  "created_at": "<iso8601>"
}
```

### Detail shape (create response / retrieve / action responses)

Adds `workflow_snapshot`, `started_at`, `finished_at`, `updated_at`, and a `steps` array.

#### Step shape (nested in detail)

```json
{
  "id": "<uuid>",
  "position": 1,
  "step_key": "step-1",
  "name": "Verify prerequisites",
  "step_type": "manual",
  "risk_level": "low",
  "command": "",
  "requires_approval": false,
  "status": "pending",
  "started_at": null,
  "finished_at": null,
  "exit_code": null,
  "error_message": ""
}
```

### Execution status values

`queued` → `claimed` → `running` → `succeeded` / `failed` / `cancelled`

### Step status values

`pending` → `running` → `succeeded` / `failed` / `skipped`

### Cancel action

`POST /api/v1/executions/{id}/cancel/`

- Only `queued` executions may be cancelled.
- Returns `400` if the execution is in any other status.
- Returns the full detail shape (including steps) on success.

### Services called

- Create: `executions.services.create_execution_from_workflow(workflow)`
- Cancel: `executions.services.cancel_execution(execution)`

---

## Error responses

DRF validation errors return `400` with a field-keyed body:

```json
{ "field_name": ["Error message."] }
```

Service-layer `ValueError` (invalid state transitions) return `400` with:

```json
{ "detail": "Human-readable reason." }
```

Object not found returns `404` via DRF's standard `get_object()`.
