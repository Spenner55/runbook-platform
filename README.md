# Runbook Platform

Runbook Platform is a governance-focused workflow execution control plane for controlled operational workflows. It models runbooks, workflow versions, approvals, policy checks, runner execution, audit events, artifacts, evidence bundles, and change-control workflows through a Docker-first local stack.

The project is intended for architecture, implementation, and evaluation review. It is a source-available portfolio project under active development, not a production-ready operations platform.

## Status

- **Maturity:** active development / portfolio review.
- **Runtime:** local Docker Compose stack for evaluation and development.
- **Production readiness:** not production-ready. The repository has production-oriented checks and design work, but no implemented production deployment path.
- **Best use today:** reviewing architecture, service boundaries, implementation style, API design, tests, and the governed execution model.

## License

This repository is **source-available, not open source**. Personal, educational, evaluation, portfolio-review, and non-commercial use are permitted.

Commercial use, production use, hosted or managed offerings, resale, paid support based primarily on this work, sublicensing, or competing products substantially derived from this repository require explicit written permission from the licensor. See [LICENSE.md](LICENSE.md) for the full license terms.

## What This Demonstrates

- Django + Django REST Framework control plane with PostgreSQL persistence.
- Versioned public REST API under `/api/v1/` and runner-only internal APIs under `/api/v1/internal/`.
- React + TypeScript + Vite frontend using React Router and TanStack Query.
- Python runner boundary that polls Django, registers/heartbeats, claims work, executes steps, reports status, uploads artifacts, and handles approval gates.
- FastAPI AI-service boundary for advisory runbook parsing, with deterministic parsing by default and optional OpenAI-backed parsing behind explicit environment opt-in.
- Service-layer Django architecture for domain transitions instead of putting business logic directly in views.
- Implemented governance workflows for authentication, organizations, runbooks, workflows, executions, approvals, policies, audit events, artifacts, integrations, change records, freeze rules, emergency exceptions, evidence bundles, auditor workspace flows, runner pools, and target connectivity metadata.
- Docker-first local development with PostgreSQL, PgBouncer, Django API, React web, runner, and AI service.
- CI coverage for frontend build/lint/format/tests, Python lint/format/compile, Django tests, runner tests, AI tests, migration checks, dependency audits, secret scanning, and container filesystem scanning.

The strongest engineering signal is the boundary discipline: React uses only Django public APIs, runners use only Django internal APIs, Django owns persistence and validation, and AI output is advisory rather than authoritative.

## Architecture

```text
Browser / React UI
        |
        | public REST API only
        v
Django / DRF control plane  ----->  FastAPI AI service
        |                            advisory parsing only
        |
        | owns persistence
        v
PostgreSQL via PgBouncer
        ^
        |
        | internal runner API only
        |
Python runner
```

Boundary rules:

- The frontend calls Django public APIs only.
- The runner calls Django internal APIs only.
- The runner does not connect to PostgreSQL directly.
- The runner does not call the AI service directly.
- The AI service is stateless and advisory; Django validates and persists the final workflow state.
- PostgreSQL is owned through the Django control plane.
- Docker Compose is the local runtime source of truth.

## Repository Structure

```text
apps/
  api/       Django + DRF control plane and domain services
  web/       React + TypeScript + Vite frontend
  runner/    Python worker and local execution boundary
  ai/        FastAPI advisory parsing service
packages/
  contracts/        Shared contract/schema material
  workflow-schema/  Workflow schema and pilot action schemas
  sdk/              Scaffolded TypeScript SDK package
docs/
  architecture/     Current architecture and boundary docs
  api/              Public and internal API references
  runbooks/         Local development and operating guides
  blueprints/       Planning documents, not proof of implementation
  reports/          Audits, readiness reports, and implementation summaries
infra/
  aws/              Placeholder only; AWS infrastructure is not implemented
.github/
  workflows/        CI pipeline
  ISSUE_TEMPLATE/   Bug and feature issue templates
```

## Local Development

### Prerequisites

- Docker and Docker Compose.
- `make`.
- Git.

Normal local development does not require host-level Python, Node, npm, or PostgreSQL installs.

### Environment Setup

```sh
cp .env.example .env
```

Before starting Compose, edit `.env` and set `RUNNER_REGISTRATION_TOKEN` to a non-empty local development value. `docker-compose.yml` requires this variable for the API and runner services.

Optional AI parsing with OpenAI is disabled by default. To enable it, set `OPENAI_API_KEY`, choose `AI_PARSE_MODEL`, and set `AI_USE_LLM_PARSER=true`. This can send runbook text to OpenAI and can incur cost.

### Start The Stack

```sh
make bootstrap
```

`make bootstrap` builds images, starts services in the background, waits for the database, applies migrations, and seeds local development data.

Local URLs:

- Web: `http://localhost:5173`
- Django API: `http://localhost:8000`
- AI service: `http://localhost:8001`
- PostgreSQL: `localhost:5432`

The seed command prints local test login credentials when it completes.

### Common Commands

| Command | Purpose |
| --- | --- |
| `make help` | List available Makefile targets. |
| `make up` | Build and start all services in the foreground. |
| `make up-d` | Build and start all services in the background. |
| `make down` | Stop containers while preserving volumes. |
| `make restart` | Restart existing containers without rebuilding. |
| `make ps` | Show container status. |
| `make logs` | Tail logs for all services. |
| `make migrate` | Apply Django migrations. |
| `make seed-dev` | Seed local development data. |
| `make seed-execution-smoke` | Re-queue execution smoke scenarios. |
| `make reset` | Destructive local reset: removes volumes, rebuilds, migrates, and seeds. |

### Tests, Lint, And Build

Prefer Makefile targets where they exist:

| Command | Purpose |
| --- | --- |
| `make test-api` | Run the Django pytest suite. |
| `make test-runner` | Run the runner pytest suite. |
| `make test-web` | Run the frontend Vitest suite once. |
| `make test` | Run API, runner, and web tests. |
| `make lint` | Run Python Ruff checks and frontend ESLint. |
| `make format-check` | Check Python and frontend formatting. |
| `make check-migrations` | Check Django migration state. |
| `make check-prod` | Run Django production deployment checks with local-only env values. |
| `make ci` | Run local CI-style lint, format, tests, migration checks, and prod checks. |
| `make ci-full` | Run `make ci` plus dependency, secret, and container filesystem scans. |

Additional direct commands used by CI:

```sh
docker compose exec ai pytest tests/
docker compose exec web npm run build
```

The security scan target installs audit tooling and runs Docker-based scanners, so it can be slower than the normal development checks.

## Implementation Status

| Area | Status | Notes |
| --- | --- | --- |
| Docker Compose local stack | Implemented | API, web, runner, AI, PostgreSQL, and PgBouncer. |
| Django domain model | Implemented | Organizations, users, runbooks, workflows, executions, approvals, policies, audit, artifacts, integrations, changes, evidence, auditor access, and runners. |
| Authentication | Implemented | JWT access tokens, HTTP-only refresh cookie flow, `/api/v1/auth/*` endpoints, and organization memberships. |
| Public REST API | Implemented | Versioned under `/api/v1/`; used by the React frontend. |
| Internal runner API | Implemented | Claim, heartbeat, step start/update, completion, approval status, artifact upload, runner registration/heartbeat, and change callbacks. |
| React product UI | Implemented | Routes for login, runbooks, workflows, executions, approvals, changes, audit, retro reviews, freeze rules, policies, integrations, runners, and settings. |
| Runner execution loop | Implemented | Polling, claiming, heartbeats, cancellation observation, approval waits, action dispatch, artifacts, and change-binding callbacks. |
| Runner sandbox | Partial | Simulated execution is the default. A local-process sandbox and pilot action handlers exist for development and smoke testing, but this is not a production execution substrate. |
| Workflow schema v2 / pilot actions | Partial | Pilot schemas and handlers exist for manual tasks, approval gates, shell commands, HTTP requests, and artifact assertions. The schema is still evolving. |
| AI parsing | Partial | Deterministic parser is default. Optional OpenAI-backed structured parsing exists behind explicit opt-in. Enrich and failure-summary routes are placeholders. |
| Artifacts and evidence | Partial | Local artifact storage, uploads, evidence bundles, sealing/export flows, retention/legal-hold concepts, and UI/API flows exist. Durable object storage is not implemented. |
| Integrations | Partial | Integration connection and delivery-attempt modeling exists. External delivery depth is limited and not a full enterprise integration platform. |
| Live execution stream | Partial | Server-sent execution stream exists using a process-local event bus. Multi-worker or horizontally scaled streaming needs an external event bus. |
| AWS / production deployment | Planned | `infra/aws` is documentation-only. No Terraform, CDK, Pulumi, live resources, or deploy workflow exists. |
| Enterprise hardening | Planned | SSO, fine-grained RBAC, production credential brokerage, HA, backups, observability, and operational support workflows remain future work. |
| Shared SDK package | Scaffold | `packages/sdk` exists but is not a published or complete client SDK. |

## Documentation Map

Current implementation references:

- [Docs index](docs/README.md)
- [Architecture overview](docs/architecture/architecture-overview.md)
- [Service boundaries](docs/architecture/service-boundaries.md)
- [Repository map](docs/architecture/repository-map.md)
- [API contracts](docs/architecture/api-contracts.md)
- [Data model](docs/architecture/data-model.md)
- [Frontend architecture](docs/architecture/frontend.md)
- [Runner architecture](docs/architecture/runner.md)
- [AI service boundary](docs/architecture/ai-service-boundary.md)
- [Local development runbook](docs/runbooks/local-development.md)
- [Manual execution-plane testing](docs/runbooks/manual-execution-plane-testing.md)

Planning and roadmap material:

- [Blueprints](docs/blueprints/) are planning documents unless an implementation report says otherwise.
- [AWS infrastructure](infra/aws/README.md) is explicitly not implemented.
- Readiness and strategy reports under `docs/reports/` are analysis documents, not product claims.

When code, docs, and blueprints disagree, treat the current code and tests as the source of truth.

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting guidance.

Please do not open public GitHub issues for suspected security vulnerabilities. This project has no support SLA and is not intended for production deployment.

## Issues And Contributions

Issues and feedback are welcome. Contributions may be reviewed at the maintainer's discretion, but this is not currently run as a broad community open-source project.

Commercial use or production use requires explicit permission under the license terms.

## Screenshots And Demo

Screenshots will be added as the public-facing UI matures. The current UI can be reviewed locally after running `make bootstrap`.
