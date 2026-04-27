# AI Service

FastAPI advisory service for runbook-to-workflow parsing.

## Current Scope

- Health endpoint at `GET /health`.
- Implemented parse endpoint at `POST /parse/runbook`.
- Pydantic request/response schemas for runbook parsing.
- Deterministic parser service that extracts numbered steps and emits fallback steps.
- Placeholder `POST /enrich/workflow` and `POST /summarize/failure` routes.

## Boundary Rules

- FastAPI is stateless and advisory only.
- Django is the only intended caller of `POST /parse/runbook`.
- FastAPI does not persist workflows, executions, runbooks, approvals, policies, audit events, or artifacts.
- FastAPI does not assign workflow versions or own state transitions.

## Commands

From the repo root:

```sh
make logs-ai
docker compose exec ai pytest tests/
```

See `docs/architecture/ai-service-boundary.md` for integration rules.
