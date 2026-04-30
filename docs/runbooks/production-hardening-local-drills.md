# Production Hardening Local Drills

These drills validate Phase 10.9 behavior in local Docker Compose without adding
new features or deploying infrastructure. Run them from the repository root.

## Prerequisites

Start the local stack and apply migrations:

```sh
make up-d
make migrate
```

Use `make ps` to confirm `api`, `ai`, `runner`, `web`, and `postgres` are
running before beginning.

## Drill 1: Runner SIGTERM During Execution

Purpose: confirm the runner receives `SIGTERM`, stops polling for new work, lets
current work drain, and relies on the watchdog if hard shutdown leaves an
execution stale.

1. Start a workflow execution from the UI or API.
2. Wait until the runner has claimed work:

```sh
docker compose logs --tail=100 runner
```

3. Send `SIGTERM` to the runner container:

```sh
docker compose kill --signal=SIGTERM runner
```

4. Inspect runner logs:

```sh
docker compose logs --tail=100 runner
```

Expected:

- Logs include `SIGTERM received`.
- Polling exits cleanly if no step is active.
- If a step cannot finish before the hard timeout, the container exits and the
  Django watchdog can recover the stale execution.

Restart the runner when finished:

```sh
docker compose up -d runner
```

## Drill 2: Stale Heartbeat Recovery

Purpose: confirm the Django watchdog recovers executions stuck in `claimed` or
`running` after heartbeat timeout.

1. Stop the runner after it has claimed an execution, or create a local stuck
   execution in a development database.
2. Run the watchdog with a short threshold for the drill:

```sh
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 1
```

3. Run it again to verify idempotence:

```sh
docker compose exec api python manage.py check_stuck_executions --threshold-seconds 1
```

Expected:

- First run prints `Recovered N stuck execution(s)` when stale rows exist.
- Recovered executions move to `failed`.
- Running steps on those executions move to `failed`.
- A second run prints `No stuck executions found`.

See [stuck-execution-recovery.md](stuck-execution-recovery.md) for the full
recovery procedure.

## Drill 3: Broken AI Health Dependency

Purpose: confirm Django `/health/` reports unhealthy when the AI service is
unreachable. This endpoint currently checks both database and AI service health.

1. Stop the AI service:

```sh
docker compose stop ai
```

2. Check Django health from inside the API container:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

Expected:

- HTTP status is `503`.
- Response JSON has `"healthy": false`.
- `checks.ai` contains the AI connection failure.

Restore AI:

```sh
docker compose up -d ai
```

Then verify health returns `200` after AI is ready:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

## Drill 4: Missing Production Env Var

Purpose: confirm production settings fail closed when required secrets or
production settings are absent.

Run a production settings check with a required variable removed:

```sh
docker compose exec \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e DJANGO_SECRET_KEY= \
  api python manage.py check --deploy --settings=config.settings.prod
```

Expected:

- Command fails.
- Error includes `Required environment variable 'DJANGO_SECRET_KEY' is not set`
  or equivalent `ImproperlyConfigured` output.

Then run the supported local production check:

```sh
make check-prod
```

Expected:

- Command passes using local-only placeholder values supplied by the Makefile.

## Drill 5: Request ID Trace Across Runner and Django

Purpose: confirm runner internal API calls send `X-Request-ID` and Django echoes
request IDs on responses.

1. Confirm Django generates a request ID when one is absent:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/", timeout=5)
print(response.headers.get("x-request-id"))
PY
```

Expected: output is a UUID.

2. Confirm Django preserves an incoming request ID:

```sh
docker compose exec api python - <<'PY'
import httpx
request_id = "local-drill-request-id"
response = httpx.get(
    "http://localhost:8000/health/",
    headers={"X-Request-ID": request_id},
    timeout=5,
)
print(response.headers.get("x-request-id"))
PY
```

Expected: output is `local-drill-request-id`.

3. Confirm the runner client has request ID coverage:

```sh
docker compose exec runner pytest runner/tests/test_client.py
```

Expected:

- Client tests pass.
- Runner requests include a fresh `X-Request-ID` and `X-Runner-ID` header.

See [structured-logging-and-request-ids.md](structured-logging-and-request-ids.md)
for operational tracing guidance.

## Drill 6: Metrics Endpoint Smoke Check

Purpose: confirm API and AI metrics endpoints expose Prometheus text.

Check Django metrics:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/metrics/", timeout=5)
print(response.status_code)
print(response.text[:300])
PY
```

Expected:

- HTTP status is `200`.
- Response contains Prometheus text such as `python_info`, `django_`, or
  `runbook_` metrics.

Check AI metrics:

```sh
docker compose exec ai python - <<'PY'
import httpx
response = httpx.get("http://localhost:8001/metrics/", timeout=5)
print(response.status_code)
print(response.text[:300])
PY
```

Expected:

- HTTP status is `200`.
- Response contains Prometheus text.

## Final Local Verification

Run the Phase 10.9 Step 9 verification commands:

```sh
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec runner pytest
cd apps/web && npm run build
cd apps/web && npm run lint
```

Also run the hardening gates before Phase 10.10:

```sh
make hardening-check
```
