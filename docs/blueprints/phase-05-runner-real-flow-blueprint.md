# Phase 05 Blueprint: Runner Real Flow

## 1. Phase Summary

| Field | Value |
| --- | --- |
| Phase number | 05 |
| Objective | Implement the first real runner execution flow for the vertical slice: poll Django for queued executions, claim work, simulate step execution, emit structured logs, send heartbeat updates, and close executions through Django internal endpoints only. |
| Status | Planned |
| Primary outputs | Real poller loop, typed runner API client, sequential fake executor, deterministic failure path via `FAIL_STEP`, heartbeat flow, structured logging, thin `main.py`, and runner-focused tests. |
| Dependencies | `/home/dylan/code/runbook-platform/docs/blueprints/phase-02-django-domain-foundation-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-03-application-service-layer-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-04-versioned-rest-apis-blueprint.md`, `/home/dylan/code/runbook-platform/apps/runner`, `/home/dylan/code/runbook-platform/docker-compose.yml`, `/home/dylan/code/runbook-platform/.env.example`. |
| Current runner state | `/home/dylan/code/runbook-platform/apps/runner/runner/main.py` is a heartbeat print loop; `/home/dylan/code/runbook-platform/apps/runner/runner/client.py`, `/home/dylan/code/runbook-platform/apps/runner/runner/executor.py`, and `/home/dylan/code/runbook-platform/apps/runner/runner/log_streamer.py` are placeholders. |
| Runtime baseline in repo | Python 3.12 from `/home/dylan/code/runbook-platform/apps/runner/Dockerfile`, `httpx>=0.27,<1.0`, `pydantic>=2.0,<3.0` from `/home/dylan/code/runbook-platform/apps/runner/requirements.txt`. |
| Documentation basis reviewed on | 2026-03-31 |
| Phase guardrails | Runner must not talk directly to PostgreSQL, must call Django internal endpoints only, must stay poll-based, must keep `main.py` thin, and must not introduce Celery, Redis, Kafka, websockets, or background infrastructure beyond the runner process itself. |

### Official Documentation Reviewed

Python:

- [logging reference](https://docs.python.org/3/library/logging.html)
- [Logging Cookbook](https://docs.python.org/3/howto/logging-cookbook.html)

HTTPX:

- [Clients](https://www.python-httpx.org/advanced/clients/)
- [Timeouts](https://www.python-httpx.org/advanced/timeouts/)
- [Exceptions](https://www.python-httpx.org/exceptions/)
- [Event Hooks](https://www.python-httpx.org/advanced/event-hooks/)
- [Transports](https://www.python-httpx.org/advanced/transports/)
- [Async Support](https://www.python-httpx.org/async/)

Pydantic:

- [Models](https://docs.pydantic.dev/latest/concepts/models/)
- [Configuration](https://docs.pydantic.dev/latest/concepts/config/)
- [Serialization](https://docs.pydantic.dev/latest/concepts/serialization/)

### Version Alignment Notes

- Latest official docs were reviewed first, as required.
- Recommendations in this blueprint are intentionally limited to APIs that remain compatible with the repo’s current runtime:
  - Python 3.12
  - `httpx>=0.27,<1.0`
  - `pydantic>=2,<3`
- No Python 3.13+ or 3.14-only implementation requirement is introduced for this phase.
- The runner should stay synchronous in v1. HTTPX explicitly offers a standard synchronous API by default and async support as an option, but this phase does not need async client complexity for one poll loop and one active execution at a time.

### Phase Goal in One Sentence

Make the runner a real but intentionally simple worker that continuously polls Django, safely claims one execution, walks steps sequentially, sends narrow execution updates back to Django, and produces production-shaped logs without introducing queueing infrastructure or direct database access.

## 2. Runner’s Role in the Vertical Slice

The vertical slice remains:

1. User or API client creates a runbook, workflow, and execution through Django.
2. Django persists the execution and materialized execution steps.
3. Runner polls Django internal endpoints for the next queued execution.
4. Django atomically claims the execution and returns the execution snapshot plus steps.
5. Runner performs fake step execution in order.
6. Runner reports step transitions, heartbeat updates, and terminal completion back to Django.
7. Frontend and operators continue reading execution state from Django, not from the runner.

### Boundary Rules

- Runner never imports Django models.
- Runner never opens a database connection.
- Runner never reads or writes execution state outside Django APIs.
- Runner never talks directly to the frontend.
- Runner never talks directly to the AI service in this phase.
- Runner calls only the internal endpoints planned in Phase 04:
  - `POST /api/v1/internal/executions/claim-next/`
  - `POST /api/v1/internal/executions/{execution_id}/heartbeat/`
  - `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`
  - `POST /api/v1/internal/executions/{execution_id}/complete/`

### Why This Matters

This keeps Django as the control plane and source of truth. The runner is an execution engine only. If the runner starts owning persistence logic, later replacement with a real execution backend becomes much harder and the architecture from Phases 02 to 04 collapses.

## 3. Target Package Layout Under `apps/runner`

Use the existing runner package and add only the minimum new modules needed for a real flow.

```text
/home/dylan/code/runbook-platform/apps/runner/
  Dockerfile
  README.md
  requirements.txt
  runner/
    __init__.py
    main.py
    client.py
    poller.py
    executor.py
    schemas.py
    log_streamer.py
    artifact_uploader.py
    sandbox.py
    tests/
      __init__.py
      test_schemas.py
      test_client.py
      test_executor.py
      test_poller.py
      test_orchestration.py
```

### Naming Decision: `schemas.py` Over `models.py`

Use `schemas.py`, not `models.py`.

Reason:

- This service does not own persistence models.
- `models.py` strongly implies ORM/database ownership in this repository.
- The file’s job is typed request/response payloads and runner-local state objects, which maps directly to Pydantic schemas.

If the team later insists on `models.py` for service-local data structures, the contents below still apply, but `schemas.py` is the better v1 name.

### Modules Explicitly Left Out of Scope

- `/home/dylan/code/runbook-platform/apps/runner/runner/sandbox.py`
- `/home/dylan/code/runbook-platform/apps/runner/runner/artifact_uploader.py`

These should remain placeholders in Phase 05. The real flow here is fake execution, not real shell sandboxing or artifact handling.

## 4. Module Responsibilities

### `/home/dylan/code/runbook-platform/apps/runner/runner/main.py`

Keep this file thin.

It should do only bootstrap work:

- load environment configuration
- configure logging
- build one long-lived `httpx.Client`
- construct `RunnerApiClient`
- construct `LogStreamer`
- construct `Executor`
- construct `Poller`
- call `poller.run_forever()`

It should not:

- contain the claim loop
- contain step orchestration logic
- construct ad hoc request payload dictionaries inline
- contain retry policy logic
- parse execution snapshots itself

Target shape:

```python
def main() -> None:
    settings = RunnerSettings.from_env()
    logger = configure_logging(settings)
    with build_httpx_client(settings, logger) as http_client:
        api_client = RunnerApiClient(settings=settings, http_client=http_client, logger=logger)
        log_streamer = LogStreamer(base_logger=logger)
        executor = Executor(settings=settings, api_client=api_client, log_streamer=log_streamer, logger=logger)
        poller = Poller(settings=settings, api_client=api_client, executor=executor, logger=logger)
        poller.run_forever()
```

### `/home/dylan/code/runbook-platform/apps/runner/runner/client.py`

Owns all Django HTTP communication.

Responsibilities:

- construct internal endpoint URLs from `API_BASE_URL`
- send typed POST requests
- apply explicit timeouts
- raise or wrap HTTPX exceptions consistently
- deserialize responses into Pydantic models
- expose narrow methods:
  - `claim_next()`
  - `heartbeat()`
  - `update_step()`
  - `complete_execution()`

Design rules:

- one reusable `httpx.Client` instance for the process
- no direct `httpx.post(...)` calls scattered across modules
- no automatic generic retries for mutating POST requests
- log request/response metadata, not full workflow snapshots or secrets

### `/home/dylan/code/runbook-platform/apps/runner/runner/poller.py`

Owns the outer long-running claim loop.

Responsibilities:

- idle polling when no work exists
- invoking `claim_next()`
- sleeping based on Django `poll_after_seconds` or local fallback
- handing claimed executions to `Executor`
- applying bounded idle/error backoff
- ensuring only one execution is active per runner process in v1

The poller should not:

- know per-step execution details
- build step-update payloads
- manage heartbeat request formatting directly

### `/home/dylan/code/runbook-platform/apps/runner/runner/executor.py`

Owns the in-memory lifecycle of one claimed execution.

Responsibilities:

- accept one claimed execution payload from `Poller`
- start heartbeat activity for that execution
- iterate steps in `position` order
- send `running` step updates
- simulate step execution
- detect `FAIL_STEP`
- send terminal step updates
- call execution `complete`
- stop further steps after first unrecoverable failure

The executor should be the only place that understands:

- happy path sequencing
- failure path sequencing
- when to stop after a failed step
- when the execution as a whole should become `failed`

### `/home/dylan/code/runbook-platform/apps/runner/runner/schemas.py`

Owns typed payloads and runner-local state shapes.

Recommended contents:

- configuration model: `RunnerSettings`
- API request models:
  - `ClaimNextRequest`
  - `HeartbeatRequest`
  - `StepUpdateRequest`
  - `CompleteExecutionRequest`
- API response models:
  - `ClaimNextResponse`
  - `HeartbeatResponse`
  - `StepUpdateResponse`
  - `CompleteExecutionResponse`
- nested execution payloads:
  - `ClaimedExecution`
  - `ClaimedExecutionStep`
- local runtime result models:
  - `StepRunResult`
  - `ExecutionRunSummary`

### `/home/dylan/code/runbook-platform/apps/runner/runner/log_streamer.py`

Owns structured log emission for execution lifecycle events.

Responsibilities:

- turn runner events into JSON log lines
- attach stable execution and step context to logs
- centralize log event names so they stay consistent
- optionally expose helper methods such as:
  - `execution_claimed(...)`
  - `step_started(...)`
  - `step_log(...)`
  - `step_finished(...)`
  - `heartbeat_sent(...)`
  - `execution_completed(...)`

It should not:

- call Django APIs
- store logs in the database
- write artifacts
- own retry logic

## 5. Detailed Lifecycle

This section defines the real flow the runner should implement.

### 5.1 Idle

Idle is the normal state when no execution is active.

Sequence:

1. Runner process starts.
2. `main.py` builds configuration, logging, HTTP client, and service objects.
3. `Poller.run_forever()` begins.
4. Poller emits `runner_poll_cycle_started`.
5. Poller calls `RunnerApiClient.claim_next(...)`.
6. If Django returns `execution: null`, poller logs `runner_no_work_available`.
7. Poller sleeps for `poll_after_seconds` from the response, or local `RUNNER_POLL_INTERVAL_SECONDS` fallback if absent.
8. Loop repeats.

Idle rules:

- no warnings should be emitted for the normal “no jobs” case
- no heartbeat should run when there is no claimed execution
- no step logic should run from the idle state

### 5.2 Claim

Claim is a single POST to Django internal API.

Request:

- `runner_id`
- `runner_version`
- `requested_at`

Expected success outcomes:

- `execution: null` and `poll_after_seconds`
- or a claimed execution payload plus `claim_token`

Claim rules:

- runner treats Django as the authority on whether a claim succeeded
- runner never infers a claim from local timing
- runner never claims by modifying local status
- runner never retries `claim-next` transparently at the HTTP layer because it is a mutating POST and may have succeeded server-side even if the response was lost

When work is returned:

1. Poller validates the JSON into `ClaimNextResponse`.
2. Poller logs `execution_claim_received`.
3. Poller passes the typed claim to `Executor.run_execution(...)`.
4. Poller does not continue polling until that execution returns terminally or aborts.

### 5.3 Running

An execution is considered locally active as soon as the runner has a valid claim payload.

Recommended local sequence:

1. Executor constructs an execution context from:
   - `runner_id`
   - `execution_id`
   - `claim_token`
   - ordered steps
2. Executor starts a heartbeat worker for the execution.
3. Executor sorts steps defensively by `position` even if Django already returns them ordered.
4. Executor processes one step at a time.
5. Executor stops processing further steps after the first failure.
6. Executor sends exactly one terminal execution update via `complete_execution(...)`.

Why heartbeat starts before the first step:

- the claim already represents active ownership
- a long setup pause before step 1 should still refresh liveness
- it reduces the window where a slow local runner appears abandoned immediately after claim

### 5.4 Per-Step Updates

Per-step behavior should be explicit and sequential.

For each step:

1. Emit a local `step_starting` structured log.
2. Call step-update with `status="running"` and `started_at`.
3. Perform fake execution.
4. If fake execution succeeds:
   - emit `step_succeeded` log
   - call step-update with `status="succeeded"`, `finished_at`, `exit_code=0`, `error_message=""`
5. If fake execution fails:
   - emit `step_failed` log
   - call step-update with `status="failed"`, `finished_at`, `exit_code=1`, and error text
   - stop iterating further steps

Step transition rules for the runner:

- never jump `pending -> succeeded` directly
- always send `pending -> running` first
- always send terminal `running -> succeeded` or `running -> failed`
- do not use step-update to mark the whole execution terminal

### 5.5 Completion

Completion happens only after all required step updates are done.

Successful completion:

1. All processed steps succeeded.
2. No step ended in `failed`.
3. Executor calls `complete_execution(final_status="succeeded", finished_at=...)`.
4. Executor emits `execution_succeeded`.
5. Heartbeat worker stops.
6. Control returns to poller.

Important rule:

- even if all steps succeeded, the execution is not done until `complete` succeeds or clearly fails

### 5.6 Failure

Failure path must be deterministic and visible.

Failure can happen in three different places:

1. Before any step runs
2. While running a specific step
3. While attempting to send lifecycle updates back to Django

#### Failure Before Any Step Runs

Examples:

- malformed claim payload
- heartbeat worker cannot start
- internal executor invariant fails before step 1

Expected behavior:

1. Emit `execution_startup_failure`.
2. Call `complete_execution(final_status="failed", error_message=...)` if the claim is already known.
3. Stop the execution locally.

#### Failure During a Step

Examples:

- `FAIL_STEP` token encountered
- fake execution raises an unexpected exception

Expected behavior:

1. Mark the active step `failed`.
2. Stop processing remaining steps.
3. Call `complete_execution(final_status="failed", error_message=...)`.
4. Leave not-yet-started steps in `pending`.

#### Failure While Sending Updates

Examples:

- heartbeat `409 Conflict`
- step-update request timeout
- complete request network error

Expected behavior:

1. Emit a high-severity log event with full execution context.
2. Stop local execution work immediately if claim ownership is uncertain.
3. Do not continue to later steps after a failed mutation call whose server-side result is unknown.
4. Return control to the poller only after the execution is considered locally abandoned.

This is intentionally conservative. It avoids double-reporting or continuing work after the runner may already have lost claim ownership.

### 5.7 Heartbeat

Heartbeat runs only while an execution is active.

Recommended v1 design:

- background thread started by `Executor`
- thread uses `threading.Event` for stop control
- thread wakes every `RUNNER_HEARTBEAT_INTERVAL_SECONDS`
- thread calls Django `heartbeat(...)`
- thread logs `heartbeat_sent` or `heartbeat_failed`

Observed status rule:

- before first step starts, heartbeat can send `observed_status="claimed"`
- after first step starts successfully, heartbeat sends `observed_status="running"`

The heartbeat loop ends when:

- execution `complete` succeeds
- local execution aborts
- claim ownership appears lost
- process is shutting down

### Happy Path Sequence

1. Runner idle-polls.
2. Django returns one claimed execution.
3. Heartbeat worker starts.
4. Step 1 marked `running`.
5. Step 1 fake-executes and becomes `succeeded`.
6. Step 2 marked `running`.
7. Step 2 fake-executes and becomes `succeeded`.
8. Executor calls `complete(final_status="succeeded")`.
9. Heartbeat worker stops.
10. Poller returns to idle polling.

### Failure Path Sequence

1. Runner idle-polls.
2. Django returns one claimed execution.
3. Heartbeat worker starts.
4. Step 1 marked `running`.
5. Fake executor detects `FAIL_STEP`.
6. Step 1 marked `failed`.
7. Executor calls `complete(final_status="failed")`.
8. Heartbeat worker stops.
9. Poller returns to idle polling.

## 6. Suggested Payload Schemas / Typed Models

Use Pydantic v2 for all typed contracts in the runner.

### Schema Design Rules

- `model_config = ConfigDict(extra="forbid")` for API contracts
- use `model_validate(...)` for inbound JSON
- use `model_dump(mode="json")` for outbound payloads
- avoid custom `__init__`
- avoid `model_construct()` in normal flow
- keep request and response models separate

This aligns with current Pydantic guidance:

- models and validation methods are the normal entry point
- `extra='forbid'` is appropriate for strict API contracts
- `model_dump(mode="json")` is the right way to force JSON-compatible serialization

### Recommended `RunnerSettings`

```python
class RunnerSettings(BaseModel):
    api_base_url: str
    runner_id: str
    runner_version: str = "0.1.0"
    registration_token: str = ""
    poll_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 10
    fake_step_delay_seconds: float = 1.0
    log_level: str = "INFO"

    model_config = ConfigDict(extra="forbid", frozen=True)
```

Recommended environment variables:

- `API_BASE_URL`
- `RUNNER_ID`
- `RUNNER_VERSION`
- `RUNNER_REGISTRATION_TOKEN`
- `RUNNER_POLL_INTERVAL_SECONDS`
- `RUNNER_HEARTBEAT_INTERVAL_SECONDS`
- `RUNNER_FAKE_STEP_DELAY_SECONDS`
- `RUNNER_LOG_LEVEL`

If `RUNNER_ID` is not explicitly provided, a safe fallback is container hostname, but explicit configuration is better for logs and concurrency tests.

### Recommended Claim Models

```python
class ClaimNextRequest(BaseModel):
    runner_id: str
    runner_version: str
    requested_at: datetime

class ClaimedExecutionStep(BaseModel):
    id: UUID
    position: int
    step_key: str
    name: str
    step_type: str
    risk_level: str
    command: str = ""
    requires_approval: bool = False
    status: Literal["pending", "running", "succeeded", "failed", "skipped"]

class ClaimedExecution(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    workflow_version: int
    status: Literal["claimed", "running"]
    claimed_by_runner_id: str
    claimed_at: datetime
    last_heartbeat_at: datetime | None = None
    workflow_snapshot: dict[str, Any]
    steps: list[ClaimedExecutionStep]

class ClaimNextResponse(BaseModel):
    execution: ClaimedExecution | None
    claim_token: UUID | None = None
    poll_after_seconds: int
```

### Recommended Mutation Models

```python
class HeartbeatRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    observed_status: Literal["claimed", "running"]
    sent_at: datetime

class StepUpdateRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    status: Literal["running", "succeeded", "failed", "skipped"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str = ""

class CompleteExecutionRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    final_status: Literal["succeeded", "failed"]
    finished_at: datetime
    error_message: str = ""
```

### Recommended Local Runtime Models

Keep these local models separate from wire contracts so executor logic stays explicit.

```python
class StepRunResult(BaseModel):
    status: Literal["succeeded", "failed"]
    exit_code: int
    error_message: str = ""
    emitted_log_lines: int = 0

class ExecutionRunSummary(BaseModel):
    final_status: Literal["succeeded", "failed"]
    failed_step_id: UUID | None = None
    error_message: str = ""
```

### What Not to Do

- do not pass raw `dict[str, Any]` payloads between modules
- do not let `Executor` parse arbitrary JSON
- do not mix configuration objects and API payload objects in one ambiguous class
- do not treat Pydantic models as database entities

## 7. Logging Strategy

Use Python standard-library logging with structured JSON output to stdout.

### Why Standard Logging Is Enough Here

- The Python stdlib already provides a robust logging system.
- `LoggerAdapter` is the right built-in tool for attaching context.
- Python’s logging cookbook explicitly notes that logging from multiple threads requires no special effort, which is relevant for a heartbeat thread.
- This phase does not need an external logging library to emit useful JSON lines.

### Output Format

One JSON object per line to stdout.

Required properties:

- machine-readable
- stable event names
- no multi-line blobs for normal events
- exception stack traces only for unexpected failures

### Structured Log Fields

Minimum field set for every log line:

| Field | Purpose |
| --- | --- |
| `ts` | UTC ISO8601 timestamp |
| `level` | log level |
| `logger` | module or component name |
| `event` | stable machine-readable event name |
| `message` | short human-readable message |
| `runner_id` | stable runner identity |
| `runner_version` | deployed runner version |

Additional fields when available:

| Field | Purpose |
| --- | --- |
| `execution_id` | primary execution correlation key |
| `step_id` | specific step correlation |
| `step_key` | copied workflow step identifier |
| `position` | execution order |
| `claim_token_prefix` | first 8 chars only; avoid full-token logging by default |
| `execution_status` | runner-observed execution status |
| `step_status` | runner-observed step status |
| `poll_after_seconds` | idle-loop behavior |
| `heartbeat_interval_seconds` | heartbeat cadence |
| `http_method` | API call method |
| `url_path` | API path only, not full base URL |
| `http_status_code` | response status |
| `elapsed_ms` | latency |
| `error_class` | exception class |
| `error_message` | summarized failure |

### Correlation Identifiers

Use these in descending order of importance:

1. `execution_id`
2. `step_id`
3. `runner_id`
4. `claim_token_prefix`

Important rule:

- `execution_id` is the primary operator-facing correlation key
- do not depend on `claim_token` alone for log search
- do not emit the full `claim_token` in ordinary logs unless debugging a local-only incident

### Suggested Event Names

- `runner_started`
- `runner_poll_cycle_started`
- `runner_no_work_available`
- `execution_claim_received`
- `execution_claim_failed`
- `heartbeat_started`
- `heartbeat_sent`
- `heartbeat_failed`
- `step_starting`
- `step_started`
- `step_progress`
- `step_succeeded`
- `step_failed`
- `execution_succeeded`
- `execution_failed`
- `execution_terminal_update_failed`
- `execution_claim_lost`

### HTTPX Logging Hooks

Use HTTPX event hooks for lightweight metadata only.

Safe uses:

- add per-request timestamp
- emit request path and method
- emit response status and latency

Unsafe uses for v1:

- logging full request bodies
- logging full response bodies
- logging workflow snapshots verbatim
- logging tokens or auth secrets

## 8. Failure Strategy

The runner must have an intentionally testable red path.

### `FAIL_STEP` Token Behavior

Define one deterministic rule:

- if `FAIL_STEP` appears anywhere in `ClaimedExecutionStep.command`, case-sensitive, that step fails intentionally

Recommended behavior when token is found:

1. log `step_intentional_failure_triggered`
2. sleep the normal fake-step delay so timing still resembles a real run
3. return `StepRunResult(status="failed", exit_code=1, error_message="Intentional failure triggered by FAIL_STEP token.")`
4. post the failed step update
5. mark the execution failed through `complete`

Why command-only matching is better than broad matching:

- it is explicit
- it avoids surprises from step names or descriptions
- test fixtures remain easy to read

### Partial Failures

Partial failure in v1 means:

- steps before the failed step may already be `succeeded`
- the active failed step becomes `failed`
- steps after the failed step remain `pending`
- the overall execution becomes `failed`

Do not:

- auto-mark remaining steps `skipped`
- auto-run cleanup steps not defined in the execution payload
- continue after a failed step in v1

### Terminal Execution Updates

The runner must always attempt exactly one terminal execution update after the final outcome is known.

Rules:

- success path: call `complete(final_status="succeeded")` once
- failure path: call `complete(final_status="failed")` once
- do not call `complete` after every step
- do not treat step failure as implicit execution completion

If the terminal update fails:

1. emit `execution_terminal_update_failed` at `ERROR` or `CRITICAL`
2. stop processing any further local work
3. do not retry blindly in a hot loop
4. return control so the process can continue polling later, but with a visible operator signal in logs

### Handling Unknown Write Outcomes

Any POST to Django can fail in a way that leaves write outcome uncertain.

Examples:

- request body sent, server processed it, response lost
- timeout occurs after Django committed the change
- network resets after write but before response is read

V1 rule:

- do not automatically retry mutating POSTs at the HTTP client layer

This is an implementation inference from HTTPX docs plus the non-idempotent nature of the runner APIs. It is safer to surface the ambiguous failure than to duplicate a transition.

### Failure Severity Classification

| Failure | Severity | Expected behavior |
| --- | --- | --- |
| `claim-next` returns no work | normal | sleep and continue |
| `claim-next` network error | warning | log and back off |
| malformed claim payload | error | fail current cycle; do not execute |
| heartbeat `409`/ownership mismatch | critical | abort execution locally |
| step-update failure | critical | abort execution locally |
| `complete` failure | critical | emit terminal-update failure log |
| `FAIL_STEP` | info/warning | expected red-path verification |

## 9. Heartbeat and Abandonment Considerations

Heartbeat exists to prove liveness, not to decide persistence policy inside the runner.

### Recommended Timing

Suggested defaults:

- heartbeat interval: `10` seconds
- poll interval: `5` seconds
- Django stale-execution threshold: `>= 30` seconds, preferably `45` seconds in v1

Reasoning:

- heartbeat should be more frequent than stale detection
- stale detection should allow at least three missed beats before action
- the values are easy to reason about in local Docker verification

### Ownership Rules

Heartbeat must only be sent when all are true:

- execution is currently claimed by this runner
- claim token is present
- execution is still locally active

If Django rejects heartbeat because:

- execution is terminal
- runner ID mismatches
- claim token mismatches

then the runner should treat claim ownership as lost and stop local execution.

### Stuck Execution Detection

Stuck detection should be a Django concern, not a runner concern.

Runner responsibilities:

- send heartbeats regularly
- stop heartbeats when the execution ends
- log failures clearly

Django responsibilities in later work:

- detect executions with stale `last_heartbeat_at`
- decide whether to mark them failed, requeue them, or require operator action

Do not implement in Phase 05:

- claim stealing
- automatic requeue from the runner
- database-side lease sweeper inside the runner container

### Local Shutdown Behavior

If the runner process receives shutdown while executing:

1. stop polling
2. stop accepting new work
3. stop heartbeat thread cleanly if possible
4. do not invent a local “cancelled” transition unless Django exposes that workflow

In v1, clean shutdown matters, but full interruption recovery is out of scope.

## 10. File-by-File Implementation Plan

### `/home/dylan/code/runbook-platform/apps/runner/runner/schemas.py`

Add all typed config, request, response, and runtime models.

Implementation notes:

- use `ConfigDict(extra="forbid")`
- use enums or `Literal` for narrow status values
- keep timestamps timezone-aware
- keep `workflow_snapshot` and unknown future step fields permissive only where necessary

### `/home/dylan/code/runbook-platform/apps/runner/runner/client.py`

Replace placeholder with a real `RunnerApiClient`.

Implementation notes:

- accept injected `httpx.Client`
- centralize URL paths
- serialize requests with `model_dump(mode="json")`
- parse responses with `model_validate(...)`
- wrap HTTPX exceptions into a small runner-local error type if helpful
- optionally send `Authorization` or `X-Runner-Token` once Django internal auth is defined; until then, keep the code ready but local-dev tolerant

### `/home/dylan/code/runbook-platform/apps/runner/runner/log_streamer.py`

Replace placeholder with structured logger helpers.

Implementation notes:

- expose methods for common execution events
- use `LoggerAdapter` or equivalent context merging
- ensure step logs include execution and step context
- keep payload sizes small

### `/home/dylan/code/runbook-platform/apps/runner/runner/executor.py`

Replace placeholder with sequential orchestrator.

Implementation notes:

- own heartbeat start/stop
- own fake step execution
- own `FAIL_STEP` detection
- own terminal completion call
- stop on first failure
- return an `ExecutionRunSummary`

### `/home/dylan/code/runbook-platform/apps/runner/runner/poller.py`

Create new module.

Implementation notes:

- outer infinite loop belongs here, not in `main.py`
- call `claim_next()`
- respect `poll_after_seconds`
- apply bounded sleep after client/network errors
- hand off to executor and wait for completion before next claim

### `/home/dylan/code/runbook-platform/apps/runner/runner/main.py`

Replace print-loop bootstrap with thin wiring only.

Implementation notes:

- no inline while loop except calling the poller
- no `print`
- no step execution logic
- no direct payload dicts

### `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_schemas.py`

Add schema validation tests.

Coverage:

- valid claim response
- forbidden extra fields
- missing required fields
- JSON serialization behavior for outbound requests

### `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_client.py`

Add client contract tests using `httpx.MockTransport`.

Coverage:

- correct URL paths
- correct methods and payloads
- response parsing
- HTTP error handling
- timeout/request error wrapping behavior

### `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_executor.py`

Add executor unit tests.

Coverage:

- all-success path
- `FAIL_STEP` path
- terminal update invoked exactly once
- remaining steps stop after first failure

### `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_poller.py`

Add poller behavior tests.

Coverage:

- no-work loop sleeps correctly
- claim handed to executor
- claim client error triggers backoff

### `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_orchestration.py`

Add lightweight orchestration tests with fake client and fake logger helpers.

Coverage:

- end-to-end happy path sequencing
- failure sequencing
- heartbeat start/stop sequencing

## 11. Step-by-Step Implementation Checklist With Small Safe Batches

### Batch 1: Typed Contracts First

Files:

- `runner/schemas.py`
- `runner/tests/test_schemas.py`

Goal:

- lock payload shapes before client and executor logic

Verification:

- schema tests pass

### Batch 2: Real HTTP Client

Files:

- `runner/client.py`
- `runner/tests/test_client.py`

Goal:

- isolate all Django HTTP traffic behind one tested client

Verification:

- contract tests pass with `httpx.MockTransport`

### Batch 3: Structured Logging Helpers

Files:

- `runner/log_streamer.py`

Goal:

- remove `print` usage and stabilize event names before orchestration work

Verification:

- local smoke run emits JSON log lines

### Batch 4: Fake Step Executor Core

Files:

- `runner/executor.py`
- `runner/tests/test_executor.py`

Goal:

- implement sequential fake step execution and `FAIL_STEP`

Verification:

- success and failure unit tests pass

### Batch 5: Poller Claim Loop

Files:

- `runner/poller.py`
- `runner/tests/test_poller.py`

Goal:

- implement no-jobs behavior and claim handoff

Verification:

- poller tests pass

### Batch 6: Thin Bootstrap Wiring

Files:

- `runner/main.py`

Goal:

- remove business logic from entrypoint and wire real components together

Verification:

- runner starts cleanly in Docker and stays alive in idle mode

### Batch 7: Heartbeat Integration

Files:

- `runner/executor.py`
- `runner/tests/test_orchestration.py`

Goal:

- add heartbeat start/stop and claim-loss handling

Verification:

- orchestration tests cover heartbeat lifecycle

### Batch 8: Full Local Verification

Files:

- no new code required beyond prior batches

Goal:

- validate no-work, success, failure, and heartbeat cases against real Docker services

Verification:

- commands in Section 13 complete successfully

## 12. Commands to Run Locally in Docker

Run all commands from:

```bash
cd /home/dylan/code/runbook-platform
```

### Baseline Startup

```bash
cp .env.example .env
docker compose up --build -d postgres api
docker compose exec api python manage.py check
```

### Runner Dependency Sanity

```bash
docker compose run --rm runner python -c "import httpx, pydantic; print(httpx.__version__, pydantic.__version__)"
```

### Start a Single Foreground Runner for Verification

Prefer a one-off runner container during manual verification so you do not accidentally run two workers locally.

```bash
docker compose run --rm runner python -m runner.main
```

### Tail Runner Logs

If you start the runner as a service instead:

```bash
docker compose up --build -d runner
docker compose logs -f runner
```

### Manual Internal Endpoint Smoke Commands

Claim next:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/claim-next/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","runner_version":"0.1.0","requested_at":"2026-03-31T15:00:00Z"}'
```

Heartbeat:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/<execution_id>/heartbeat/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","claim_token":"<claim_token>","observed_status":"claimed","sent_at":"2026-03-31T15:00:10Z"}'
```

Step update:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/<execution_id>/steps/<step_id>/update/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","claim_token":"<claim_token>","status":"running","started_at":"2026-03-31T15:00:12Z"}'
```

Complete execution:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/<execution_id>/complete/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","claim_token":"<claim_token>","final_status":"succeeded","finished_at":"2026-03-31T15:00:25Z","error_message":""}'
```

### Runner Test Commands

If runner tests are implemented with stdlib `unittest`:

```bash
docker compose run --rm runner python -m unittest discover -s runner/tests -v
```

If the team later adds `pytest` to runner dev dependencies:

```bash
docker compose run --rm runner pytest -q
```

## 13. Verification Plan

### 13.1 No Jobs Case

Setup:

- ensure Django has no queued executions

Run:

```bash
docker compose run --rm runner python -m runner.main
```

Expected behavior:

- runner starts successfully
- repeated `claim-next` calls return `execution: null`
- logs show `runner_no_work_available`
- runner sleeps between polls
- no heartbeat logs
- no step-update logs
- no errors

Verification focus:

- idle state is normal, not noisy
- poll cadence follows `poll_after_seconds` or fallback interval

### 13.2 Successful Job Case

Seed one queued execution whose step commands do not include `FAIL_STEP`.

Preferred seed path once earlier phases exist:

- create via public Django API

Fallback seed path for local development:

- create one organization, workflow, execution, and two execution steps through Django shell or fixture loading

Run:

```bash
docker compose run --rm runner python -m runner.main
```

Expected lifecycle:

- execution claimed
- heartbeat starts
- step 1 `pending -> running -> succeeded`
- step 2 `pending -> running -> succeeded`
- execution `claimed -> running -> succeeded`
- complete endpoint called once
- heartbeat stops
- runner returns to idle polling

What to verify first:

- exact ordering of step updates
- execution does not remain stuck in `running`
- only one completion call is sent

### 13.3 Failing Job Case

Seed one queued execution with at least one step command containing `FAIL_STEP`.

Run:

```bash
docker compose run --rm runner python -m runner.main
```

Expected lifecycle:

- execution claimed
- failing step marked `running`, then `failed`
- execution marked `failed`
- subsequent pending steps remain `pending`
- logs contain `step_intentional_failure_triggered`
- runner returns to idle polling after the failed execution closes

What to verify first:

- failed step sends terminal update before execution completion
- no later steps run after the failure
- execution final status is `failed`, not left `running`

### 13.4 Heartbeat Checks

For heartbeat verification, set fake step delay longer than the heartbeat interval.

Example target settings:

- `RUNNER_FAKE_STEP_DELAY_SECONDS=25`
- `RUNNER_HEARTBEAT_INTERVAL_SECONDS=10`

Run:

```bash
docker compose run --rm -e RUNNER_FAKE_STEP_DELAY_SECONDS=25 -e RUNNER_HEARTBEAT_INTERVAL_SECONDS=10 runner python -m runner.main
```

Expected behavior:

- heartbeat sent while the fake step is still active
- `last_heartbeat_at` advances at least twice during the long-running step
- no stale-execution logic fires during the active run

Verification sources:

- runner structured logs
- Django execution detail API
- Django shell inspection if needed for local debugging

## 14. Test Plan

### Unit Tests

Target modules:

- `test_schemas.py`
- `test_executor.py`
- `test_poller.py`

Required cases:

- schema validation success and failure
- fake success path
- `FAIL_STEP` path
- executor stops after first failure
- poller handles no-work response
- poller backs off after client error

### Client Contract Tests

Use HTTPX transport-based tests.

Recommended approach:

- `httpx.MockTransport` for deterministic request/response testing

Required cases:

- `claim_next()` sends the correct endpoint and body
- `heartbeat()` sends runner identity, token, and observed status
- `update_step()` sends the correct terminal fields
- `complete_execution()` serializes final status correctly
- non-2xx responses become runner-visible exceptions
- malformed JSON becomes schema validation failure, not silent dict usage

### Orchestration Tests

Use fake client objects and a fake sleeper or controllable clock where practical.

Required cases:

- happy path sequencing
- failure sequencing
- heartbeat start and stop behavior
- terminal update invoked exactly once
- remaining steps untouched after failure

### Tests Explicitly Not Required in Phase 05

- real subprocess execution tests
- sandbox integration tests
- artifact upload tests
- multi-runner concurrency tests in the runner codebase itself

Concurrency safety for claiming belongs primarily to Django tests from Phase 04.

## 15. Best Practices / Anti-Patterns

### Best Practices

- keep `main.py` as bootstrap only
- inject one reusable `httpx.Client`
- use strict typed contracts for every API payload
- log structured events to stdout
- treat Django as the only state authority
- make failure deterministic and easy to verify with `FAIL_STEP`
- keep v1 execution single-threaded except for the heartbeat helper thread
- keep every state transition explicit and narrow

### Anti-Patterns

- letting the runner import or query Django ORM models
- opening a direct database connection from the runner
- retrying mutating POSTs automatically and blindly
- mixing claim-loop logic into `main.py`
- letting `Executor` build raw JSON dicts itself
- marking execution terminal from a step-update helper
- using `print` instead of structured logging
- introducing asyncio, Celery, Redis, Kafka, or websockets for this phase
- implementing real shell execution before the fake orchestration path is stable
- coupling logs to a database persistence design that does not exist yet

## 16. Codex Execution Batching Plan

This section is intentionally written so Codex can implement the phase in controlled slices later.

### Batch A

Implement:

- `runner/schemas.py`
- `runner/tests/test_schemas.py`

Gate:

- typed contracts compile and validate

### Batch B

Implement:

- `runner/client.py`
- `runner/tests/test_client.py`

Gate:

- all runner-to-Django HTTP calls go through one client

### Batch C

Implement:

- `runner/log_streamer.py`
- minimal logging bootstrap in `runner/main.py`

Gate:

- no more `print`-based operational output

### Batch D

Implement:

- `runner/executor.py`
- `runner/tests/test_executor.py`

Gate:

- success and `FAIL_STEP` paths are deterministic

### Batch E

Implement:

- `runner/poller.py`
- `runner/tests/test_poller.py`

Gate:

- no-jobs loop works cleanly

### Batch F

Integrate:

- real wiring in `runner/main.py`
- orchestration tests

Gate:

- local Docker smoke run succeeds without touching the database directly

### Batch G

Verify:

- no jobs
- success
- failure
- heartbeat

Gate:

- all Section 13 scenarios pass before any real execution backend is attempted

## 17. Definition of Done

Phase 05 is done when all of the following are true:

- runner polls Django internal endpoints continuously
- runner never talks directly to PostgreSQL
- runner never imports Django ORM models
- `main.py` is only bootstrap and dependency wiring
- `client.py` owns all Django HTTP communication
- `poller.py` owns the claim loop and idle behavior
- `executor.py` owns sequential step orchestration
- `schemas.py` owns typed request/response models
- `log_streamer.py` emits structured logs
- no-jobs case is quiet and stable
- success case reaches execution `succeeded`
- failure case reaches execution `failed` through `FAIL_STEP`
- heartbeat is sent while an execution is active
- remaining steps do not run after the first failure
- terminal execution update is attempted exactly once per execution
- runner uses Django internal endpoints only
- local verification and test plan pass

### Final Implementation Principle

This phase should feel production-shaped in boundaries and observability, but still intentionally small in mechanics:

- polling instead of queue infrastructure
- fake execution instead of real shell execution
- one active execution per runner process
- clear contracts instead of clever abstractions
