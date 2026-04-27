# Internal Runner API

Runner endpoints are under `/api/v1/internal/` and are not public product APIs.

The frontend must never call these endpoints. The runner must not use public execution endpoints to mutate execution state.

For full contract status, see [API contracts](../architecture/api-contracts.md).

## Design Principles

- Runner state mutations use explicit `POST` actions.
- Mutating endpoints validate `runner_id` and `claim_token`.
- Step transitions are allowlisted in the service layer.
- Claiming work uses `SELECT FOR UPDATE SKIP LOCKED`.

## Claim Next

`POST /api/v1/internal/executions/claim-next/`

Request:

```json
{
  "runner_id": "runner-dev",
  "runner_version": "0.1.0",
  "requested_at": "<iso8601>"
}
```

Response with work includes `execution`, top-level `claim_token`, and `poll_after_seconds`.

Response with no work:

```json
{
  "execution": null,
  "poll_after_seconds": 5
}
```

## Heartbeat

`POST /api/v1/internal/executions/{execution_id}/heartbeat/`

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

## Step Update

`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`

Service-allowed transitions:

- `pending -> running`
- `running -> succeeded`
- `running -> failed`

Response includes `execution_id`, updated `step`, and `execution_status`.

## Complete Execution

`POST /api/v1/internal/executions/{execution_id}/complete/`

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

## Ownership Model

When claim-next succeeds, Django records:

| Field | Value |
| --- | --- |
| `claimed_by_runner_id` | Request `runner_id`. |
| `claim_token` | Fresh Django-generated UUID. |
| `claimed_at` | Claim timestamp. |
| `last_heartbeat_at` | Initially same as claim timestamp. |

All later internal mutation calls must supply the matching `runner_id` and `claim_token`.
