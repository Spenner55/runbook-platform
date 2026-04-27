# Phase 10.9: Production Hardening Blueprint

| Field | Value |
|---|---|
| Phase number | 10.9 |
| Phase name | Production Hardening |
| Objective | Make the platform safe, reliable, and observable before AWS deployment — without introducing new features, queue infrastructure, or microservice boundaries. |
| Status | Blueprint only |
| Depends on | Phases 01–09 complete and verified; Phase 10.1–10.8 complete and verified |
| Authored | 2026-04-24 |

---

## 1. Purpose and sequencing rationale

### What the system has after phases 10.1–10.8

After eight expansion phases, the platform has:

- A working approval gate system with `waiting_for_approval` step state
- Policy evaluation that can override workflow-level approval flags
- An immutable audit trail written synchronously within database transactions
- Artifact storage through `django-storages` with per-step upload endpoints
- External integrations (Slack, PagerDuty, generic webhook) dispatched fire-and-forget
- Real LLM-backed parsing with a mandatory human review gate
- JWT authentication and org-scoped authorization across every endpoint
- Server-Sent Events replacing the polling loop on the execution detail page
- A uvicorn ASGI server replacing `manage.py runserver`

What the system does not yet have is any guarantee that it will survive real-world operation:

- `prod.py` is two lines: `from .base import *` and `DEBUG = False`. No security headers, no HSTS, no CSP, no connection pool settings.
- The runner handles `KeyboardInterrupt` but has no `SIGTERM` handler. A container restart mid-execution leaves a step stuck in `running` with no recovery path.
- Logging is standard Python `logging` with `print()`-style output. There are no structured fields, no request IDs, and no correlation across service boundaries.
- The Django health endpoint at `/health/` returns `{"status": "ok", "service": "api"}` unconditionally — it does not test the database connection or AI service reachability.
- There is no Django watchdog for executions stuck in `claimed` or `running` beyond the heartbeat timestamp.
- There are no application metrics. The CI pipeline has no security scanning, no secret detection, and no migration validation gate.
- The `requirements/prod.txt` file is essentially empty.

### Why hardening comes before AWS deployment (10.9 → 10.10)

Every hardening decision is informed by knowing the full feature set. You cannot set a meaningful rate limit threshold until you know what endpoints exist. You cannot size a connection pool until you know how many concurrent requests each feature generates. You cannot write an operational runbook for "stuck execution recovery" until the approval gate, the watchdog, and the audit trail all exist.

Additionally, hardening mistakes discovered in production are expensive. Hardening discovered in local Docker is free. Phase 10.9 locks in the operational posture — security headers, secrets handling, graceful shutdown, structured logging — in a local environment where iteration is fast. Phase 10.10 then transplants this hardened system onto AWS infrastructure, where a misconfiguration costs time and sometimes money.

Hardening also produces the artifacts that AWS deployment depends on:
- A production `settings/prod.py` that reads all secrets from environment variables — which in AWS means Secrets Manager.
- A runner that handles `SIGTERM` cleanly — which is required for ECS rolling deploys.
- Structured logs with request IDs — which CloudWatch Logs Insights requires to correlate a single user request across Django, the AI service, and the runner.
- Health endpoints that verify database connectivity — which ALB target health checks require.

### What this phase does not do

- Does not deploy to AWS. AWS infrastructure is Phase 10.10.
- Does not add Celery, Redis, or any message queue.
- Does not add database replicas or read replicas.
- Does not rewrite the observability stack. Metrics are added through `django-prometheus` and `prometheus-fastapi-instrumentator`; no separate observability platform (Datadog, Honeycomb, Grafana Cloud) is configured here.
- Does not add microservice boundaries. Django remains the single control plane.
- Does not add CDN or WAF configuration.
- Does not add SSO, SAML, or OIDC.

---

## 2. Current-state inspection checklist

Before implementation begins, read the following files in order. Do not implement from memory.

**Django settings and configuration:**
- [ ] Read `apps/api/config/settings/base.py` — confirm current middleware stack, REST_FRAMEWORK config, CORS settings, AI timeout settings.
- [ ] Read `apps/api/config/settings/prod.py` — confirm it is only `from .base import *` and `DEBUG = False`. This must be expanded significantly.
- [ ] Read `apps/api/config/settings/dev.py` — confirm it is only `from .base import *` and `DEBUG = True`. Dev settings should not change in this phase.
- [ ] Read `apps/api/config/settings/test.py` — confirm test settings; verify they remain valid after new middleware is added.
- [ ] Read `apps/api/config/urls.py` — confirm the `/health/` endpoint exists and what it returns.
- [ ] Read `apps/api/config/asgi.py` — confirm it only contains `get_asgi_application()`. Confirm the `DJANGO_SETTINGS_MODULE` default is `config.settings.dev` (correct for development; production must set it via environment variable).
- [ ] Read `apps/api/requirements/base.txt` — note current dependencies. `structlog`, `django-prometheus`, `django-ratelimit`, `gunicorn`, and `uvicorn[standard]` (if not already added in Phase 10.8) will be added.
- [ ] Read `apps/api/requirements/prod.txt` — confirm it is nearly empty. This will be expanded with production-only dependencies.

**Runner:**
- [ ] Read `apps/runner/runner/main.py` — confirm there is no `SIGTERM` handler. Only `KeyboardInterrupt` is caught in the poller loop.
- [ ] Read `apps/runner/runner/poller.py` — confirm `run_forever()` has a fixed 5-second sleep on error. Note: no adaptive backoff, no graceful drain on shutdown.
- [ ] Read `apps/runner/runner/executor.py` — confirm `_HeartbeatThread` uses a 10-second interval. Note: no SIGTERM awareness in the executor.
- [ ] Read `apps/runner/runner/client.py` — confirm `httpx.Timeout(10.0)` is the only timeout configured (in `main.py`). Note: runner does not send a `X-Request-ID` header on any request.
- [ ] Read `apps/runner/runner/schemas.py` — confirm `RunnerSettings.from_env()` fields. No startup validation that required fields are non-empty.

**AI service:**
- [ ] Read `apps/ai/app/api/routes/health.py` — confirm it returns `{"status": "ok", "service": "ai"}` unconditionally, without checking any dependency.
- [ ] Read `apps/ai/app/main.py` — confirm no structured logging, no Prometheus instrumentation.

**Execution model and watchdog gap:**
- [ ] Read `apps/api/apps/executions/models.py` — confirm `last_heartbeat_at` field exists on `Execution`. Note: there is no management command or service function that sweeps for executions with stale heartbeats.
- [ ] Read `apps/api/apps/executions/services.py` — confirm no watchdog/recovery logic exists. Note: `complete_execution` and `cancel_execution` do not check `last_heartbeat_at`.

**Docker and environment:**
- [ ] Read `docker-compose.yml` — confirm no PgBouncer service, no `stop_grace_period` on any service, no `stop_signal: SIGTERM` explicit configuration.
- [ ] Read `.env.example` — confirm all required keys are documented.

**CI pipeline:**
- [ ] Read `.github/workflows/ci.yml` — confirm there is no security scanning (trivy, pip-audit, npm audit), no secret detection, and no migration validation gate.

**Verification commands (run before starting any milestone):**
```bash
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec api python manage.py showmigrations
cd apps/web && npm run build
cd apps/web && npm run lint
```

Record the full passing counts. All existing tests must remain green after every milestone.

---

## 3. Architecture invariants and boundaries

The following invariants from the platform roadmap apply in full. Each has a specific Phase 10.9 consequence.

| Invariant | Phase 10.9 consequence |
|---|---|
| **INV-1: Django is the control plane.** | The stuck-execution watchdog runs as a Django management command (`check_stuck_executions`), not as a standalone script or runner capability. Recovery state transitions go through `services.py`. |
| **INV-2: Runner talks only to Django internal APIs.** | Request ID propagation flows from runner → Django via an `X-Request-ID` header on every internal API call. The runner still has no awareness of the database, AI service, or SSE bus. |
| **INV-3: Frontend talks only to Django public APIs.** | Frontend security hardening is limited to CSP headers served by Django, CORS lockdown, and production build optimization. The frontend does not gain new service connections. |
| **INV-4: AI service is stateless and advisory.** | The AI service gains structured logging and a richer health endpoint (`/health` checks OpenAI reachability). It does not gain state. |
| **INV-5: API versioning is non-negotiable.** | The new metrics endpoint is at `/metrics/` (not under `/api/v1/` — Prometheus convention). The new detailed health endpoint is at `/health/` (existing path, expanded). No v1 URL contracts change. |
| **INV-6: UUID primary keys everywhere.** | Request IDs generated by the middleware are UUIDs. |
| **INV-7: Business logic in `services.py`.** | The watchdog sweep logic lives in `apps/api/apps/executions/services.py` as `recover_stuck_executions(...)`. The management command calls the service function. |
| **INV-8: No premature event infrastructure.** | Metrics are emitted via `django-prometheus` (in-process counters). No Kafka, Redis, or separate metrics collector is added. |

**Additional hardening-specific constraints:**

- **No hardcoded secrets.** Every secret (Django `SECRET_KEY`, DB password, OpenAI key, runner registration token) must be read from environment variables. No secret may appear in any settings file, Dockerfile, or docker-compose override.
- **No broad observability platform rewrite.** Add structured logging and Prometheus counters. Do not configure a full APM agent, distributed tracer, or log aggregation platform — those belong in Phase 10.10 when AWS infrastructure is chosen.
- **PgBouncer in transaction mode only for dev/prod.** Do not use statement mode (breaks `SET` and advisory locks) or session mode (defeats the purpose). Transaction mode is correct for Django's ORM-based workloads.
- **SIGTERM handler in runner only.** The API and AI services are managed by uvicorn/uvicorn's own graceful shutdown. Only the runner has custom SIGTERM logic because the runner holds per-execution state in memory (the heartbeat thread, the step iterator) that must be drained before exit.

---

## 4. Implementation scope by repo area

### `apps/api/config/settings/`

**`prod.py` (major rewrite):**
- HSTS, CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy security headers
- `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`
- Database connection pool settings (`CONN_MAX_AGE`, `CONN_HEALTH_CHECKS`)
- `ALLOWED_HOSTS` read from environment variable (no hardcoded values)
- `CORS_ALLOWED_ORIGINS` read from environment variable
- Rate limiting configuration
- Structured logging configuration (`structlog`)
- Prometheus metrics configuration
- Startup environment validation (raise `ImproperlyConfigured` for any missing required key)

**`base.py` (minimal additions):**
- Add `RequestIDMiddleware` to `MIDDLEWARE` (between SecurityMiddleware and CorsMiddleware)
- Add `csp.middleware.CSPMiddleware` to `MIDDLEWARE` — **required**: without this middleware registered, all `CSP_*` settings in `prod.py` are silently no-ops; no `Content-Security-Policy` header is emitted. Place it after `SecurityMiddleware`.
- Add `structlog` to `INSTALLED_APPS` if required
- Add `django_prometheus` to `INSTALLED_APPS`
- Logging configuration pointing to `structlog` processor chain (dev: pretty console, prod: JSON)

### `apps/api/apps/common/`

**`middleware.py` (new file):**
- `RequestIDMiddleware`: generates `X-Request-ID` UUID on each incoming request if not present, sets it on `request.request_id`, and includes it in the response header.
- `StructlogMiddleware` or integration hook: binds `request_id`, `method`, and `path` to the structlog context for the duration of the request.

**`health.py` (new file):**
- `detailed_health_view`: checks Django DB connectivity (one cheap `SELECT 1`), checks AI service reachability (one `GET /health` with a 2-second timeout via httpx), returns structured JSON with per-dependency status and overall `healthy: bool`. Returns HTTP 200 if healthy, HTTP 503 if any dependency is down.

### `apps/api/apps/executions/`

**`services.py` (additions only):**
- `recover_stuck_executions(*, stuck_threshold_seconds: int = 300) -> list[str]`: sweeps for executions in `claimed` or `running` status whose `last_heartbeat_at` is older than `stuck_threshold_seconds`. For each: transitions execution to `failed` with `error_message = "Execution marked failed by watchdog: heartbeat timeout"`, transitions all `running` steps to `failed`, emits an audit event (if audit app is active), and logs a structured warning. Returns a list of execution IDs recovered.
- The function uses `select_for_update(skip_locked=True)` to be safe under concurrent command invocations.

**`management/commands/check_stuck_executions.py` (new):**
- Django management command that calls `recover_stuck_executions(...)` and reports results to stdout.
- Designed to be run from a `docker compose exec api` command or a Kubernetes CronJob / ECS scheduled task.
- Accepts `--threshold-seconds` argument (default: 300).
- Idempotent: calling it multiple times produces the same result.

### `apps/runner/runner/`

**`main.py` (SIGTERM handler):**
- Install a `SIGTERM` signal handler before starting the poll loop.
- On `SIGTERM`: set a `_shutdown_requested` flag. The `Poller.run_forever()` loop checks this flag on each iteration and breaks cleanly after the current `_poll_once()` completes.
- The `Executor.run()` must be allowed to finish its current step before exit. The SIGTERM handler does not interrupt mid-step; it prevents new steps from starting after the current step finishes.
- Add a hard shutdown timeout: if the current step has not completed within 60 seconds of `SIGTERM`, log a critical error and exit anyway. A stuck step will be recovered by the Django watchdog.

**`poller.py` (adaptive backoff):**
- When `claim-next` returns an empty queue, use adaptive backoff: start at 2 seconds, double up to a maximum of `RUNNER_POLL_INTERVAL_SECONDS` (default: 5 from `.env.example`). Reset to minimum when work is found.
- When `claim-next` raises an `httpx.HTTPError`, back off exponentially: 5s, 10s, 20s, max 60s. Reset on success.

**`client.py` (request ID propagation):**
- All `httpx` requests from the runner must include an `X-Request-ID` header. Generate a new UUID per request (not per execution) so individual API calls can be correlated in Django logs.
- Add `X-Runner-ID` header to all requests (already in runner settings; add to every HTTP call via a default header on the `httpx.Client`).

**`schemas.py` (startup validation):**
- Add a startup validation method that raises `SystemExit(1)` with a clear error message if any required environment variable is empty or missing: `API_BASE_URL`, `RUNNER_REGISTRATION_TOKEN` (must not be `"change-me"`), `RUNNER_ID`.

### `apps/ai/`

**`app/api/routes/health.py` (expanded):**
- The `/health` endpoint performs a lightweight connectivity check: attempt to instantiate the OpenAI client and call a trivially cheap API endpoint (e.g., `models.list()` with a 2-second timeout). If this fails, return `{"status": "degraded", "checks": {"openai": "unreachable"}}` with HTTP 200 (not 503 — the AI service itself is up; the dependency is degraded). Log the check result.
- Note: do not call a real LLM completion from the health check — that costs tokens. Use a metadata endpoint or a client initialization check. If the OpenAI client initialization itself fails (bad key format, missing key), return degraded status without making a network call.

**`app/main.py` (structured logging + metrics):**
- Add `structlog` configuration (JSON output in production, pretty output in dev).
- Add `prometheus-fastapi-instrumentator` for automatic HTTP request metrics on the FastAPI app.
- Add custom gauge/counter for AI service calls: `ai_parse_requests_total`, `ai_parse_latency_seconds`, `ai_enrich_requests_total`, `ai_enrich_latency_seconds`, `ai_summarize_requests_total`, `ai_summarize_latency_seconds`.
- Expose `/metrics` endpoint via `prometheus-fastapi-instrumentator`.

### `apps/api/config/urls.py`

- Replace the simple `health` function with a call to `detailed_health_view` from `apps.common.health`.
- Add `path("metrics/", include("django_prometheus.urls"))` for Prometheus metrics scraping.
- The `admin/` endpoint must be disabled in production (not removed from code, but protected with `DJANGO_ADMIN_ENABLED` env var check).

### `apps/api/requirements/`

**`base.txt` (additions):**
- `structlog>=24.0,<25.0`
- `django-prometheus>=0.3,<1.0`
- `django-ratelimit>=4.1,<5.0`
- `django-csp>=3.7,<4.0` — required to emit `Content-Security-Policy` response headers. Without this package installed, the `CSP_*` settings in `prod.py` are silently ignored because no middleware reads them.
- `uvicorn[standard]>=0.29,<1.0` (if not already added in Phase 10.8)

**`prod.txt` (complete rewrite):**
```
-r base.txt
gunicorn>=22.0,<23.0
```

Note: `psycopg[binary]` is already in `base.txt`. `PgBouncer` is a separate Docker service, not a Python package.

### `docker-compose.yml` (additions)

- Add `pgbouncer` service using `bitnami/pgbouncer` image in transaction pooling mode.
- Update `api` service to connect to PgBouncer (port 5432 on the `pgbouncer` service) instead of Postgres directly.
- Add `stop_grace_period: 90s` to the `runner` service (must be longer than the 60-second SIGTERM hard timeout).
- Add `stop_signal: SIGTERM` explicitly to the `runner` service (Docker default is SIGTERM, but making it explicit documents the intent).
- Add a healthcheck to the `api` service: `test: ["CMD", "curl", "-f", "http://localhost:8000/health/ready/"]`. Use `/health/ready/` (DB-only check), not `/health/` (which also checks the AI service — AI being down must not fail the Django container healthcheck).
- Add a healthcheck to the `ai` service: `test: ["CMD", "curl", "-f", "http://localhost:8001/health"]`.

### `.env.example` (additions)

- `PGBOUNCER_POOL_SIZE=10` — maximum connections PgBouncer maintains to Postgres per pool.
- `PGBOUNCER_MAX_CLIENT_CONN=100` — maximum client connections PgBouncer accepts.
- `DJANGO_RATE_LIMIT_ANON=100/m` — rate limit for unauthenticated endpoints.
- `DJANGO_RATE_LIMIT_USER=1000/m` — rate limit for authenticated users.
- `WATCHDOG_STUCK_THRESHOLD_SECONDS=300` — threshold before an execution is considered stuck.
- `PROMETHEUS_METRICS_TOKEN=` — optional bearer token for scraping `/metrics/` in production.
- Document all AI timeout settings with their defaults and purpose.

### `.github/workflows/ci.yml` (additions)

- Add `security` job: runs `pip-audit` against all Python requirements files and `npm audit --audit-level=high` against `apps/web`.
- Add `secret-scan` job: runs `trufflehog` or `git-secrets` on the repository to detect accidentally committed secrets.
- Add `migration-check` job: runs `python manage.py migrate --check` to detect unapplied migrations that were committed without a migration file.
- Add `dependency-check` job: runs `trivy fs --exit-code 1 --severity HIGH,CRITICAL .` to scan Docker build contexts for known CVEs.
- Extend `api-tests` job to also run `python manage.py check --deploy` (with `DJANGO_SETTINGS_MODULE=config.settings.prod` and all required prod env vars set) to catch production-settings misconfiguration in CI.

---

## 5. Observability plan: logs, metrics, traces

### 5.1 Structured logging

**Decision: use `structlog`.**

`structlog` produces JSON log lines in production (one compact JSON object per event) and a colored, human-readable format in development. It binds contextual variables (request ID, execution ID, organization ID) to the log context at the start of a request and includes them on every subsequent log line within that request's scope.

**All services must emit structured logs. No `print()` statements.**

**Django log format (production):**
```json
{
  "timestamp": "2026-04-24T12:00:00.123Z",
  "level": "info",
  "service": "api",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "...",
  "execution_id": "...",
  "user_id": "...",
  "method": "POST",
  "path": "/api/v1/internal/executions/claim-next/",
  "status_code": 200,
  "duration_ms": 14,
  "event": "request completed"
}
```

**Runner log format (production):**
```json
{
  "timestamp": "2026-04-24T12:00:05.000Z",
  "level": "info",
  "service": "runner",
  "runner_id": "runner-1",
  "runner_version": "1.0.0",
  "execution_id": "...",
  "step_id": "...",
  "step_position": 2,
  "request_id": "550e8400-...",
  "event": "step completed"
}
```

**AI service log format (production):**
```json
{
  "timestamp": "2026-04-24T12:00:02.000Z",
  "level": "info",
  "service": "ai",
  "request_id": "550e8400-...",
  "route": "/parse",
  "tokens_used": 1243,
  "duration_ms": 2100,
  "event": "parse completed"
}
```

**Implementation approach:**
- Django: Add `structlog.configure(...)` in `base.py` (dev: `ConsoleRenderer`, prod: `JSONRenderer`). Add `StructlogRequestMiddleware` that binds `request_id`, `method`, `path`, `user_id` (if authenticated), `organization_id` (from `X-Organization-Id` header) at the start of each request and logs a "request completed" line with `status_code` and `duration_ms` on exit.
- Runner: Replace `configure_logging(...)` in `log_streamer.py` with `structlog.configure(...)`. Bind `runner_id`, `runner_version`, `execution_id`, and `request_id` to the structlog context before each API call.
- AI service: Call `structlog.configure(...)` in `app/main.py`. Add a FastAPI middleware that binds `request_id` (from the `X-Request-ID` header, or generates a new UUID) to the context for each request.

### 5.2 Request/correlation ID propagation

The `X-Request-ID` header is the cross-service correlation key.

**Flow:**
1. Browser sends a request to Django. If `X-Request-ID` is present (from a previous request or a manual test), Django uses it. If absent, Django generates a UUID and sets `request.request_id`.
2. Django's `RequestIDMiddleware` includes `X-Request-ID: <uuid>` in every response. This allows the frontend to log the request ID from the browser's DevTools.
3. When Django calls the AI service via `httpx`, it passes the current `request_id` in the `X-Request-ID` header. The AI service logs this ID on every line for the duration of that request.
4. When the runner calls Django's internal API, it generates a new UUID per HTTP call and passes it as `X-Request-ID`. Django logs this on the internal endpoint's request log line.

This means a single user request that triggers a `/parse` call to the AI service can be correlated across both service logs using a shared UUID.

### 5.3 Metrics

**Decision: use `django-prometheus` for Django, `prometheus-fastapi-instrumentator` for the AI service.**

Both emit standard Prometheus text format at their respective `/metrics` endpoints. In Phase 10.10 (AWS), a Prometheus sidecar or CloudWatch agent scrapes these endpoints.

**Django metrics (auto-generated by `django-prometheus`):**
- `django_http_requests_total_by_method_view_transport_status` — request count by method, view, transport, status code
- `django_http_request_duration_seconds` — request latency histogram
- `django_db_query_duration_seconds` — DB query latency histogram by operation type
- `django_db_execute_total` — total DB queries

**Custom application metrics (added manually to Django services):**

| Metric name | Type | Labels | Where emitted |
|---|---|---|---|
| `runbook_executions_total` | Counter | `status` (queued/claimed/running/succeeded/failed/cancelled), `organization_id` | `services.py` at status transitions |
| `runbook_step_duration_seconds` | Histogram | `step_type`, `risk_level`, `outcome` | `services.py` in `update_execution_step` |
| `runbook_approval_latency_seconds` | Histogram | `outcome` (approved/rejected/timed_out) | `approvals/services.py` in `decide_approval` |
| `runbook_integration_dispatch_duration_seconds` | Histogram | `integration_type`, `outcome` (success/failure) | `integrations/services.py` in `dispatch` |
| `runbook_artifact_upload_bytes` | Histogram | (no labels) | `artifacts/services.py` in `create` |
| `runbook_stuck_executions_recovered_total` | Counter | (no labels) | `executions/services.py` in `recover_stuck_executions` |

**AI service metrics (via `prometheus-fastapi-instrumentator` + custom):**

| Metric name | Type | Labels | Where emitted |
|---|---|---|---|
| `ai_parse_request_duration_seconds` | Histogram | `outcome` (success/error) | `/parse` route |
| `ai_enrich_request_duration_seconds` | Histogram | `outcome` | `/enrich` route |
| `ai_summarize_request_duration_seconds` | Histogram | `outcome` | `/summarize` route |
| `ai_llm_tokens_used_total` | Counter | `route`, `token_type` (prompt/completion) | LLM client wrapper |

**Metrics access control:** In production, the `/metrics/` endpoint must not be publicly accessible. It exposes execution counts, latency distributions, and organization-level activity patterns.

> **ARCHITECTURE DECISION (H-08): Metrics fail-closed in production.**
>
> The `PrometheusMetricsPermission` class must fail-closed, not fail-open. If `PROMETHEUS_METRICS_ENABLED=True` and `PROMETHEUS_METRICS_TOKEN` is empty or unset, startup must raise `ImproperlyConfigured` — not silently serve metrics to the world. Dev mode (`DEBUG=True`) may skip the check.

Implementation:
1. Add to the startup validation in `prod.py` (alongside `_require_env` checks):
   ```python
   if env.bool("PROMETHEUS_METRICS_ENABLED", default=False):
       _require_env("PROMETHEUS_METRICS_TOKEN")  # raises ImproperlyConfigured if missing
   ```
2. Implement `PrometheusMetricsPermission` to check `Authorization: Bearer <PROMETHEUS_METRICS_TOKEN>` on every request to `/metrics/`. Return 403 if token is missing or wrong.
3. In `dev.py`, `PROMETHEUS_METRICS_ENABLED = False` (metrics off by default in local dev; enable explicitly when needed).

Add to `.env.example`:
```
PROMETHEUS_METRICS_ENABLED=false
PROMETHEUS_METRICS_TOKEN=
```

Phase 10.10 (network-level VPC restriction) is a defense-in-depth addition, not a replacement for the token check. Both controls should be active in production.

### 5.4 Traces

Distributed tracing (OpenTelemetry) is explicitly deferred to Phase 10.10. The operational cost of configuring an OTLP collector in local Docker is not justified when the benefit (cross-service span correlation) can be achieved with request IDs in logs. Add traces in Phase 10.10 after the collector infrastructure exists in AWS.

---

## 6. Reliability plan: timeouts, retries, watchdogs, health checks, graceful shutdown

### 6.1 Timeout standards

Every inter-service HTTP call must have an explicit timeout. No call may use the httpx default (unlimited) or a global timeout that is too broad.

| Call direction | Client | Connect timeout | Read timeout | Write timeout | Total |
|---|---|---|---|---|---|
| Django → AI service | `httpx.AsyncClient` | `AI_CONNECT_TIMEOUT_SECONDS` (default: 1.0s) | `AI_READ_TIMEOUT_SECONDS` (default: 20.0s) | `AI_WRITE_TIMEOUT_SECONDS` (default: 5.0s) | N/A |
| Django → integrations (Slack, PagerDuty) | `httpx.Client` (sync — Phase 10.5 uses synchronous Django views; see M-04) | 3.0s | 3.0s | 3.0s | 9.0s |
| Runner → Django internal API | `httpx.Client` | 5.0s | 30.0s | 10.0s | N/A |

These values already exist for the Django → AI direction (configured in `base.py`). The integration and runner timeouts must be explicitly set and documented in `.env.example`.

Rationale for runner's 30-second read timeout: the `claim-next` response is fast, but the `update_step` call with a large artifact upload payload may take longer. 30 seconds is conservative.

### 6.2 Retry standards

**Django → AI service:** No automatic retry in Django. If the AI service returns a 5xx or network error, Django returns an error to the user immediately. The user can retry the parse operation. LLM calls are expensive and non-idempotent (cost tokens on each call) — silent retries are inappropriate.

**Django → integrations:** No retry (as documented in Phase 10.5 blueprint). Log the failure in `IntegrationEvent`. Move on.

**Runner → Django internal API:** Retry with exponential backoff on network errors and HTTP 5xx responses. Retry schedule: 1s, 2s, 4s, 8s, max 3 attempts before marking the step/execution as failed. On HTTP 4xx (client error), do not retry — the request is wrong.

**PgBouncer → Postgres:** PgBouncer handles reconnection to Postgres automatically. No Django-side retry needed.

### 6.3 Watchdog: stuck execution recovery

**Problem:** If a runner crashes mid-execution (OOM kill, SIGKILL, power loss), the execution remains in `claimed` or `running` status indefinitely. The runner's heartbeat stops, but no code currently detects the stale heartbeat and recovers the execution.

**Solution:** A Django management command `check_stuck_executions` that:
1. Queries for executions in `claimed` or `running` status where `last_heartbeat_at < now() - threshold_seconds`.
2. For each stuck execution (using `select_for_update(skip_locked=True)`):
   - Sets all `running` steps to `failed` with `error_message = "Step failed: runner heartbeat timeout"`.
   - Sets the execution status to `failed` with `finished_at = now()`.
   - Emits an audit event: `execution.watchdog_recovery`.
   - Logs a structured warning including `execution_id`, `claimed_by_runner_id`, `last_heartbeat_at`, and `threshold_seconds`.
3. Returns a count of recovered executions (for monitoring).

**Scheduling:** Run `check_stuck_executions` via a `docker compose exec api python manage.py check_stuck_executions` cron command. For local development: run manually. For Phase 10.10 AWS: schedule as an ECS scheduled task every 5 minutes.

**Threshold:** Default 300 seconds (5 minutes). The runner sends heartbeats every 10 seconds (`_HEARTBEAT_INTERVAL_SECONDS`). A 5-minute threshold gives the runner 30 missed heartbeats before recovery triggers — generous enough to survive transient network issues but short enough to unblock executions quickly.

**Important:** The watchdog must not compete with a live runner. `select_for_update(skip_locked=True)` ensures that if a live runner is currently updating a step on an execution, the watchdog skips that execution. The runner's heartbeat timestamp will be updated before the watchdog's 300-second window expires.

### 6.3.1 Watchdog: expired approval recovery (K-M07)

**Problem:** If a human approver never acts on an `ApprovalRequest` and it passes its `expires_at` deadline, the execution remains blocked on `wait_for_approval` indefinitely — no runner crash, no stale heartbeat. The stuck-execution watchdog in §6.3 does not detect this case because the execution may have a live heartbeat from a runner that is correctly waiting.

**Solution:** A second sweep function `recover_expired_approvals()` that runs in the same `check_stuck_executions` management command:
1. Queries for `ApprovalRequest` rows in `pending` status where `expires_at < now()`.
2. For each expired approval (using `select_for_update(skip_locked=True)`):
   - Sets `ApprovalRequest.status = "timed_out"` with `decided_at = now()`, `decided_by_label = "watchdog"`.
   - Emits an audit event: `approval.timeout`.
   - Finds the blocked execution and sets it to `failed` with `error_message = "Execution failed: approval request timed out"`.
   - Emits an audit event: `execution.approval_timeout`.
   - Logs a structured warning including `approval_id`, `execution_id`, `expires_at`.
3. Returns a count of expired approvals resolved.

**Prerequisite:** Phase 10.1 must add an `expires_at` field on `ApprovalRequest` and populate it from a configurable `APPROVAL_TIMEOUT_SECONDS` setting (default: `None` for no timeout). Phase 10.9's watchdog management command is the consumer of that field — the command must gracefully skip the sweep if `ApprovalRequest` does not have an `expires_at` column (use `hasattr` check or Django `check` framework, not a hard import-time dependency).

**Scheduling:** Same ECS scheduled task as the stuck-execution watchdog — run both sweeps in a single management command invocation. Update `check_stuck_executions` to also call `recover_expired_approvals()`.

### 6.4 Health check endpoints

> **ARCHITECTURE DECISION (H-02): Split health endpoints — ALB must never use the AI-dependency check.**
>
> The Django API exposes three distinct health endpoints. The AI service being unreachable must not cause the ALB to mark Django API containers as unhealthy. Coupling ALB target health to an external dependency means a transient AI service outage takes the entire API out of the load balancer rotation — which is far worse than serving partial functionality.

**Three-endpoint model:**

| Endpoint | Checks | Used by | Returns 503 when |
|---|---|---|---|
| `GET /health/live` | None (process up = healthy) | Internal watchdog, docs | Never (if process is dead, no response is returned) |
| `GET /health/ready/` | DB connection only | **ALB target health check, docker-compose healthcheck** | Database is unreachable |
| `GET /health/` | DB + AI service | Operations/ops dashboards only | DB or AI is unhealthy |

**Django `GET /health/live` (liveness):**
Returns immediately with no I/O. Proves the Django process is alive and accepting requests.
```json
{"status": "live", "service": "api"}
```
Always HTTP 200. No database or AI service call.

**Django `GET /health/ready/` (readiness — ALB-facing):**
Checks only that the database is reachable and migrations are current. Used by the ALB target group health check and the docker-compose healthcheck.
```json
{"status": "ready", "checks": {"database": {"status": "healthy", "latency_ms": 3}}}
```
HTTP 200 when database is reachable and migrations are current. HTTP 503 if database is unreachable or unapplied migrations exist.

The database check calls `connection.ensure_connection()` then `cursor.execute("SELECT 1")` with a 2-second timeout. Migrations check calls `django.core.management.call_command("migrate", "--check")`.

**INVARIANT:** The ALB target health check and the docker-compose healthcheck MUST use `/health/ready/`. They MUST NOT use `/health/`. An AI service outage must not remove the Django API from the load balancer rotation.

**Django `GET /health/` (dependency health — informational only):**
Checks DB + AI service. Used by operators and monitoring dashboards only — never by ALB or docker-compose.
```json
{
  "status": "healthy" | "unhealthy",
  "service": "api",
  "version": "1.0.0",
  "timestamp": "2026-04-24T12:00:00Z",
  "checks": {
    "database": {"status": "healthy", "latency_ms": 3},
    "ai_service": {"status": "healthy", "latency_ms": 45}
  }
}
```
HTTP 200 when all checks pass. HTTP 503 if any check fails. Both checks run concurrently using `asyncio.gather` (async view). The AI service check calls `httpx.AsyncClient().get(settings.AI_BASE_URL + "/health", timeout=2.0)`.

**AI service `GET /health` (improved):**
Returns `{"status": "ok" | "degraded", "service": "ai", "checks": {"openai": "ok" | "unreachable"}}`. Always HTTP 200 (the AI service itself is up; dependency state is informational).

**Runner (no HTTP health endpoint):**
The runner is not an HTTP server and does not serve a health endpoint. Instead, it writes a PID file to `/tmp/runner.pid` on startup and removes it on clean shutdown. Docker healthcheck can use `test: ["CMD", "test", "-f", "/tmp/runner.pid"]`. This is not a liveness check (the PID file persists even if the process is deadlocked), but it is sufficient for Phase 10.9. Phase 10.10 may add a more sophisticated probe.

### 6.5 Graceful shutdown

**Runner SIGTERM handler:**

```python
import signal
import threading

_shutdown_event = threading.Event()

def _sigterm_handler(signum, frame):
    logger.info("SIGTERM received — will shut down after current step completes")
    _shutdown_event.set()

signal.signal(signal.SIGTERM, _sigterm_handler)
```

In `Poller.run_forever()`:
```python
while not _shutdown_event.is_set():
    try:
        self._poll_once()
    except KeyboardInterrupt:
        break
    except Exception as exc:
        ...
```

In `Poller._poll_once()`, after claiming an execution:
```python
if _shutdown_event.is_set():
    # Release the claim via a cancel API call (if one exists) or let the watchdog recover.
    logger.warning("SIGTERM received before execution started — leaving execution queued for watchdog")
    return
```

If an execution is already running when SIGTERM arrives, `Executor.run()` continues through the current step. The SIGTERM handler sets the event; the next iteration of the step loop checks it and stops after the current step completes. The executor calls `complete_execution` with `outcome="failed"` and a note that it was interrupted by shutdown.

**Hard timeout:** If the current step is still running 60 seconds after SIGTERM, the runner logs a critical error and calls `sys.exit(1)`. The execution will be recovered by the watchdog.

**API service (uvicorn):** uvicorn handles graceful shutdown natively on SIGTERM — it stops accepting new connections and waits for in-flight requests to complete (up to the configured `--timeout-graceful-shutdown` seconds, set to 30).

**AI service (uvicorn):** Same as API service.

### 6.6 Database connection pooling (PgBouncer)

**Why PgBouncer:**
- Django's default connection behavior opens one persistent connection per worker process.
- uvicorn with multiple async workers still creates connections per worker.
- PostgreSQL's default `max_connections` is 100. With 8 uvicorn workers and a PgBouncer default pool of 10, Django sees a virtual pool of 100 client connections, but only 10 actual Postgres connections are used.

**Configuration (docker-compose):**
```yaml
pgbouncer:
  image: bitnami/pgbouncer:1.23
  environment:
    POSTGRESQL_HOST: postgres
    POSTGRESQL_PORT: 5432
    POSTGRESQL_DATABASE: runbook_platform
    POSTGRESQL_USERNAME: postgres
    POSTGRESQL_PASSWORD: postgres
    PGBOUNCER_POOL_SIZE: 10
    PGBOUNCER_MAX_CLIENT_CONN: 100
    PGBOUNCER_POOL_MODE: transaction
  depends_on:
    postgres:
      condition: service_healthy
```

**Update `api` service `DATABASE_URL`** to point to PgBouncer: `postgresql://postgres:postgres@pgbouncer:5432/runbook_platform`.

**Django settings addition for production:**
```python
DATABASES["default"]["CONN_MAX_AGE"] = 0  # Let PgBouncer manage pooling; disable Django's persistent connections
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
```

**Important constraint:** PgBouncer in transaction pooling mode breaks any feature that requires a persistent connection: `LISTEN/NOTIFY`, `SET LOCAL`, advisory locks held across multiple queries, and `pg_notify`. Phase 10.8 explicitly avoided `LISTEN/NOTIFY` for this reason. Confirm no code uses these before activating PgBouncer.

**Verification:**
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'runbook_platform' AND application_name = 'pgbouncer';
```
With PgBouncer active, this count must be ≤ `PGBOUNCER_POOL_SIZE` regardless of how many Django workers are running.

---

## 7. Security hardening plan

### 7.1 Environment validation on startup

Add to `prod.py`:
```python
def _require_env(key: str) -> str:
    value = env(key, default="")
    if not value or value == "change-me":
        raise ImproperlyConfigured(f"Required environment variable {key!r} is not set or has default value.")
    return value

_require_env("DJANGO_SECRET_KEY")
_require_env("DATABASE_URL")
_require_env("RUNNER_REGISTRATION_TOKEN")
```

Add to runner `schemas.py`:
```python
def validate(self) -> None:
    if not self.runner_registration_token or self.runner_registration_token == "change-me":
        raise SystemExit("RUNNER_REGISTRATION_TOKEN is not configured. Exiting.")
```

Call `settings.validate()` at the start of `main()`.

### 7.2 Django security headers

Add to `prod.py`:
```python
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")  # Vite inlines some styles; narrow in Phase 10.10
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
```

**IMPORTANT:** The `CSP_*` settings above are read by `django-csp`'s middleware. They have no effect unless `csp.middleware.CSPMiddleware` is registered in `MIDDLEWARE` (documented in §4 `base.py` additions). Verify with a response header test — see §11 test suite.

Note: CSP is initially permissive on `style-src` because Vite production builds may inline critical CSS. Tighten to `'nonce-...'` in Phase 10.10 once the exact requirements are known.

### 7.3 CORS lockdown for production

In `prod.py`:
```python
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
```

In `.env.example` (add):
```
CORS_ALLOWED_ORIGINS=https://app.example.com
```

In dev, `base.py` keeps `http://localhost:5173` in `CORS_ALLOWED_ORIGINS`.

### 7.4 Rate limiting

Add `django-ratelimit` to `base.txt`. Configure limits in `prod.py`:
```python
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = "default"
```

Apply `@ratelimit` decorator at the view level on public endpoints:
- Unauthenticated endpoints (login, health): 60 requests / minute / IP.
- Authenticated endpoints (execution create, runbook parse): 300 requests / minute / user.
- Internal runner endpoints: exempt from rate limiting (they are internal; the runner token is the authentication mechanism).

Do not apply rate limiting in dev or test settings (`RATELIMIT_ENABLE = False` in `dev.py` and `test.py`).

### 7.5 CSRF settings

The API uses JWT authentication (stateless). CSRF protection applies to session-based auth and to any endpoint that can be called from a browser form. For DRF endpoints using `JWTAuthentication`, CSRF is automatically disabled by DRF for `SessionAuthentication`-free views. However, Django admin still uses session auth and requires CSRF.

Verify in `prod.py` that `CsrfViewMiddleware` remains in `MIDDLEWARE`. Confirm DRF views use `JWTAuthentication` only (no `SessionAuthentication`) on any endpoint that handles sensitive mutations.

### 7.6 Secrets management

Phase 10.9 standards:
- No secret may appear in any committed file. `.env` is in `.gitignore`. `.env.example` must contain only placeholder values (not real keys).
- `DJANGO_SECRET_KEY` must be a random 50-character string, not the `django-insecure-change-me` default.
- `RUNNER_REGISTRATION_TOKEN` must not be `"change-me"`. Startup validation enforces this.
- `OPENAI_API_KEY` is validated on AI service startup (check that it starts with `sk-` as a minimal format check).
- All integration credentials (Slack webhook URLs, PagerDuty keys) are stored Fernet-encrypted in the database (Phase 10.5 implementation). Never stored in environment variables.

### 7.7 Dependency security scanning

Add to CI:
- `pip-audit` on all `requirements/*.txt` files: `pip-audit -r apps/api/requirements/base.txt`.
- `npm audit --audit-level=high` on `apps/web/package.json`.
- `trivy fs --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed .` on the repository.

These run in a new `security` CI job that does not block other jobs but must pass before a PR can merge (branch protection rule).

### 7.8 Admin endpoint security

The Django admin at `/admin/` exposes the full data model. In production:
- Add `DJANGO_ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=False)` to `prod.py`.
- In `urls.py`: `if settings.DJANGO_ADMIN_ENABLED: urlpatterns += [path("admin/", admin.site.urls)]`.
- Default to disabled. Ops engineers enable it temporarily via a task definition environment variable change when needed for data migrations.

---

## 8. Data integrity and recovery plan

### 8.1 Execution state machine integrity

Every state transition is already inside a `transaction.atomic()` block or a single `.save()` call that is implicitly atomic. Phase 10.9 adds no new state transitions but enforces this constraint explicitly:

- Add a database-level `CHECK` constraint on `Execution.status` to reject any status value not in the `Status.choices` enum.
- Add a database-level `CHECK` constraint on `ExecutionStep.status` similarly.
- These are migration changes only (no model field changes). Generate via:
  ```python
  # In a new migration:
  migrations.AddConstraint(
      model_name="execution",
      constraint=models.CheckConstraint(
          check=models.Q(status__in=[s[0] for s in Execution.Status.choices]),
          name="execution_status_valid",
      ),
  )
  ```

### 8.2 Watchdog recovery durability

When the watchdog marks an execution as failed:
- The audit event must be written in the same `atomic()` block as the status update.
- The watchdog must be idempotent: running it twice on the same stuck execution produces the same result (the second run finds no stuck executions matching the criteria because the first run already transitioned them to `failed`).
- The watchdog must not touch executions that are in `queued` or terminal states (`succeeded`, `failed`, `cancelled`).

### 8.3 N+1 query analysis

Run `EXPLAIN ANALYZE` on the following queries and add indexes or `select_related` calls where needed:

**Execution list endpoint (`GET /api/v1/executions/`):**
- Current query: one query for the execution list + N queries for step counts (one per execution). Fix: annotate the queryset with `annotate(step_count=Count("steps"))` and add a `select_related("workflow", "organization")`.
- Add `prefetch_related("steps")` if the execution list includes per-step status summaries.

**Audit trail endpoint (`GET /api/v1/audit/`):**
- Current query: one query per audit event to load the actor label (if not denormalized). Confirm actor label is stored on the `AuditEvent` row (denormalized per Phase 10.3 blueprint) and does not require a JOIN.
- Add index on `audit_auditevent (organization_id, occurred_at DESC)`.

**Approval inbox (`GET /api/v1/approvals/?status=pending`):**
- Add index on `approvals_approvalrequest (status, requested_at)`.

**Integration dispatch path:**
- `IntegrationService.dispatch(...)` queries all active integrations for an organization. Add index on `integrations_integration (organization_id, is_active)`.

**Tool for local profiling:**
```bash
docker compose exec api python manage.py shell
# In shell:
from django.db import connection, reset_queries
from django.conf import settings
settings.DEBUG = True
reset_queries()
# ... run the view function ...
from pprint import pprint
pprint(connection.queries)
```

Do not use `django-debug-toolbar` in Phase 10.9 — it is a dev-only tool and adds middleware that should not be in any production-adjacent settings file.

### 8.4 Migration safety

Before each production deploy, confirm:
```bash
docker compose exec api python manage.py migrate --check
docker compose exec api python manage.py showmigrations
```

For the migrations added in Phase 10.9 (CHECK constraints, new indexes):
- CHECK constraints on columns with existing data will fail if any row violates the constraint. Run a data audit before adding the constraint: `SELECT DISTINCT status FROM executions_execution;`. If any unexpected values exist, clean them before migrating.
- Index creation on large tables (`CONCURRENTLY` flag): for Phase 10.9 (dev/local), use standard `CREATE INDEX`. For Phase 10.10 (AWS production), use `migrations.RunSQL("CREATE INDEX CONCURRENTLY ...")` to avoid locking the table.

---

## 9. CI/CD validation gates without deploying AWS yet

The CI pipeline after Phase 10.9 must enforce the following gates on every pull request. None of these require AWS infrastructure.

### 9.1 Existing gates (preserved)

- `web` job: `npm ci`, `npm run build`, `npm run lint`, `npm run format:check`, `npx vitest run`
- `python-lint` job: `ruff check`, `ruff format --check` on all Python services
- `api-tests` job: `pytest` against all Django app tests with a real Postgres service
- `runner-tests` job: `pytest` against runner tests
- `ai-tests` job: `pytest tests/` against AI service tests

### 9.2 New gates added in Phase 10.9

**`production-settings-check` job:**
```yaml
- name: Check Django production settings
  env:
    DJANGO_SETTINGS_MODULE: config.settings.prod
    DJANGO_SECRET_KEY: ci-prod-check-secret-key-not-for-real
    DATABASE_URL: postgresql://postgres:postgres@localhost:5432/runbook_platform
    RUNNER_REGISTRATION_TOKEN: ci-test-runner-token
    DJANGO_ALLOWED_HOSTS: localhost
    CORS_ALLOWED_ORIGINS: http://localhost:5173
  run: python manage.py check --deploy
```

`manage.py check --deploy` runs Django's deployment checklist and reports all settings that are insecure for production. This gate catches future `prod.py` regressions.

**`migration-check` job:**
```yaml
- name: Check for unapplied migrations
  run: python manage.py migrate --check
```

Catches the case where a model change was committed without a corresponding migration file.

**`security` job:**
```yaml
- name: pip-audit (API)
  run: pip-audit -r apps/api/requirements/base.txt -r apps/api/requirements/prod.txt
- name: pip-audit (runner)
  run: pip-audit -r apps/runner/requirements/base.txt
- name: pip-audit (AI)
  run: pip-audit -r apps/ai/requirements/base.txt
- name: npm audit (web)
  run: npm audit --audit-level=high
  working-directory: apps/web
```

**`secret-scan` job:**
```yaml
- name: Scan for secrets
  uses: trufflesecurity/trufflehog-actions-scan@main
  with:
    path: ./
    base: main
    head: HEAD
    extra_args: --debug --only-verified
```

**`trivy-scan` job (vulnerability scan on build contexts):**
```yaml
- name: Trivy filesystem scan
  uses: aquasecurity/trivy-action@master
  with:
    scan-type: fs
    scan-ref: .
    exit-code: 1
    severity: HIGH,CRITICAL
    ignore-unfixed: true
```

### 9.3 Branch protection configuration (manual step, not automated)

Configure the following branch protection rules on the `main` branch in GitHub:
- Require status checks: all CI jobs must pass.
- Require linear history (no merge commits on main).
- Dismiss stale reviews on new pushes.
- Do not allow force pushes.

This is a one-time manual setup in the GitHub repository settings, not a CI file change.

### 9.4 Load testing gate (manual, pre-AWS)

Before signing off on Phase 10.9 and moving to 10.10, run a local load test:

```bash
docker compose up -d
# Install k6 locally
k6 run --vus 50 --duration 60s scripts/load-test.js
```

The `scripts/load-test.js` load test (new file, created in this phase) hits `GET /api/v1/executions/` with a valid JWT for 60 seconds at 50 virtual users. The gate: P99 latency < 200ms, 0 HTTP 5xx responses, DB connection count ≤ `PGBOUNCER_POOL_SIZE`.

---

## 10. Ordered milestones

Each milestone is a small, independently verifiable unit of work. Commit at every verification gate. Do not proceed to the next milestone if the current gate fails.

---

### Milestone 1 — Structured logging with `structlog`

**Purpose:** Replace all `print()` and bare `logging.getLogger` calls with structured JSON logs that include contextual fields. This is the foundation for all subsequent observability work.

**Files touched:**
- `apps/api/requirements/base.txt` — add `structlog>=24.0,<25.0`
- `apps/api/config/settings/base.py` — add `LOGGING` config for structlog
- `apps/api/apps/common/middleware.py` (new) — `RequestIDMiddleware`
- `apps/api/config/settings/base.py` — add `RequestIDMiddleware` to `MIDDLEWARE`
- `apps/runner/runner/log_streamer.py` — replace with structlog configuration
- `apps/ai/requirements/base.txt` — add `structlog>=24.0,<25.0`
- `apps/ai/app/main.py` — configure structlog on startup

**Steps:**
1. Add `structlog` to `apps/api/requirements/base.txt`.
2. Configure structlog in `base.py` (dev: `ConsoleRenderer`, prod: `JSONRenderer`). Integrate with Django's `logging` module via `structlog.stdlib.ProcessorFormatter`.
3. Create `apps/api/apps/common/middleware.py` with `RequestIDMiddleware` that generates a UUID if `X-Request-ID` is not in the request headers, stores it on `request.request_id`, passes it to structlog context, adds it to the response, and logs a "request completed" event with status code and duration.
4. Add `"apps.common.middleware.RequestIDMiddleware"` to `MIDDLEWARE` in `base.py` (second position, after `SecurityMiddleware`, before `CorsMiddleware`).
5. Update `apps/runner/runner/log_streamer.py` to use structlog instead of standard logging. Bind `runner_id`, `runner_version` to the global context.
6. Add structlog to AI service requirements and configure in `app/main.py`.

**Verification:**
```bash
make down && make up
make logs
# Confirm log lines are JSON objects with timestamp, level, service, request_id fields
curl http://localhost:8000/health/ -v
# Check response header: X-Request-ID: <uuid>
# Check API logs: line with request_id matching the response header
docker compose exec api pytest
# All tests pass
```

**Rollback notes:** Remove `RequestIDMiddleware` from `MIDDLEWARE`. Revert `log_streamer.py` and `base.py` LOGGING config. Test suite must pass.

**Human approval gate:** Confirm via `make logs` that Django log lines are structured JSON in production mode (set `DJANGO_DEBUG=0`) and human-readable in dev mode.

---

### Milestone 2 — Request ID propagation to AI service and runner

**Purpose:** Ensure that the `X-Request-ID` generated by Django is passed to the AI service on every `httpx` call, and that the runner generates and sends a request ID on every call to Django's internal API.

**Files touched:**
- `apps/api/apps/runbooks/services.py` (or wherever AI service is called) — add `X-Request-ID` header to `httpx` calls
- `apps/runner/runner/client.py` — add `X-Request-ID` and confirm `X-Runner-ID` headers on all requests
- `apps/ai/app/main.py` — add FastAPI middleware to bind `request_id` from `X-Request-ID` header to structlog context

**Steps:**
1. In the Django service layer that calls the AI service (inspect `runbooks/services.py`), add `headers={"X-Request-ID": request_id}` to all `httpx` calls. The `request_id` is read from `structlog.contextvars.get_contextvars()["request_id"]` or from a thread-local set by `RequestIDMiddleware`.
2. In `apps/runner/runner/client.py`, add a `default_headers` dict to the `httpx.Client` constructor: `{"X-Request-ID": str(uuid.uuid4()), "X-Runner-Id": self._runner_id}`. Generate a fresh `X-Request-ID` per request (not per connection) by using a per-request event hook.
3. In the AI service `app/main.py`, add a FastAPI middleware that reads `X-Request-ID` from the request (or generates a new UUID) and binds it to the structlog context.

**Verification:**
```bash
# Start a runbook parse from the UI (or via API call)
# In Django logs: find the parse request with its request_id
# In AI service logs: find the parse request with the same request_id
make logs | grep -A5 "parse"
```

**Human approval gate:** Verify via `make logs` that a single parse operation produces log lines with the same `request_id` in both Django and AI service logs.

---

### Milestone 3 — Expanded health and readiness endpoints

**Purpose:** Split Django health into three endpoints so the ALB target health check never depends on AI service availability. See §6.4 for endpoint contract.

**Files touched:**
- `apps/api/apps/common/health.py` (new)
- `apps/api/config/urls.py` — add `live_view`, replace simple `health` function with `detailed_health_view`, add `readiness_view` at `/health/ready/`

**Steps:**
1. Create `apps/api/apps/common/health.py` with three views:
   - `live_view` (sync, no I/O): returns `{"status": "live", "service": "api"}` with HTTP 200.
   - `readiness_view` (sync): runs `connection.ensure_connection()` + `cursor.execute("SELECT 1")` with a 2-second timeout, then `call_command("migrate", "--check")`. Returns `{"status": "ready", "checks": {"database": {"status": "healthy", "latency_ms": N}}}` HTTP 200, or `{"status": "not_ready", ...}` HTTP 503.
   - `detailed_health_view` (async): runs DB check + AI service check concurrently via `asyncio.gather`. Returns HTTP 200 if all pass, HTTP 503 if any fail. See §6.4 for full JSON shape.
2. Update `apps/api/config/urls.py`:
   ```python
   path("health/live", live_view),
   path("health/ready/", readiness_view),
   path("health/", detailed_health_view),
   ```
3. Update `docker-compose.yml` API healthcheck to use `/health/ready/` (done in the docker-compose additions above in §5).

**Verification:**
```bash
curl -s http://localhost:8000/health/live
# Expect: {"status": "live", "service": "api"}
curl -s http://localhost:8000/health/ready/ | python3 -m json.tool
# Expect: {"status": "ready", "checks": {"database": {"status": "healthy", ...}}}
curl -s http://localhost:8000/health/ | python3 -m json.tool
# Expect: {"status": "healthy", "checks": {"database": {...}, "ai_service": {...}}}

# Stop AI service; confirm readiness still returns 200 (DB-only):
docker compose stop ai
curl -s http://localhost:8000/health/ready/ -o /dev/null -w "%{http_code}"
# Expect: 200  <-- AI being down must NOT fail the readiness probe
curl -s http://localhost:8000/health/ -o /dev/null -w "%{http_code}"
# Expect: 503  <-- detailed health correctly reflects AI is down
docker compose start ai

# Stop postgres; confirm readiness returns 503:
docker compose stop postgres
curl -s http://localhost:8000/health/ready/ -o /dev/null -w "%{http_code}"
# Expect: 503
docker compose start postgres
```

**Human approval gate:** Confirm: (1) `/health/ready/` returns 200 when AI is down but DB is up. (2) `/health/ready/` returns 503 when DB is down. (3) `/health/` returns 503 when AI is down.

---

### Milestone 4 — Prometheus metrics (Django and AI service)

**Purpose:** Add application-level metrics that can be scraped by Prometheus and later by CloudWatch in Phase 10.10.

**Files touched:**
- `apps/api/requirements/base.txt` — add `django-prometheus>=0.3,<1.0`
- `apps/api/config/settings/base.py` — add `django_prometheus` to `INSTALLED_APPS`; add PrometheusBeforeMiddleware / PrometheusAfterMiddleware to `MIDDLEWARE`
- `apps/api/config/urls.py` — add `path("metrics/", include("django_prometheus.urls"))`
- `apps/api/apps/executions/services.py` — add counter/histogram emit calls at key transition points
- `apps/ai/requirements/base.txt` — add `prometheus-fastapi-instrumentator>=0.9,<1.0`
- `apps/ai/app/main.py` — instrument FastAPI with `Instrumentator()`

**Steps:**
1. Add `django-prometheus` and configure its middleware in `base.py` (`PrometheusBeforeMiddleware` at the beginning of `MIDDLEWARE`, `PrometheusAfterMiddleware` at the end).
2. Add `/metrics/` URL. Add `PrometheusMetricsPermission` class that checks `PROMETHEUS_METRICS_TOKEN` env var.
3. Add custom metrics counters and histograms in execution services (see section 5.3 table). Use `prometheus_client` directly.
4. Instrument AI service with `prometheus-fastapi-instrumentator`. Expose `/metrics` endpoint on the AI service.

**Verification:**
```bash
curl http://localhost:8000/metrics/ | grep "django_http_requests"
# Expect: Prometheus-format metric lines
curl http://localhost:8001/metrics
# Expect: FastAPI Prometheus metrics
# Run a test execution:
# ... trigger execution via UI ...
curl http://localhost:8000/metrics/ | grep "runbook_executions_total"
# Expect: counter > 0
```

**Human approval gate:** Confirm custom `runbook_executions_total` counter increments after running an execution.

---

### Milestone 5 — PgBouncer connection pooling

**Purpose:** Add PgBouncer as a connection proxy between Django and PostgreSQL to prevent connection exhaustion under load.

**Files touched:**
- `docker-compose.yml` — add `pgbouncer` service; update `api` `DATABASE_URL` environment reference
- `.env.example` — add `PGBOUNCER_POOL_SIZE`, `PGBOUNCER_MAX_CLIENT_CONN`
- `apps/api/config/settings/prod.py` — add `CONN_MAX_AGE = 0`

**Steps:**
1. Add `pgbouncer` service to `docker-compose.yml` as documented in section 6.6.
2. Update the `api` service to use `DATABASE_URL=postgresql://postgres:postgres@pgbouncer:5432/runbook_platform`.
3. Add `CONN_MAX_AGE = 0` to `prod.py` (PgBouncer handles pooling; Django should not keep its own persistent connections).
4. Add pool size env vars to `.env.example`.

**Verification:**
```bash
make down && make up
docker compose exec api python manage.py check
docker compose exec api python manage.py migrate
# Confirm Django can connect through PgBouncer
docker compose exec api pytest
# Confirm all tests still pass
# Check PgBouncer stats:
docker compose exec pgbouncer psql -p 5432 -U postgres -c "SHOW POOLS;" 2>/dev/null || \
  docker compose exec postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE 'pgbouncer%';"
```

**Rollback notes:** Revert `docker-compose.yml` changes and `DATABASE_URL` to point to `postgres:5432` directly.

**Human approval gate:** Run 50 concurrent API requests; verify `pg_stat_activity` shows ≤ `PGBOUNCER_POOL_SIZE` connections from PgBouncer to Postgres.

---

### Milestone 6 — Production settings hardening

**Purpose:** Complete the `prod.py` settings file with security headers, CORS lockdown, rate limiting, startup validation, and admin endpoint protection.

**Files touched:**
- `apps/api/config/settings/prod.py` — major expansion
- `apps/api/config/urls.py` — conditional admin endpoint
- `apps/api/requirements/base.txt` — add `django-ratelimit>=4.1,<5.0`
- `.env.example` — add production-relevant env vars

**Steps:**
1. Expand `prod.py` with all settings from section 7.2 (HSTS, CSP, cookie security, X-Frame-Options).
2. Add `CORS_ALLOWED_ORIGINS` from environment variable.
3. Add startup validation for required environment variables.
4. Add `RATELIMIT_ENABLE = True` in `prod.py`; add `RATELIMIT_ENABLE = False` in `dev.py` and `test.py`.
5. Apply `@ratelimit` to the login endpoint and the runbook parse endpoint.
6. Add conditional admin endpoint in `urls.py`.
7. Add production env vars to `.env.example`.

**Verification:**
```bash
DJANGO_SETTINGS_MODULE=config.settings.prod \
  DJANGO_SECRET_KEY=test-prod-key-123456789012345678901234567890 \
  DATABASE_URL=postgresql://postgres:postgres@localhost:5432/runbook_platform \
  RUNNER_REGISTRATION_TOKEN=test-token \
  DJANGO_ALLOWED_HOSTS=localhost \
  CORS_ALLOWED_ORIGINS=http://localhost:5173 \
  docker compose exec api python manage.py check --deploy
# Expect: 0 warnings, 0 errors
```

If the startup validation raises `ImproperlyConfigured` for a missing var, fix the test invocation. The `check --deploy` command must pass with zero issues.

**Rollback notes:** Revert `prod.py` to two-line version. Remove rate limit decorators. Remove `django-ratelimit` from requirements.

**Human approval gate:** `manage.py check --deploy` must pass with zero issues. This is a hard gate — do not proceed to Milestone 7 if any issue is reported.

---

### Milestone 7 — Runner SIGTERM handler and adaptive backoff

**Purpose:** Ensure the runner handles container restart signals gracefully and reduces polling load when no work is available.

**Files touched:**
- `apps/runner/runner/main.py` — add SIGTERM handler
- `apps/runner/runner/poller.py` — add shutdown event check, adaptive backoff
- `apps/runner/runner/schemas.py` — add startup validation
- `docker-compose.yml` — add `stop_grace_period: 90s` to runner service

**Steps:**
1. Add `signal.signal(signal.SIGTERM, _sigterm_handler)` in `main.py` before calling `poller.run_forever()`. Pass `_shutdown_event` to the poller.
2. In `Poller.run_forever()`: change `while True:` to `while not _shutdown_event.is_set():`. Handle clean exit on shutdown event.
3. In `Poller._poll_once()`: after claiming an execution, check `_shutdown_event.is_set()` — if set, log a warning and skip execution (let watchdog recover it).
4. Add exponential backoff for empty queue: track consecutive empty-queue responses; sleep `min(2 ** empty_count, RUNNER_POLL_INTERVAL_SECONDS)`.
5. Add startup validation in `RunnerSettings.validate()`.
6. Add `stop_grace_period: 90s` to runner service in `docker-compose.yml`.

**Verification:**
```bash
# Start a multi-step execution
# While it's running, send SIGTERM to the runner:
docker compose kill --signal=SIGTERM runner
# Check logs:
make logs | grep runner | grep -E "SIGTERM|shutdown|completed"
# Expected: "SIGTERM received", then "step N completed", then "Execution X completed with outcome: succeeded/failed"
# The execution must reach a terminal state, not get stuck in running.
# Check the execution status in Django:
docker compose exec api python manage.py shell -c "from apps.executions.models import Execution; print(Execution.objects.last().status)"
# Expected: succeeded or failed (not claimed or running)
```

**Rollback notes:** Remove signal handler, revert to `while True:`, remove backoff logic.

**Human approval gate:** SIGTERM during a running step must result in the step completing (or the watchdog recovering it), never in a stuck `running` status.

---

### Milestone 8 — Stuck execution watchdog

**Purpose:** Recover executions abandoned by crashed runners before the AWS deployment, where container restarts are routine.

**Files touched:**
- `apps/api/apps/executions/services.py` — add `recover_stuck_executions(...)`
- `apps/api/apps/executions/management/__init__.py` (new directory)
- `apps/api/apps/executions/management/commands/__init__.py`
- `apps/api/apps/executions/management/commands/check_stuck_executions.py` (new)
- `apps/api/apps/executions/tests/test_watchdog.py` (new)

**Steps:**
1. Implement `recover_stuck_executions(*, stuck_threshold_seconds: int = 300)` in `services.py` (see section 6.3 design).
2. Create `check_stuck_executions` management command.
3. Write tests:
   - `test_recover_execution_with_stale_heartbeat` — create execution in `running` status with `last_heartbeat_at = now() - 400 seconds`; call `recover_stuck_executions(threshold_seconds=300)`; assert execution is now `failed`.
   - `test_live_execution_not_recovered` — execution with heartbeat 60 seconds ago; assert not recovered.
   - `test_watchdog_idempotent` — call twice; assert no error and recovery count is 0 on second call.
   - `test_watchdog_concurrent_safety` — two concurrent calls; assert no double-recovery.

**Verification:**
```bash
docker compose exec api pytest apps/executions/tests/test_watchdog.py -v
# Manually create a stuck execution:
docker compose exec api python manage.py shell -c "
from apps.executions.models import Execution
from django.utils import timezone
from datetime import timedelta
e = Execution.objects.filter(status='running').first()
if e:
    e.last_heartbeat_at = timezone.now() - timedelta(seconds=400)
    e.save(update_fields=['last_heartbeat_at'])
    print(f'Set heartbeat stale on {e.id}')
"
docker compose exec api python manage.py check_stuck_executions --threshold-seconds=300
# Expect: "Recovered 1 stuck execution(s)"
```

**Human approval gate:** A manually-staged stuck execution is recovered by the management command without error.

---

### Milestone 9 — CI pipeline security gates

**Purpose:** Add security scanning, secret detection, migration validation, and production settings check to CI. No code changes to the platform itself.

**Files touched:**
- `.github/workflows/ci.yml` — add new jobs as specified in section 9.2

**Steps:**
1. Add `production-settings-check` job.
2. Add `migration-check` job.
3. Add `security` job (pip-audit + npm audit).
4. Add `secret-scan` job (trufflehog or similar).
5. Add `trivy-scan` job.

**Verification:**
Push a branch with these changes and open a PR. Verify all new CI jobs run and pass (assuming no existing vulnerabilities). If `pip-audit` or `npm audit` finds any vulnerabilities, address them before merging.

**Human approval gate:** All new CI jobs green on a PR before merging.

---

### Milestone 10 — Operational runbooks and load test script

**Purpose:** Write the human-readable operational runbooks for common failure scenarios and the k6 load test script.

**Files touched:**
- `docs/runbooks/runner-crash-recovery.md` (new)
- `docs/runbooks/stuck-execution-recovery.md` (new)
- `docs/runbooks/ai-service-outage.md` (new)
- `docs/runbooks/database-outage.md` (new)
- `docs/runbooks/integration-delivery-failure.md` (new)
- `scripts/load-test.js` (new) — k6 load test script

**Steps:**
1. Write each operational runbook per section 12 (Failure modes). Each runbook must include: symptom detection, immediate mitigation, root cause investigation, and recovery verification steps.
2. Write `scripts/load-test.js` that:
   - Authenticates as a test user (using a fixture credential set in the environment).
   - Calls `GET /api/v1/executions/` at 50 virtual users for 60 seconds.
   - Asserts P99 < 200ms and HTTP error rate < 0.1%.
3. Run the load test locally: `k6 run --vus 50 --duration 60s scripts/load-test.js`.

**Verification:**
```bash
k6 run --vus 50 --duration 60s scripts/load-test.js
# Expect: ✓ http_req_duration p(99) < 200ms
# Expect: ✓ http_req_failed < 0.1%
```

**Human approval gate:** Load test passes. All operational runbooks reviewed by a second person.

---

### Milestone 11 — Database CHECK constraints and index additions

**Purpose:** Enforce execution state machine validity at the database level and add missing indexes from the N+1 analysis.

**Files touched:**
- `apps/api/apps/executions/migrations/XXXX_add_status_constraints_and_indexes.py` (new migration)
- `apps/api/apps/audit/migrations/XXXX_add_audit_index.py` (new migration, if audit app is active)
- `apps/api/apps/approvals/migrations/XXXX_add_approval_index.py` (new migration, if approvals app is active)

**Steps:**
1. Create a migration that adds:
   - `CheckConstraint` on `Execution.status` (values must be in `Status.choices`)
   - `CheckConstraint` on `ExecutionStep.status` (values must be in `Status.choices`)
   - `Index(fields=["organization_id", "-occurred_at"])` on `AuditEvent` (if model exists)
   - `Index(fields=["status", "requested_at"])` on `ApprovalRequest` (if model exists)
   - `Index(fields=["organization_id", "is_active"])` on `Integration` (if model exists)
2. Before applying: run `SELECT DISTINCT status FROM executions_execution;` and `SELECT DISTINCT status FROM executions_executionstep;` to confirm no invalid values.
3. Run `python manage.py migrate` and `python manage.py showmigrations`.

**Verification:**
```bash
docker compose exec api python manage.py migrate
docker compose exec api python manage.py showmigrations
docker compose exec api pytest
# Test the constraint is enforced:
docker compose exec api python manage.py shell -c "
from apps.executions.models import Execution
try:
    e = Execution.objects.first()
    e.status = 'invalid_status'
    e.save()
    print('ERROR: constraint not enforced')
except Exception as exc:
    print(f'Constraint enforced: {exc}')
"
```

**Human approval gate:** None — verification commands suffice.

---

## 11. Testing strategy

### 11.1 Django tests

**Middleware tests (`apps/api/apps/common/tests/test_middleware.py`):**
- `test_request_id_generated_when_absent` — request without `X-Request-ID`; response includes generated UUID.
- `test_request_id_preserved_when_present` — request with `X-Request-ID: my-id`; response echoes `my-id`.
- `test_request_id_in_response_header` — confirm header name is `X-Request-ID`.

**Health endpoint tests (`apps/api/apps/common/tests/test_health.py`):**
- `test_live_always_returns_200` — assert `GET /health/live` returns HTTP 200 with no mocking required.
- `test_readiness_returns_200_when_db_healthy` — mock DB check succeeds; assert `GET /health/ready/` returns HTTP 200 and `"status": "ready"`.
- `test_readiness_returns_503_when_db_down` — mock DB check raises exception; assert `GET /health/ready/` returns HTTP 503.
- `test_readiness_returns_200_when_ai_service_down` — mock DB check succeeds, mock AI service raises `httpx.ConnectError`; assert `GET /health/ready/` returns **HTTP 200**. This is the critical ALB-decoupling test: AI service outage must not fail the readiness probe.
- `test_health_returns_200_when_all_checks_pass` — mock DB check and AI service check both succeed; assert `GET /health/` returns HTTP 200 and `"status": "healthy"`.
- `test_health_returns_503_when_db_down` — mock DB check raises exception; assert `GET /health/` returns HTTP 503 and `"database": {"status": "unhealthy"}`.
- `test_health_returns_503_when_ai_service_down` — mock AI service check raises `httpx.ConnectError`; assert `GET /health/` returns HTTP 503.

**Watchdog tests (`apps/api/apps/executions/tests/test_watchdog.py`):**
- `test_recover_execution_with_stale_heartbeat` — see Milestone 8.
- `test_live_execution_not_recovered` — execution with recent heartbeat; not recovered.
- `test_watchdog_idempotent` — two consecutive calls; no error.
- `test_watchdog_emits_audit_event` — if audit app is active, assert `AuditEvent` with `event_type="execution.watchdog_recovery"` is created.
- `test_watchdog_handles_empty_table` — no executions; returns empty list without error.

**Security header tests (`apps/api/apps/common/tests/test_security_headers.py`):**
- `test_csp_header_present_in_response` — with `DJANGO_SETTINGS_MODULE=config.settings.prod` overrides active, make any authenticated GET; assert response has `Content-Security-Policy` header containing `default-src 'self'`. This test confirms `csp.middleware.CSPMiddleware` is registered and `django-csp` is installed — without both, the header is absent.
- `test_x_frame_options_deny` — assert response has `X-Frame-Options: DENY`.
- `test_referrer_policy_present` — assert response has `Referrer-Policy: strict-origin-when-cross-origin`.

**Metrics tests (`apps/api/apps/executions/tests/test_metrics.py`):**
- `test_execution_counter_increments_on_completion` — mock `prometheus_client.Counter`; call `complete_execution`; assert counter was incremented.
- `test_step_histogram_records_duration` — mock histogram; call `update_execution_step` with `succeeded`; assert histogram observed a positive duration.
- `test_metrics_endpoint_returns_403_without_token` — set `PROMETHEUS_METRICS_ENABLED=True` and `PROMETHEUS_METRICS_TOKEN=secret`; call `GET /metrics/` without Authorization header; assert HTTP 403.
- `test_metrics_endpoint_returns_200_with_valid_token` — same setup; call with `Authorization: Bearer secret`; assert HTTP 200.
- `test_metrics_startup_fails_if_token_missing_when_enabled` — simulate prod settings with `PROMETHEUS_METRICS_ENABLED=True` and empty `PROMETHEUS_METRICS_TOKEN`; assert `ImproperlyConfigured` is raised at settings load time.

**Production settings check (CI only, not a pytest test):**
- Run `manage.py check --deploy` in CI as described in Milestone 6.

### 11.2 Runner tests

**SIGTERM tests (`apps/runner/runner/tests/test_shutdown.py`):**
- `test_poller_stops_after_shutdown_event` — create poller with mocked client and executor; set `_shutdown_event`; call `run_forever()`; assert loop exits within 1 second.
- `test_executor_completes_current_step_before_shutdown` — mock executor to simulate a slow step; set shutdown event mid-step; assert step completes before runner exits.
- `test_adaptive_backoff_increases_on_empty_queue` — mock `claim_next` to return empty 5 times; assert sleep duration increases up to the cap.
- `test_adaptive_backoff_resets_on_work_found` — after backoff reaches cap, mock one successful claim; assert backoff resets to minimum.

**Startup validation tests:**
- `test_missing_runner_registration_token_exits` — create `RunnerSettings` with empty token; assert `validate()` raises `SystemExit`.

### 11.3 AI service tests

**Health endpoint tests (`apps/ai/tests/test_health.py`):**
- `test_health_returns_ok_when_openai_reachable` — mock OpenAI client initialization success; assert `{"status": "ok"}`.
- `test_health_returns_degraded_when_openai_unreachable` — mock OpenAI client raises connection error; assert `{"status": "degraded", "checks": {"openai": "unreachable"}}`.

**Metrics tests:**
- `test_metrics_endpoint_returns_prometheus_format` — `GET /metrics`; assert `Content-Type: text/plain; version=0.0.4` and body contains metric names.

### 11.4 Frontend build tests (existing, confirmed passing)

- `npm run build` — production build must succeed with no TypeScript errors.
- `npm run lint` — ESLint must pass.
- `npx vitest run` — all existing frontend tests must pass.

No new frontend code is added in Phase 10.9. All existing frontend tests must remain green.

### 11.5 Infrastructure validation tests

**PgBouncer connection pool test:**
```bash
# Run 100 concurrent API requests
for i in $(seq 1 100); do
  curl -s "http://localhost:8000/api/v1/executions/" \
    -H "Authorization: Bearer $TEST_JWT" \
    -H "X-Organization-Id: $TEST_ORG_ID" &
done
wait
# Check Postgres connection count
docker compose exec postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
# Must be ≤ PGBOUNCER_POOL_SIZE + a small buffer
```

**Health endpoint dependency test:**
```bash
# Bring down Postgres
docker compose stop postgres
curl -o /dev/null -s -w "%{http_code}" http://localhost:8000/health/
# Must return 503
docker compose start postgres
```

### 11.6 Manual failure drills (required before Phase 10.9 sign-off)

Each drill must be performed manually by a human operator. Results recorded in the PR description.

| Drill | Steps | Expected outcome |
|---|---|---|
| **Runner crash mid-step** | Start a multi-step execution. `docker compose kill runner`. Wait 6 minutes. Run `manage.py check_stuck_executions`. | Execution transitions to `failed`. Audit event created. |
| **SIGTERM during step** | Start a multi-step execution. `docker compose kill --signal=SIGTERM runner`. Watch logs. | Runner logs "SIGTERM received". Current step completes. Runner reports outcome to Django. Execution reaches terminal state. |
| **AI service outage** | `docker compose stop ai`. Attempt to parse a runbook. | Django returns an error (not a 500). User sees a meaningful error message. |
| **PgBouncer unavailable** | `docker compose stop pgbouncer`. Make an API request. | Django returns 503. Health endpoint returns 503 with database check failed. |
| **Postgres unavailable** | `docker compose stop postgres`. Make an API request. | Django returns 503. PgBouncer detects loss and reports error. Health endpoint returns 503. |
| **Integration delivery failure** | Create a Slack integration with an invalid webhook URL. Run a failing execution. | Execution status is `failed`. `IntegrationEvent` record shows `status=failed`. Execution UI shows `failed` without indicating integration issue. |

---

## 12. Failure modes and risks

### 12.1 Runner crash mid-step

**Description:** The runner process is killed (OOM, SIGKILL, infrastructure failure) while a step is in `running` status.

**Impact:** Execution stuck in `running` or `claimed`. Runner heartbeat stops. No step completion reported.

**Detection:** `last_heartbeat_at` becomes stale. Alert: `runbook_stuck_executions_recovered_total` counter increases.

**Recovery:**
1. `check_stuck_executions` management command runs (manually or on cron).
2. Execution transitions to `failed`.
3. Operator can re-queue or investigate.

**Mitigation built in Phase 10.9:** SIGTERM handler (Milestone 7) prevents this scenario for clean container restarts. Watchdog command (Milestone 8) handles the unclean kill case.

### 12.2 AI service outage

**Description:** The AI service container crashes or is unreachable.

**Impact:** Runbook parse/enrich/summarize operations fail. No execution impact (AI service is not in the execution hot path once a workflow exists).

**Detection:** Django health endpoint returns 503 with `ai_service: unhealthy`. `ai_parse_requests_total` counter stops incrementing.

**Recovery:**
1. `docker compose restart ai` (local) or ECS task restart (production).
2. Health endpoint returns 200 once AI service is back.
3. Django automatically reconnects (httpx creates a new connection per request).

**Operational runbook:** `docs/runbooks/ai-service-outage.md`.

### 12.3 Database outage

**Description:** Postgres becomes unavailable (crash, network partition, max_connections exceeded).

**Impact:** All Django API calls fail with 500/503. PgBouncer returns connection errors to Django. Runner calls to Django internal API fail, triggering httpx retry logic.

**Detection:** Django health endpoint returns 503 with `database: unhealthy`. All `django_db_query_duration_seconds` metrics stop.

**Recovery:**
1. PgBouncer reconnects automatically when Postgres recovers.
2. Django receives fresh connections from PgBouncer without restart.
3. In-flight runner executions: if a runner lost its Django API connection mid-step, it retries (exponential backoff). If Django was down for more than 60 seconds during a step, the runner marks the step as failed after exhausting retries.

**Important:** Executions that were `claimed` or `running` during a DB outage may have stale heartbeats after recovery. Run `check_stuck_executions` after a DB outage to recover any stuck executions.

**Operational runbook:** `docs/runbooks/database-outage.md`.

### 12.4 Integration delivery failure

**Description:** A Slack, PagerDuty, or generic webhook call fails (network error, 5xx from the external service, timeout).

**Impact:** Notification not sent. Execution status and audit trail unaffected (integration dispatch is fire-and-forget).

**Detection:** `IntegrationEvent` rows with `status=failed`. Monitor `runbook_integration_dispatch_duration_seconds_count{outcome="failure"}` counter.

**Recovery:** No automatic retry in Phase 10.9. Operators can view failed `IntegrationEvent` records and manually re-trigger notifications if needed.

### 12.5 Approval timeout

**Description:** An approval gate has an `approvalTimeoutSeconds` set. No operator approves within the window.

**Impact:** Step transitions to `failed` with `timed_out` reason. Execution transitions to `failed`.

**Detection:** Audit trail shows `approval.timed_out` event. Execution status is `failed`.

**Recovery:** No automatic recovery. Operator must create a new execution from the same workflow.

**Note:** This is Phase 10.1 behavior, documented here for completeness in the failure mode register.

### 12.6 SSE stream failure (from Phase 10.8)

**Description:** The SSE connection between the browser and Django drops. This may happen due to proxy timeout, network interruption, or API server restart.

**Impact:** The UI does not receive live execution updates.

**Detection:** The browser's `useExecutionStream` hook detects 3 consecutive connection failures and activates the polling fallback. The UI shows "Polling for updates (streaming unavailable)."

**Recovery:** The polling fallback continues to work correctly. The UI shows the correct state. When the SSE connection is restored (page refresh or automatic reconnect), streaming resumes.

**Note for Phase 10.9:** The process-local event bus from Phase 10.8 must run with `--workers 1` on uvicorn. When Phase 10.10 runs multiple uvicorn workers or multiple ECS tasks, SSE requires either sticky sessions (ALB) or an external event bus (Redis pub/sub). This constraint is documented and must be addressed in Phase 10.10 before multi-worker deployment.

### 12.7 PgBouncer misconfiguration

**Description:** PgBouncer is running in session mode (incorrect) instead of transaction mode. Or PgBouncer is configured with a pool size smaller than the number of concurrent Django workers.

**Impact (session mode):** No benefit from connection pooling. Each Django worker holds a PgBouncer connection continuously, which maps to a Postgres connection. Same as without PgBouncer.

**Impact (pool too small):** Django workers queue waiting for PgBouncer connections. API latency spikes. Possible `PoolError: pool full` exceptions surfaced as 500 errors.

**Detection:** Check `PGBOUNCER_POOL_MODE` in docker-compose environment config. Run `SHOW POOLS;` on the PgBouncer admin console to see mode and wait queue depth.

**Recovery:** Update `PGBOUNCER_POOL_MODE=transaction` in docker-compose and restart PgBouncer (`docker compose restart pgbouncer`).

### 12.8 Stuck watchdog race condition

**Description:** The `check_stuck_executions` command is called twice concurrently (e.g., two cron invocations overlap). Both see the same stuck execution.

**Impact:** First invocation claims the lock via `select_for_update(skip_locked=True)` and recovers the execution. Second invocation skips the execution (already locked) and does not double-recover.

**Detection:** `runbook_stuck_executions_recovered_total` counter does not double-count.

**Recovery:** None needed — `select_for_update(skip_locked=True)` prevents double-recovery by design.

---

## 13. What NOT to do

**Do not deploy to AWS in this phase.** Phase 10.10 is the AWS deployment phase. Phase 10.9 locks in the configuration that Phase 10.10 will deploy. Deploying before hardening is complete means discovering production issues on live infrastructure.

**Do not add Celery, Redis, or any message queue.** Phase 10.9 hardens what exists. The stuck execution watchdog is a synchronous management command, not a background worker. If the system's current scale requires a background task queue, that would have surfaced during Phase 10.1–10.8. It has not.

**Do not add database read replicas.** Read replicas require Django routing changes, connection pool reconfiguration, and operational runbooks for replication lag. No measurement in Phases 10.1–10.8 has shown read throughput as a bottleneck.

**Do not rewrite the observability stack.** Do not configure Datadog, Honeycomb, New Relic, or any SaaS APM in Phase 10.9. Prometheus + structlog is the correct in-process instrumentation layer. The APM agent or CloudWatch exporter is wired up in Phase 10.10 when the cloud provider is chosen.

**Do not add distributed tracing (OpenTelemetry) in Phase 10.9.** Request ID propagation in logs provides the same cross-service correlation capability at zero infrastructure cost. OTel requires a collector, a backend (Jaeger, Zipkin, AWS X-Ray), and client instrumentation. That belongs in Phase 10.10.

**Do not add the metrics endpoint without access control.** `/metrics/` exposes internal execution counts, latency distributions, and organization-level activity. Without the `PROMETHEUS_METRICS_TOKEN` guard (or network-level restriction in Phase 10.10), any internet user can scrape operational intelligence.

**Do not use `CONN_MAX_AGE > 0` when PgBouncer is in transaction mode.** Django's persistent connections (controlled by `CONN_MAX_AGE`) require the connection to remain available between requests. PgBouncer in transaction mode may reassign the connection to a different client between Django's requests. Set `CONN_MAX_AGE = 0` in `prod.py` so Django does not attempt to reuse connections when PgBouncer is the intermediary.

**Do not add hardcoded `ALLOWED_HOSTS` or `CORS_ALLOWED_ORIGINS` in `prod.py`.** Production hosts are deployment-specific. They must come from environment variables so the same `prod.py` works for staging and production without file edits.

**Do not skip the `manage.py check --deploy` gate.** This gate exists precisely because Django knows which settings are unsafe for production. Trust it.

**Do not run the watchdog as a Django model `post_save` signal.** The watchdog is a recovery sweep over a set of stale records. Running it on every save would add overhead to every execution update and would not work (a crashed runner does not trigger `post_save`). It must be a scheduled management command.

**Do not change the workflow schema or add new domain features in Phase 10.9.** This phase is exclusively for hardening and observability. Any new feature belongs in a Phase 11+ blueprint.

---

## 14. Definition of done

Phase 10.9 is complete when all of the following are true:

- [ ] `structlog` is configured in all three Python services (Django, runner, AI). Log output is structured JSON (production) or colored text (development).
- [ ] `RequestIDMiddleware` generates `X-Request-ID` on every Django request and includes it in the response header.
- [ ] The same `X-Request-ID` appears in Django logs and AI service logs for a single parse operation. Verified via `make logs`.
- [ ] Django `GET /health/live` returns HTTP 200 unconditionally (process liveness).
- [ ] Django `GET /health/ready/` checks DB connection and migrations only. Returns HTTP 200 when database is reachable. Returns HTTP 200 even when the AI service is unreachable (ALB-decoupling invariant).
- [ ] Django `GET /health/` (dependency health) checks DB + AI service. Returns HTTP 503 when either is down. Used by ops dashboards only — never by ALB or docker-compose healthcheck.
- [ ] `docker-compose.yml` api service healthcheck uses `/health/ready/`, not `/health/`.
- [ ] Test `test_readiness_returns_200_when_ai_service_down` passes — confirms ALB does not remove API containers from rotation when AI is down.
- [ ] `GET /metrics/` returns Prometheus-format metrics including `runbook_executions_total`, `runbook_step_duration_seconds`, and standard `django_http_requests_total_*`.
- [ ] AI service `GET /metrics` returns Prometheus-format metrics.
- [ ] PgBouncer is running in docker-compose in transaction pooling mode. `pg_stat_activity` shows ≤ `PGBOUNCER_POOL_SIZE` connections from PgBouncer to Postgres when 50 concurrent API requests are in flight.
- [ ] `apps/api/config/settings/prod.py` includes HSTS, CSP, X-Frame-Options, Referrer-Policy, `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`.
- [ ] `django-csp>=3.7` is in `apps/api/requirements/base.txt` and `csp.middleware.CSPMiddleware` is registered in `MIDDLEWARE`. Verified by `test_csp_header_present_in_response` — response includes `Content-Security-Policy` header.
- [ ] If `PROMETHEUS_METRICS_ENABLED=True`, Django startup raises `ImproperlyConfigured` when `PROMETHEUS_METRICS_TOKEN` is empty. Metrics endpoint fails-closed, not fails-open.
- [ ] `GET /metrics/` returns HTTP 403 without a valid `Authorization: Bearer` token when `PROMETHEUS_METRICS_ENABLED=True`.
- [ ] `manage.py check --deploy` with `DJANGO_SETTINGS_MODULE=config.settings.prod` reports zero issues. Confirmed in CI.
- [ ] `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` in `prod.py` are read from environment variables — no hardcoded values.
- [ ] Startup validation in `prod.py` raises `ImproperlyConfigured` if `DJANGO_SECRET_KEY`, `DATABASE_URL`, or `RUNNER_REGISTRATION_TOKEN` is missing or is `"change-me"`.
- [ ] Runner startup validation raises `SystemExit(1)` if `RUNNER_REGISTRATION_TOKEN` is not set or is `"change-me"`.
- [ ] The runner handles `SIGTERM` by completing the current step (or waiting up to 60 seconds) before exiting. Verified via manual drill.
- [ ] Adaptive polling backoff in `Poller`: empty queue → sleep doubles up to cap; work found → sleep resets. Verified by runner tests.
- [ ] `recover_stuck_executions(stuck_threshold_seconds=300)` in `services.py` recovers executions whose heartbeat is stale. Uses `select_for_update(skip_locked=True)`.
- [ ] `check_stuck_executions` management command exists, accepts `--threshold-seconds`, and reports recovered count.
- [ ] All watchdog tests pass (no recovery of live executions, idempotent, concurrent-safe).
- [ ] `docker-compose.yml` has `stop_grace_period: 90s` and `stop_signal: SIGTERM` on the runner service.
- [ ] `docker-compose.yml` has a healthcheck on the `api` service and `ai` service.
- [ ] CI pipeline includes: `production-settings-check`, `migration-check`, `security` (pip-audit + npm audit), `secret-scan`, and `trivy-scan` jobs. All pass on the phase-10.9 branch.
- [ ] All existing pytest tests (Django, runner, AI) pass after all milestones are complete.
- [ ] Load test via k6 at 50 VUs / 60 seconds against `GET /api/v1/executions/` passes: P99 < 200ms, HTTP error rate < 0.1%.
- [ ] All six manual failure drills completed successfully (see section 11.6 table).
- [ ] Five operational runbooks exist in `docs/runbooks/`: runner crash recovery, stuck execution recovery, AI service outage, database outage, integration delivery failure.
- [ ] `scripts/load-test.js` k6 script exists and is runnable.
- [ ] Database CHECK constraints added for `Execution.status` and `ExecutionStep.status`. New indexes added on `AuditEvent`, `ApprovalRequest`, and `Integration` models.
- [ ] No secret appears in any committed file. `.env.example` contains only placeholder values.
- [ ] The process-local SSE event bus constraint (uvicorn `--workers 1`) is explicitly documented in a code comment in the Dockerfile `CMD` and in a Phase 10.10 known constraint list.

**Gate for moving from Phase 10.9 → Phase 10.10:**
- All checkboxes above are complete.
- P99 API latency < 200ms under 50 concurrent users: load test passes.
- Graceful runner shutdown completes without stuck executions: manual drill passes.
- All secrets are read from environment variables, not hardcoded: code review confirms.
- `manage.py check --deploy` passes with zero issues: CI confirms.

---

## Summary

**File created:** `docs/blueprints/phase-10-09-production-hardening-blueprint.md`

**Major sections included:**
1. Purpose and sequencing rationale — why hardening precedes AWS deployment; what is missing after phases 10.1–10.8 (observed from current codebase)
2. Current-state inspection checklist — 20+ files/commands to verify before writing code
3. Architecture invariants — 8 platform invariants mapped to hardening-specific consequences, plus hardening-specific constraints (no hardcoded secrets, PgBouncer in transaction mode, SIGTERM in runner only)
4. Implementation scope by repo area — 9 areas with specific files touched: settings, common middleware, executions services, runner main/poller/client/schemas, AI service health/metrics, docker-compose, requirements, CI pipeline
5. Observability plan — structured logging format for all three services, request ID propagation flow, Prometheus metrics table (6 custom Django metrics, 4 AI metrics), traces deferred to Phase 10.10 with rationale
6. Reliability plan — timeout standards table, retry policy per call direction, watchdog design (select_for_update(skip_locked=True), 300-second threshold), detailed health check behavior, graceful shutdown with 60-second hard timeout, PgBouncer configuration
7. Security hardening plan — env validation, security headers (HSTS/CSP/XFO), CORS lockdown, rate limiting, CSRF, secrets management, dependency scanning, admin endpoint protection
8. Data integrity and recovery plan — CHECK constraints on status enums, watchdog durability guarantees, N+1 query analysis, migration safety for new constraints
9. CI/CD validation gates — 5 new CI jobs (production-settings-check, migration-check, security, secret-scan, trivy-scan), branch protection rules, local load test gate
10. 11 ordered milestones — each with purpose, files touched, numbered steps, verification commands, rollback notes, and human approval gate
11. Testing strategy — 6 categories: Django (middleware, health, watchdog, metrics), runner (SIGTERM, backoff, startup validation), AI service (health, metrics), frontend build (unchanged), infrastructure validation, manual failure drills (6-drill table)
12. Failure modes and risks — 8 failure modes with description, impact, detection, recovery, and cross-reference to mitigations
13. What NOT to do — 10 explicit prohibitions with rationale
14. Definition of done — 27 checkboxes + explicit gate conditions for 10.9 → 10.10 transition

**Key assumptions:**
- Phases 10.1–10.8 are complete and all their definitions of done are satisfied before Phase 10.9 begins.
- Phase 10.8 has already switched the API server from `manage.py runserver` to `uvicorn config.asgi:application`. If not, Milestone 1 of Phase 10.8 must be completed first.
- The system is not publicly deployed during Phase 10.9 (local Docker only). Security hardening in `prod.py` is validated in CI (`check --deploy`) but not exercised in a live public environment.
- The AI service health check avoids calling a real LLM completion (cost avoidance). It uses OpenAI client initialization or a metadata API call.
- `structlog` integration with Django's `LOGGING` dict uses `structlog.stdlib.ProcessorFormatter` — the standard approach that preserves compatibility with third-party packages that use `logging.getLogger`.
- uvicorn runs with `--workers 1` (established in Phase 10.8). The process-local SSE event bus constraint is a known limitation documented for Phase 10.10.
- PgBouncer is run as a Docker sidecar in transaction pooling mode. When Phase 10.10 deploys to AWS, PgBouncer may be replaced by RDS Proxy or retained as an ECS sidecar container — both are valid; this blueprint does not prescribe the AWS implementation.
- The watchdog threshold of 300 seconds (5 minutes, 30 missed heartbeats at 10-second intervals) is the correct balance between false positives (recovering live executions) and recovery speed. Adjust via `WATCHDOG_STUCK_THRESHOLD_SECONDS` env var.
