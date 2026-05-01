# Phase 10.9 Definition Of Done

Phase 10.9 is complete when the production-hardening implementation, local
drills, and verification gates below pass without introducing new platform
features.

## Final Checklist

| Area | Done when |
| --- | --- |
| Security headers | Production settings enable HTTPS redirect, HSTS, secure cookies, frame denial, referrer policy, content type nosniff, and CSP through registered middleware. |
| Prod settings validation | `config.settings.prod` fails startup when required production env vars are missing or placeholder values. |
| No hardcoded secrets | Secrets are read from environment variables; `.env.example` contains placeholders only; secret scanning passes. |
| Health endpoint behavior | `/health/live` returns process liveness, `/health/ready/` checks database and migrations only for ALB/docker readiness, and `/health/` remains dependency health for operators with database and AI reachability. |
| PgBouncer runtime contract | Local Compose routes Django through PgBouncer in transaction mode, Django persistent connections remain disabled for PgBouncer, and pool behavior is verified before AWS handoff. |
| Metrics exposure control | Metrics endpoints exist and production metrics exposure is protected by bearer token, private network path, or both. Metrics auth must fail closed when production metrics are enabled. |
| Admin exposure control | Django admin is disabled in production unless `DJANGO_ADMIN_ENABLED=true` is explicitly set. |
| Watchdog behavior | `check_stuck_executions` recovers stale `claimed` and `running` executions, fails running steps, emits audit metadata, and is idempotent. |
| Structured logs | API, runner, and AI use the Phase 10.9 logging setup; request and runner identifiers are available for correlation. |
| Metrics | `/metrics/` exists for Django and `/metrics/` exists for AI; execution counters and latency histograms are registered. |
| CI gates | CI includes web build/lint/tests, Python lint/tests, production deploy check, migration check, dependency audits, secret scan, and container/filesystem scan. |
| Load evidence | `scripts/load-test.js` exists, the 50 VU / 60 second k6 gate is run, and P99 latency, 5xx rate, HTTP error rate, and PgBouncer pool evidence are recorded. |
| Operator runbooks | Runner crash, stuck execution, AI outage, database outage, and integration delivery failure runbooks exist and are linked from the runbook index. |
| All tests pass | API tests, runner tests, web build, and web lint pass locally before Phase 10.10 begins. |

## Required Manual Drills

Run and record results for:

- runner `SIGTERM` during execution;
- stale heartbeat recovery;
- expired approval recovery;
- AI outage where `/health/ready/` remains `200` and `/health/` returns `503`;
- database outage where `/health/ready/` returns `503`;
- PgBouncer outage behavior and recovery;
- integration delivery failure;
- metrics unauthorized and authorized scrape checks;
- missing production env var;
- request ID trace across Django and AI, plus runner-to-Django internal calls;
- k6 load test with 50 VUs for 60 seconds.

The drill procedures live in
[production-hardening-local-drills.md](production-hardening-local-drills.md).

## Required Local Commands

Run these exact commands for Step 9 verification:

```sh
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec runner pytest
cd apps/web && npm run build
cd apps/web && npm run lint
```

Run the hardening and load gates before Phase 10.10:

```sh
make hardening-check
k6 run --vus 50 --duration 60s scripts/load-test.js
```

## Remaining Risks Before Phase 10.10

- Phase 10.10 ALB and container health checks must use `/health/ready/`, never
  `/health/`, so an AI outage does not remove healthy API tasks from rotation.
- Metrics access must remain restricted by token, network path, or both when AWS
  networking is defined.
- Request IDs are propagated through headers, but full request ID binding into
  every Django log line should be confirmed before CloudWatch queries are
  declared production-ready.
- Watchdog recovery exists as a management command. Phase 10.10 must schedule
  it in AWS and alert on repeated recoveries.
- Phase 10.8 SSE events are process-local. Phase 10.10 must not scale API tasks
  or workers for SSE-dependent behavior until a shared event transport or an
  explicit single-task tradeoff is approved.
- Security scanners can fail on newly disclosed CVEs unrelated to app changes.
  Triage and ignore policy must be documented before enforcing scans on release
  branches.
