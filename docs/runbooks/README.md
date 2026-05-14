# Operational Runbooks

Runbooks describe repeatable development and maintenance procedures.

| File | Contents |
| --- | --- |
| [ai-service-outage.md](ai-service-outage.md) | AI dependency outage procedure and health endpoint expectations. |
| [database-outage.md](database-outage.md) | Postgres/PgBouncer outage recovery and readiness verification. |
| [integration-delivery-failure.md](integration-delivery-failure.md) | Slack/webhook/PagerDuty delivery failure triage and recovery. |
| [local-development.md](local-development.md) | Docker Compose, Makefile, migrations, seed data, tests, linting, and troubleshooting. |
| [phase-10-09-hardening-checks.md](phase-10-09-hardening-checks.md) | Local and CI production-hardening validation gates. |
| [production-hardening-local-drills.md](production-hardening-local-drills.md) | Manual Phase 10.9 drills for SIGTERM, watchdog recovery, health, env validation, request IDs, and metrics. |
| [runner-pools-phase-c-operations.md](runner-pools-phase-c-operations.md) | Phase C runner registration, credential rotation/revocation, drain, route diagnostics, offline-pool triage, and stale execution recovery. |
| [runner-crash-recovery.md](runner-crash-recovery.md) | Runner crash loop and stale execution recovery procedure. |
| [stuck-execution-recovery.md](stuck-execution-recovery.md) | Operational recovery procedure for stale heartbeat and stuck execution failures. |
| [structured-logging-and-request-ids.md](structured-logging-and-request-ids.md) | Request ID propagation and local tracing checks across runner and Django. |
| [phase-10-09-definition-of-done.md](phase-10-09-definition-of-done.md) | Final Phase 10.9 readiness checklist and remaining risks before Phase 10.10. |
| [ai-agent-working-guide.md](ai-agent-working-guide.md) | How Codex and Claude Code should work safely in this repo. |
| [documentation-maintenance.md](documentation-maintenance.md) | When and how to keep docs, blueprints, and implementation status aligned. |
