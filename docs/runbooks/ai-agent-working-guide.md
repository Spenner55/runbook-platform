# AI-Agent Working Guide

This guide is for Codex, Claude Code, and similar AI coding agents working in this repository.

## Operating Rules

- Read the repo before editing.
- Preserve the architecture invariants.
- Keep changes small and scoped.
- Treat blueprints as plans, not proof of implementation.
- Mark implemented, partially implemented, planned, and deferred behavior explicitly.
- Do not implement future blueprint features unless the task explicitly approves that work.
- Do not refactor product code during documentation-only tasks.

## Architecture Invariants

- Django is the control plane.
- React calls only Django APIs.
- Runner calls only Django internal APIs.
- Runner never talks directly to PostgreSQL.
- Runner never calls the AI service directly.
- FastAPI AI service is stateless and advisory only.
- Django owns persistence, orchestration, validation, state transitions, and API contracts.
- APIs are versioned under `/api/v1/`.
- Runner-only endpoints live under `/api/v1/internal/`.
- Business logic belongs in service-layer modules, not views or serializers.
- UUIDs are used for domain entities.
- Avoid premature event infrastructure such as Kafka, RabbitMQ, Celery, or websockets unless an approved blueprint phase requires it.
- Docker-first local development remains the source of truth.

## Read-Only Audit First

For non-trivial changes:

1. Inspect `README.md`.
2. Inspect `docs/README.md`.
3. Inspect relevant architecture docs.
4. Inspect relevant blueprints.
5. Inspect current code paths.
6. Check `git status --short`.
7. Identify planned vs implemented behavior before editing.

Do not rely only on blueprint examples.

## Safe Implementation Pattern

1. State the intended scope.
2. Make the smallest coherent change.
3. Keep business logic in service modules.
4. Update serializers/views only as transport adapters.
5. Update frontend only through Django public APIs.
6. Update runner only through Django internal API contracts.
7. Update docs when contracts, boundaries, data model, or workflows change.
8. Run relevant verification commands.

## Required Verification Commands

Choose commands based on changed areas:

| Area changed | Commands |
| --- | --- |
| Docs only | `git status --short`, `find docs -maxdepth 3 -type f | sort`, link/text checks with `rg` where useful. |
| Django API | `make test-api`, targeted `pytest` when available, `make lint` if style changed. |
| Runner | `make test-runner`, targeted runner pytest. |
| Web | `make test-web`, `docker compose exec web npm run build`, `make lint` if relevant. |
| Compose/config | `docker compose config`. |

Do not run destructive commands unless explicitly requested.

## When To Stop And Ask For Human Approval

Stop before:

- Adding auth, approvals, policies, audit, artifacts, integrations, streaming, AWS deployment, or production hardening.
- Adding Celery, Kafka, RabbitMQ, websockets, SSE, or a new service.
- Changing database deletion strategy.
- Rewriting workflow schema ownership.
- Changing public or internal API contracts in a breaking way.
- Running destructive commands such as volume resets.
- Installing new dependencies when not clearly necessary.

## Documenting Assumptions

If code does not prove a claim:

- Mark it as planned or deferred.
- Point to the blueprint that proposes it.
- Avoid saying "implemented" or "supported".
- Add a short note in the relevant doc or audit.

## Updating Blueprints Safely

Blueprints preserve intent. Do not rewrite them into implementation logs.

Prefer adding a small section:

```md
## Current repo alignment notes

- As of YYYY-MM-DD, ...
- Implemented: ...
- Still planned/deferred: ...
```

Keep historical context unless it is actively misleading.

## Avoiding Accidental Feature Work

Placeholder directories are not implementations:

- `apps/api/apps/approvals`
- `apps/api/apps/audit`
- `apps/api/apps/artifacts`
- `apps/api/apps/integrations`
- `apps/api/apps/policies`
- `apps/api/apps/users`

Do not fill them in unless the task explicitly approves that phase.

## Documentation Tasks

For documentation-only work:

- Do not edit runtime code unless a tiny comment/docstring prevents future boundary mistakes.
- Do not edit tests except documentation comments if truly necessary.
- Do not run migrations.
- Do not start long-running services.
- Do not install dependencies.
