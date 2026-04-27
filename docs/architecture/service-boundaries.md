# Service Boundaries

This document defines what each service may call and what would violate the architecture.

## Boundary Summary

| Caller | Allowed targets | Forbidden targets |
| --- | --- | --- |
| React frontend | Django public `/api/v1/` endpoints | FastAPI AI, runner, PostgreSQL, `/api/v1/internal/` |
| Django API | PostgreSQL through ORM, FastAPI AI through internal client | Runner runtime control channels, direct browser state mutation |
| Runner | Django `/api/v1/internal/` endpoints | PostgreSQL, FastAPI AI, public endpoints for execution state |
| FastAPI AI | Local parser/provider code | PostgreSQL, runner, frontend, workflow persistence |
| PostgreSQL | Django ORM only | Direct app access from web, runner, or AI |

## Django API / Control Plane Boundary

Django owns:

- Domain models and migrations.
- Transactions and state transitions.
- Public and internal API contracts.
- Runner claim ownership and `claim_token` validation.
- Workflow creation orchestration and AI response validation.
- Execution snapshots and execution history.

Django may call FastAPI only for advisory workflow parsing or future advisory AI tasks. It must validate all AI output before persistence.

## Runner Boundary

The runner owns:

- Polling for queued executions.
- Sending heartbeats.
- Reporting step status transitions.
- Completing claimed executions.
- Local execution mechanics as they are implemented.

The runner must never:

- Connect to PostgreSQL.
- Call the AI service.
- Create or publish workflows.
- Decide persisted approval or policy state without Django.
- Mutate execution state through public `/api/v1/executions/` endpoints.

## FastAPI AI Boundary

FastAPI owns:

- Stateless advisory parsing.
- Request/response validation through Pydantic.
- Future provider orchestration only after an approved phase.

FastAPI must never:

- Persist workflows, runbooks, executions, approvals, artifacts, or audit rows.
- Assign workflow versions.
- Decide lifecycle state.
- Expose browser-facing product APIs.

## React Frontend Boundary

React owns:

- UI state and browser routing.
- Calling Django public APIs.
- Rendering loading, error, and success states.
- Client-side cache invalidation through TanStack Query.

React must never call:

- `http://localhost:8001` or any AI-service URL.
- Runner APIs or runner containers.
- `/api/v1/internal/...`.
- PostgreSQL or direct database endpoints.

## Database Boundary

PostgreSQL is only reachable through Django application code. Direct reads and writes from the runner, AI service, frontend, scripts, or SDKs would bypass validation and break the control-plane model.

## Internal Vs Public API Boundary

| Namespace | Audience | Examples |
| --- | --- | --- |
| `/api/v1/` | Browser/product clients and future public clients | Organizations, runbooks, workflows, executions. |
| `/api/v1/internal/` | Runner only | Claim next, heartbeat, step update, complete. |
| `/health/` | Service health checks | Django health. |
| FastAPI `/health`, `/parse/runbook` | Django dependency calls and health checks | AI service only. |

Internal endpoints should use dedicated serializers and views. They should not be added as public viewset actions.

## Allowed Calls

| Scenario | Allowed call |
| --- | --- |
| User creates a runbook | React -> `POST /api/v1/runbooks/` -> Django service -> PostgreSQL |
| User creates a workflow | React -> `POST /api/v1/workflows/` -> Django -> FastAPI `/parse/runbook` -> Django -> PostgreSQL |
| Runner claims work | Runner -> `POST /api/v1/internal/executions/claim-next/` -> Django -> PostgreSQL |
| Runner reports step success | Runner -> `POST /api/v1/internal/executions/{id}/steps/{step_id}/update/` |
| UI reads execution detail | React -> `GET /api/v1/executions/{id}/` |

## Disallowed Calls

| Disallowed call | Why it is wrong |
| --- | --- |
| React -> FastAPI `/parse/runbook` | Bypasses Django validation, versioning, and persistence ownership. |
| Runner -> PostgreSQL | Bypasses claim ownership, state transition validation, and service-layer logic. |
| Runner -> FastAPI | Lets execution depend on advisory AI service outside Django orchestration. |
| React -> `/api/v1/internal/executions/claim-next/` | Internal runner contract, not a public product API. |
| AI -> PostgreSQL | Violates stateless advisory boundary. |
| Viewset action directly mutating model state without a service | Moves business rules out of the service layer. |

## What Would Violate The Architecture

- Adding database credentials to `apps/runner` or `apps/ai`.
- Adding `VITE_AI_BASE_URL` and browser code that calls it.
- Adding policy or approval decisions in runner code.
- Persisting AI-generated workflow rows inside FastAPI.
- Creating public endpoints outside `/api/v1/` except health endpoints.
- Adding unversioned product APIs.
- Adding event/queue infrastructure before an approved phase requires it.
