# Internal Runner API

These endpoints are used exclusively by the runner process. They live under
`/api/v1/internal/` and are separate from the public REST API.

**The frontend never calls these endpoints. The runner never calls public endpoints for execution state.**

---

## Design principles

- All state mutations use explicit `POST` actions, not `PATCH`.
- Every mutating endpoint validates runner ownership via `runner_id` + `claim_token`.
- Step transitions are a narrow allowlist — arbitrary field mutation is not possible.
- The claim uses `SELECT FOR UPDATE SKIP LOCKED` for concurrency safety.

---

## Endpoints

### Claim next execution

`POST /api/v1/internal/executions/claim-next/`

Atomically claims the oldest `queued` execution and returns its full step list.
If no work is available, returns `execution: null` with a sleep hint.

**Request**

```json
{ "runner_id": "my-runner-token" }
```

**Response — work available**

```json
{
  "execution": {
    "id": "<uuid>",
    "status": "claimed",
    "workflow_id": "<uuid>",
    "organization_id": "<uuid>",
    "workflow_version": 1,
    "workflow_snapshot": { ... },
    "claim_token": "<uuid>",
    "steps": [
      {
        "id": "<uuid>",
        "position": 1,
        "step_key": "s1",
        "name": "Step 1",
        "step_type": "manual",
        "risk_level": "low",
        "command": "echo hello",
        "requires_approval": false,
        "status": "pending"
      }
    ]
  },
  "poll_after_seconds": 5
}
```

**Response — no work**

```json
{ "execution": null, "poll_after_seconds": 5 }
```

**Service called:** `executions.services.claim_next_execution(runner_id)`

---

### Heartbeat

`POST /api/v1/internal/executions/{execution_id}/heartbeat/`

Updates `last_heartbeat_at` on the execution. Valid only while the execution is
in `claimed` or `running` status.

**Request**

```json
{
  "runner_id": "my-runner-token",
  "claim_token": "<uuid>"
}
```

**Response**

```json
{ "status": "ok" }
```

**Errors**

| HTTP | Condition |
|------|-----------|
| 400 | Runner ID or claim token mismatch |
| 400 | Execution not in `claimed` or `running` status |
| 404 | Execution not found |

**Service called:** `executions.services.heartbeat_execution(execution, runner_id, claim_token)`

---

### Update step

`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`

Applies a status transition to one step. Allowed transitions:

- `pending` → `running`
- `running` → `succeeded`
- `running` → `failed`

When the first step transitions to `running`, Django automatically moves the
parent execution from `claimed` to `running` and records `started_at`.

**Request**

```json
{
  "runner_id": "my-runner-token",
  "claim_token": "<uuid>",
  "status": "running",
  "started_at": "<iso8601>",
  "finished_at": null,
  "exit_code": null,
  "error_message": ""
}
```

Fields `started_at`, `finished_at`, `exit_code`, and `error_message` are
optional. Django defaults timestamps to `now()` when omitted.

**Response** — the updated step in the public `ExecutionStep` shape:

```json
{
  "id": "<uuid>",
  "position": 1,
  "step_key": "s1",
  "name": "Step 1",
  "step_type": "manual",
  "risk_level": "low",
  "command": "echo hello",
  "requires_approval": false,
  "status": "running",
  "started_at": "<iso8601>",
  "finished_at": null,
  "exit_code": null,
  "error_message": ""
}
```

**Errors**

| HTTP | Condition |
|------|-----------|
| 400 | Runner ID or claim token mismatch |
| 400 | Invalid step transition (e.g. `pending` → `succeeded`) |
| 400 | Step ID not found on this execution |
| 404 | Execution not found |

**Service called:** `executions.services.update_execution_step(...)`

---

### Complete execution

`POST /api/v1/internal/executions/{execution_id}/complete/`

Marks an execution terminal. Valid only while the execution is in `claimed` or
`running` status.

**Request**

```json
{
  "runner_id": "my-runner-token",
  "claim_token": "<uuid>",
  "outcome": "succeeded"
}
```

`outcome` must be `"succeeded"` or `"failed"`.

**Response** — the full execution detail shape (same as the public `GET /api/v1/executions/{id}/`).

**Errors**

| HTTP | Condition |
|------|-----------|
| 400 | Runner ID or claim token mismatch |
| 400 | Execution not in a completable status |
| 400 | Invalid outcome value |
| 404 | Execution not found |

**Service called:** `executions.services.complete_execution(execution, runner_id, claim_token, outcome)`

---

## Runner ownership model

When `claim-next` succeeds, Django records:

| Field | Value |
|-------|-------|
| `claimed_by_runner_id` | The `runner_id` from the request |
| `claim_token` | A freshly generated UUID |
| `claimed_at` | Timestamp of the claim |
| `last_heartbeat_at` | Same as `claimed_at` initially |

All subsequent internal calls must supply the same `runner_id` and `claim_token`.
Mismatches return `400`. These fields are internal — they are not exposed on the
public execution endpoints.
