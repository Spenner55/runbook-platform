# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **Web**: React 19 + TypeScript + Vite (`apps/web`) — port 5173
- **API**: Django 5 + DRF (`apps/api`) — port 8000
- **AI**: FastAPI (`apps/ai`) — port 8001
- **Runner**: Python long-running worker (`apps/runner`)
- **DB**: PostgreSQL 17 (`runbook_platform` database)

## Common Commands

All services run inside Docker. Most commands go through `make` or `docker compose exec`.

```bash
make up               # build and start all services
make up-d             # same, detached
make down             # stop all services
make logs             # tail all logs
make bootstrap        # start + run migrations (first-time setup)
make migrate          # run Django migrations
make makemigrations   # generate Django migrations
make api-shell        # sh into api container
make db-shell         # psql into postgres
```

### Django management
```bash
docker compose exec api python manage.py check
docker compose exec api python manage.py shell
docker compose exec api python manage.py showmigrations
```

### Django tests (pytest-django)
```bash
docker compose exec api pytest                        # all tests
docker compose exec api pytest apps/runbooks/tests/   # single app
docker compose exec api pytest -k test_name           # single test
```
The test settings file is `apps/api/config/settings/test.py`. Set `DJANGO_SETTINGS_MODULE=config.settings.test` if running pytest outside the container.

### Web (inside container or locally with Node)
```bash
cd apps/web && npm run dev      # dev server
cd apps/web && npm run build    # production build
cd apps/web && npm run lint     # ESLint
```

## Architecture

### Service boundaries (strictly enforced)

| Service | Responsibility | May call |
|---------|---------------|----------|
| React | UI only | Django API |
| Django | Orchestration + persistence | AI service (via httpx), DB |
| Runner | Execution engine | Django API only |
| FastAPI | AI processing (parse/enrich/summarize) | External LLM providers |

**The frontend never calls the AI service directly. The runner never touches the database directly.**

### Django app layout (`apps/api/apps/`)

Domain apps under `apps/api/apps/`: `organizations`, `runbooks`, `workflows`, `executions`, `approvals`, `artifacts`, `audit`, `policies`, `users`, `integrations`, `common`.

- `common` holds `BaseModel` (UUID PK, `created_at`, `updated_at`) — all domain models inherit from it.
- Each app follows: `models.py` → `services.py` → `serializers.py` → `views.py`.
- Business logic lives in `services.py`, not in views or serializers.

### Settings

Settings are split by environment in `apps/api/config/settings/`:
- `base.py` — shared config, reads `.env` from repo root via `django-environ`
- `dev.py`, `prod.py`, `test.py` — environment overrides

`DJANGO_SETTINGS_MODULE` controls which settings file is active.

### API versioning

All endpoints are under `/api/v1/...`. Internal runner endpoints go under `/api/v1/internal/...`.

### Execution model

Poll-based (no queues). The runner polls `POST /api/v1/internal/executions/claim-next`, executes steps, and reports status back via the API.

**Execution status**: `queued` → `claimed` → `running` → `succeeded` / `failed` / `cancelled`  
**Step status**: `pending` → `running` → `succeeded` / `failed` / `skipped`

### Workflow schema

The canonical workflow definition lives in `packages/workflow-schema/workflow.schema.json`. A workflow has a `name` and `steps` array; each step requires `id`, `name`, `type`, and `risk`, with optional `command` and `requiresApproval`.

### AI service routes (`apps/ai/app/`)

FastAPI routes: `/health`, `/parse`, `/enrich`, `/summarize`. Django calls the AI service over HTTP using `httpx` — the AI service is a dependency, not a source of truth.

### Runner modules (`apps/runner/runner/`)

- `main.py` — polling loop entrypoint
- `client.py` — API client for Django
- `executor.py` — step execution
- `sandbox.py` — execution sandboxing
- `log_streamer.py` — log forwarding
- `artifact_uploader.py` — artifact upload

## Environment

Copy `.env.example` to `.env` at repo root. Required values: `DJANGO_SECRET_KEY`, `OPENAI_API_KEY`, `RUNNER_REGISTRATION_TOKEN`, `DATABASE_URL`. The web app reads `VITE_API_BASE_URL`.

## Phase Blueprints

Step-by-step implementation plans live in `docs/blueprints/`. Follow them in order (phase 01–08). Each blueprint defines explicit verification gates — run them before moving to the next step.

## Working Rules

- Prefer small, reviewable changes over large refactors.
- Before making multi-file or cross-service changes, first explain the plan briefly.
- Do not change architecture boundaries without explicitly calling it out.
- Preserve existing naming conventions and directory structure unless there is a clear reason to change them.
- When editing, prefer the minimum viable diff.
- After changes, run the smallest relevant validation command first, then broader checks if needed.

## Safety / Approval Rules

Do not perform the following without explicit approval:
- destructive git commands (`git reset --hard`, `git clean -fd`, force pushes)
- database-destructive actions (`flush`, dropping DBs, deleting volumes)
- deleting large groups of files
- editing `.env`, secrets, tokens, or credentials-related files
- dependency upgrades across multiple services
- major Docker / compose changes affecting the whole stack

## Validation Expectations

Prefer targeted validation based on the area changed:

- Django models / services / views:
  - `docker compose exec api python manage.py check`
  - `docker compose exec api pytest apps/<relevant_app>/tests/`

- Django migrations:
  - `docker compose exec api python manage.py showmigrations`
  - `docker compose exec api python manage.py migrate`

- Web UI changes:
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`

- AI service changes:
  - run relevant FastAPI tests
  - verify `/health`

- Runner changes:
  - run runner tests
  - verify runner can start cleanly

## Sensitive / Source-of-Truth Files

Treat these as high-sensitivity areas:
- `docker-compose.yml`
- repo-root `.env` and `.env.example`
- `packages/workflow-schema/workflow.schema.json`
- Django settings under `apps/api/config/settings/`

If changing any of these, explain why and verify downstream impact.

## Change Strategy

For cross-service features, prefer this order:
1. inspect contracts / schema
2. update backend models or API contracts
3. update service-layer logic
4. update frontend or runner clients
5. run targeted verification