# Execution Flow

End-to-end lifecycle of a runbook execution — from creation through terminal state.

---

## Actors

| Actor | Responsibility |
|-------|---------------|
| **React frontend** | Triggers execution creation and reads status via public API |
| **Django API** | Owns all state. Exposes public API and internal runner API |
| **Runner** | Polls Django, claims work, executes steps, reports status |
| **PostgreSQL** | Single source of truth for execution and step state |

The runner never touches PostgreSQL directly. The frontend never calls internal endpoints.

---

## Lifecycle overview

```
[User] POST /api/v1/executions/
         │
         ▼
  Execution: queued
  ExecutionSteps: all pending
         │
         ▼  (runner polls claim-next)
  Execution: claimed  ◄── claim_token issued
         │
         ▼  (first step marked running)
  Execution: running
  started_at recorded
         │
         ├── for each step (in order):
         │     pending → running → succeeded
         │     (on failure: running → failed, stop)
         │
         ▼
  Execution: succeeded | failed
  finished_at recorded
```

---

## Step-by-step

### 1. Create execution

`POST /api/v1/executions/` with `{ "workflow_id": "..." }`

Django service `create_execution_from_workflow`:
- Validates workflow is `published`.
- Creates one `Execution` record (`status=queued`).
- Materializes all workflow steps as `ExecutionStep` records (`status=pending`).

### 2. Runner claims execution

Runner calls `POST /api/v1/internal/executions/claim-next/`.

Django service `claim_next_execution`:
- Acquires a row lock (`SELECT FOR UPDATE SKIP LOCKED`).
- Sets execution `status=claimed`.
- Records `claimed_by_runner_id`, `claim_token`, `claimed_at`, `last_heartbeat_at`.
- Returns execution metadata + all steps + `claim_token`.

If no work exists, returns `execution: null` with `poll_after_seconds`.

### 3. Heartbeat (ongoing)

Runner starts a background thread that calls
`POST /api/v1/internal/executions/{id}/heartbeat/` every 10 seconds for the
lifetime of the execution.

Django updates `last_heartbeat_at`. Ownership is validated on every call.

### 4. Step execution

For each step in `position` order:

**a. Mark running**
`POST /api/v1/internal/executions/{id}/steps/{step_id}/update/`
`{ "status": "running", "started_at": "..." }`

Side effect on Django: first step to run triggers `execution.status = running`
and records `execution.started_at`.

**b. Execute (placeholder)**
Runner checks if `command` contains `FAIL_STEP`:
- No → sleep 0.5 s, treat as success.
- Yes → treat as failure immediately.

**c. Mark succeeded or failed**
`POST .../update/` with `{ "status": "succeeded"|"failed", "exit_code": 0|1, ... }`

On failure: runner stops processing remaining steps.

### 5. Complete execution

`POST /api/v1/internal/executions/{id}/complete/`
`{ "outcome": "succeeded"|"failed" }`

Django:
- Validates ownership.
- Sets `status = outcome`.
- Records `finished_at`.
- Records `started_at` if not already set.

Heartbeat thread is stopped before this call.

---

## Status state machine

### Execution

```
queued ──(claim-next)──► claimed ──(first step running)──► running
                                                               │
                                          ┌────────────────────┤
                                          ▼                    ▼
                                      succeeded             failed

queued ──(cancel action)──► cancelled
```

### ExecutionStep

```
pending ──(update running)──► running ──(update succeeded)──► succeeded
                                       ──(update failed)────► failed
```

Skipped is reserved for future approval/gate flows and is not set by the runner.

---

## Failure handling

| Failure type | Behavior |
|-------------|---------|
| Step command contains `FAIL_STEP` | Step marked `failed`, execution stops, remaining steps stay `pending`, execution marked `failed` |
| HTTP error marking a step | Step treated as failed, execution stops |
| Unexpected exception in executor | Execution marked `failed`, heartbeat stopped cleanly |
| HTTP error on heartbeat | Warning logged, execution continues |
| HTTP error on `claim-next` | Poller sleeps 5 s and retries |

---

## Data model (relevant fields)

### `Execution`

| Field | Set when |
|-------|---------|
| `status` | Every state transition |
| `started_at` | First step transitions to `running` |
| `finished_at` | `complete_execution` called |
| `claimed_by_runner_id` | `claim_next` succeeds |
| `claim_token` | `claim_next` succeeds |
| `claimed_at` | `claim_next` succeeds |
| `last_heartbeat_at` | `claim_next` + every heartbeat |

### `ExecutionStep`

| Field | Set when |
|-------|---------|
| `status` | Every step update |
| `started_at` | Step transitions to `running` |
| `finished_at` | Step transitions to `succeeded` or `failed` |
| `exit_code` | Step transitions to terminal status |
| `error_message` | Step transitions to `failed` |
