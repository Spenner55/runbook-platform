# Runbook Platform

Governed AI-assisted runbook-to-workflow execution platform for engineering teams.

## Stack
- React + TypeScript + Vite
- Django + DRF
- FastAPI
- Python runner
- PostgreSQL
- Docker
- GitHub Actions

## Monorepo Layout
- `apps/web` for the Vite frontend
- `apps/api` for the Django + DRF API
- `apps/ai` for the FastAPI AI service
- `apps/runner` for the Python workflow runner
- `packages/contracts` for shared JSON contracts
- `packages/workflow-schema` for the canonical workflow schema package scaffold
- `packages/sdk` for future shared client helpers
- `infra/docker`, `infra/compose`, `infra/aws`, and `infra/scripts` for operational assets
- `docs/architecture`, `docs/product`, `docs/runbooks`, and `docs/decisions` for project documentation

## Getting Started
1. Copy `.env.example` to `.env`.
2. Fill in manual values such as `DJANGO_SECRET_KEY`, `OPENAI_API_KEY`, and `RUNNER_REGISTRATION_TOKEN`.
3. Start the stack with `make up`.

## Notes
- `.env` is intentionally not committed.
- AWS infrastructure is intentionally left as documentation and placeholders until account, region, and deployment decisions are made.
