# Currently Implemented Runbook Platform Blueprint

This blueprint documents the repository as implemented in the current working tree. It treats source code as the authority and treats older blueprints, reports, and README claims as historical context unless current code proves the capability exists.

Status language used below:

| Status | Meaning |
|---|---|
| Implemented and verified | Confirmed by source inspection in this task. Tests may exist, but the full suite was not run. |
| Implemented but needs verification | Code exists, but operational behavior needs manual, integration, or production-like verification. |
| Partially implemented | Meaningful code exists, but important parts of the capability are missing or limited. |
| Documented only / blueprint only | Described in docs or blueprints without implemented code support. |
| Missing | No meaningful implementation found. |

## 1. Executive Summary

Runbook Platform is currently a Docker-first, multi-service governed operations platform. The working product shape is: users create organizations, write runbooks, ask Django to create workflow definitions through the AI boundary, review/publish workflows, create executions, let a Python runner claim and execute work through Django internal APIs, and inspect execution state, approvals, policies, audit events, artifacts, change records, evidence bundles, and auditor views through the React web app.

The strongest implemented value proposition is not generic automation. It is a governed change-execution control plane: approvals, policy evaluation, audit events, artifacts, change dossiers, dispatch gates, verification, breakglass, sealed evidence bundles, and auditor control coverage all have real Django models, services, APIs, and visible frontend routes. The implementation is much more complete than the oldest phase-10 roadmap language in `docs/blueprints/phase10/phase-10-platform-expansion-roadmap-blueprint.md` and `README.md` suggests.

The core workflow currently implemented is:

1. Browser user authenticates and selects an organization.
2. User creates a runbook in `apps/web/src/features/runbooks/`.
3. User creates a workflow; Django calls FastAPI AI through `apps/runbooks/ai_client.py` and `apps/workflows/internal_clients.py`.
4. User reviews, validates, and publishes the workflow through `apps/api/apps/workflows/`.
5. User or change-dispatch flow creates an execution through `apps/api/apps/executions/`.
6. Runner registers/polls/claims via `/api/v1/internal/...`, executes simulated or local-process work, uploads artifacts, sends heartbeats, and completes the execution.
7. UI observes status through public APIs and SSE in `apps/web/src/features/executions/useExecutionStream.ts`.

Technical maturity is strongest in the Django control plane. The API layer, service layer, domain models, migrations, tests, audit/evidence boundaries, and CI are substantial. The runner has moved beyond pure simulation and now includes a `SandboxProvider` abstraction plus a `local_process` provider, typed pilot actions, step timeouts, stdout/stderr capture, artifact collection, cancellation checks, and resource limit hooks in `apps/runner/runner/sandbox/`. However, this is not a production-safe execution substrate: it is local-process execution, not a hardened container/VM sandbox with network policy, credential brokerage, or durable object storage.

The biggest implementation gaps are:

- Production-safe runner isolation and target connectivity.
- General secret and credential brokerage; `apps/runner/runner/secrets/null_provider.py` fails closed and `docs/blueprints/pilot/pilot-phase-d-secrets-credential-brokerage-blueprint.md` is blueprint-only.
- Durable artifact/evidence storage; `apps/api/apps/artifacts/storage.py` intentionally supports only local filesystem storage.
- Production deployment/IaC; `infra/*/README.md` files are placeholders and `docs/blueprints/phase10/phase-10-10-aws-deployment-workflows-blueprint.md` remains planning.
- Multi-worker/event-bus readiness; execution SSE uses an in-process event bus in `apps/api/apps/executions/event_bus.py`.
- Enterprise identity and fine-grained authorization beyond local JWT auth, organization roles, and auditor grants.

Readiness verdict: the project is credible demo-grade and close to controlled technical pilot-grade for non-production or tightly scoped internal pilot scenarios. It is not production-grade for customer production changes. The reason is narrow: the governance control plane is deep, but the execution, secrets, storage, deployment, and operational-hardening layers are not yet safe enough for real customer production operations.

## 2. Repository and System Overview

| Area | Current implementation |
|---|---|
| Monorepo | Root Makefile, Docker Compose, Python/Node app folders, shared packages, infra placeholders, docs, and GitHub Actions. Key files: `Makefile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `pyproject.toml`, `.pre-commit-config.yaml`. |
| Frontend | React 19 + Vite + React Router + TanStack Query in `apps/web`. Browser calls Django only through `apps/web/src/shared/api/client.ts`. Routes live in `apps/web/src/app/router.tsx`. |
| Django API/control plane | Django/DRF app in `apps/api`. Owns PostgreSQL persistence, domain models, API contracts, service-layer business logic, auth, runner internal APIs, audit, evidence, and change governance. Settings are in `apps/api/config/settings/`. |
| Runner | Python runner in `apps/runner`. Talks to Django internal APIs through `apps/runner/runner/client.py`, polls in `apps/runner/runner/poller.py`, executes in `apps/runner/runner/executor.py`, and uses typed actions/sandbox modules under `apps/runner/runner/actions/` and `apps/runner/runner/sandbox/`. |
| AI service | FastAPI service in `apps/ai`. Routes include health, parse, enrich, summarize, and metrics. Default behavior is deterministic; optional OpenAI-backed behavior is gated by settings. |
| Database | PostgreSQL 17 in `docker-compose.yml`. Django is the only app service that should connect to it. PgBouncer is included in compose and prod settings support PgBouncer transaction pooling. |
| Workflow schema/packages | V1/v2 JSON schemas and action catalog live in `packages/workflow-schema/`. `packages/contracts/workflow/workflow.schema.json` is a duplicate/older contract scaffold. `packages/sdk/src/index.ts` is placeholder. |
| Docker/local dev | `docker-compose.yml` defines `postgres`, `pgbouncer`, `api`, `ai`, `runner`, and `web`. `Makefile` wraps startup, tests, linting, migrations, security checks, and hardening checks. |
| CI/testing | `.github/workflows/ci.yml` runs web build/lint/format/tests, Python lint/compile, API tests, migration checks, runner tests, AI tests, pip-audit, npm audit, gitleaks, and Trivy image scans. |
| Docs/blueprints | `docs/architecture/`, `docs/api/`, `docs/blueprints/foundation/`, `docs/blueprints/phase10/`, `docs/blueprints/phase11/`, `docs/blueprints/pilot/`, reports, runbooks, and implemented notes. Several docs are historical and understate current code. |

The repository structure found by inspection:

- `apps/api`: Django control plane, domain apps, migrations, tests, settings, URLs.
- `apps/web`: React web app, feature modules, tests, API client, routes.
- `apps/runner`: Python runner, internal API client, poller, executor, actions, sandbox, tests.
- `apps/ai`: FastAPI AI boundary, deterministic/optional LLM services, tests.
- `packages/workflow-schema`: JSON schemas and pilot action catalog.
- `packages/contracts`: older workflow contract package.
- `packages/sdk`: placeholder TypeScript SDK.
- `infra`: placeholder folders for AWS, Docker, compose, scripts.
- `.github`: CI workflow only; no deployment workflow found.

## 3. Core Architecture Invariants

| Invariant | Implemented status | Source files that prove it | Remaining risks |
|---|---|---|---|
| Django is the control plane. | Implemented and verified. Django owns models, migrations, transactions, API routing, state transitions, audit, artifacts, changes, evidence, and runner internal contracts. | `apps/api/config/settings/base.py`, `apps/api/config/api_v1_urls.py`, `apps/api/apps/*/models.py`, `apps/api/apps/*/services.py`, `docs/architecture/service-boundaries.md`. | Service-layer discipline is strong but not machine-enforced everywhere; future changes could bypass services if review is weak. |
| Runner talks only to Django internal APIs. | Implemented and verified. Runner client methods target Django internal endpoints; no DB or AI client found in runner. | `apps/runner/runner/client.py`, `apps/runner/runner/poller.py`, `apps/runner/runner/executor.py`, `apps/api/config/api_v1_urls.py`, `docs/api/internal-runner-api.md`. | The runner does make outbound HTTP for the `http_request` action, so "only Django" applies to control-plane APIs, not step payload behavior. SSRF/network policy still needs stronger controls. |
| Frontend talks only to Django public APIs. | Implemented and verified. `apiRequest` rejects internal paths and all feature API modules use `/api/v1/...`. | `apps/web/src/shared/api/client.ts`, `apps/web/src/features/*/api/*.ts`, `apps/web/src/app/router.tsx`. | Future frontend code could bypass `apiRequest`; no static gate was found beyond tests/lint. |
| AI service is advisory/stateless. | Implemented and verified. FastAPI has no persistence layer; Django validates and persists derived workflow data. | `apps/ai/app/main.py`, `apps/ai/app/api/routes/*.py`, `apps/ai/app/services/*.py`, `apps/runbooks/ai_client.py`, `apps/workflows/internal_clients.py`, `apps/workflows/services.py`. | Optional OpenAI calls introduce external availability/cost/data-handling concerns; default deterministic parser is limited. |
| Business logic belongs in services. | Mostly implemented. Major domains use `services.py` or dedicated selectors/access modules; views are usually transport adapters. | `apps/api/apps/workflows/services.py`, `apps/api/apps/executions/services.py`, `apps/api/apps/approvals/services.py`, `apps/api/apps/policies/services.py`, `apps/api/apps/changes/services.py`, `apps/api/apps/evidence/services.py`, `apps/api/apps/auditor/services.py`. | Some APIView classes still contain orchestration and projection logic, especially in newer governance surfaces; keep auditing during feature work. |
| API versioning. | Implemented and verified. Product APIs are under `/api/v1/`; runner-only APIs are under `/api/v1/internal/`; health/metrics live outside versioning. | `apps/api/config/urls.py`, `apps/api/config/api_v1_urls.py`, `docs/api/rest-api-v1.md`, `docs/api/internal-runner-api.md`. | Some docs lag current endpoints; API docs are not complete for every phase-11/pilot endpoint. |
| UUID/domain model conventions. | Implemented and verified. Base model uses UUID primary keys and timestamps; domain models inherit it. | `apps/api/apps/common/models.py`, `apps/api/apps/*/models.py`. | Admin models and some external references may still expose human labels; public URLs use UUIDs for domain resources. |
| Organization scoping. | Implemented and verified. Public APIs require `X-Organization-Id` and membership checks for most domain resources. | `apps/api/apps/common/org_context.py`, `apps/api/apps/common/permissions.py`, `apps/api/apps/organizations/models.py`, `apps/web/src/shared/api/client.ts`. | Granularity is role-based and coarse for many resources; enterprise team/project/resource scopes are incomplete. |
| Audit/evidence boundary. | Implemented but needs operational verification. Audit events are append-only and evidence bundles materialize/seal deterministic packages, but storage is local-only. | `apps/api/apps/audit/models.py`, `apps/api/apps/audit/services.py`, `apps/api/apps/evidence/models.py`, `apps/api/apps/evidence/services.py`, `apps/api/apps/evidence/storage.py`. | Append-only is Django-level, not database immutability. Evidence byte durability depends on local filesystem until object storage is built. |

## 4. Implemented Product Capabilities

| Capability | What the user/operator can do | Frontend route/component | API endpoints involved | Backend/runner/AI involvement | Current limitations | Test coverage |
|---|---|---|---|---|---|---|
| Login/session bootstrap | Log in, refresh via cookie, load current user and memberships, log out. | `/login`, `apps/web/src/features/auth/`, `AuthProvider`, `ProtectedRoute`. | `/api/v1/auth/login/`, `/api/v1/auth/refresh/`, `/api/v1/auth/logout/`, `/api/v1/auth/me/`. | `apps/users/views.py`, `apps/users/authentication.py`, SimpleJWT. | No SSO/SAML/SCIM; role model is organization-level. Refresh rotation path should be reviewed before enabling. | API tests under `apps/api/apps/users/tests/`; web tests under auth feature. |
| Organizations and memberships | Create/list organizations and manage members. | `/organizations`, `/settings`, org selector in `AppLayout`. | `/api/v1/organizations/`, member routes in `apps/organizations/views.py`. | `Organization`, `Membership`, org context and permissions. | No billing/workspace provisioning; membership permissions are coarse. | `apps/api/apps/organizations/tests/`; web org tests. |
| Runbook CRUD/status | Create, list, view, mark ready, archive runbooks. | `/runbooks`, `/runbooks/:runbookId`. | `/api/v1/runbooks/`, `/mark-ready/`, `/archive/`. | `apps/runbooks/models.py`, `serializers.py`, `views.py`, `services.py`. | Raw content is stored; no rich editor or import workflow found. | `apps/api/apps/runbooks/tests/`; web runbook tests. |
| AI-assisted workflow creation | Generate a draft workflow from runbook content through Django-to-AI boundary. | `/workflows/new`, workflow review/detail pages. | `POST /api/v1/workflows/`. | Django `WorkflowService`; `RunbookAiClient`; FastAPI `/parse/runbook` and `/enrich/workflow`. | Default parser is deterministic and simplistic; LLM mode is optional and needs configured OpenAI key/model. | `apps/api/apps/workflows/tests/`, `apps/ai/tests/`, web workflow tests. |
| Workflow lifecycle | List/detail, validate, publish, archive, accept/reject AI review, create v2 draft. | `/workflows`, `/workflows/:workflowId`, `/workflows/:workflowId/review`. | `/api/v1/workflows/`, `/publish/`, `/archive/`, `/accept-review/`, `/reject-review/`, `/create-v2-draft/`, `/validate/`. | `apps/workflows/models.py`, `services.py`, `validators.py`, `schema_loader.py`, `action_catalog.py`. | V2 support exists but product UX and action breadth are still pilot-oriented. | Workflow API/service tests plus schema tests. |
| Execution creation/list/detail/cancel | Start executions from published workflows, inspect materialized steps, cancel queued/active work. | `/executions`, `/executions/:executionId`. | `/api/v1/executions/`, `/cancel/`, `/policy-evaluations/`, `/api/v1/executions/:id/stream/`. | `apps/executions/models.py`, `services.py`, `views.py`, `stream_views.py`. | Active cancellation is cooperative through heartbeat; SSE is process-local; list caching needs production tuning. | `apps/api/apps/executions/tests/`; web execution tests. |
| Live execution status | Browser receives SSE updates and falls back to polling. | `apps/web/src/features/executions/useExecutionStream.ts`, execution detail UI. | `/api/v1/executions/<id>/stream/`. | `apps/executions/event_bus.py`, `stream_views.py`. | In-process ring buffer only; not safe across multiple API workers or restarts. | API/web stream tests exist; production topology not verified. |
| Runner registration and liveness | Register runners, heartbeat, view/disable/drain/revoke runners and pools. | `/runners`, `/runners/pools/:poolId`, `/runners/runners/:runnerId`, `/runners/routes`. | Public runner pool/routes APIs plus internal `/api/v1/internal/runners/register/` and `/heartbeat/`. | `apps/runners/models.py`, `services.py`, `views.py`; runner `main.py`, `state.py`. | Per-runner tokens exist, but deployment and secure token distribution are not productionized. | `apps/api/apps/runners/tests/`, `apps/runner/runner/tests/test_registration.py`. |
| Runner claim/execution loop | Runner polls, claims eligible work, sends heartbeat, runs steps, uploads artifacts, completes execution. | Operator sees status in executions/runners UI. | `/api/v1/internal/executions/claim-next/`, heartbeat, step-start, approval-status, step-update, complete. | `apps/runner/runner/poller.py`, `executor.py`, `client.py`; `apps/executions/internal_views.py`, `services.py`. | One execution at a time per runner process; production queue/backpressure remains limited. | Runner tests cover poller, client, executor, orchestration, shutdown. |
| Simulated execution mode | Run synthetic steps for demos/tests without real command execution. | Execution detail. | Same internal execution APIs. | `Executor._execute_command` simulated path; stdout/stderr artifact uploads. | Demo behavior can mislead if not disclosed; `FAIL_STEP` marker drives failure. | Runner executor tests. |
| Local-process sandbox execution | Execute v1 command/shell steps and v2 `shell_command` steps in a per-step workspace with timeouts, output capture, artifact collection, cleanup. | Execution detail/artifact UI. | Internal execution + artifact upload APIs. | `apps/runner/runner/sandbox/local_process.py`, `workspace.py`, `streams.py`, `redaction.py`; `actions/shell_command.py`. | Local subprocess, not container/VM isolation. Network egress, filesystem, user isolation, and credentials are not production-safe. | Runner sandbox/action tests. |
| Typed pilot actions | Execute/validate `manual_task`, `approval_gate`, `shell_command`, `http_request`, `artifact_assertion`. | Workflow v2/detail and execution UI. | Workflow v2 validation; internal step-start/update. | `apps/runner/runner/actions/registry.py`, action handler files, `packages/workflow-schema/action-catalog.pilot.v1.json`. | Action catalog is narrow; shell schema/runtime have some shape mismatch risk; `http_request` needs stronger network policy. | `test_action_dispatch.py`, `test_action_handlers.py`, workflow validator tests. |
| Approvals | See pending approval requests, approve/reject, unblock gated steps. | `/approvals`. | `/api/v1/approvals/`, `/<id>/`, `/<id>/decide/`, internal approval-status. | `apps/approvals/models.py`, `services.py`, `views.py`; execution step-start gate. | Routing is policy/role limited; separation of duties is not comprehensive. | Approval API/service tests and runner approval loop tests. |
| Policies | Create/update policies and rules; enforce approval/block/auto-approve decisions at step start. | `/policies`, `/policies/:policyId`. | `/api/v1/policies/`, `/rules/`, execution policy evaluations. | `apps/policies/models.py`, `services.py`, `views.py`; execution step-start. | Condition language is deliberately structured/narrow; policy UX likely needs real-user validation. | Policy tests. |
| Audit trail | Persist audit events for domain actions and inspect audit records. | Audit surfaces in execution/change/auditor pages. | `/api/v1/audit/`, `/api/v1/executions/<id>/audit/`. | `apps/audit/models.py`, `services.py`, `views.py`. | Append-only enforced by model/queryset, not a separate immutable datastore. | Audit tests. |
| Artifacts | Runner uploads stdout/stderr/files; users list and download artifacts. | Execution artifact UI under execution detail. | Public execution artifacts/download/content; internal runner artifact upload routes. | `apps/artifacts/models.py`, `services.py`, `storage.py`; runner `artifact_uploader.py`. | Storage is local filesystem only; no S3 backend. Byte-level secret redaction is limited. | Artifact API/service tests and runner uploader tests. |
| Integrations | Configure Slack/generic webhooks and view delivery attempts. | `/integrations`, `/integrations/:integrationId`. | `/api/v1/integrations/`, deactivate, delivery-attempt routes. | `apps/integrations/models.py`, `services.py`, `ssrf.py`. | Only webhook-style integrations found; dispatch is synchronous/budgeted; no Jira/PagerDuty-specific API flow beyond type scaffolding. | Integration tests. |
| Change records/dossiers | Create, submit, approve/reject, schedule, dispatch, and inspect governed change records. | `/changes`, `/changes/new`, `/changes/:changeId`. | `/api/v1/changes/`, submit, dispatch, window, preflight/latest, verification, close, exceptions. | `apps/changes/models.py`, `services.py`, `views.py`. | Complex lifecycle needs end-to-end manual verification; customer-specific templates not mature. | Extensive change tests. |
| Change windows/freezes/locks | Define windows/freezes, preflight dispatch eligibility, enforce target locks. | `/freeze-rules`, change detail/preflight UI. | `/api/v1/freeze-rules/`, `/api/v1/changes/<id>/window/`, preflight routes. | `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`. | Timezone/business-calendar edge cases need real-world validation. | Phase 11.2 implemented note and tests. |
| Verification/closure | Define verification plans/checks, submit verification results, close changes. | Change detail verification and close UI. | `/verification-plan/`, `/verification-results/`, `/close/`. | `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`. | Some checks are manual/metadata based; external assertions are not broadly integrated. | Change verification tests. |
| Emergency/breakglass/retro review | Create exceptions, activate/end breakglass sessions, track retro reviews. | `/changes/new/emergency`, `/retro-reviews`. | Exception routes, breakglass activate/end, retro review inbox/routes, internal breakglass heartbeat. | `ChangeException`, `BreakglassSession`, `RetroReview`, runner breakglass contract. | Needs operational policy and human-process validation. | Change and runner breakglass tests. |
| Evidence bundles/exports/legal hold | Materialize, inspect, seal, download, export/redact evidence bundles; create/release legal holds. | Evidence UI integrated into change/audit pages. | Evidence bundle, manifest, completeness, seal, invalidate, download/content, export, legal-hold routes. | `apps/evidence/models.py`, `services.py`, `storage.py`. | Local-only storage undermines production evidence durability; database immutability is application-level. | Evidence public API, export, model tests. |
| Auditor workspace/control coverage | Scoped audit search/detail, external references, service catalog, control mapping, coverage recompute, access grants. | `/audit/changes`, `/audit/changes/:changeId`, `/audit/access`. | Auditor routes in `apps/auditor/urls.py`. | `apps/auditor/models.py`, `services.py`, `selectors.py`, `coverage.py`, `access.py`. | Enterprise auditor workflows need customer validation; external refresh clients are limited/stubbed. | Auditor API/access/coverage tests. |
| Health/metrics/ops commands | Check live/readiness/health, expose metrics, seed dev data, wait for DB, recover stuck executions, cleanup expired evidence storage. | Operator/dev only. | `/health/live`, `/health/ready/`, `/health/`, `/metrics/`. | `apps/common/health.py`, `apps/common/metrics.py`, management commands. | Metrics exposure must be carefully configured in prod; operational runbooks need live drills. | CI and command-specific tests where present. |

## 5. Backend / Django Control Plane

Installed apps are defined in `apps/api/config/settings/base.py`:

- Django/platform: `django_prometheus`, `django.contrib.admin`, `auth`, `contenttypes`, `sessions`, `messages`, `staticfiles`, `rest_framework`, `rest_framework_simplejwt`, `corsheaders`.
- Domain apps: `apps.users`, `apps.common`, `apps.organizations`, `apps.runbooks`, `apps.workflows`, `apps.executions`, `apps.approvals`, `apps.policies`, `apps.audit`, `apps.artifacts`, `apps.integrations`, `apps.changes`, `apps.evidence`, `apps.auditor`, `apps.runners`.

Implemented domain models include:

| App | Real models |
|---|---|
| `common` | `BaseModel` UUID/timestamp base. |
| `users` | Custom `User` with email login. |
| `organizations` | `Organization`, `Membership` with owner/admin/operator/viewer roles. |
| `runbooks` | `Runbook` with draft/ready/archived status. |
| `workflows` | `Workflow` with versioning, status, definition JSON, validation status/report, AI review fields. |
| `executions` | `Execution`, `ExecutionStep` with runner claim, heartbeat, cancellation, sandbox metadata, step statuses. |
| `approvals` | `ApprovalRequest`, `ApprovalDecision`. |
| `policies` | `Policy`, `PolicyRule`, `PolicyEvaluation`. |
| `audit` | Append-only `AuditEvent`. |
| `artifacts` | `Artifact` metadata and upload status. |
| `integrations` | `IntegrationConnection`, `IntegrationDeliveryAttempt`. |
| `runners` | `RunnerPool`, `Runner`, `RunnerRegistrationToken`, `TargetConnectivityRoute`, `ExecutionLease`. |
| `changes` | `OperationProfile`, `ChangeRecord`, targets, execution binding, windows, freezes, locks, verification, exceptions, breakglass, retro review, closure. |
| `evidence` | `EvidenceBundle`, items, redaction policies, exports, retention policies, legal holds. |
| `auditor` | External references, service catalog, control mapping profiles, coverage, auditor grants. |

Service layer is real and substantial. Key files:

- `apps/api/apps/workflows/services.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/integrations/services.py`
- `apps/api/apps/changes/services.py`
- `apps/api/apps/evidence/services.py`
- `apps/api/apps/auditor/services.py`
- Supporting selectors/access files such as `apps/api/apps/auditor/selectors.py`, `apps/api/apps/auditor/access.py`, and `apps/api/apps/auditor/coverage.py`.

Serializers/views/viewsets are real across the domain apps. Public route aggregation lives in `apps/api/config/api_v1_urls.py`. DRF routers are used for organizations, runbooks, workflows, executions, runner resources, and other app-specific URL modules.

Public API routes include at least:

- Auth: `/api/v1/auth/...`
- Organizations: `/api/v1/organizations/...`
- Runbooks: `/api/v1/runbooks/...`
- Workflows: `/api/v1/workflows/...`
- Executions: `/api/v1/executions/...`
- Approvals: `/api/v1/approvals/...`
- Policies: `/api/v1/policies/...`
- Audit: `/api/v1/audit/...`
- Artifacts: `/api/v1/executions/<id>/artifacts/`, `/api/v1/artifacts/<id>/download/`, content token route.
- Integrations: `/api/v1/integrations/...`
- Changes: `/api/v1/changes/...`
- Freeze rules: `/api/v1/freeze-rules/...`
- Evidence: `/api/v1/changes/<id>/evidence-bundles/...`, evidence export/legal hold routes.
- Auditor: `/api/v1/audit/changes/...`, external references, service catalog, control mappings, access grants.
- Runners: runner pools, runners, registration tokens, target routes, eligibility.

Internal runner API routes include:

- `/api/v1/internal/runners/register/`
- `/api/v1/internal/runners/heartbeat/`
- `/api/v1/internal/executions/claim-next/`
- `/api/v1/internal/executions/<id>/heartbeat/`
- `/api/v1/internal/executions/<id>/steps/<step_id>/start/`
- `/api/v1/internal/executions/<id>/steps/<step_id>/approval-status/`
- `/api/v1/internal/executions/<id>/steps/<step_id>/update/`
- `/api/v1/internal/executions/<id>/complete/`
- Internal artifact upload and change execution/breakglass/verification routes.

Authentication/authorization status:

- JWT authentication is implemented in `apps/users/views.py` and `apps/users/authentication.py`.
- Default DRF permission is `IsAuthenticated` in `apps/api/config/settings/base.py`.
- Organization role permissions exist in `apps/common/permissions.py`.
- Organization context is enforced through `apps/common/org_context.py`.
- Runner authentication is implemented in `apps/common/authentication.py` with per-runner bearer tokens and dev/test-only legacy token mode.
- Auditor grants add scoped read-only access in `apps/auditor/access.py`.

Permissions status:

- Implemented for org membership, admin/operator/viewer distinctions, runner-only internal APIs, and auditor-scoped reads.
- Partially implemented for enterprise separation of duties, project/service/environment scopes, service accounts, API tokens, SSO, SCIM, and fine-grained action/target permissions.

Error handling:

- `apps/common/api_errors.py` normalizes API errors into `{"errors": [...]}`.
- Domain exceptions live in `apps/common/exceptions.py`.
- Many services raise explicit domain errors rather than raw model errors.

Transactions/state transitions:

- Executions use transactional claim and state transition logic in `apps/executions/services.py`, including `select_for_update(skip_locked)` style claiming.
- Approval decisions use service-layer locking.
- Change/evidence objects include immutability rules and lifecycle transitions.
- Runner ownership is enforced with runner id plus claim token for mutating execution routes.

Migrations/admin/commands:

- 58 Django migration files were found under `apps/api/apps/*/migrations/`.
- Admin registrations exist for all major domain apps, including audit, workflows, users, artifacts, runners, runbooks, policies, organizations, integrations, approvals, executions, evidence, auditor, and changes.
- Management commands found: `wait_for_db`, `seed_dev`, `check_stuck_executions`, and `cleanup_evidence_storage`.

Test coverage:

- 112 backend test files were found under `apps/api/apps/*/tests/`.
- Coverage is broad by file count, especially for changes/evidence/auditor, but this task did not execute the suite.

## 6. Runner Implementation

Runner entrypoint:

- `apps/runner/runner/main.py` loads settings, validates startup, configures logging, installs a SIGTERM handler, registers or restores runner identity, and starts `Poller`.
- Settings live in `apps/runner/runner/schemas.py`.
- Local state persistence lives in `apps/runner/runner/state.py`.

Polling behavior:

- `apps/runner/runner/poller.py` heartbeats the runner in a background thread, calls claim-next, backs off on empty/error responses, and stops on drain action.
- One claimed execution is processed at a time by the current poller.

Claim flow:

- Runner calls Django through `apps/runner/runner/client.py`.
- Django internal execution views and `apps/executions/services.py` choose eligible queued executions, set `claimed_by_runner_id`, issue a `claim_token`, and return materialized steps.
- Change-bound executions include additional binding/dispatch-token mechanics through `apps/changes`.

Execution flow:

- `apps/runner/runner/executor.py` binds change executions when needed, starts heartbeat, processes steps sequentially, asks Django `step-start` before running each step, waits for approval when instructed, dispatches v2 actions when action snapshots exist, executes v1 sandbox/simulated commands, uploads artifacts, and completes the execution.
- Runner does not decide approvals/policies independently; it follows Django `runner_action` responses.

Sandbox or command execution behavior:

- Default `execution_mode` is `simulated` in runner settings.
- Supported runner execution modes are `simulated` and `sandboxed`.
- Real command execution is local-process based through `apps/runner/runner/sandbox/local_process.py`.
- `LocalProcessSandboxProvider` creates per-step directories, runs `/bin/bash -c` with `set -euo pipefail`, captures stdout/stderr with byte limits, applies optional `resource` limits where available, handles timeout/cancellation, redacts configured environment values, collects declared artifacts, and cleans up based on policy.
- This is local-process execution, not a container, VM, Firecracker, Kubernetes job, or remote worker sandbox.

Artifact/log handling:

- Runner uploads stdout/stderr and files through `apps/runner/runner/artifact_uploader.py`.
- Django stores artifact metadata in `apps/artifacts/models.py` and bytes through local `ArtifactStorage`.
- `apps/runner/runner/log_streamer.py` and sandbox stream helpers exist for bounded capture/redaction.

Heartbeat behavior:

- Execution heartbeat is sent by `_HeartbeatThread` in `apps/runner/runner/executor.py`.
- Runner heartbeat is separate in `apps/runner/runner/poller.py`.
- Django records `last_heartbeat_at`, and `check_stuck_executions` can recover stale executions.

Cancellation/timeout behavior:

- Public execution cancel records terminal cancellation for queued executions or cancellation intent for claimed/running executions in `apps/executions/services.py`.
- Runner observes cancellation through heartbeat response and sets a cancellation event.
- Local process provider sends SIGTERM then SIGKILL to the process group on timeout/cancellation.
- Step timeouts are supported through workflow/runner settings and clamped by runner defaults.

Failure handling:

- Simulated mode fails on `FAIL_STEP`.
- Sandbox non-zero exit, timeout, cancellation, missing required artifacts, setup errors, and action validation errors produce failed step results.
- Runner stops execution on failed step and completes with final failure/cancellation status.
- Django watchdog functions handle stale heartbeat and approval timeout cases.

Environment/config requirements:

- Runner needs `API_BASE_URL`, runner identity/state settings, and either a registration token or existing bearer token.
- `RUNNER_REGISTRATION_TOKEN` is required unless a bearer token/state file exists.
- Sandbox settings include provider, workspace root, cleanup policy, timeout, stdout/stderr/artifact limits, env allowlists/prefixes, and shell allowance.

Tests:

- 21 runner test files were found under `apps/runner/runner/tests/`.
- Tests cover settings, registration, poller, client, executor, orchestration, action dispatch/handlers, artifact uploads, sandbox factory/workspace/streams/redaction/local process, declared artifacts, secrets, breakglass contract, shutdown, and timing callbacks.

Production-safety verdict:

- Implemented execution is simulated or local-process sandboxed.
- It is useful for demos, local development, and controlled technical pilots.
- It is not production-safe for untrusted commands or customer production target mutation until container/VM isolation, network policy, credential brokerage, durable storage, and operational deployment are implemented.

## 7. AI Service Implementation

FastAPI routes:

- `GET /health` in `apps/ai/app/api/routes/health.py`.
- `POST /parse/runbook` in `apps/ai/app/api/routes/parse.py`.
- `POST /enrich/workflow` in `apps/ai/app/api/routes/enrich.py`.
- `POST /summarize/execution` in `apps/ai/app/api/routes/summarize.py`.
- `/metrics` and `/metrics/` are registered in `apps/ai/app/main.py`.

Implemented capabilities:

- Parse runbook text into workflow candidates in `apps/ai/app/services/workflow_parser.py`.
- Enrich workflow steps with risk/approval metadata in `apps/ai/app/services/workflow_enricher.py`.
- Summarize execution status in `apps/ai/app/services/execution_summarizer.py`.
- Add request-id and metrics middleware in `apps/ai/app/main.py`.

LLM-backed parsing:

- Real LLM-backed code exists through `apps/ai/app/services/llm_client.py`.
- It is disabled by default through `AI_USE_LLM_PARSER=false` in `apps/ai/app/core/config.py`.
- If enabled and `OPENAI_API_KEY` is present, parser/enricher/summarizer can call OpenAI.
- Default behavior is deterministic/stub-like compared with a production parser. It extracts simple numbered/bulleted steps and does keyword-based enrichment.

Django-to-AI boundary:

- Django calls AI through `apps/runbooks/ai_client.py`.
- Workflow creation uses `apps/workflows/internal_clients.py`.
- AI output is candidate data; Django maps, validates, versions, hashes, and persists workflows.

Validation behavior:

- FastAPI uses Pydantic schemas under `apps/ai/app/schemas/`.
- Django validates transformed workflow definitions through workflow services and schema validators.
- AI failures are handled at the Django client boundary and do not let FastAPI persist state.

Prompt files:

- No dedicated prompt file directory was found for AI prompts. Prompt/request shaping appears inside service/client code.

Settings/env vars:

- `AI_USE_LLM_PARSER`, `AI_ENABLE_LLM_TESTS`, `OPENAI_API_KEY`, `AI_PARSE_MODEL`, and health/cache/timeout settings live in `apps/ai/app/core/config.py`.
- Django AI base URL/timeout settings live in `apps/api/config/settings/base.py` and compose env.

Tests:

- 8 AI test files were found under `apps/ai/tests/`.

Current limitations:

- Default parser is not enough for arbitrary real-world runbooks.
- LLM mode needs provider configuration, safety review, prompt/version management, and data-handling policy.
- `apps/ai/README.md` is stale where it describes enrich/summarize as placeholders; code now implements deterministic and optional LLM paths.

## 8. Frontend Implementation

Routing is implemented in `apps/web/src/app/router.tsx`.

Current routes:

- `/login`
- `/` redirects to `/runbooks`
- `/organizations`
- `/runbooks`, `/runbooks/:runbookId`
- `/workflows`, `/workflows/new`, `/workflows/:workflowId`, `/workflows/:workflowId/review`
- `/executions`, `/executions/:executionId`
- `/approvals`
- `/policies`, `/policies/:policyId`
- `/integrations`, `/integrations/:integrationId`
- `/changes`, `/changes/new`, `/changes/new/emergency`, `/changes/:changeId`
- `/audit/changes`, `/audit/changes/:changeId`, `/audit/access`
- `/retro-reviews`
- `/freeze-rules`
- `/settings`
- `/runners`, `/runners/pools/:poolId`, `/runners/runners/:runnerId`, `/runners/routes`

Feature modules exist under `apps/web/src/features/` for:

- Approvals
- Artifacts
- Audit
- Auditor
- Auth
- Changes
- Evidence
- Executions
- Freeze rules
- Integrations
- Organizations
- Policies
- Runbooks
- Runners
- Workflows

API client:

- `apps/web/src/shared/api/client.ts` is the central fetch wrapper.
- It attaches JWT bearer token and `X-Organization-Id`.
- It rejects `/api/v1/internal/` and `/internal/v1/`.
- It attempts token refresh on 401 through the auth refresh flow.
- Feature API modules call Django public APIs only.

Query/data fetching:

- TanStack Query is used for server state. Package dependencies are in `apps/web/package.json`.
- Feature modules define API functions/hooks/types per domain.

Execution status UI:

- Execution pages consume execution detail/list APIs.
- `apps/web/src/features/executions/useExecutionStream.ts` uses `fetchEventSource` for SSE and falls back to polling after repeated failures.
- `apps/web/src/features/executions/executionStreamEvents.ts` updates query cache for execution and step events.

Approval/policy/artifact/change/evidence UI:

- Approvals UI exists at `/approvals`.
- Policies UI exists at `/policies`.
- Artifact UI is integrated with execution detail.
- Changes UI includes standard and emergency creation, change detail, dispatch/preflight/verification/closure flows.
- Evidence UI is integrated with change/audit views.
- Auditor UI exists for audit search/detail/access grants.

Loading/error states:

- Shared API error normalization exists.
- Domain pages have tests, but this task did not manually inspect every loading/empty/error state for UX completeness.

Test coverage:

- 35 web test/spec files were found under `apps/web/src`.
- CI runs `npm run build`, `npm run lint`, `npm run format:check`, and Vitest.

UX gaps:

- The app is broad and operator-facing, but workflow authoring and action configuration are still early.
- No evidence was found of polished onboarding, templates, customer-specific setup, or guided pilot flows.
- Complex change/evidence/auditor surfaces likely need usability testing with real operators and auditors.

## 9. Workflow Schema and Action Model

Current schema files:

- `packages/workflow-schema/workflow.schema.json`: v1 workflow schema.
- `packages/workflow-schema/workflow.v2.schema.json`: v2 typed workflow schema.
- `packages/workflow-schema/action-catalog.pilot.v1.json`: pilot action catalog.
- `packages/workflow-schema/actions/*.schema.json`: per-action schemas.
- `packages/contracts/workflow/workflow.schema.json`: older/duplicate v1 contract scaffold.

Supported step/action types:

- V1 service-supported types include `manual_task`, `shell_command`, and `approval` in `apps/workflows/services.py`.
- V2 pilot action catalog supports:
  - `manual_task`
  - `approval_gate`
  - `shell_command`
  - `http_request`
  - `artifact_assertion`
- Runner action handlers live in `apps/runner/runner/actions/`.

Typed inputs/outputs:

- V2 action schemas define structured params/inputs.
- `apps/workflows/validators.py` validates v2 action contracts, catalog version, type/version match, action params, secret refs, artifact declarations, retry/idempotency, dry-run strategy, and pilot restrictions.
- Runner maps action snapshots into `ActionExecutionContext` and handler-specific behavior.

Approval/risk fields:

- V1 and v2 steps include risk and approval fields.
- `requiresApproval` and `approvalTimeoutSeconds` are recognized.
- Policy evaluation can escalate or block at step start.

Artifact/secrets declarations:

- V2 includes artifact declarations and secret declarations.
- Runner can collect declared artifacts for shell commands and perform artifact assertions.
- Secret refs are recognized, but runtime secret provisioning is not implemented. `NullProvider` in `apps/runner/runner/secrets/null_provider.py` fails closed.

Validation behavior:

- Django loads schemas through `apps/workflows/schema_loader.py`.
- Action catalog lookup is in `apps/workflows/action_catalog.py`.
- V2 validator is meaningful and fail-closed for many unsafe shapes.

Compatibility with runner:

- Runner supports the pilot v1 catalog action types.
- There are compatibility risks:
  - V2 schema and shell handler shapes need continued contract testing, especially around `command`, `commandMode`, and `argv`.
  - Workflow validator allows `http://` absolute URLs in some checks, while runner `http_request` requires HTTPS for execution.
  - V1/v2 docs and duplicate contract files are not perfectly aligned.

Gaps versus safe pilot execution:

- No production credential brokerage.
- No hardened sandbox provider.
- Limited action catalog.
- Limited network/egress controls.
- No remote target inventory/environment model beyond change targets and runner routes.
- No mature workflow template/test harness for customer onboarding.

## 10. Testing and Quality Gates

Backend test commands:

- `make test-api`
- App-specific targets in `Makefile`, including `test-api-core`, `test-api-approvals`, `test-api-policies`, `test-api-audit`, `test-api-artifacts`, `test-api-integrations`, `test-api-auth`, `test-api-streaming`, `test-api-changes`, `test-api-evidence`, `test-api-auditor`, `test-api-runners`.

Runner test commands:

- `make test-runner`

Frontend test commands:

- `make test-web`
- CI also runs `npm run build`, `npm run lint`, `npm run format:check`, and `npx vitest run` inside `apps/web`.

AI test commands:

- CI runs pytest against `apps/ai/tests/`.

Approximate test file counts discovered:

| Area | Count basis | Count |
|---|---|---:|
| API/backend | `find apps/api/apps -path '*/tests/*.py' -not -name '__init__.py'` | 112 files |
| Runner | `find apps/runner/runner/tests -name 'test_*.py'` | 21 files |
| AI | `find apps/ai/tests -name 'test_*.py'` | 8 files |
| Web | `find apps/web/src -name '*.test.*' -o -name '*.spec.*'` | 35 files |

CI workflows:

- `.github/workflows/ci.yml` has jobs for web, Python lint, API tests, migration check, runner tests, AI tests, Python dependency audit, npm audit, secret scan, and container scan.

Linting/formatting:

- Python: Ruff through `pyproject.toml` and Makefile targets.
- Frontend: ESLint/Prettier through `apps/web/package.json`.
- Pre-commit: `.pre-commit-config.yaml` covers whitespace/YAML checks, Ruff format/check, and Prettier for web files.

Security/dependency checks:

- `make security-scan`
- CI `pip-audit`
- CI `npm audit --audit-level=high`
- CI gitleaks secret scan
- CI Trivy image scan
- `make hardening-check`
- `make check-prod`

Gaps:

- This task did not run the full test suite.
- No Playwright/Cypress browser e2e suite was found.
- Manual end-to-end runbooks exist under `docs/manual-end-to-end-testing-runbook.md` and `docs/runbooks/`, but current real-world smoke status is unknown.
- Production-like integration tests for multi-worker SSE, object storage, real runner networking, and customer target connectivity are missing.

## 11. Local Development and Operations

Docker Compose setup:

- `docker-compose.yml` defines `postgres`, `pgbouncer`, `api`, `ai`, `runner`, and `web`.
- API uses Django settings module `config.settings.dev`.
- Runner points at `http://api:8000` and uses compose-provided runner settings.
- Web points at Django via `VITE_API_BASE_URL=http://localhost:8000`.

Makefile commands:

- Startup/lifecycle: `make up`, `make down`, `make restart`, `make logs`, `make ps`.
- Database/dev data: migration-related targets, `seed_dev`, `wait_for_db` through container commands.
- Tests: `make test-api`, `make test-runner`, `make test-web`, app-specific API targets.
- Quality/security: `make lint`, `make format`, `make check-prod`, `make check-migrations`, `make security-scan`, `make hardening-check`, `make ci`, `make ci-full`.

Seed data:

- `apps/api/apps/common/management/commands/seed_dev.py` wipes and reseeds a local dev database with comprehensive test data and no AI calls.

Environment variables:

- API env includes database settings, Django settings, AI base URL/timeouts, artifact/integration settings, runner registration token, and hardening settings.
- AI env includes LLM parser switches, OpenAI key/model, and health/timeout settings.
- Runner env includes API base URL, runner id/name/version, registration token, heartbeat/poll settings, sandbox settings, and simulated step delay.
- Web env uses `VITE_API_BASE_URL`.

Local startup flow:

- Docker Compose is the intended local source of truth.
- API readiness checks database and migrations via `apps/common/health.py`.
- AI has a separate `/health`.
- Runner should register or load state, then poll Django.

Health checks/logs:

- Django endpoints: `/health/live`, `/health/ready/`, `/health/`.
- Metrics: `/metrics/` with optional token protection in production settings.
- Compose logs are accessible through Makefile.
- Structured logging/request-id docs exist in `docs/runbooks/structured-logging-and-request-ids.md`.

Operational scripts/commands:

- `wait_for_db`
- `seed_dev`
- `check_stuck_executions`
- `cleanup_evidence_storage`

Known local dev pain points:

- Runner registration token/state setup must be correct; placeholder tokens are rejected in stricter paths.
- Local artifact/evidence bytes live on filesystem and are not durable across careless cleanup.
- SSE is process-local, so local multi-worker API experiments can produce misleading event behavior.
- Some docs are stale and understate implemented features or describe older runner behavior.

## 12. Implemented Governance / Compliance / Evidence Features

| Feature | Status | Implemented files | Blueprint/planning files if only planned | Gap summary |
|---|---|---|---|---|
| Approvals | Implemented and verified. | `apps/api/apps/approvals/*`, `apps/api/apps/executions/services.py`, `apps/runner/runner/executor.py`, `apps/web/src/features/approvals/`. | `docs/blueprints/phase10/phase-10-01-approvals-blueprint.md`. | Needs stronger routing/separation-of-duties and live operational validation. |
| Policies | Implemented and verified. | `apps/api/apps/policies/*`, `apps/api/apps/executions/internal_views.py`, policy UI. | `docs/blueprints/phase10/phase-10-02-policies-blueprint.md`. | Structured rules are useful but narrow; enterprise policy model is not complete. |
| Audit trail | Implemented and verified. | `apps/api/apps/audit/*`, calls from domain services. | `docs/blueprints/phase10/phase-10-03-audit-trail-blueprint.md`. | Application-level append-only, not external immutable ledger. |
| Artifacts | Partially implemented. | `apps/api/apps/artifacts/*`, `apps/runner/runner/artifact_uploader.py`, execution artifact UI. | `docs/blueprints/phase10/phase-10-04-artifacts-blueprint.md`, `docs/blueprints/pilot/pilot-phase-e-durable-artifact-evidence-storage-blueprint.md`. | Local-only storage; no S3/durable backend. |
| Integrations | Partially implemented. | `apps/api/apps/integrations/*`, integrations UI. | `docs/blueprints/phase10/phase-10-05-integrations-blueprint.md`. | Webhook integration only; synchronous dispatch; limited product integrations. |
| Authentication/RBAC | Partially implemented. | `apps/users/*`, `apps/common/permissions.py`, `apps/common/org_context.py`, auth UI. | `docs/blueprints/phase10/phase-10-07-authentication-authorization-blueprint.md`, `docs/implemented/phase-10-07-authentication-authorization.md`. | No SSO/SCIM/service accounts/fine-grained project or target RBAC. |
| SSE/live streaming | Partially implemented. | `apps/executions/stream_views.py`, `apps/executions/event_bus.py`, `apps/web/src/features/executions/useExecutionStream.ts`. | `docs/blueprints/phase10/phase-10-08-live-event-streaming-blueprint.md`. | In-process event bus only; not multi-worker durable. |
| Production hardening | Partially implemented. | `apps/api/config/settings/prod.py`, `apps/common/metrics.py`, CI scans, Makefile checks. | `docs/blueprints/phase10/phase-10-09-production-hardening-blueprint.md`. | No production deployment/IaC, external storage, backup/restore proof, or load testing. |
| Change records | Implemented and verified by source inspection. | `apps/api/apps/changes/models.py`, `services.py`, `views.py`, changes UI. | `docs/blueprints/phase11/phase-11.1-change-dossier-blueprint.md`. | Needs end-to-end operational validation with real workflows. |
| Change windows/freezes/locks | Implemented and verified by source inspection. | `ChangeWindow`, `FreezeRule`, `TargetLock`, preflight/dispatch services, freeze UI. | `docs/blueprints/phase11/phase-11.2-windows-freezes-target-locks-blueprint.md`, `docs/implemented/phase-11.2-windows-freezes-target-locks.md`. | Real timezone/scheduling/customer policy testing needed. |
| Verification plans | Implemented and verified by source inspection. | `VerificationPlan`, `VerificationCheck`, `VerificationResult`, closure services/UI. | `docs/blueprints/phase11/phase-11.3-verification-closure-blueprint.md`. | External assertions are limited; some verification remains manual. |
| Emergency/breakglass | Implemented and verified by source inspection. | `ChangeException`, `BreakglassSession`, `RetroReview`, runner breakglass heartbeat. | `docs/blueprints/phase11/phase-11.4-emergency-exceptions-breakglass-blueprint.md`. | Human-process policy and separation-of-duties need validation. |
| Sealed evidence bundles | Partially implemented. | `apps/api/apps/evidence/*`, evidence UI/API. | `docs/blueprints/phase11/phase-11.5-sealed-evidence-bundles-blueprint.md`, pilot phase E durable storage blueprint. | Local storage and application-level immutability prevent production-grade evidence claims. |
| Auditor workspace/control coverage | Implemented and verified by source inspection. | `apps/api/apps/auditor/*`, audit UI routes. | `docs/blueprints/phase11/phase-11.6-auditor-workspace-control-coverage-blueprint.md`. | External system integrations and customer auditor workflows need validation. |
| Runner pools/target connectivity | Partially implemented. | `apps/api/apps/runners/*`, `apps/runner/runner/main.py`, runner UI/routes. | `docs/blueprints/pilot/pilot-phase-c-runner-pools-target-connectivity-blueprint.md`. | Scheduling/routing exists, but real private-network deployment and target access are not proven. |
| Secrets credential brokerage | Documented only / blueprint only. | `apps/runner/runner/secrets/null_provider.py` fails closed; integration credentials are narrow and encrypted. | `docs/blueprints/pilot/pilot-phase-d-secrets-credential-brokerage-blueprint.md`. | No general secret registry, broker, backend integration, or step-scoped credential injection. |
| Durable artifact/evidence storage | Documented only / blueprint only beyond local. | Local storage only in `apps/api/apps/artifacts/storage.py` and `apps/api/apps/evidence/storage.py`. | `docs/blueprints/pilot/pilot-phase-e-durable-artifact-evidence-storage-blueprint.md`. | No S3/object storage backend. |
| AWS deployment workflows | Documented only / blueprint only. | Placeholder `infra/*/README.md`; no IaC found. | `docs/blueprints/phase10/phase-10-10-aws-deployment-workflows-blueprint.md`. | No production deployment substrate. |
| Admin DB statistics | Documented only / blueprint only. | Admin registrations exist, but no special DB statistics feature confirmed. | `docs/blueprints/phase11/phase-11-admin-db-statistics-blueprint.md`. | Not an implemented product capability. |

## 13. Product Readiness Assessment

| Area | Status | Evidence | Biggest Gap |
|---|---|---|---|
| Demo readiness | Strong demo-grade. | End-to-end UI/API/runner/AI flow exists across `apps/web`, `apps/api`, `apps/runner`, `apps/ai`; Docker Compose and seed data exist. | Demo must disclose simulated/local-process execution and local storage. |
| Manual testing readiness | Good for local/manual testing. | Manual runbooks in `docs/manual-end-to-end-testing-runbook.md` and `docs/runbooks/`; broad tests and Makefile targets. | Need current manual smoke results and browser e2e coverage. |
| Pilot readiness | Controlled technical pilot-grade only for narrow, non-production or low-risk environments. | Change governance, runner pools, typed actions, local sandbox, artifacts, evidence, auditor features exist. | Production-safe runner isolation, secrets, durable storage, and deployment are missing. |
| Production readiness | Not production-grade. | `settings/prod.py` and CI hardening exist, but `infra` is placeholder and storage is local-only. | No IaC/deployment, object storage, hardened execution, backup/restore proof, or multi-worker event bus. |
| Enterprise readiness | Partial. | Auth, org roles, auditor grants, audit/evidence/control coverage exist. | No SSO/SCIM/service accounts/fine-grained RBAC/customer admin workflows. |
| Compliance/audit readiness | Strong prototype, not compliance-grade production evidence. | Evidence bundles, redaction exports, legal holds, auditor coverage models are implemented. | Local-only storage and application-level immutability weaken evidentiary claims. |
| Security readiness | Partial. | JWT auth, runner token auth, SSRF checks for integrations, prod settings checks, CI scans. | Secrets brokerage, sandbox isolation, network egress policy, session hardening, and threat-model validation incomplete. |
| Founder sales readiness | Useful for technical discovery/demo, not broad paid production sale. | Product surface demonstrates concrete governed operations workflow. | Need validated ICP, positioning, pricing, legal terms, support model, deployment story, and customer-safe pilot package. |

## 14. Current ICP and Wedge Implied by the Product

Based only on the repository, the likely target customer is a small-to-mid engineering or platform team that performs high-risk operational changes and needs better control, traceability, evidence, and auditor-ready records than ad hoc scripts, tickets, chat approvals, and spreadsheets provide.

Likely buyer/user:

- Buyer: Head of Engineering, Infrastructure/Platform lead, DevOps/SRE manager, security/compliance-adjacent engineering leader.
- Daily users: operators, release engineers, SREs, platform engineers, approvers, and auditors.

Strongest pain point implied by the code:

- "We need production changes to be approved, executed, verified, audited, and exportable without relying on scattered tickets, Slack threads, shell history, and manual evidence collection."

Strongest wedge:

- Governed execution plus sealed evidence for production changes. The repo has more code depth in approvals, policies, change records, verification, evidence, and auditor views than in generic runbook automation.

Weakest assumptions:

- That teams will trust a new platform to sit in the production-change path.
- That local-process or future customer-hosted runners are acceptable operationally.
- That evidence/control coverage maps to real buyer urgency before integrations with existing systems such as Jira, ServiceNow, PagerDuty, GitHub, cloud providers, or SIEM tools mature.
- That workflow authoring can become easy enough for non-founder users.

Features required before serious outreach:

- A credible demo dataset and guided story.
- A safe local/non-production pilot path.
- Clear limitation disclosures for execution, storage, and secrets.
- Real manual test pass of the complete demo path.
- Minimal customer-facing docs: what it does, what it does not do, deployment assumptions, security boundary, pilot criteria.

Features that can wait:

- Broad marketplace of integrations.
- Billing/self-serve signup.
- Multi-cloud deployment automation.
- Large action catalog beyond one or two validated customer workflows.
- Advanced analytics and dashboards.

## 15. Engineering Roadmap From Current State

Must fix before credible demo:

- Run and record a full local smoke test using `docker-compose.yml`, `seed_dev`, and the manual runbook.
- Update stale top-level docs that still describe implemented features as future work: `README.md`, `docs/architecture/architecture-overview.md`, `docs/api/rest-api-v1.md`, `docs/api/internal-runner-api.md`, `apps/ai/README.md`.
- Ensure the demo uses explicit labels for simulated versus local-process execution in `apps/web/src/features/executions/` and runner settings.
- Fix or document workflow v2/runtime contract mismatches around shell/http action validation in `packages/workflow-schema/`, `apps/api/apps/workflows/validators.py`, and `apps/runner/runner/actions/`.

Must fix before pilot:

- Build a narrowly scoped production-safe execution path or define a strict non-production pilot: `apps/runner/runner/sandbox/`, `apps/runner/runner/actions/`, runner deployment docs.
- Implement a minimal secret reference/broker model or prohibit secreted workflows explicitly: `apps/runner/runner/secrets/`, `apps/api/apps/workflows/`, `apps/api/apps/executions/`.
- Add durable artifact/evidence storage backend: `apps/api/apps/artifacts/storage.py`, `apps/api/apps/evidence/storage.py`, settings, tests.
- Add a pilot deployment architecture under `infra/` or a documented customer-hosted local pilot topology.
- Add e2e/manual verification coverage for runbook to workflow to approval/policy to execution to artifact to evidence bundle.

Must fix before paid pilot:

- Harden runner isolation and network controls for the paid pilot's exact target type.
- Add customer-safe onboarding docs, support runbooks, incident response, backup/restore procedures, and logging/metrics dashboards.
- Implement enterprise login path or at least a defensible invite/membership/admin flow.
- Add legal/security artifacts: terms, DPA/security overview, data retention, evidence/storage policy, runner threat model.
- Add integration with the customer's source of truth if required: ticket/change system, chat, PagerDuty, GitHub, cloud provider, or SIEM.

Must fix before production:

- Infrastructure as code and deployment workflows in `infra/` and `.github/workflows/`.
- S3/object storage with KMS and retention/legal hold semantics.
- External event broker or durable stream support for multi-worker execution events.
- Hardened sandbox provider, least-privilege runner identity, egress policy, and resource isolation.
- Full secrets backend integration and value-aware redaction.
- Backups, restore drills, migrations, load testing, alerting, runbooks, and operational ownership.
- Fine-grained RBAC, SSO/SCIM or enterprise identity, service accounts/API tokens.

Can defer:

- Billing and self-serve onboarding.
- Broad action/plugin marketplace.
- Advanced compliance framework packs beyond one validated control mapping.
- Multiple deployment clouds.
- Complex workflow visual builder.

## 16. Solo Founder Readiness Context

What the founder has built so far:

- A real monorepo with four services and a coherent architecture.
- A Django control plane with a substantial governance/compliance domain model.
- A React operator UI that exposes most major backend surfaces.
- A Python runner that can register, poll, claim, heartbeat, execute simulated/local-process steps, upload artifacts, and observe approvals/cancellation.
- A FastAPI AI boundary with deterministic and optional LLM parse/enrich/summarize paths.
- CI, tests, hardening checks, security scans, local Docker Compose, and many operational docs/runbooks.

Current technical assets:

- Executable end-to-end local product slice.
- Rich change-management and evidence model.
- Audit/event/evidence/auditor implementation that can support a strong demo narrative.
- Typed workflow v2/action catalog foundation.
- Runner pool/target route foundation.
- Production settings and checks that show security intent even without full production infra.

Current proof points:

- Broad source-level implementation across `apps/api`, `apps/web`, `apps/runner`, and `apps/ai`.
- 112 API test files, 35 web test/spec files, 21 runner test files, and 8 AI test files discovered.
- CI includes tests, lint, dependency audit, secret scan, and image scan.
- Governance features are not just docs; many have models, services, APIs, UI, admin, and tests.

Current missing business assets:

- Validated ICP and buyer pain with interview evidence.
- Sharp positioning and one-sentence category/wedge.
- Demo script and pilot offer.
- Pricing hypothesis.
- Legal/security packet for pilots.
- Support model and founder operating cadence.
- Customer discovery tracker and objection log.
- Deployment/pilot terms that honestly bound product risk.

Likely next non-engineering tasks:

- Conduct targeted customer interviews with SRE/platform/security/compliance-adjacent leaders.
- Validate whether governed evidence around production changes is urgent enough to buy.
- Build a founder-led demo story around the implemented change/evidence workflow.
- Draft pilot criteria: non-production first, narrow action type, explicit data handling, success metrics.
- Prepare security/architecture one-pager from this repo-grounded truth source.

What needs external validation:

- Whether buyers care more about execution, evidence, approvals, audit export, or integration with existing change systems.
- Whether customer-hosted runners are acceptable.
- Which first integration is mandatory.
- Whether auditors/compliance teams are real users or just downstream beneficiaries.
- Whether the wedge should be "governed runbook execution", "change evidence automation", or another framing.

Assumptions to test with customers:

- Existing change approval/evidence collection is painful enough to switch workflows.
- The platform can start as a layer beside existing ticketing rather than replacing it.
- A narrow pilot workflow can prove value without full enterprise deployment.
- Customers will tolerate a founder-operated pilot before production hardening is complete.

What should not be done yet:

- Do not pitch production-safe autonomous execution until runner isolation, secrets, storage, and deployment are real.
- Do not build billing or self-serve before validating the buyer and pilot workflow.
- Do not expand the action catalog broadly before one customer workflow is validated.
- Do not claim compliance-grade evidence durability while storage is local-only.
- Do not treat old blueprints as implementation proof.

## 17. Known Unknowns and Required Follow-Up Audits

Commands that should be run manually or in a dedicated verification pass:

- `make test-api`
- `make test-runner`
- `make test-web`
- `make check-migrations`
- `make check-prod`
- `make security-scan`
- `make hardening-check`
- `docker compose up` followed by the manual end-to-end runbook.
- A live browser smoke test for login, org selection, runbook, workflow, execution, approval, artifact, change, evidence, and auditor flows.

Tests that should be added or strengthened:

- Browser e2e tests for core workflows.
- Multi-worker SSE/event behavior tests or explicit single-worker production guard tests.
- Workflow schema v2 contract tests between JSON schema, Django validator, and runner action handlers.
- Production settings tests for artifact storage backend assumptions.
- Runner sandbox threat-model tests for network/filesystem/secret leakage once a real sandbox ships.

Files requiring human review:

- `README.md` and `docs/architecture/architecture-overview.md` because they contain stale "future expansion" language.
- `docs/api/rest-api-v1.md` and `docs/api/internal-runner-api.md` because current endpoint surface is much broader.
- `apps/ai/README.md` because implementation has moved beyond placeholder enrichment/summarization.
- `packages/contracts/workflow/workflow.schema.json` versus `packages/workflow-schema/*` because schema ownership is unclear.
- `apps/users/views.py` refresh rotation logic before enabling token rotation.
- `apps/runner/runner/actions/http_request.py` and validator URL policy for SSRF/egress consistency.

Business assumptions needing later validation:

- ICP, buyer, budget owner, and urgency.
- First paid use case and "must-have" integration.
- Acceptable deployment topology.
- Evidence/audit requirements that matter in real audits.
- Security questionnaire expectations for pilots.

Technical risks needing deeper audit:

- Sandbox escape/network egress/secret leakage risk.
- Evidence immutability and retention claims under local storage.
- Runner registration token lifecycle and state-file security.
- Multi-tenant org scoping across every new endpoint.
- Complex change lifecycle edge cases under concurrent dispatch/locks/freezes.
- Audit redaction completeness across metadata, artifacts, integrations, and evidence exports.

## 18. Deep Research Prompt Input Summary

The section below is intended to be copied into a future deep research prompt. It deliberately avoids market conclusions and startup advice beyond repo-grounded context.

## Deep Research Context Packet

Product: Runbook Platform is a governed operations/change-execution platform. It lets users create runbooks, generate/review/publish workflows, execute them through a Django-controlled runner flow, and collect approvals, policy decisions, audit events, artifacts, verification results, sealed evidence bundles, and auditor-facing control coverage.

Current implementation state: The repository has a substantial working control plane. Django models/services/APIs exist for organizations, users/auth, runbooks, workflows, executions, approvals, policies, audit, artifacts, integrations, runners, changes, evidence, and auditor workflows. React routes exist for the major product areas. The Python runner can register, poll, claim, heartbeat, run simulated steps or local-process sandboxed steps, dispatch a small typed action catalog, upload artifacts, observe approvals/cancellation, and complete executions. The FastAPI AI service provides deterministic parse/enrich/summarize behavior by default and optional OpenAI-backed behavior when enabled.

Current architecture: Django is the stateful control plane and sole PostgreSQL owner. React calls only Django public `/api/v1/` APIs. Runner calls only Django internal `/api/v1/internal/` control APIs. FastAPI AI is stateless and advisory. Workflow schemas/action catalog live under `packages/workflow-schema/`. Docker Compose runs Postgres, PgBouncer, API, AI, runner, and web locally. CI runs backend, frontend, runner, AI, migration, lint, audit, secret scan, and image scan jobs.

Current feature maturity: Demo-grade and close to controlled technical pilot-grade for narrow, disclosed, low-risk scenarios. Strongest implemented surface is governed change management and evidence: approvals, policies, audit, artifacts, change windows/freezes/locks, verification, breakglass, sealed evidence bundles, auditor grants/search/control coverage. Execution is not production-safe yet because real execution is local-process based and secrets/storage/deployment are incomplete.

Current gaps: Production-safe runner isolation; general secret/credential brokerage; durable S3/object storage for artifacts/evidence; production IaC/deployment; multi-worker/durable event streaming; enterprise SSO/SCIM/fine-grained RBAC; browser e2e/manual verification; customer onboarding/pilot assets; first mandatory integration; pricing/legal/support/GTM materials.

Desired founder outcome for later research: Produce exact next steps for the solo founder across business, engineering, operations, sales, GTM, legal, finance, support, and product strategy, using this implementation truth source. The later research should focus on choosing a narrow ICP/wedge, defining a safe pilot offer, deciding what engineering must be finished before outreach versus before paid pilot, creating a customer discovery and demo plan, identifying legal/security/compliance artifacts needed for pilots, and avoiding premature production or market claims not supported by the current repo.
