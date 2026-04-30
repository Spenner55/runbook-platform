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
| Health endpoint behavior | `/health/` checks database and AI reachability and returns `503` when either dependency fails. |
| Watchdog behavior | `check_stuck_executions` recovers stale `claimed` and `running` executions, fails running steps, emits audit metadata, and is idempotent. |
| Structured logs | API, runner, and AI use the Phase 10.9 logging setup; request and runner identifiers are available for correlation. |
| Metrics | `/metrics/` exists for Django and `/metrics/` exists for AI; execution counters and latency histograms are registered. |
| CI gates | CI includes web build/lint/tests, Python lint/tests, production deploy check, migration check, dependency audits, secret scan, and container/filesystem scan. |
| All tests pass | API tests, runner tests, web build, and web lint pass locally before Phase 10.10 begins. |

## Required Manual Drills

Run and record results for:

- runner `SIGTERM` during execution;
- stale heartbeat recovery;
- broken AI health dependency;
- missing production env var;
- request ID trace across runner and Django;
- metrics endpoint smoke check.

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

Run the hardening gate before Phase 10.10:

```sh
make hardening-check
```

## Remaining Risks Before Phase 10.10

- `/health/` currently checks both database and AI. Phase 10.10 should use an
  ALB-facing readiness endpoint that does not remove healthy API tasks during an
  AI outage.
- Metrics access is implemented locally. Production exposure must be restricted
  by token, network path, or both when AWS networking is defined.
- Request IDs are propagated through headers, but full request ID binding into
  every Django log line should be confirmed before CloudWatch queries are
  declared production-ready.
- Watchdog recovery exists as a management command. Phase 10.10 must schedule
  it in AWS and alert on repeated recoveries.
- Security scanners can fail on newly disclosed CVEs unrelated to app changes.
  Triage and ignore policy must be documented before enforcing scans on release
  branches.
