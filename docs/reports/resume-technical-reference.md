# Runbook Platform Resume Technical Reference

This reference is based on the current repository implementation, including the working tree state at audit time. It is intended for resume, LinkedIn, cover letter, and interview preparation.

Do not claim production scale, active customers, cloud deployment, security certification, uptime, performance improvement, revenue, or usage metrics from this project. The repository supports a local Docker-first platform with production-readiness checks and deployment placeholders, not a live production deployment.

## One-Line Project Description

Built a Docker-first governed runbook execution platform that converts human-authored operational runbooks into versioned workflows, routes execution through a Django control plane, coordinates a Python runner over internal APIs, and exposes a React operator UI with authentication, approval, policy, audit, artifact, integration, and change-management flows.

## Supported Resume Positioning

- Designed and implemented a multi-service operations control plane with Django REST Framework, FastAPI, React, PostgreSQL, and a Python runner.
- Modeled governed workflow execution with versioned workflow definitions, immutable execution snapshots, materialized execution steps, runner claim tokens, heartbeats, approval waits, policy evaluation, audit trails, artifacts, and change records.
- Built service boundaries where Django owns persistence and state transitions, React calls only public Django APIs, runner calls only internal Django APIs, and FastAPI remains stateless/advisory.
- Implemented authenticated, organization-scoped APIs using JWT access tokens, HTTP-only refresh cookies, organization membership roles, and explicit `X-Organization-Id` context checks.
- Added production-hardening foundations including structured logging, request IDs, Prometheus metrics, health/readiness checks, rate limits, security headers, dependency audits, secret scans, migration checks, and CI gates.

## Technologies Used

### Backend

- Python 3.12.
- Django 5.x.
- Django REST Framework.
- Simple JWT (`djangorestframework-simplejwt`) for access and refresh tokens.
- PostgreSQL 17 in Docker Compose.
- PgBouncer in transaction pooling mode.
- `psycopg[binary]`.
- `django-environ` for settings.
- `django-cors-headers`.
- `django-csp`.
- `django-ratelimit`.
- `django-prometheus`.
- `structlog`.
- `jsonschema` for workflow definition validation.
- `cryptography.Fernet` for encrypted integration credentials.
- `httpx` for outbound service calls and runner API client calls.

### AI Service

- FastAPI.
- Uvicorn.
- Pydantic and `pydantic-settings`.
- OpenAI Python SDK.
- Prometheus client and `prometheus-fastapi-instrumentator`.
- Structlog.

### Runner

- Python worker process.
- `httpx.Client`.
- Pydantic request/response schemas.
- Threaded heartbeat loop.
- Structured JSON logging helpers.

### Frontend

- React 19.
- TypeScript 5.9.
- Vite.
- React Router 7.
- TanStack Query 5.
- `@microsoft/fetch-event-source` for SSE client streaming.
- Vitest.
- Testing Library.
- ESLint and Prettier.

### DevOps / Platform

- Docker Compose.
- Per-service Dockerfiles for API, AI, runner, and web.
- Makefile-based local orchestration.
- GitHub Actions CI.
- Ruff for Python lint/format.
- npm audit.
- pip-audit.
- Gitleaks.
- Trivy.

## Architecture Patterns

- Multi-service architecture with clear ownership boundaries:
  - Django API is the control plane and sole application owner of PostgreSQL persistence.
  - React UI calls only Django public `/api/v1/` endpoints.
  - Runner calls only Django `/api/v1/internal/` endpoints.
  - FastAPI AI service returns advisory candidates and does not persist state.
- Versioned public REST API under `/api/v1/`.
- Internal runner API namespace under `/api/v1/internal/`.
- Service-layer architecture: views and serializers delegate business logic to `services.py`.
- Explicit state-machine style lifecycle transitions for runbooks, workflows, executions, approvals, policies, and change records.
- UUID primary keys for domain entities.
- Tenant scoping through direct organization foreign keys and organization membership checks.
- Immutable snapshot strategy:
  - `Execution.workflow_snapshot` stores execution-time workflow definition.
  - `ExecutionStep.step_snapshot` stores execution-time step definition.
  - `ChangeRecord.request_snapshot` stores a frozen change dossier.
- Advisory AI boundary:
  - Django calls FastAPI.
  - FastAPI returns parse/enrich/summarize candidates.
  - Django validates, maps, versions, and persists.
- Runner ownership model:
  - Django assigns `claim_token`.
  - Runner must send `runner_id` and `claim_token`.
  - Internal services validate runner ownership before heartbeat, step update, completion, artifact upload, and change-bound execution actions.
- In-process Server-Sent Events event bus for execution streaming, with documented single-worker limitation.

## Backend Skills Demonstrated

- Built Django apps for users, organizations, runbooks, workflows, executions, approvals, policies, audit, artifacts, integrations, and changes.
- Implemented custom `User` model with email login.
- Implemented organization membership model with `owner`, `admin`, `operator`, and `viewer` roles.
- Built organization-scoped querysets and permission helpers.
- Added public REST endpoints for auth, organizations, memberships, runbooks, workflows, executions, approvals, policies, audit events, integrations, artifacts, changes, freeze rules, and execution streaming.
- Added internal runner endpoints for claiming executions, heartbeats, step start, approval status polling, step updates, completion, artifact upload, and change execution binding.
- Used `select_for_update()` and `skip_locked=True` for concurrent-safe claim and recovery flows.
- Used database constraints and indexes for integrity:
  - Unique runbook slug per organization.
  - Unique workflow version per runbook.
  - Unique execution step position and step key per execution.
  - Partial unique active target lock per organization/target.
  - Check constraints for lifecycle status enums.
  - Check constraints for change windows and freeze rule time ranges.
- Implemented custom normalized error envelope: `{"errors": [{"code", "detail", "attr"}]}`.
- Added request ID middleware that propagates `X-Request-ID` and logs request duration.
- Used Django transactions for lifecycle consistency and audit emission.
- Protected production settings with required environment validation and fail-closed configuration checks.

## Frontend Skills Demonstrated

- Built a React + TypeScript product UI using route-based screens and feature folders.
- Implemented authenticated route protection with `ProtectedRoute`.
- Built auth context that bootstraps sessions from refresh-cookie flow, stores access token client-side, and clears TanStack Query cache on logout/unauthorized events.
- Built a shared API client that:
  - Adds bearer access tokens.
  - Sends credentials for refresh-cookie support.
  - Auto-refreshes access tokens on 401.
  - Adds `X-Organization-Id`.
  - Blocks browser calls to `/api/v1/internal/`.
  - Parses API error envelopes.
- Implemented route coverage for:
  - Login.
  - Organizations.
  - Runbooks list/detail.
  - Workflow create/detail/review.
  - Executions list/detail.
  - Approvals inbox.
  - Policies list/detail.
  - Integrations list/detail.
  - Changes list/create/detail.
  - Settings.
- Used TanStack Query hooks and query keys for server state.
- Implemented live execution streaming with `fetch-event-source`, query-cache updates, stream-close handling, and polling fallback after repeated failures.
- Added page and hook tests using Vitest and Testing Library.

## DevOps / Platform Skills Demonstrated

- Built a local Docker Compose stack with services for PostgreSQL, PgBouncer, Django API, FastAPI AI, Python runner, and React web.
- Added health checks for PostgreSQL, PgBouncer, API, and AI containers.
- Configured API container to run Uvicorn ASGI with one worker to support process-local SSE event bus.
- Added Makefile targets for:
  - Bootstrap.
  - Compose lifecycle.
  - Migrations.
  - Seeding.
  - API, AI, runner, and web tests.
  - Linting and formatting.
  - Production checks.
  - Migration checks.
  - Security scans.
  - Full hardening checks.
- Built GitHub Actions CI with jobs for:
  - Web build, lint, format check, and Vitest.
  - Python compile, Ruff lint, and Ruff format check.
  - API tests against PostgreSQL 17.
  - Production Django deploy check.
  - Migration dry-run and migrate check.
  - Runner tests.
  - AI tests.
  - Python dependency audit.
  - npm audit.
  - Gitleaks secret scan.
  - Trivy filesystem vulnerability scan.
- Added production settings checks for required secrets, allowed hosts, CORS origins, runner token, integration key, dispatch token secret, HTTPS redirect, HSTS, secure cookies, CSP, admin disablement, and Prometheus scrape token enforcement.

## Security / Auth / Governance Skills Demonstrated

- Implemented JWT access-token authentication with HTTP-only refresh cookie.
- Added refresh-cookie path scoping under `/api/v1/auth/`.
- Implemented login and refresh rate limits via `django-ratelimit`.
- Implemented cached JWT user lookup to reduce repeated DB reads on authenticated requests.
- Implemented organization membership and role-based authorization.
- Required `X-Organization-Id` for organization-scoped endpoints and validated it against query/body organization IDs.
- Prevented browser client access to internal runner endpoints in the shared frontend API client.
- Added runner-only authentication with bearer token and separate `RunnerPrincipal`, intentionally not a Django user.
- Rejects valid user JWTs on internal runner endpoints to prevent user sessions from acting as runners.
- Uses constant-time comparison for runner bearer tokens and change dispatch token verification.
- Uses HMAC-derived change dispatch tokens with stored hashes.
- Rejects missing/placeholder `CHANGE_DISPATCH_TOKEN_SECRET` when generating dispatch tokens.
- Encrypts integration credentials with Fernet.
- Validates outbound integration webhook URLs to reduce SSRF risk:
  - HTTPS only.
  - No user info.
  - Blocks localhost/local hostnames.
  - Blocks metadata service IPs.
  - Blocks private, loopback, link-local, reserved, multicast, and unspecified addresses.
  - Blocks common internal service ports.
- Scrubs or rejects sensitive keys in audit metadata, integration previews, and change target metadata.
- Adds artifact checksum validation, file size limits, per-step artifact count limit, per-execution quota, and per-runner daily upload quota.
- Sanitizes artifact file names and prevents local artifact storage path traversal.
- Generates time-limited signed local artifact download URLs.
- Uses production security headers: HSTS, SSL redirect, content type nosniff, `X_FRAME_OPTIONS=DENY`, referrer policy, secure cookies, and CSP.

## Compliance / Audit-Readiness Skills Demonstrated

- Implemented append-only audit events:
  - Model prevents update/delete.
  - QuerySet prevents bulk update/delete.
  - Audit metadata is scrubbed and size-limited.
- Captures actor type, actor ID, actor label, event type, object type, object ID, organization ID, metadata, and occurrence timestamp.
- Supports audit object types across organizations, runbooks, workflows, executions, execution steps, approvals, policies, artifacts, integrations, operation profiles, change records, targets, bindings, windows, freeze rules, target locks, and dispatch eligibility checks.
- Emits audit events for key lifecycle transitions:
  - Workflow created, reviewed, published, archived.
  - Execution created, claimed, started, cancelled, failed, completed.
  - Execution step status changes and approval waits.
  - Approval requested, decided, timed out.
  - Policy and policy-rule CRUD.
  - Artifact uploaded and download URL created.
  - Integration created, updated, deactivated.
  - Change created, submitted, approval-bound, dispatch-reserved, status transitions.
- Implements change dossier integrity:
  - Canonical JSON SHA-256 hashing.
  - Frozen requested-input hash.
  - Frozen request snapshot hash.
  - Rebuild-and-compare validation to detect drift after submit.
- Enforces change request immutability after submit for core request fields and targets.
- Adds change windows, freeze rules, target locks, and dispatch eligibility snapshots for controlled production-target changes.
- Includes watchdog recovery paths for stuck executions and expired approvals, with audit events and metrics.

## Testing Practices

Quantifiable repo facts:

- 61 Django API test files under `apps/api/apps/**/tests/`.
- 17 AI/runner Python test files under `apps/ai/tests` and `apps/runner/runner/tests`.
- 18 frontend test files under `apps/web/src`.
- 741 Python test functions across API, AI, and runner test files.
- 135 frontend `test(...)` / `it(...)` cases across Vitest files.
- 39 Django migration files, excluding migration package `__init__.py` files.
- 89 markdown documentation files under `docs`.
- 588 files visible to `rg --files` in the repository.

Test coverage themes:

- API contract tests for runbooks, workflows, executions, approvals, and runner APIs.
- Service-layer tests for lifecycle transitions and domain invariants.
- Concurrency tests for execution claim behavior.
- Audit integration tests.
- Policy integration tests.
- Artifact service and internal upload API tests.
- Integration crypto and SSRF tests.
- Change immutability, hashing, transitions, execution binding, window service, and target-lock tests.
- Metrics, middleware, health, and production settings tests.
- Runner tests for client, poller, executor, orchestration, settings, shutdown, schemas, artifact uploader, and change binding.
- AI tests for parse, enrich, summarize, health, metrics, workflow parser, LLM client, and opt-in LLM parsing.
- Frontend tests for route pages, API client behavior, execution streaming events, and SSE integration handling.

## Data Modeling And Database Work

Implemented domain models:

- `User`.
- `Organization`.
- `Membership`.
- `Runbook`.
- `Workflow`.
- `Execution`.
- `ExecutionStep`.
- `ApprovalRequest`.
- `ApprovalDecision`.
- `Policy`.
- `PolicyRule`.
- `PolicyEvaluation`.
- `AuditEvent`.
- `Artifact`.
- `IntegrationConnection`.
- `IntegrationDeliveryAttempt`.
- `OperationProfile`.
- `ChangeRecord`.
- `ChangeTarget`.
- `ChangeExecutionBinding`.
- `ChangeWindow`.
- `FreezeRule`.
- `TargetLock`.
- `DispatchEligibilityCheck`.

Shared model patterns:

- `BaseModel` abstract model with UUID primary key, `created_at`, and `updated_at`.
- Direct organization foreign keys on tenant-scoped root records.
- Protective foreign keys for history-preserving relationships.
- Cascade only where rows are aggregate children, such as execution steps and policy rules.
- JSON fields for workflow definitions, snapshots, policy conditions, artifact metadata, integration config, requested inputs, and governance snapshots.
- Explicit database indexes for common organization/status/time queries.
- Check constraints for valid enum values and time-window validity.
- Unique constraints for workflow versions, runbook slugs, membership uniqueness, policy rule priority/name, execution step uniqueness, target uniqueness, and active target locks.

Notable modeling decisions:

- Workflow definitions are versioned by runbook.
- Executions store immutable workflow snapshots.
- Execution steps are materialized from workflow definitions at execution creation.
- Approval requests can target execution steps or change records.
- Policy evaluations store rule/condition context snapshots.
- Audit events are append-only and intentionally denormalized around actor/object metadata.
- Artifacts store checksums, storage keys, MIME type, size, runner uploader, and metadata.
- Change records store frozen hashes and snapshots for auditability.
- Target locks use a partial unique constraint to prevent concurrent active locks for the same production target.

## API Design

Public API structure:

- `/api/v1/auth/login/`.
- `/api/v1/auth/refresh/`.
- `/api/v1/auth/logout/`.
- `/api/v1/auth/me/`.
- `/api/v1/organizations/`.
- `/api/v1/organizations/{id}/members/`.
- `/api/v1/organizations/{id}/members/{membership_id}/`.
- `/api/v1/runbooks/`.
- `/api/v1/runbooks/{id}/mark-ready/`.
- `/api/v1/runbooks/{id}/archive/`.
- `/api/v1/workflows/`.
- `/api/v1/workflows/{id}/publish/`.
- `/api/v1/workflows/{id}/archive/`.
- `/api/v1/workflows/{id}/accept-review/`.
- `/api/v1/workflows/{id}/reject-review/`.
- `/api/v1/executions/`.
- `/api/v1/executions/{id}/cancel/`.
- `/api/v1/executions/{id}/policy-evaluations/`.
- `/api/v1/executions/{execution_id}/stream/`.
- `/api/v1/executions/{execution_id}/audit/`.
- `/api/v1/executions/{execution_id}/artifacts/`.
- `/api/v1/artifacts/{artifact_id}/download/`.
- `/api/v1/artifacts/{artifact_id}/content/`.
- `/api/v1/approvals/`.
- `/api/v1/approvals/{approval_request_id}/`.
- `/api/v1/approvals/{approval_request_id}/decide/`.
- `/api/v1/policies/`.
- `/api/v1/policies/{policy_id}/`.
- `/api/v1/policies/{policy_id}/rules/`.
- `/api/v1/policies/{policy_id}/rules/{rule_id}/`.
- `/api/v1/audit/`.
- `/api/v1/integrations/`.
- `/api/v1/integrations/{integration_id}/`.
- `/api/v1/integrations/{integration_id}/deactivate/`.
- `/api/v1/integrations/{integration_id}/delivery-attempts/`.
- `/api/v1/changes/`.
- `/api/v1/changes/operation-profiles/`.
- `/api/v1/changes/{change_id}/`.
- `/api/v1/changes/{change_id}/submit/`.
- `/api/v1/changes/{change_id}/window/`.
- `/api/v1/freeze-rules/`.
- `/api/v1/freeze-rules/{rule_id}/`.
- `/api/v1/freeze-rules/{rule_id}/deactivate/`.

Internal runner API structure:

- `/api/v1/internal/executions/claim-next/`.
- `/api/v1/internal/executions/{execution_id}/heartbeat/`.
- `/api/v1/internal/executions/{execution_id}/steps/{step_id}/start/`.
- `/api/v1/internal/executions/{execution_id}/steps/{step_id}/approval-status/`.
- `/api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`.
- `/api/v1/internal/executions/{execution_id}/complete/`.
- `/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/`.
- `/api/v1/internal/executions/{execution_id}/artifacts/`.
- `/api/v1/internal/changes/{change_id}/bind-execution/`.

API design patterns:

- Public APIs use DRF serializers and service-layer delegation.
- State changes use explicit `POST` action endpoints.
- Internal runner APIs use dedicated serializers and bearer-token authentication.
- API error responses are normalized into a consistent envelope.
- Organization-scoped APIs require membership and `X-Organization-Id`.
- SSE stream endpoint authenticates JWT, validates organization membership, sends replayable event IDs, heartbeats, terminal snapshots, and stream close events.

## AI / LLM Integration

- FastAPI service exposes:
  - `GET /health`.
  - `POST /parse/runbook`.
  - `POST /enrich/workflow`.
  - `POST /summarize/execution`.
  - `/metrics` and `/metrics/`.
- Default mode is deterministic and does not require an OpenAI API key.
- LLM parsing is opt-in via `AI_USE_LLM_PARSER=true`.
- OpenAI API key must be supplied explicitly for LLM mode.
- AI parse model is intentionally a human decision in settings; Django has no default model string.
- AI health checks:
  - Report OpenAI as disabled when LLM parsing is off.
  - Report degraded when LLM mode lacks required OpenAI configuration.
  - Use the OpenAI models endpoint for non-generative connectivity check.
  - Cache connectivity check results to avoid provider health-check amplification.
- LLM client supports:
  - Standard chat completions.
  - Structured completion parsing into Pydantic models.
  - Configurable timeout and max tokens.
- Deterministic parser extracts numbered runbook steps and falls back to default steps when none are found.
- Deterministic enrichment assigns risk/approval based on keyword categories.
- Deterministic summarizer generates completed/failed execution summaries and key outcomes.
- Django validates AI output against candidate invariants and a workflow JSON schema before persistence.
- Django performs the AI call outside the DB transaction before allocating workflow version.

## Runner / Execution Architecture

- Python runner loads environment config with Pydantic.
- Startup validation requires non-placeholder runner registration token.
- Poller repeatedly calls `claim-next`.
- Empty queue and error paths use backoff.
- Runner processes one claimed execution at a time.
- Claimed execution includes workflow snapshot, steps, claim token, and optional change-binding fields.
- Executor starts a heartbeat thread while execution is active.
- Runner asks Django to start each step; Django returns runner action:
  - `run`.
  - `wait_for_approval`.
  - `blocked`.
- Runner polls approval status when Django puts a step into waiting-for-approval state.
- Runner simulates command execution:
  - `FAIL_STEP` marker produces a failed step.
  - Otherwise the runner sleeps briefly and reports success.
- Runner uploads stdout/stderr artifacts before reporting terminal step status.
- Runner completes execution as succeeded or failed after sequential step processing.
- SIGTERM handler requests graceful shutdown and starts a hard-exit watchdog after 60 seconds.
- Django includes watchdog services for:
  - Stuck executions with stale heartbeats.
  - Expired approval requests.
- Runner does not connect to PostgreSQL, call FastAPI, or mutate public APIs.

## Observability / Logging / Metrics

- Django request middleware:
  - Generates or propagates `X-Request-ID`.
  - Binds request context into structlog contextvars.
  - Logs method, path, status code, and duration.
- AI service middleware:
  - Generates or propagates `X-Request-ID`.
  - Logs request completion with duration.
  - Records metrics per AI operation.
- Runner:
  - Emits JSON logs to stdout.
  - Includes runner ID, runner version, execution IDs, step IDs, and retry context.
  - Logs runner API request attempts, retries, status codes, and durations.
- Prometheus metrics implemented for:
  - Django execution lifecycle events.
  - Django execution service operation latency.
  - Step transitions.
  - Step durations.
  - Approval latency.
  - Integration dispatch duration.
  - Artifact upload bytes.
  - Stuck execution recoveries.
  - AI request counts, latency, errors, and operation durations.
- Metrics endpoint can be token-protected in production when enabled.
- Health endpoints:
  - API live check.
  - API readiness check for DB and migrations.
  - API detailed health check for DB and AI.
  - AI health check with OpenAI dependency status.
  - Compose health checks for PostgreSQL, PgBouncer, API, and AI.

## Product / Business-Relevant Accomplishments

Use these as product-oriented bullets without claiming external adoption:

- Turned free-form operational runbooks into versioned workflow definitions and execution histories.
- Created a governed execution model where high-risk operational steps can require approval before runner execution.
- Added policy rules for risk level, step type, and time-window conditions with outcomes including approval required, auto approve, and block.
- Added organization-scoped multi-user controls with role-based access.
- Added audit trails across workflow, execution, approval, policy, artifact, integration, and change-management domains.
- Added artifact capture for runner stdout/stderr and other files, including checksum validation and time-limited download flow.
- Added integration delivery model for webhooks with delivery attempts, latency capture, and safe payload previews.
- Added change-management workflow for production-target operations:
  - Operation profiles.
  - Production targets.
  - Change approval.
  - Scheduling/dispatchability.
  - Frozen request snapshots.
  - Dispatch tokens.
  - Runner binding.
  - Change windows.
  - Freeze rules.
  - Target locks.
  - Dispatch eligibility checks.
- Added live execution detail updates through SSE, plus frontend fallback to polling.
- Added local hardening workflow so security, migration, production settings, dependency, secret, and filesystem checks can be run before release-oriented changes.

## Quantifiable Implementation Facts

Only use these as implementation facts, not performance or usage claims:

- 4 application services: Django API, React web, FastAPI AI, Python runner.
- 6-service local Compose stack including PostgreSQL and PgBouncer.
- 24 implemented domain models plus an abstract shared base model.
- 39 Django migration files.
- 61 Django API test files.
- 17 AI/runner Python test files.
- 18 frontend test files.
- 741 Python test functions across API, AI, and runner.
- 135 frontend Vitest test cases.
- 89 markdown documentation files under `docs`.
- 588 files visible to `rg --files`.
- 1 GitHub Actions workflow with jobs for web, Python lint, API tests, migration check, runner tests, AI tests, Python dependency audit, npm audit, secret scan, and container scan.
- 11 feature API modules in the React frontend.
- 18 protected/product frontend route entries plus login.

## Strong Resume Bullet Bank

### Architecture / Platform

- Architected a Docker-first governed execution platform split across Django, React, FastAPI, a Python runner, PostgreSQL, and PgBouncer, with Django as the sole persistence-owning control plane.
- Defined and enforced service boundaries so browser clients call only public Django APIs, runners use dedicated internal APIs, and AI services remain stateless/advisory.
- Modeled versioned workflows and immutable execution snapshots to preserve historical explainability after workflow definitions evolve.
- Implemented explicit domain lifecycle services for runbooks, workflows, executions, approvals, policies, artifacts, integrations, and production change records.

### Backend / API

- Built versioned DRF APIs under `/api/v1/` with normalized error envelopes, organization scoping, service-layer orchestration, and action endpoints for state transitions.
- Implemented runner-only internal APIs for claim, heartbeat, step start, approval polling, step update, completion, artifact upload, and change-execution binding.
- Used PostgreSQL row locks and `skip_locked` queries to support concurrent-safe execution claiming and watchdog recovery.
- Added JSON-schema validation and semantic validation for workflow definitions before persistence and execution materialization.

### Security / Governance

- Implemented JWT access authentication, HTTP-only refresh cookies, organization memberships, role-based permissions, and explicit organization-context validation.
- Added runner bearer-token authentication with a separate runner principal and claim-token ownership checks for all internal execution mutations.
- Built append-only audit logging with actor/object metadata, sensitive-key scrubbing, metadata size limits, and update/delete protections.
- Added Fernet-encrypted integration credentials and SSRF validation for outbound webhook URLs.
- Implemented checksum, quota, filename sanitization, path traversal, and signed download controls for runner artifacts.

### AI / LLM

- Integrated a FastAPI AI service as a stateless advisory boundary for runbook parsing, workflow enrichment, and execution summarization.
- Added deterministic default parsing/enrichment/summarization plus opt-in OpenAI-backed parsing guarded by explicit configuration and health checks.
- Validated AI-generated workflow candidates in Django before version allocation and persistence.

### Runner / Execution

- Built a Python runner with Pydantic contracts, HTTP retries, claim-token validation, heartbeat thread, approval polling, artifact uploads, and graceful SIGTERM handling.
- Implemented governed step execution flow where the runner asks Django for a `runner_action` before executing each step.
- Added watchdog paths for stale heartbeats and approval timeouts, emitting audit events and metrics during recovery.

### Frontend

- Built a TypeScript React operator UI with authenticated routes, feature-level API modules, TanStack Query hooks, and organization-aware API requests.
- Implemented live execution streaming via Server-Sent Events with cache updates, terminal stream handling, and polling fallback after repeated stream failures.
- Added route-level tests for runbooks, workflows, executions, approvals, policies, integrations, changes, organizations, and shared API behavior.

### DevOps / Quality

- Created a Docker Compose local platform with health checks and Makefile workflows for bootstrap, migrations, seed data, tests, lint, formatting, and hardening checks.
- Built GitHub Actions CI covering web build/lint/test, Python lint/format, API tests with PostgreSQL, migration safety, runner tests, AI tests, dependency audits, secret scanning, and container scanning.
- Added production settings validation for required secrets, HTTPS/HSTS, secure cookies, CSP, admin disablement, CORS, allowed hosts, metrics token protection, and runner/integration secrets.

## Interview Talking Points

- Why Django owns persistence: centralizes validation, transactions, audit, state transitions, and tenant scoping.
- Why FastAPI AI is advisory: AI output is untrusted derived data and must not assign versions or persist workflows.
- Why runner uses internal APIs only: keeps execution history and state transitions controlled by Django.
- Why execution snapshots matter: historical executions remain explainable even if workflow definitions change later.
- Why claim tokens matter: `runner_id` alone is not enough; claim tokens bind ownership to a specific claim.
- Why change dossiers are hashed: submitted production changes need drift detection and reviewable immutable evidence.
- Why target locks use a partial unique constraint: database-level guard prevents concurrent active locks for the same production target.
- Why local SSE event bus is single-worker: in-memory process-local subscribers and buffers require external broker before multi-worker scaling.
- Why production settings fail closed: missing secrets or metrics tokens should stop startup rather than silently weaken security posture.

## Claims To Avoid Unless More Evidence Is Added

- Do not claim production deployment or live AWS infrastructure; `infra/aws` is a placeholder.
- Do not claim real sandboxed command execution; current runner execution is simulated and `runner/sandbox.py` is a placeholder.
- Do not claim multiple runner concurrency per process; current runner processes one claimed execution at a time.
- Do not claim distributed event streaming; SSE event bus is process-local and documented as single-worker.
- Do not claim S3 artifact storage is implemented; settings validate S3 configuration, but storage implementation is local filesystem only.
- Do not claim compliance certification such as SOC 2, HIPAA, ISO 27001, or PCI.
- Do not claim LLM parsing is enabled by default; it is opt-in and deterministic mode is default.
- Do not claim performance improvements, uptime, scale, user count, cost reduction, or revenue impact without external measurements.
- Do not claim direct production hardening is complete; the repo includes hardening checks and production settings foundations.

## Customization Angles By Target Role

### Backend Engineer

Emphasize Django/DRF service layers, PostgreSQL constraints, transactions, row locks, API contracts, auth, audit, and runner internal APIs.

### Platform Engineer

Emphasize Docker Compose, PgBouncer, health/readiness checks, CI, hardening gates, production settings, metrics, logging, and service boundaries.

### Security / Governance Engineer

Emphasize organization-scoped RBAC, runner authentication, audit immutability, sensitive metadata scrubbing, encrypted credentials, SSRF protection, artifact controls, change dossiers, freeze rules, target locks, and dispatch tokens.

### Full-Stack Engineer

Emphasize React/TypeScript UI, TanStack Query, auth refresh flow, SSE streaming, DRF APIs, and cross-service execution flows.

### AI Platform Engineer

Emphasize advisory AI boundary, deterministic fallback, opt-in OpenAI structured parsing, AI health checks, request IDs, Prometheus metrics, schema validation, and Django-owned persistence.

## Source Pointers

Primary implementation areas:

- `apps/api`: Django control plane.
- `apps/web`: React frontend.
- `apps/ai`: FastAPI AI service.
- `apps/runner`: Python runner.
- `packages/workflow-schema/workflow.schema.json`: workflow schema used by Django validation.
- `docker-compose.yml`: local multi-service stack.
- `Makefile`: local operational commands.
- `.github/workflows/ci.yml`: CI, audit, and scan gates.
- `docs/architecture`: architecture and service-boundary docs.
- `docs/runbooks`: operational runbooks.
- `docs/blueprints`: planning docs; do not treat blueprints as implemented unless code confirms it.
