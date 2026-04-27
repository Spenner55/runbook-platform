# Runner Service

Python worker that polls Django internal APIs and reports execution progress.

## Current Scope

- Loads runtime settings from environment.
- Polls `POST /api/v1/internal/executions/claim-next/`.
- Sends heartbeats while an execution is active.
- Updates step status through Django internal APIs.
- Completes executions as `succeeded` or `failed`.
- Simulates step execution; `FAIL_STEP` in a command triggers a deliberate failure path.

## Boundary Rules

- The runner calls only Django internal APIs.
- The runner never connects to PostgreSQL.
- The runner never calls the FastAPI AI service.
- The runner does not own workflow creation, policy decisions, approvals, or persistence.

## Important Files

- `runner/main.py` wires settings, client, executor, and poller.
- `runner/client.py` is the HTTP client for Django internal APIs.
- `runner/poller.py` owns the claim loop.
- `runner/executor.py` owns step execution simulation and heartbeat lifecycle.
- `runner/schemas.py` contains Pydantic request/response schemas.

## Commands

From the repo root:

```sh
make test-runner
make logs-runner
make runner-shell
```

See `docs/architecture/runner.md` for the full lifecycle.
