# Phase 01 Implemented Architecture Blueprint

## 1. Title and Metadata

| Field | Value |
| --- | --- |
| Phase number | 01 |
| Status | Implemented in parts; audited against the current working tree |
| Audit date | 2026-04-15 |
| Scope reviewed | `apps/api`, `apps/runner`, `apps/web`, `apps/ai`, `packages/contracts`, `packages/workflow-schema`, `docker-compose.yml`, `Makefile`, `.env.example`, and `docs/blueprints/phase-01` through `phase-08` |
| Runtime source of truth | Docker Compose in `docker-compose.yml` |
| Audit basis | Current repository state, including uncommitted Phase 1-related changes present in the working tree during the audit |
| Related blueprint dependencies | `phase-01-end-to-end-vertical-slice-blueprint.md`, `phase-02-django-domain-foundation-blueprint.md`, `phase-03-application-service-layer-blueprint.md`, `phase-04-versioned-rest-apis-blueprint.md`, `phase-05-runner-real-flow-blueprint.md`, `phase-06-react-product-slice-blueprint.md`, `phase-07-ai-service-boundary-blueprint.md`, `phase-08-targeted-testing-blueprint.md` |

## Current repo alignment notes

As of 2026-04-27, this implemented snapshot is partially stale. The React product slice now includes real routes, feature API clients, TanStack Query hooks, and page tests. The AI service now has parse tests. Use `docs/architecture/` for current architecture truth and keep this file as a historical implementation audit.

## 2. Executive Summary

Phase 1 currently delivers a real backend execution slice across Django, PostgreSQL, the runner, and the FastAPI parsing service. Organizations, runbooks, workflows, executions, and execution steps are real persisted models. Public and internal versioned APIs exist under `/api/v1/...`. The runner really polls Django, claims queued executions, updates step status, sends heartbeats, and completes executions. The AI boundary is real in the sense that Django now calls FastAPI over HTTP to create workflow candidates before persisting workflows.

The slice now includes a real React product surface for the core local workflow: organizations, runbooks, workflow creation/detail, and execution detail are represented in `apps/web`. The AI behavior is still stubbed in practice: the FastAPI service uses deterministic parsing in `app/services/workflow_parser.py`, not a provider-backed model workflow. The runner execution path is also intentionally fake: it simulates step work and treats `FAIL_STEP` in a command as a deliberate failure marker.

Practical maturity:

- Real now: Django domain model, core service layer, versioned APIs, runner polling and claim flow, execution persistence, internal AI HTTP boundary, targeted Django and runner tests, Docker runtime wiring.
- Stubbed or incomplete: real sandboxed command execution, artifact upload, structured runner logging helpers, AI provider integration, auth/permissions, approvals, policies, audit, artifacts, integrations, and production hardening.

## 3. End-to-End System Walkthrough

### 3.1 Organization creation

`POST /api/v1/organizations/` lands in `apps/api/apps/organizations/views.py` on `OrganizationViewSet.create`. The view validates with `OrganizationSerializer`, then delegates creation to `apps/api/apps/organizations/services.py:create_organization`. Persistence happens through the `Organization` model in `apps/api/apps/organizations/models.py`.

### 3.2 Runbook creation

`POST /api/v1/runbooks/` lands in `RunbookViewSet.create` in `apps/api/apps/runbooks/views.py`. The view validates payload with `RunbookCreateSerializer`, loads the target `Organization`, then delegates persistence to `apps/api/apps/runbooks/services.py:create_runbook`. Runbooks are stored with raw authored content in `Runbook.raw_content` and start in `draft` status.

### 3.3 Workflow generation

`POST /api/v1/workflows/` lands in `WorkflowViewSet.create` in `apps/api/apps/workflows/views.py`. The view loads the `Runbook` and delegates orchestration to `apps/api/apps/workflows/services.py:create_workflow_from_runbook`.

The workflow service does three real things:

1. Generates a `request_id`.
2. Calls `apps/api/apps/runbooks/ai_client.py:parse_runbook_to_workflow_candidate` outside the database transaction.
3. Maps the AI response into canonical workflow JSON, assigns the next workflow version, and persists a `Workflow` row inside `transaction.atomic()`.

Django calls FastAPI at `POST {AI_BASE_URL}/parse/runbook`. The FastAPI route is `apps/ai/app/api/routes/parse.py`, which delegates to `apps/ai/app/services/workflow_parser.py`. That parser currently uses deterministic numbered-step extraction and fallback steps, not LLM inference.

### 3.4 Workflow publication

`POST /api/v1/workflows/{workflow_id}/publish/` lands in `WorkflowViewSet.publish`. The view delegates to `apps/api/apps/workflows/services.py:publish_workflow`, which only allows `draft -> published`.

Publication is real, but still minimal:

- there is no supersede flow for older versions
- there is no archive flow
- there is no approval layer

### 3.5 Execution creation

`POST /api/v1/executions/` lands in `ExecutionViewSet.create` in `apps/api/apps/executions/views.py`. The view loads the target `Workflow` and delegates to `apps/api/apps/executions/services.py:create_execution_from_workflow`.

Execution creation is real and transactional:

- workflow must already be `published`
- `Execution` is persisted with `workflow_version` and `workflow_snapshot`
- each workflow step is materialized into an `ExecutionStep`
- steps begin in `pending`

### 3.6 Runner claim and execution

The runner process starts in `apps/runner/runner/main.py`, creates one `ApiClient`, one `Executor`, and one `Poller`, then calls `Poller.run_forever()`.

The polling loop in `apps/runner/runner/poller.py` repeatedly calls `POST /api/v1/internal/executions/claim-next/` through `apps/runner/runner/client.py`. Django handles that in `apps/api/apps/executions/views.py:claim_next`, which delegates to `apps/api/apps/executions/services.py:claim_next_execution`.

Claim behavior is real and concurrency-aware:

- only `queued` executions are eligible
- claiming is wrapped in `transaction.atomic()`
- the service uses `select_for_update(skip_locked=True)`
- the execution is updated to `claimed`
- Django records `claimed_by_runner_id`, `claim_token`, `claimed_at`, and `last_heartbeat_at`

### 3.7 Step updates

The runner executes steps sequentially in `apps/runner/runner/executor.py`.

For each step:

- runner marks the step `running` through `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`
- Django validates ownership and transition rules in `apps/api/apps/executions/services.py:update_execution_step`
- on first running step, Django moves the parent execution from `claimed` to `running`
- the runner either marks the step `succeeded` or `failed`

Step execution is intentionally fake in Phase 1:

- no subprocess or sandbox execution exists
- no artifact upload exists
- `FAIL_STEP` inside the step command is the deliberate failure trigger

### 3.8 Completion

When the runner finishes or hits a failure, it calls `POST /api/v1/internal/executions/{execution_id}/complete/`. Django validates ownership and status in `complete_execution`, then marks the execution `succeeded` or `failed` and sets `finished_at`.

### 3.9 Frontend visibility

Frontend visibility is implemented for the core local vertical slice. `apps/web` includes React Router routes, a shared Django API client, TanStack Query providers/hooks, feature API modules, creation forms, workflow detail, and execution detail views.

The product surface still lacks future auth, approvals, policies, audit, artifacts, integrations, and live streaming.

### 3.10 AI service interaction

The AI service boundary is live but narrow:

- Django is the only caller of FastAPI
- the endpoint used is `/parse/runbook`
- FastAPI does not persist anything
- Django maps the candidate into canonical workflow JSON and persists the `Workflow`

What remains stubbed:

- no provider-backed AI call
- no summary generation flow
- no enrich flow used by Django
- no schema validation against the shared JSON schema package at runtime

### 3.11 Test coverage

The repo has targeted automated coverage for the implemented slice:

- Django tests cover runbook, workflow, and execution service behavior plus core API contracts.
- Execution claim tests cover basic queue claim behavior.
- Runner tests cover poller and executor behavior.
- Frontend page tests cover route-level behavior.
- AI tests cover parse route and parser behavior.

During this audit the following runtime checks succeeded:

- `docker compose config`
- `docker compose ps`
- `docker compose exec api python manage.py check`
- `docker compose exec api pytest -q` with `31 passed`
- `docker compose exec runner pytest -q` with `10 passed`
- `docker compose exec web npm run build`

## 4. Current Architecture by Layer

### 4.1 React frontend

Responsibilities now:

- render the core product slice for organizations, runbooks, workflows, and executions
- call Django public APIs only
- keep server state in TanStack Query hooks and feature API modules

Entry points:

- `apps/web/src/main.tsx`
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`

Key files:

- `apps/web/package.json`
- `apps/web/src/main.tsx`
- `apps/web/src/index.css`
- `apps/web/src/features/*`
- `apps/web/src/routes/*`

Important implementation choices:

- React Router is installed but unused.
- TanStack Query is installed but unused.
- `VITE_API_BASE_URL` is defined in `.env.example`, but the frontend does not yet consume it.
- There are no browser calls to FastAPI or runner endpoints, which preserves the intended boundary by omission.

### 4.2 Django control plane

Responsibilities now:

- own the domain model and persistence
- own orchestration for runbook, workflow, and execution flows
- expose public `/api/v1/` endpoints
- expose internal runner-only `/api/v1/internal/` endpoints
- own workflow and execution history

Entry points:

- `apps/api/config/urls.py`
- `apps/api/apps/*/views.py`

Key modules:

- `apps/api/config/settings/base.py`
- `apps/api/apps/organizations/*`
- `apps/api/apps/runbooks/*`
- `apps/api/apps/workflows/*`
- `apps/api/apps/executions/*`

Important implementation choices:

- health remains outside `/api/v1` at `/health/`
- public and internal routes are separated structurally
- services are used for create and state-transition flows
- AI HTTP call is made outside the workflow persistence transaction
- execution claim uses row locking and `skip_locked`

### 4.3 Runner

Responsibilities now:

- poll Django for work
- claim one execution at a time
- execute steps sequentially in memory
- send heartbeat, step, and completion updates back to Django

Entry points:

- `apps/runner/runner/main.py`
- `apps/runner/runner/poller.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/client.py`

Key modules:

- `apps/runner/runner/schemas.py`
- `apps/runner/runner/tests/test_poller.py`
- `apps/runner/runner/tests/test_executor.py`

Important implementation choices:

- one long-lived synchronous `httpx.Client`
- polling remains the only dispatch mechanism
- fake execution uses `FAIL_STEP` to force failure paths
- heartbeat uses a background thread while an execution is active
- log streaming, artifact upload, and sandboxing are still placeholders

### 4.4 FastAPI AI service

Responsibilities now:

- accept runbook parsing requests from Django
- return a structured workflow candidate
- expose service health

Entry points:

- `apps/ai/app/main.py`
- `apps/ai/app/api/routes/parse.py`
- `apps/ai/app/api/routes/health.py`

Key modules:

- `apps/ai/app/schemas/workflow_parse.py`
- `apps/ai/app/services/workflow_parser.py`

Important implementation choices:

- parsing is deterministic and local
- FastAPI does not own persistence
- `enrich` and `summarize` routes are still mounted as placeholders but unused by Django

### 4.5 PostgreSQL / persistence

Responsibilities now:

- durable storage for all Django-owned domain entities
- source of truth for workflow versions, execution state, and execution history

Key model files:

- `apps/api/apps/organizations/models.py`
- `apps/api/apps/runbooks/models.py`
- `apps/api/apps/workflows/models.py`
- `apps/api/apps/executions/models.py`

Important implementation choices:

- UUID primary keys everywhere in the domain
- workflow definitions and execution snapshots stored in JSON fields
- execution-step rows materialized from workflow snapshots
- runner never writes to PostgreSQL directly

### 4.6 Test layer

Responsibilities now:

- protect service-layer behavior
- protect critical API contracts
- protect core runner sequencing logic

Key files:

- `apps/api/apps/runbooks/tests/test_services.py`
- `apps/api/apps/runbooks/tests/test_api_contracts.py`
- `apps/api/apps/workflows/tests/test_services.py`
- `apps/api/apps/workflows/tests/test_api_contracts.py`
- `apps/api/apps/executions/tests/test_services.py`
- `apps/api/apps/executions/tests/test_api_contracts.py`
- `apps/api/apps/executions/tests/test_concurrency.py`
- `apps/runner/runner/tests/test_poller.py`
- `apps/runner/runner/tests/test_executor.py`

Important implementation choices:

- Django uses `pytest` with `pytest-django`
- runner uses `pytest`
- frontend has no test setup yet
- AI has no test setup yet

## 5. Current Domain Model Summary

### Organization

Defined in `apps/api/apps/organizations/models.py`.

- fields: `id`, `created_at`, `updated_at`, `name`, `slug`
- relationships: parent of runbooks, workflows, and executions
- constraints: global unique `slug`

### Runbook

Defined in `apps/api/apps/runbooks/models.py`.

- fields: `organization`, `title`, `slug`, `raw_content`, `status`
- statuses: `draft`, `ready`, `archived`
- relationships: belongs to one organization; parent of workflows
- constraints: unique `(organization, slug)`

### Workflow

Defined in `apps/api/apps/workflows/models.py`.

- fields: `organization`, `runbook`, `name`, `version`, `status`, `definition_schema_version`, `definition`
- statuses: `draft`, `published`, `superseded`, `archived`
- relationships: belongs to one organization and one runbook; parent of executions
- constraints: unique `(runbook, version)` and `version >= 1`

### Execution

Defined in `apps/api/apps/executions/models.py`.

- fields: `organization`, `workflow`, `workflow_version`, `workflow_snapshot`, `status`, `started_at`, `finished_at`, `claimed_by_runner_id`, `claim_token`, `claimed_at`, `last_heartbeat_at`
- statuses: `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`
- relationships: belongs to one organization and one workflow; parent of execution steps

### ExecutionStep

Defined in `apps/api/apps/executions/models.py`.

- fields: `execution`, `position`, `step_key`, `name`, `step_type`, `risk_level`, `command`, `requires_approval`, `step_snapshot`, `status`, `started_at`, `finished_at`, `exit_code`, `error_message`
- statuses: `pending`, `running`, `succeeded`, `failed`, `skipped`
- relationships: belongs to one execution
- constraints: unique `(execution, position)` and unique `(execution, step_key)`

### Shared base model

Defined in `apps/api/apps/common/models.py`.

- abstract `BaseModel`
- supplies UUID primary key plus timestamps

## 6. Current API Surface Summary

### Public endpoints

- `GET /api/v1/organizations/`
- `POST /api/v1/organizations/`
- `GET /api/v1/organizations/{id}/`
- `GET /api/v1/runbooks/`
- `POST /api/v1/runbooks/`
- `GET /api/v1/runbooks/{id}/`
- `GET /api/v1/workflows/`
- `POST /api/v1/workflows/`
- `GET /api/v1/workflows/{id}/`
- `POST /api/v1/workflows/{id}/publish/`
- `GET /api/v1/executions/`
- `POST /api/v1/executions/`
- `GET /api/v1/executions/{id}/`
- `POST /api/v1/executions/{id}/cancel/`

### Internal runner endpoints

- `POST /api/v1/internal/executions/claim-next/`
- `POST /api/v1/internal/executions/{execution_id}/heartbeat/`
- `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`
- `POST /api/v1/internal/executions/{execution_id}/complete/`

### Health endpoints

- Django: `GET /health/`
- FastAPI: `GET /health`

### Versioning structure

- the repo uses a static `/api/v1/` URL prefix
- versioning is path-based by route inclusion, not DRF namespace versioning

### Actual deviations from plan

- no standardized error envelope exists yet
- error status codes remain simple `400` responses for most invalid transition cases
- no auth or permission boundary exists yet beyond URL separation
- internal responses are simpler than the later blueprint examples

## 7. Current Runner Architecture Summary

### Loop

`Poller.run_forever()` in `apps/runner/runner/poller.py` owns the outer loop. It calls `claim_next()`, sleeps on no-work responses, and hands claimed work to `Executor.run()`.

### Claim behavior

Claiming is initiated only through Django internal API. The runner does not touch the database. Django selects the oldest queued execution and marks it claimed inside the same transaction.

### Step execution behavior

The runner sorts steps by `position`, marks each step `running`, waits briefly, then marks it `succeeded`. If a command contains `FAIL_STEP`, the runner marks the step `failed` and stops processing later steps.

### Heartbeat behavior

Heartbeat is handled by a background thread in `apps/runner/runner/executor.py`. It sends `POST /heartbeat/` every 10 seconds while the execution is active.

### Failure behavior

Current failure handling is conservative in some places but not fully hardened:

- step update failures are treated as execution failure
- unexpected executor exceptions produce failed completion
- heartbeat failures are only logged; they do not currently abort local execution
- API client errors are surfaced through `httpx.HTTPError`

### Logging behavior

Logging uses Python standard logging through `logging.basicConfig`. There is no dedicated structured logging helper yet. Current live logs also include `httpx` request logging noise.

## 8. Current Frontend Architecture Summary

### Routes

There are no real routes. The app mounts a single `App` component.

### Data fetching

There is no API client and no data fetching logic yet.

### Polling

There is no frontend polling yet.

### Feature boundaries

The frontend does not violate the Django-only boundary because it does not yet call anything. React Router and React Query are installed but not wired.

### Current UX limitations

- no organization creation UI
- no runbook creation UI
- no workflow generation or publish UI
- no execution creation UI
- no execution detail page
- no progress visualization
- no loading or error-state UX for the vertical slice

## 9. Current AI Boundary Summary

Django calls FastAPI only through `apps/api/apps/runbooks/ai_client.py`. The client reads `AI_BASE_URL` and timeout settings from Django settings, posts to `/parse/runbook`, validates the response shape, and returns a typed `WorkflowCandidate`.

Boundary correctness today:

- frontend does not call FastAPI
- runner does not call FastAPI
- FastAPI does not persist workflows or executions
- Django remains the source of truth for workflow versions and stored definitions

What remains stubbed:

- parse behavior is deterministic, not model-backed
- no shared runtime schema validation against `packages/contracts` or `packages/workflow-schema`
- `enrich` and `summarize` are mounted but unused placeholders

## 10. Testing Summary

### What tests exist now

- Django service tests for runbooks, workflows, and executions
- Django API contract tests for create/detail and some actions
- Django claim-next behavior tests
- runner poller tests
- runner executor tests

### What critical flows are covered

- creating a runbook
- generating a workflow
- publishing a workflow
- creating an execution from a published workflow
- basic queue claiming
- runner happy path and deliberate failure path

### What is still lightly covered

- AI client transport and failure mapping
- FastAPI parse route behavior
- heartbeat ownership failures and other runner-facing state transitions
- true concurrent PostgreSQL claim races
- runner HTTP client contract mapping
- broader frontend behavior beyond current route/page smoke tests

## 11. Known Limitations

- The React product slice covers the core local vertical slice, but it is still unauthenticated and lacks future expansion features.
- Execution work is fake and sequential; there is no subprocess, sandbox, or artifact handling.
- Workflow parsing is deterministic and local; it is not yet real AI orchestration.
- AI failures are translated to the current Django error envelope, but production-grade retry/observability behavior is still deferred.
- `Workflow.definition_schema_version` currently defaults to `workflow.schema.v1`.
- Two workflow schema packages exist with duplicated placeholder JSON schema files.
- Internal endpoint isolation is structural only; auth and permissions are not implemented.
- Logging is functional but not structured to the level planned in later blueprints.

## 12. Definition of Current Phase 1 Completion Status

Phase 1 is partially complete in implementation terms.

The backend control-plane slice is real enough to support the intended architecture:

- Django owns persistence and orchestration
- runner talks only to Django
- FastAPI stays a dependency
- PostgreSQL is the source of truth
- polling is the dispatch model

The product slice is not complete enough to call the whole phase fully done against the original end-to-end objective because the frontend workflow is still absent. The current repository is better described as:

- backend and runner vertical slice substantially implemented
- AI boundary minimally real
- frontend vertical slice still pending
- targeted testing present but not yet complete against the later blueprint standard

That is strong enough to document and extend carefully, but not strong enough to describe as a finished end-to-end user-facing Phase 1.
