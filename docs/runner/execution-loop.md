# Runner Execution Loop

The runner is a synchronous, poll-based worker process. It executes one queued
execution at a time, talking exclusively to the Django internal API — never
directly to the database.

---

## Entry point

`apps/runner/runner/main.py`

Reads configuration from environment, wires the three components together, then
calls `Poller.run_forever()`. No orchestration logic lives here.

| Env var | Purpose | Default |
|---------|---------|---------|
| `API_BASE_URL` | Base URL of the Django API | `http://api:8000` |
| `RUNNER_REGISTRATION_TOKEN` | Short-lived bootstrap token used only to register and receive a per-runner bearer token | none |
| `RUNNER_STATE_FILE` | Persistent file containing the canonical runner ID and per-runner bearer token | none |
| `RUNNER_API_RETRIES_ENABLED` | Enables bounded retries for runner API network errors and HTTP 502/503/504 responses | `true` |

---

## Components

### `Poller` (`poller.py`)

Drives the outer loop.

1. Calls `ApiClient.claim_next()`.
2. If no work: sleeps for `poll_after_seconds` returned by Django, then repeats.
3. If work claimed: passes the `ClaimedExecution` to `Executor.run()` and **blocks**
   until execution finishes before polling again.
4. On `KeyboardInterrupt`: exits cleanly.
5. On unexpected exceptions: logs the error, sleeps 5 s, retries.

### `Executor` (`executor.py`)

Processes one claimed execution to completion.

1. Starts a `_HeartbeatThread` daemon thread.
2. Iterates steps in `position` order.
3. For each step: calls `_run_step()`.
4. On first step failure: stops iteration, marks outcome `failed`.
5. After all steps (or after first failure): stops heartbeat, calls
   `ApiClient.complete_execution()`.

### `_HeartbeatThread` (`executor.py`)

Background daemon thread that fires `ApiClient.heartbeat()` every
`_HEARTBEAT_INTERVAL_SECONDS` (10 s) while an execution is active.

- Stopped via a `threading.Event` before `complete_execution` is called.
- HTTP errors during heartbeat are logged as warnings but do not abort
  the execution.

### `ApiClient` (`client.py`)

Thin wrapper around a single `httpx.Client` with explicit timeout phases:

- Standard runner API calls use connect `2 s`, read `10 s`, write `10 s`,
  and pool `2 s`.
- Artifact uploads intentionally use the same connect and pool limits but
  read/write `60 s`, because stdout/stderr file transfer can legitimately take
  longer than small JSON state-transition calls.

| Method | Endpoint called |
|--------|----------------|
| `claim_next()` | `POST /api/v1/internal/executions/claim-next/` |
| `heartbeat()` | `POST /api/v1/internal/executions/{id}/heartbeat/` |
| `update_step()` | `POST /api/v1/internal/executions/{id}/steps/{step_id}/update/` |
| `start_step()` | `POST /api/v1/internal/executions/{id}/steps/{step_id}/start/` |
| `get_step_approval_status()` | `POST /api/v1/internal/executions/{id}/steps/{step_id}/approval-status/` |
| `complete_execution()` | `POST /api/v1/internal/executions/{id}/complete/` |
| `upload_artifact()` | `POST /api/v1/internal/executions/{id}/steps/{step_id}/artifacts/` |

Standard runner API calls retry only transport errors and HTTP 502/503/504, with
1 s, 2 s, then 4 s delays. HTTP 400/401/403/404/409 responses are not retried.
State-transition retries rely on Django's existing claim-token and idempotency
checks, so stale or conflicting transitions still fail closed. Retry logs include
method, path, attempt, delay, exception or status, runner ID, and request ID.

Artifact uploads keep their existing two-attempt uploader retry behavior. The
upload-specific timeout deviation above is intentional and limited to file
transfer.

---

## Step execution lifecycle

```
pending  ──update(running)──►  running  ──update(succeeded)──►  succeeded
                                         ──update(failed)────►  failed
```

For each step, `_run_step()`:

1. Records `started_at` locally.
2. Calls `update_step(status="running")`.
3. Checks whether the step's `command` contains the string `FAIL_STEP`.
   - **Yes** → calls `update_step(status="failed", exit_code=1)` and returns
     `True` (step failed).
   - **No** → sleeps 0.5 s (placeholder work), calls
     `update_step(status="succeeded", exit_code=0)` and returns `False`.
4. On any HTTP error: logs the failure and treats the step as failed.

### Deliberate failure path

A step whose `command` contains `FAIL_STEP` is treated as a deliberate failure.
This is used for testing and for steps that should never succeed in the current
environment.

---

## Execution status transitions (runner perspective)

| Runner action | Execution status before | Execution status after |
|---------------|------------------------|------------------------|
| `claim_next` succeeds | `queued` | `claimed` |
| First step marked `running` | `claimed` | `running` |
| `complete_execution(succeeded)` | `running` | `succeeded` |
| `complete_execution(failed)` | `running` or `claimed` | `failed` |

The transition from `claimed` → `running` happens inside
`executions.services.update_execution_step` on the Django side when the first
step's status is set to `running`.

---

## Concurrency safety

- Django uses `SELECT FOR UPDATE SKIP LOCKED` inside `transaction.atomic()` on
  `claim-next`. Two runner processes cannot claim the same execution.
- Every mutation endpoint validates `runner_id` + `claim_token`. A stale runner
  that lost its claim will receive `400` and stop.
- One execution per runner process at a time. The poller does not continue
  until the executor returns.

---

## Configuration reference

| File | Purpose |
|------|---------|
| `apps/runner/runner/main.py` | Entry point, env config |
| `apps/runner/runner/poller.py` | Outer poll loop |
| `apps/runner/runner/executor.py` | Step execution + heartbeat |
| `apps/runner/runner/client.py` | HTTP client |
| `apps/runner/runner/schemas.py` | Pydantic request/response models |
