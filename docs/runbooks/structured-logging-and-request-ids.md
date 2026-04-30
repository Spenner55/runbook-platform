# Structured Logging And Request IDs

Phase 10.9 adds request ID propagation and structured logging foundations for
local operation and future CloudWatch correlation.

## Request ID Contract

- Django accepts `X-Request-ID` on every request.
- If absent, Django generates a UUID.
- Django stores it on `request.request_id`.
- Django returns it as the `X-Request-ID` response header.
- The runner sends a fresh `X-Request-ID` on every internal API request.
- The runner also sends `X-Runner-ID` on every internal API request.

Request IDs are per HTTP request, not per execution. A single execution can have
many request IDs across claim, heartbeat, step update, artifact upload, approval
polling, and completion calls.

## Local Header Checks

Generated request ID:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/", timeout=5)
print(response.headers.get("x-request-id"))
PY
```

Preserved request ID:

```sh
docker compose exec api python - <<'PY'
import httpx
request_id = "trace-drill-001"
response = httpx.get(
    "http://localhost:8000/health/",
    headers={"X-Request-ID": request_id},
    timeout=5,
)
print(response.headers.get("x-request-id"))
PY
```

Expected output for the second command is `trace-drill-001`.

## Runner To Django Trace Drill

Run the runner client tests:

```sh
docker compose exec runner pytest runner/tests/test_client.py
```

Then run an execution and inspect logs:

```sh
docker compose logs --tail=200 runner
docker compose logs --tail=200 api
```

Use the execution ID and runner ID to connect runner-side events with Django
state transitions. Use `X-Request-ID` when available in HTTP logs or future log
aggregation.

## Current Logging Behavior

Django configures `structlog` processors in `apps/api/config/settings/base.py`.
`RequestIDMiddleware` currently guarantees request ID headers, but it does not
bind request IDs into every application log line by itself.

Runner logging includes runner identity through the runner logging setup and
sends request IDs as HTTP headers.

AI metrics are exposed through FastAPI instrumentation. The AI health endpoint
currently returns static service status.

## Production Guidance For Phase 10.10

Before deploying to AWS:

- confirm CloudWatch log format preserves structured fields;
- confirm ALB or reverse proxy logs include `X-Request-ID`;
- confirm runner logs include enough execution and runner identity to correlate
  with Django audit events;
- decide whether to bind `request_id` into Django log context for every request;
- document the CloudWatch Logs Insights queries used during incidents.

## Useful Smoke Commands

API health with headers:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/health/", timeout=5)
print(response.status_code)
print(response.headers)
print(response.text)
PY
```

API metrics:

```sh
docker compose exec api python - <<'PY'
import httpx
response = httpx.get("http://localhost:8000/metrics/", timeout=5)
print(response.status_code)
print(response.text[:500])
PY
```

AI metrics:

```sh
docker compose exec ai python - <<'PY'
import httpx
response = httpx.get("http://localhost:8001/metrics/", timeout=5)
print(response.status_code)
print(response.text[:500])
PY
```
