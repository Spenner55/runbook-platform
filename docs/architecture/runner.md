# Runner

## Purpose

The runner is a Python worker that executes claimed workflow steps on behalf of Django. In the current repo it simulates step work and uses the `FAIL_STEP` command marker to exercise failure behavior.

The runner is not a control plane. It reports work progress to Django; Django owns persistence and state transitions.

## Lifecycle

1. `runner.main` reads environment settings.
2. It creates `ApiClient`, `Executor`, and `Poller`.
3. `Poller.run_forever()` repeatedly asks Django for queued work.
4. Claimed executions are passed to `Executor.run()`.
5. The executor sends heartbeats, step updates, and final completion through `ApiClient`.

## Polling Model

The runner calls:

`POST /api/v1/internal/executions/claim-next/`

If no work is available, Django returns `execution: null` and `poll_after_seconds`. The runner sleeps and retries.

The runner processes one claimed execution at a time in the current implementation.

## Claim-Next Flow

Runner sends `runner_id`, `runner_version`, and `requested_at`.

Django:

- Selects the oldest queued execution with `select_for_update(skip_locked=True)`.
- Sets status to `claimed`.
- Stores `claimed_by_runner_id`, `claim_token`, `claimed_at`, and `last_heartbeat_at`.
- Returns execution metadata, materialized steps, and the claim token.

## Heartbeat Flow

The executor starts a background heartbeat thread for each claimed execution.

The thread calls:

`POST /api/v1/internal/executions/{execution_id}/heartbeat/`

Django validates `runner_id` and `claim_token`, then updates `last_heartbeat_at`.

Heartbeat failures are logged by the runner but do not immediately stop execution.

## Step Update Flow

For each step in `position` order, the runner calls:

`POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`

Current service-level transitions:

- `pending -> running`
- `running -> succeeded`
- `running -> failed`

The first `running` step moves the parent execution from `claimed` to `running`.

## Completion And Failure Flow

After all steps succeed, the runner calls complete with `final_status: succeeded`.

If a step fails or an unexpected executor exception occurs, the runner calls complete with `final_status: failed`.

Current simulated behavior:

- If `FAIL_STEP` appears in a step command, that step fails.
- Otherwise the runner sleeps briefly and marks the step succeeded.

## Logging Expectations

Current runner logging uses standard Python logging and `LogStreamer` helpers. Logs should include runner identity, execution IDs, and step IDs where relevant.

Future structured logging belongs in an approved hardening phase.

## What The Runner Must Never Do

- Connect to PostgreSQL.
- Call FastAPI AI.
- Call frontend/public APIs to mutate execution state.
- Invent workflow definitions.
- Persist execution history directly.
- Decide approval or policy outcomes outside Django.
- Add queue/event infrastructure without an approved phase.

## How To Test Runner Changes

Use focused unit tests with fake HTTP clients or fake runner clients where possible.

Common commands:

```sh
make test-runner
docker compose exec runner pytest
```

For contract changes:

- Update `runner/schemas.py`.
- Update Django internal serializers/views/services.
- Update `docs/architecture/api-contracts.md`.
- Add or update API and runner tests.

## Future Expansion Points

Planned or deferred:

- Real command sandboxing.
- Artifact upload.
- Approval-aware step start contracts.
- Runner token authentication.
- Structured logs and request correlation.
- Stuck execution recovery.
- Parallel/concurrent runner capacity.

These require explicit phase approval and must preserve the Django-control-plane boundary.
