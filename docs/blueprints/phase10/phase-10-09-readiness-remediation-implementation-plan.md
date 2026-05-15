# Phase 10.9 Readiness Remediation Implementation Plan

| Field | Value |
| --- | --- |
| Plan date | 2026-04-30 |
| Status | M1 split health, M2 exposure controls, and M5 Compose/PgBouncer runtime contract have implementation changes in the worktree; M3/M4 also have in-progress worktree changes; later milestones remain planned |
| Source audit | `docs/blueprints/phase-10-09-production-hardening-implementation-status.md` |
| Primary blueprint | `docs/blueprints/phase-10-09-production-hardening-blueprint.md` |
| Downstream gate | `docs/blueprints/phase-10-10-aws-deployment-workflows-blueprint.md` |
| Verdict addressed | Phase 10.9 is not ready for Phase 10.10 until every blocking item below is fixed and verified |

## 1. Objective

Close every Phase 10.9 readiness audit gap without changing the platform architecture:

- Django remains the control plane and the only service that owns persistence.
- Runner, frontend, and AI continue to call Django APIs only where domain state is involved.
- FastAPI AI remains advisory and stateless.
- Phase 10.10 must receive an AWS-ready local contract: split health endpoints, PgBouncer, protected metrics, admin gating, bounded retries, correlated logs, load evidence, and operator runbooks.

The plan is intentionally milestone-based. Each milestone must be small enough to review, test, and roll back independently. Do not begin Phase 10.10 until the final evidence record is complete.

## 2. Non-Negotiable Safety Rules

1. Do not use `/health/` for ALB or docker-compose API health checks. Only `/health/ready/` is ALB-facing.
2. Do not let AI service degradation remove healthy Django API containers from rotation.
3. Metrics auth must fail closed when `PROMETHEUS_METRICS_ENABLED=true`.
4. Production Django admin must be disabled unless `DJANGO_ADMIN_ENABLED=true`.
5. PgBouncer must run in transaction mode, and Django persistent connections must remain disabled when using it.
6. Runner retry behavior must not duplicate unsafe state transitions. Retry only bounded, explicitly allowed failures and preserve claim-token/idempotency protections.
7. Operational docs and verification evidence must be updated in the same remediation series as code changes.
8. Every audit item must map to a test, smoke check, manual drill, or documented operator step.

## 3. Issue-To-Fix Traceability

| Audit issue | Fix milestone | Acceptance signal |
| --- | --- | --- |
| Missing `/health/live` and `/health/ready/` | M1 | Tests and curl prove live, ready, and detailed health contracts |
| Readiness must check DB and migrations only | M1 | AI down + DB up returns 200 from `/health/ready/`; DB down returns 503 |
| `/health/` still coupled to DB + AI | M1 | `/health/` remains dependency-health only and returns 503 when AI is down |
| Compose API and AI healthchecks absent | M5 | `docker compose ps` shows API/AI health based on correct endpoints |
| Runner `stop_signal` and `stop_grace_period` absent | M5 | Compose config includes `SIGTERM` and `90s`; drill recorded |
| PgBouncer absent; API points to Postgres | M5 | API default `DATABASE_URL` points to PgBouncer; pool verification recorded |
| `.env.example` missing PgBouncer/watchdog values | M5 | Env example includes pool and watchdog settings |
| `/metrics/` has no bearer-token guard | M2 | 403 without/invalid token and 200 with valid token when enabled |
| Django admin mounted unconditionally | M2 | `/admin/` absent when disabled; present only when enabled |
| Rate-limit dependency configured but unused | M2 | Login and parse/create endpoints have scoped rate limits and tests |
| Django request context not bound into logs | M3 | Request-completed log includes request ID, method, path, status, duration |
| Runner logging not aligned with structured logging standard | M3/M7 | Runner logs include runner ID and request ID in structured fields |
| AI logging has no request ID context | M3 | AI middleware binds or creates request ID and echoes it |
| Django AI client does not pass `X-Request-ID` | M3 | AI client tests assert outbound header on parse/enrich/summarize |
| AI `/health` static and blind to OpenAI degradation | M4 | AI health reports `ok`/`degraded` and OpenAI configured/reachable state |
| Runner timeouts/retries too broad and inconsistent | M7 | Client tests cover connect/read/write timeout config and 1s/2s/4s retries |
| Expired approvals not swept by watchdog | M6 | Management command recovers expired approvals and blocked executions |
| Watchdog audit/log taxonomy incomplete | M6 | Explicit watchdog recovery event/log fields exist; existing events preserved if useful |
| Missing `scripts/load-test.js` | M8 | k6 script committed and documented |
| Required outage runbooks missing | M8 | Required four runbooks exist and are linked from runbook README |
| Missing load-test/manual-drill evidence | M10 | `docs/verification/phase-10-09-readiness-record.md` completed |
| Metrics names drift from blueprint | M9 | Add blueprint-compatible aliases and preserve existing metric names |
| Missing approval/integration/artifact/watchdog metrics | M9 | Tests or smoke checks verify new counters/histograms are registered |
| Partial migration/index drift | M9 | Audit indexes; add missing safe migrations or document existing coverage |
| Definition of done contradicts blueprint health contract | M8 | DoD updated to require split health before Phase 10.10 |
| Branch-protection evidence not reviewed | M10 | Manual GitHub settings checklist recorded |
| SSE process-local production constraint not in handoff | M8/M10 | Phase 10.10 handoff notes include scaling constraint |

## 4. Milestones

### M0 - Preflight Baseline

Purpose: freeze the current state before remediation so failures can be attributed to a specific milestone.

Code changes: none.

Actions:

- Confirm the working tree and preserve the untracked readiness audit file.
- Run the existing focused hardening tests if the local Docker stack is already available.
- Record any existing failures before editing.

Verification:

```sh
git status --short
make lint
make test-api
make test-runner
make test-web
docker compose exec ai pytest tests/
```

Rollback: none; this is read-only.

### M1 - Split Health, Readiness, And Migration Checks

Purpose: satisfy the ALB health invariant before any AWS work.

Files:

- `apps/api/apps/common/health.py`
- `apps/api/config/urls.py`
- `apps/api/apps/common/tests/test_health.py`
- `docs/runbooks/phase-10-09-definition-of-done.md`

Implementation:

- Add `live_view` at `GET /health/live`, no I/O, always 200 when process responds.
- Replace the current DB helper with a latency-recording database probe that runs `connection.ensure_connection()` and `SELECT 1`.
- Add migration-current verification to readiness with `call_command("migrate", "--check")`.
- Add `readiness_view` at `GET /health/ready/` that checks only DB plus migrations.
- Keep `detailed_health_view` at `GET /health/` for operator dependency health: DB plus AI.
- Ensure detailed health is never referenced by Compose or future ALB instructions.
- Update the Phase 10.9 definition of done to remove the current contradictory "Phase 10.10 should add readiness later" language.

Tests:

- `/health/live` returns 200 and does not call DB or AI helpers.
- `/health/ready/` returns 200 when DB and migrations are current.
- `/health/ready/` returns 503 when DB check fails.
- `/health/ready/` returns 503 when migration check fails.
- `/health/ready/` returns 200 when AI health fails.
- `/health/` returns 503 when AI fails.

Rollback:

- Revert `urls.py` to only expose `/health/`.
- Revert `health.py` changes.
- Do not proceed to M5 or Phase 10.10 while rolled back.

### M2 - Metrics Auth, Admin Gate, And Rate Limits

Purpose: close the direct production exposure risks before expanding monitoring or AWS routes.

Files:

- `apps/api/config/urls.py`
- `apps/api/apps/common/metrics.py` or new `apps/api/apps/common/metrics_views.py`
- `apps/api/apps/common/tests/test_metrics.py`
- `apps/api/config/tests/test_prod_settings.py`
- `apps/api/apps/users/views.py`
- `apps/api/apps/users/tests/test_api.py`
- `apps/api/apps/workflows/views.py`
- `apps/api/apps/workflows/tests/test_api_contracts.py`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/prod.py`

Implementation:

- Wrap `ExportToDjangoView` in a local view that enforces metrics auth.
- Behavior:
  - If `PROMETHEUS_METRICS_ENABLED=false`, keep local/dev behavior compatible with current tests unless the team chooses fail-closed everywhere.
  - If `PROMETHEUS_METRICS_ENABLED=true`, require `Authorization: Bearer <PROMETHEUS_METRICS_TOKEN>`.
  - Return 403 for missing, malformed, or wrong tokens.
  - Startup must still fail if metrics are enabled without a token.
- Enforce `DJANGO_ADMIN_ENABLED` in `config/urls.py` by conditionally adding `path("admin/", admin.site.urls)`.
- Apply `django-ratelimit` where it matters first:
  - `LoginView.post`: IP-based limit.
  - `RefreshView.post`: IP-based limit.
  - `WorkflowViewSet.create`: user-based limit because it is the AI parse path.
- Keep internal runner endpoints exempt.
- Add settings names for limit strings so production can tune without code changes.

Tests:

- Metrics disabled/local default still returns Prometheus text if that compatibility path is preserved.
- Metrics enabled with no token is covered by prod settings startup tests.
- Metrics enabled with missing/wrong token returns 403.
- Metrics enabled with correct bearer token returns 200.
- Admin route is absent when `DJANGO_ADMIN_ENABLED=false`.
- Admin route exists when `DJANGO_ADMIN_ENABLED=true`.
- Login and workflow create rate limits return 429 after threshold under enabled settings.
- Rate limits remain disabled in `test.py` unless explicitly overridden by a test.

Rollback:

- Restore direct `ExportToDjangoView` only in local/dev if needed.
- Never deploy production with the metrics wrapper removed.
- If rate limits cause false positives, disable via setting while keeping the decorator code.

### M3 - End-To-End Structured Logging And Request ID Correlation

Purpose: make one user/API operation traceable across Django, AI, and runner logs before CloudWatch wiring.

Files:

- `apps/api/apps/common/middleware.py`
- `apps/api/config/settings/base.py`
- `apps/api/apps/common/tests/test_middleware.py`
- `apps/api/apps/runbooks/ai_client.py`
- `apps/api/apps/runbooks/tests/test_ai_client.py`
- `apps/api/apps/workflows/internal_clients.py`
- `apps/api/apps/workflows/tests/test_internal_clients.py`
- `apps/ai/requirements/base.txt`
- `apps/ai/app/main.py`
- `apps/ai/tests/test_metrics.py` or new request ID tests
- `apps/runner/runner/log_streamer.py`
- `apps/runner/runner/main.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/tests/test_client.py`

Implementation:

- Update `RequestIDMiddleware` to:
  - clear previous structlog context at request start;
  - bind `request_id`, method, and path;
  - emit one completion log with `request_id`, method, path, status code, and duration in milliseconds;
  - echo `X-Request-ID`.
- Ensure exception paths still emit the completion log in `finally` or through equivalent middleware behavior.
- Add a shared helper to build AI outbound headers from the request ID already passed into service/client calls.
- Pass `X-Request-ID` on parse, enrich, and summarize calls.
- Add FastAPI middleware that reads or creates `X-Request-ID`, binds it to structlog context, echoes it, and logs request completion.
- Add `structlog` to the AI service if absent.
- Align runner logging with structured fields for `runner_id`, `runner_version`, and per-request `request_id`.
- Keep existing human-readable local logs acceptable if they are still structured fields; production must be JSON-compatible.

Tests:

- Django response includes `X-Request-ID` for generated and inbound IDs.
- Django request-completed log contains required fields.
- AI response includes `X-Request-ID` and logs contain the same ID.
- AI client mock transport receives `X-Request-ID` on all AI calls.
- Runner client still sends a fresh `X-Request-ID` per request and includes `X-Runner-ID`.

Rollback:

- Keep request header propagation even if logging format is temporarily reverted.
- If structlog formatting breaks local readability, switch renderer by setting while preserving bound fields.

### M4 - AI Health Dependency Visibility

Purpose: make AI health truthful without making token-consuming LLM calls.

Files:

- `apps/ai/app/api/routes/health.py`
- `apps/ai/app/core/config.py`
- `apps/ai/tests/test_health.py`
- `docs/architecture/ai-service-boundary.md`
- `docs/runbooks/ai-service-outage.md` from M8 may reference this behavior

Implementation:

- Return a stable health payload:

```json
{
  "status": "ok",
  "service": "ai",
  "checks": {
    "openai": {
      "status": "ok|degraded|not_configured|disabled",
      "mode": "disabled|configured|connectivity_checked",
      "detail": "..."
    }
  }
}
```

- If LLM parsing is disabled, report OpenAI as `disabled` and keep overall status `ok`.
- If LLM parsing is enabled but `OPENAI_API_KEY` or model is missing, report `degraded`.
- If a lightweight connectivity check is implemented, use a non-generative endpoint with a short timeout and cache the result briefly to avoid health-check amplification.
- Do not make chat/completion/generation calls from health.
- Keep HTTP 200 for AI service process health; dependency degradation is informational for Django detailed health and operator dashboards.

Tests:

- Disabled parser returns overall `ok` with OpenAI `disabled`.
- Enabled parser without required config returns overall `degraded`.
- Connectivity exceptions return `degraded` without leaking secrets.
- Health never calls generation/parsing code.

Rollback:

- Return to static health only for local development if the connectivity check is unstable, but keep config validation and degraded reporting for production.

### M5 - Compose, PgBouncer, And Local Runtime Contract

Purpose: make local orchestration match the Phase 10.10 AWS handoff contract.

Implementation note, 2026-04-30:

- `docker-compose.yml` now defines PgBouncer, API/AI healthchecks, and runner
  SIGTERM/grace-period settings.
- API's tracked Compose default now routes `DATABASE_URL` through PgBouncer.
- The local untracked `.env` file can still override that default for
  troubleshooting; update or unset `DATABASE_URL` there before recording final
  M5 evidence.
- Docker Hub did not resolve the requested `bitnami/pgbouncer` tag during local
  validation, so the Compose service uses the matching pullable
  `bitnamilegacy/pgbouncer:1.24.1-debian-12-r10` image.

Files:

- `docker-compose.yml`
- `.env.example`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/prod.py`
- `docs/runbooks/production-hardening-local-drills.md`
- `docs/runbooks/phase-10-09-hardening-checks.md`

Implementation:

- Add `pgbouncer` service using `bitnami/pgbouncer:1.23` or a pinned later compatible patch version.
- Configure PgBouncer:
  - transaction pool mode;
  - `PGBOUNCER_POOL_SIZE`;
  - `PGBOUNCER_MAX_CLIENT_CONN`;
  - dependency on healthy Postgres.
- Change API default `DATABASE_URL` in Compose to `postgresql://postgres:postgres@pgbouncer:5432/runbook_platform`.
- Keep direct Postgres override possible via explicit `DATABASE_URL` for troubleshooting.
- Add API healthcheck against `http://localhost:8000/health/ready/` inside the API container.
- Add AI healthcheck against `http://localhost:8001/health`.
- Add runner `stop_signal: SIGTERM` and `stop_grace_period: 90s`.
- Add `.env.example` entries for PgBouncer and `WATCHDOG_STUCK_THRESHOLD_SECONDS`.
- Confirm no app code uses Postgres features that PgBouncer transaction pooling breaks, especially `LISTEN/NOTIFY` and session-scoped advisory locks.

Tests:

- `docker compose config` validates.
- `docker compose up -d` reaches healthy Postgres, PgBouncer, API, and AI.
- API can run migrations through PgBouncer.
- `SHOW POOLS;` or equivalent PgBouncer check verifies pool settings.
- `/health/ready/` still returns 200 with AI stopped.
- Runner SIGTERM drill is recorded.

Rollback:

- Allow one-command fallback by setting `DATABASE_URL` to direct Postgres.
- Do not remove PgBouncer service once Phase 10.10 starts using the contract.

### M6 - Watchdog Expired Approval Recovery And Audit Taxonomy

Purpose: ensure pending approval timeouts are resolved by the scheduled watchdog, not only by future reads.

Files:

- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_services.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/management/commands/check_stuck_executions.py`
- `apps/api/apps/executions/tests/test_watchdog.py`
- `docs/runbooks/stuck-execution-recovery.md`

Implementation:

- Add `recover_expired_approvals(now=None, batch_size=...)`.
- Use `transaction.atomic()` and `select_for_update(skip_locked=True)` where supported.
- Select pending approvals where `expires_at <= now`.
- For each approval:
  - transition approval to timed out using existing model fields and status constants;
  - create an `ApprovalDecision` with system source if that is the established decision record;
  - emit `approval.timeout`;
  - fail the blocked execution and waiting step through service-layer state transitions;
  - emit `execution.approval_timeout`;
  - emit or add metadata for explicit watchdog recovery, preserving existing `execution.failed` semantics if current consumers depend on them.
- Update `check_stuck_executions` to run both stale execution recovery and expired approval recovery.
- Add structured logs with `approval_id`, `execution_id`, `step_id`, and `expires_at`.

Tests:

- Expired pending approval becomes timed out.
- Associated execution fails exactly once.
- Associated waiting step fails or reaches the established terminal failure state.
- Audit events are emitted.
- Running command twice is idempotent.
- Non-expired approvals are untouched.
- Already-decided approvals are untouched.
- Concurrent calls do not double-resolve the same approval.

Rollback:

- Disable expired approval sweep by feature flag or command option if a production data issue is found.
- Keep stale execution recovery intact.

### M7 - Runner Timeout And Retry Standard

Purpose: make runner-to-Django behavior bounded, observable, and consistent.

Files:

- `apps/runner/runner/client.py`
- `apps/runner/runner/poller.py`
- `apps/runner/runner/artifact_uploader.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/tests/test_client.py`
- `apps/runner/runner/tests/test_poller.py`
- `apps/runner/runner/tests/test_executor.py`
- `docs/runner/execution-loop.md`

Implementation:

- Replace `httpx.Timeout(10.0)` with explicit connect/read/write/pool settings.
- Use 1s/2s/4s retry delays for network errors and HTTP 502/503/504 where retry is safe.
- Do not retry 400/401/403/404/409 responses.
- For state-transition calls, rely on existing claim-token and idempotency checks; add tests for duplicate-safe retry behavior where needed.
- Keep artifact upload timeout intentionally larger, but document the exact deviation and why file transfer needs different read/write limits.
- Ensure every retry log includes method/path, attempt, delay, exception/status, runner ID, and request ID.

Tests:

- Claim-next retries on transport error and 503 with bounded delays.
- Heartbeat/update/start/approval-status/complete use the same timeout object.
- 409 and other domain conflicts are not retried.
- Artifact upload uses documented upload-specific timeout and existing retry behavior.
- Shutdown event can interrupt retry sleep.

Rollback:

- Feature-flag retry wrapper off while preserving explicit timeouts.
- Keep the poller claim-next backoff as a fallback.

### M8 - Runbooks, Definition Of Done, And Handoff Documentation

Purpose: close operator-readiness gaps in the same series as code remediation.

Files:

- `docs/runbooks/runner-crash-recovery.md`
- `docs/runbooks/ai-service-outage.md`
- `docs/runbooks/database-outage.md`
- `docs/runbooks/integration-delivery-failure.md`
- `docs/runbooks/README.md`
- `docs/runbooks/phase-10-09-definition-of-done.md`
- `docs/runbooks/production-hardening-local-drills.md`
- `docs/runbooks/structured-logging-and-request-ids.md`
- `docs/blueprints/phase-10-10-aws-deployment-workflows-blueprint.md` or a linked handoff note

Implementation:

- Add the four required failure-mode runbooks with:
  - symptoms;
  - immediate checks;
  - safe mitigations;
  - recovery steps;
  - verification;
  - rollback/escalation;
  - evidence to capture.
- Update existing aggregate drill docs to link to the specific runbooks.
- Update the definition of done so Phase 10.9 requires split health, PgBouncer, metrics auth, admin gating, load evidence, and manual drills before Phase 10.10.
- Add CloudWatch Logs Insights query examples after log fields are finalized.
- Add log redaction guidance for exception messages and external response bodies.
- Add the SSE process-local production constraint to Phase 10.10 handoff notes: do not scale API tasks/workers for SSE-dependent behavior until a supported event transport or explicit single-task tradeoff is chosen.

Verification:

- All runbooks are linked from `docs/runbooks/README.md`.
- Every manual drill in the readiness audit has a documented procedure.
- DoD no longer contradicts the health blueprint.

Rollback:

- Documentation-only; revert individual runbook edits if inaccurate.

### M9 - Metrics, Indexes, And Blueprint Alignment Follow-Ups

Purpose: resolve highlighted drift that is not the first production blocker but would otherwise become dashboard and scale debt in Phase 10.10.

Files:

- `apps/api/apps/common/metrics.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/integrations/services.py`
- `apps/api/apps/artifacts/services.py`
- `apps/ai/app/main.py`
- relevant metrics tests
- relevant model migrations if indexes are missing

Implementation:

- Add blueprint-compatible metric aliases while preserving current metric names:
  - `runbook_executions_total`
  - `runbook_step_duration_seconds`
  - approval latency metric
  - integration dispatch duration metric
  - artifact upload bytes metric
  - stuck execution recovery counter
  - `ai_parse_request_duration_seconds`
  - `ai_enrich_request_duration_seconds`
  - `ai_summarize_request_duration_seconds`
  - `ai_llm_tokens_used_total` if token data exists; otherwise register only when token accounting exists and document deferred status.
- Audit indexes for:
  - audit events by `(organization_id, occurred_at DESC)`;
  - approvals by `(status, requested_at)`;
  - integrations by `(organization_id, is_active)`.
- Add safe migrations for missing indexes, using normal local migrations now and documenting `CONCURRENTLY` expectations for AWS production if tables are large.

Tests:

- Metrics registration tests prove old and new metric names can be scraped.
- Service tests assert important counters/histograms move on representative paths.
- `makemigrations --check --dry-run` passes after migrations are committed.
- `migrate --check` passes.

Rollback:

- Remove aliases only if they break Prometheus registration.
- Index migrations can be reversed before production data exists; after production exists, require a separate rollback plan.

### M10 - Load Gate, Manual Drills, And Final Evidence

Purpose: produce the durable proof required to unlock Phase 10.10.

Files:

- `scripts/load-test.js`
- `docs/verification/phase-10-09-readiness-record.md`
- `docs/blueprints/phase-10-09-production-hardening-implementation-status.md`

Implementation:

- Add k6 script for 50 VU / 60 seconds.
- The load test should use seeded local data and a valid JWT without committing credentials.
- Include thresholds:
  - no HTTP 5xx;
  - error rate within blueprint target;
  - P99 latency under the Phase 10.9 target;
  - DB connection count remains within PgBouncer pool expectations.
- Create a readiness record capturing:
  - commit SHA;
  - environment;
  - commands run;
  - test outputs summarized;
  - load-test result;
  - PgBouncer pool evidence;
  - manual drill evidence;
  - branch-protection checklist status;
  - residual risks accepted or explicitly rejected.
- Update the implementation-status audit from "not ready" to a final remediated status only after all gates pass.

Required manual drills to record:

- Runner SIGTERM during execution.
- Stale heartbeat recovery.
- Expired approval recovery.
- AI outage with `/health/ready/` still 200 and `/health/` 503.
- Postgres outage with `/health/ready/` 503.
- PgBouncer outage behavior and recovery.
- Integration delivery failure.
- Metrics unauthorized/authorized scrape.
- Request ID trace across Django and AI, plus runner-to-Django internal call.
- Missing production env var startup failure.

Verification:

```sh
make lint
make test-api
make test-runner
make test-web
docker compose exec ai pytest tests/
make check-prod
make check-migrations
make security-scan
make hardening-check
k6 run --vus 50 --duration 60s scripts/load-test.js
```

Rollback:

- If load or drills fail, do not edit the evidence to look successful. Record the failure, open a follow-up remediation item, and keep Phase 10.10 blocked.

## 5. Recommended Implementation Order

1. M0 baseline.
2. M1 health split. This removes the highest-risk AWS blocker first.
3. M2 metrics/admin/rate-limit exposure controls.
4. M3 request ID and structured logging correlation.
5. M4 AI health truthfulness.
6. M5 PgBouncer and Compose runtime contract.
7. M6 watchdog expired approval recovery.
8. M7 runner timeout/retry standard.
9. M8 runbooks and DoD cleanup.
10. M9 metric/index alignment.
11. M10 load, drills, evidence, and final audit status update.

Do not combine M1, M2, M5, M6, or M7 in one large patch. Those milestones touch production routing, security exposure, runtime topology, state recovery, and runner behavior respectively.

## 6. Approval Gates

Implementation must pause for review after:

- M1, because ALB health behavior changes.
- M2, because production exposure behavior changes.
- M5, because local database topology changes.
- M6, because watchdog behavior can fail executions.
- M7, because retries affect state-transition calls.
- M10, before Phase 10.10 starts.

Approval should confirm tests, smoke checks, rollback notes, and documentation were completed for the milestone.

## 7. Final Phase 10.10 Unlock Criteria

Phase 10.10 may start only when all of the following are true:

- `/health/live`, `/health/ready/`, and `/health/` exist and match the blueprint contract.
- API and future ALB health checks use `/health/ready/`, never `/health/`.
- PgBouncer is active in local Compose and verified.
- Metrics require a valid bearer token when enabled.
- Django admin is disabled in production by default.
- Login and AI parse/create flows have rate limits.
- Django, runner, and AI logs carry request/runner correlation fields.
- Django passes request IDs to AI.
- AI health reports dependency degradation truthfully.
- Watchdog recovers stale executions and expired approvals.
- Runner retries and timeouts are bounded and tested.
- Required runbooks exist.
- k6 load test evidence exists.
- Manual drill evidence exists.
- Full lint, tests, security, migration, production-check, and hardening gates pass.
- The final implementation-status document says Phase 10.9 is ready, with residual risks limited to explicit Phase 10.10 infrastructure work.
