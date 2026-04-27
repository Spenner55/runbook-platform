# API Service

Django + DRF control plane for the Runbook Platform.

## Current Scope

- Django project with environment-based settings.
- Health endpoint at `/health/`.
- Public API namespace under `/api/v1/`.
- Internal runner API namespace under `/api/v1/internal/`.
- Domain apps for `organizations`, `runbooks`, `workflows`, and `executions`.
- Shared `common` app for UUID timestamps, domain exceptions, and normalized error envelopes.
- Django-side AI client boundary for workflow parsing.

## Boundary Rules

- Django owns persistence, orchestration, validation, state transitions, and API contracts.
- Business logic belongs in `services.py`.
- Views and serializers are transport/validation adapters.
- Runner-only behavior stays in internal serializers/views and `/api/v1/internal/`.
- FastAPI AI output is advisory and must be validated before persistence.

## Placeholder Apps

These packages exist for future phases but are not implemented Django apps yet:

- `approvals`
- `audit`
- `artifacts`
- `integrations`
- `policies`
- `users`

Do not treat placeholder packages as implemented features.

## Common Commands

From the repo root:

```sh
make migrate
make seed-dev
make test-api
make lint
```

See `docs/architecture` and `docs/runbooks/local-development.md` for deeper guidance.
