# Runbook Platform

Runbook Platform is an early-stage governed execution platform for turning human-authored operational runbooks into versioned workflows and executable step histories.

The current repo is a local, Docker-first vertical slice. It is useful for validating the control-plane architecture, API contracts, runner flow, deterministic AI parsing boundary, and React product slice. It is not production-ready.

## Who This Is For

- Maintainers extending the platform in small, architecture-safe phases.
- Developers onboarding to the Django, runner, FastAPI, and React service boundaries.
- AI coding agents such as Codex or Claude Code implementing future approved phases.
- Project owners keeping blueprints, architecture docs, and repo state aligned.

## Core Architecture

The system is intentionally split by ownership:

- Django is the control plane.
- React calls only Django APIs.
- Runner calls only Django internal APIs.
- Runner never talks directly to PostgreSQL.
- Runner never calls the AI service directly.
- FastAPI AI service is stateless and advisory only.
- Django owns persistence, orchestration, validation, state transitions, and API contracts.
- Public APIs are versioned under `/api/v1/`.
- Runner-only endpoints live under `/api/v1/internal/`.
- Business logic belongs in service-layer modules, not views or serializers.
- Domain entities use UUID primary keys.
- Docker Compose is the local development source of truth.

See [architecture overview](docs/architecture/architecture-overview.md) and [service boundaries](docs/architecture/service-boundaries.md) for the full boundary rules.

## Services

| Service | Path | Responsibility |
| --- | --- | --- |
| Web | `apps/web` | React + TypeScript + Vite UI. Uses React Router and TanStack Query. Calls Django `/api/v1/` only. |
| API | `apps/api` | Django + DRF control plane. Owns PostgreSQL models, service-layer orchestration, public APIs, internal runner APIs, and the Django-to-AI HTTP client. |
| Runner | `apps/runner` | Python worker. Polls Django internal APIs, claims queued executions, sends heartbeats, updates step state, and completes executions. Step execution is simulated today. |
| AI | `apps/ai` | FastAPI advisory service. Implements deterministic `POST /parse/runbook`; `enrich` and `summarize` routes are placeholders. Does not persist state. |
| PostgreSQL | Compose service | Single source of truth for Django-owned domain data. |

## Local Quick Start

Prerequisites: Docker, Docker Compose, and `make`.

```sh
cp .env.example .env
make bootstrap
```

Then open:

- Web: `http://localhost:5173`
- Django API: `http://localhost:8000`
- AI service: `http://localhost:8001`

Use `make up-d` after the first setup when you want to start the stack in the background. Use `make restart` to restart containers without rebuilding images.

## Common Commands

| Command | Purpose |
| --- | --- |
| `make help` | List available Makefile targets. |
| `make bootstrap` | Build, start, wait for DB, migrate, and seed local data. |
| `make up` / `make up-d` | Build and start all services in foreground or detached mode. |
| `make down` | Stop containers while preserving volumes. |
| `make restart` | Restart existing containers without rebuilding. |
| `make migrate` | Apply Django migrations inside the API container. |
| `make seed-dev` | Seed deterministic local development data. |
| `make test-api` | Run Django tests. |
| `make test-runner` | Run runner tests. |
| `make test-web` | Run frontend tests once. |
| `make lint` | Run Python and TypeScript lint checks. |
| `make format` | Format Python and TypeScript code. |
| `make hardening-check` | Run local production settings, migration, dependency, secret, and filesystem security gates. |

More detail is in [local development](docs/runbooks/local-development.md).

## Documentation

Start at [docs/README.md](docs/README.md).

Key references:

- [Architecture overview](docs/architecture/architecture-overview.md)
- [Repository map](docs/architecture/repository-map.md)
- [API contracts](docs/architecture/api-contracts.md)
- [Data model](docs/architecture/data-model.md)
- [Runner](docs/architecture/runner.md)
- [AI service boundary](docs/architecture/ai-service-boundary.md)
- [Frontend](docs/architecture/frontend.md)
- [AI-agent working guide](docs/runbooks/ai-agent-working-guide.md)
- [Phase 10.9 hardening checks](docs/runbooks/phase-10-09-hardening-checks.md)
- [Documentation maintenance](docs/runbooks/documentation-maintenance.md)

## Blueprints

Blueprints live in [docs/blueprints](docs/blueprints). They are planning documents, not proof of implementation.

- Earlier phase blueprints document the path that produced the current vertical slice.
- [implemented/phase-01-implemented-architecture-blueprint.md](docs/blueprints/implemented/phase-01-implemented-architecture-blueprint.md) is a historical implemented snapshot.
- Phase 10 documents are forward-looking unless a later implementation explicitly lands.

When code and blueprints disagree, inspect the code and update the relevant docs. Do not silently implement planned blueprint features during unrelated work.

## Working With AI Coding Agents

Before asking Codex or Claude Code to implement changes:

1. Point it to [AI-agent working guide](docs/runbooks/ai-agent-working-guide.md).
2. Require a read-only audit before non-trivial implementation.
3. Require it to preserve the service boundaries above.
4. Require it to mark implemented, planned, partial, and deferred behavior explicitly.
5. Keep changes small and verify with the relevant Makefile targets.

AI agents must not add product features from future blueprints unless the task explicitly approves that phase.

## Current Status

Implemented today:

- Core Django domain models for organizations, runbooks, workflows, executions, and execution steps.
- Service-layer create and lifecycle flows.
- Public `/api/v1/` endpoints for organizations, runbooks, workflows, and executions.
- Internal `/api/v1/internal/` runner endpoints for claim, heartbeat, step update, and completion.
- Runner polling and simulated sequential step execution.
- FastAPI deterministic runbook parsing endpoint.
- React product slice for organizations, runbooks, workflow creation/detail, and execution detail.
- Docker Compose local workflow, seed command, lint/format/test commands, and CI gates.

Not production-ready:

- Authentication and authorization are deferred.
- Approvals, policies, audit trail, artifacts, integrations, live event streaming, production hardening, and AWS deployment remain blueprint-level work.
- Runner execution is simulated and does not run real sandboxed commands.
- AI parsing is deterministic and not provider-backed.

## Intentionally Out Of Scope Right Now

- Direct frontend calls to FastAPI or runner services.
- Direct runner database access.
- Direct runner AI calls.
- Kafka, RabbitMQ, Celery, websockets, or event streaming infrastructure.
- Production deployment automation or live AWS resources.
- Broad refactors that move business logic out of Django services.
