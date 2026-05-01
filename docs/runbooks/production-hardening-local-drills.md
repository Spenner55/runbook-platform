# Production Hardening Local Drills

These drills validate Phase 10.9 behavior in local Docker Compose without adding
new features or deploying infrastructure. Run them from the repository root.

## Prerequisites

Start the local stack and apply migrations:

```sh
make up-d
make migrate
```

Use `make ps` to confirm `api`, `ai`, `runner`, `web`, `postgres`, and
`pgbouncer` are running before beginning.

## Drill 0: Compose Runtime Contract And PgBouncer

Purpose: confirm the local runtime matches the Phase 10.10 handoff contract:
API readiness is DB/migration-only, Django connects through PgBouncer, and
container health uses the split health endpoints.

1. Validate the rendered Compose configuration:

```sh
docker compose config
```

Expected:

- `api.environment.DATABASE_URL` points to `pgbouncer:5432` unless you have set
  an explicit troubleshooting override.
- `api.healthcheck` calls `/health/ready/`.
- `ai.healthcheck` calls `/health`.
- `runner.stop_signal` is `SIGTERM`.
- `runner.stop_grace_period` is `1m30s`.

2. Confirm service health:

```sh
docker compose ps
```

Expected:

- `postgres`, `pgbouncer`, `api`, and `ai` report healthy.

3. Confirm Django can run checks and migrations through PgBouncer:

```sh
docker compose exec api python manage.py check
docker compose exec api python manage.py migrate --check
```

Expected: both commands pass.

4. Inspect PgBouncer pool configuration:

```sh
docker compose exec pgbouncer sh -c 'PGPASSWORD="$POSTGRESQL_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$POSTGRESQL_USERNAME" -d pgbouncer -c "SHOW DATABASES;"'
```

Expected:

- Output includes the application database.
- `pool_size` for the application database matches `PGBOUNCER_POOL_SIZE`.
- During active load, `SHOW POOLS;` can be used to verify server connection
  counts stay within `PGBOUNCER_POOL_SIZE`.

5. Confirm the ALB-facing readiness endpoint ignores AI dependency health:

```sh
docker compose stop ai
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/ready/", timeout=5)
print(response.status_code)
print(response.text)
PY
docker compose up -d ai
```

Expected:

- `/health/ready/` returns `200` while AI is stopped.
- `/health/` may return `503` while AI is stopped because it is the operator
  dependency-health endpoint, not the ALB readiness endpoint.

## Drill 1: Runner SIGTERM During Execution

Purpose: confirm the runner receives `SIGTERM`, stops polling for new work, lets
current work drain, and relies on the watchdog if hard shutdown leaves an
execution stale.

Incident procedure: [runner-crash-recovery.md](runner-crash-recovery.md).

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
- Compose grants the runner up to 90 seconds to drain after `SIGTERM`.
- If a step cannot finish before the hard timeout, the container exits and the
  Django watchdog can recover the stale execution.

Restart the runner when finished:

```sh
docker compose up -d runner
```

## Drill 2: Stale Heartbeat Recovery

Purpose: confirm the Django watchdog recovers executions stuck in `claimed` or
`running` after heartbeat timeout and sweeps expired pending approvals.

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
- First run prints `Recovered N expired approval(s)` when expired pending
  approvals exist.
- Recovered executions move to `failed`.
- Running steps on those executions move to `failed`.
- Waiting approval steps and blocked executions move to failed when an approval
  times out.
- A second run prints `No stuck executions found` and
  `No expired approvals found`.

See [stuck-execution-recovery.md](stuck-execution-recovery.md) for the full
recovery procedure.

## Drill 3: Broken AI Health Dependency

Purpose: confirm Django `/health/` reports unhealthy when the AI service is
unreachable. This endpoint currently checks both database and AI service health.

Incident procedure: [ai-service-outage.md](ai-service-outage.md).

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

Confirm the production bearer-token guard with the focused Django tests:

```sh
docker compose exec api pytest apps/common/tests/test_metrics.py
```

Expected:

- Metrics remain readable in local disabled mode.
- Missing and wrong bearer tokens return `403` when
  `PROMETHEUS_METRICS_ENABLED=true`.
- The configured bearer token returns `200`.

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

## Drill 7: Database Or PgBouncer Outage

Purpose: confirm API readiness fails closed when database access is unavailable.

Incident procedure: [database-outage.md](database-outage.md).

1. Stop PgBouncer:

```sh
docker compose stop pgbouncer
```

2. Check readiness:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/ready/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

Expected:

- `/health/ready/` returns `503`.
- The response indicates the database check failed.

3. Restore PgBouncer and confirm readiness recovers:

```sh
docker compose up -d pgbouncer
docker compose exec api python manage.py migrate --check
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/ready/", timeout=5)
print(response.status_code)
print(response.text)
PY
```

Expected:

- `migrate --check` passes.
- `/health/ready/` returns `200`.

## Drill 8: Integration Delivery Failure

Purpose: confirm a failed external notification is recorded without failing the
core execution state transition.

Incident procedure:
[integration-delivery-failure.md](integration-delivery-failure.md).

1. Configure a local generic webhook or Slack webhook integration with a
   destination that returns an error or is unreachable.
2. Trigger an event covered by the integration connection.
3. Inspect recent delivery attempts:

```sh
docker compose exec api python manage.py shell -c '
from apps.integrations.models import IntegrationDeliveryAttempt
for attempt in IntegrationDeliveryAttempt.objects.order_by("-attempted_at")[:5]:
    print(attempt.attempted_at, attempt.integration_id, attempt.event_type, attempt.success, attempt.http_status, attempt.error_detail[:200])
'
```

Expected:

- A failed delivery attempt is recorded with redacted error detail.
- The triggering execution or approval state transition still completes.

## Drill 9: k6 Load Test

Purpose: confirm the Phase 10.9 local performance gate can run against seeded
data and authenticated API reads.

Run with a valid local user and organization ID:

```sh
RUNBOOK_API_BASE_URL=http://localhost:8000 \
RUNBOOK_LOAD_TEST_EMAIL=<email> \
RUNBOOK_LOAD_TEST_PASSWORD=<password> \
RUNBOOK_ORG_ID=<organization-id> \
k6 run --vus 50 --duration 60s scripts/load-test.js
```

If you expose PgBouncer pool stats through a local authenticated HTTP probe,
the same k6 script can enforce the pool cap during the run:

```sh
RUNBOOK_PGBOUNCER_STATS_URL=http://localhost:<port>/pgbouncer/pools \
RUNBOOK_PGBOUNCER_STATS_TOKEN=<token> \
RUNBOOK_PGBOUNCER_POOL_SIZE=20 \
k6 run --vus 50 --duration 60s scripts/load-test.js
```

Expected:

- `http_req_duration` p(99) is below 200ms.
- `http_req_failed` is below 0.1%.
- `runbook_http_5xx_rate` is zero.
- `runbook_pgbouncer_pool_utilization` stays at or below `1.0` when
  `RUNBOOK_PGBOUNCER_STATS_URL` is configured.
- PgBouncer pool counts remain within `PGBOUNCER_POOL_SIZE` during the run.

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
