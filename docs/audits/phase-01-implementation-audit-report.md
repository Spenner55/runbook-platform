# Phase 01 Implementation Audit Report

## 1. Audit Objective

Audit the current Phase 1 implementation in the repository, document what is actually built, verify that the vertical slice wiring is correct where implemented, and measure drift against the planned Phase 2 through Phase 8 blueprints without force-fitting the code to the plan.

## 2. Audit Method

This audit followed a read-first process:

1. Reviewed the root runtime and environment files: `docker-compose.yml`, `Makefile`, `.env.example`, `README.md`, and `apps/api/README.md`.
2. Reviewed the current implementation in `apps/api`, `apps/runner`, `apps/web`, `apps/ai`, `packages/contracts`, and `packages/workflow-schema`.
3. Reviewed the Phase 1 through Phase 8 blueprint documents under `docs/blueprints/`.
4. Searched the repo for architecture-boundary evidence such as `AI_BASE_URL`, internal endpoint paths, `httpx`, `fetch`, router usage, and queue/websocket references.
5. Verified live runtime behavior where possible through Docker Compose.

Important basis note:

- The repository had relevant uncommitted changes during the audit. This report reflects the current working tree, not only the last Git commit.

## 3. Repo Areas Reviewed

- `apps/api/config`
- `apps/api/apps/common`
- `apps/api/apps/organizations`
- `apps/api/apps/runbooks`
- `apps/api/apps/workflows`
- `apps/api/apps/executions`
- `apps/runner/runner`
- `apps/ai/app`
- `apps/web/src`
- `packages/contracts`
- `packages/workflow-schema`
- `docker-compose.yml`
- `Makefile`
- `.env.example`
- `docs/blueprints/phase-01-end-to-end-vertical-slice-blueprint.md`
- `docs/blueprints/phase-02-django-domain-foundation-blueprint.md`
- `docs/blueprints/phase-03-application-service-layer-blueprint.md`
- `docs/blueprints/phase-04-versioned-rest-apis-blueprint.md`
- `docs/blueprints/phase-05-runner-real-flow-blueprint.md`
- `docs/blueprints/phase-06-react-product-slice-blueprint.md`
- `docs/blueprints/phase-07-ai-service-boundary-blueprint.md`
- `docs/blueprints/phase-08-targeted-testing-blueprint.md`

## 4. Comparison Against Phase 1 Intended Goals

| Phase 1 objective | Status | Evidence |
| --- | --- | --- |
| User creates organization | Implemented | `apps/api/apps/organizations/views.py`, `services.py`, and routed `POST /api/v1/organizations/` |
| User creates runbook | Implemented | `apps/api/apps/runbooks/views.py`, `services.py`, and routed `POST /api/v1/runbooks/` |
| System generates workflow | Implemented differently | `apps/api/apps/workflows/services.py` calls `apps/api/apps/runbooks/ai_client.py`, which calls FastAPI; parsing is deterministic stub logic in `apps/ai/app/services/workflow_parser.py` rather than model-backed AI |
| User publishes workflow | Implemented | `POST /api/v1/workflows/{id}/publish/` in `apps/api/apps/workflows/views.py` and `services.py` |
| User starts execution | Implemented | `POST /api/v1/executions/` in `apps/api/apps/executions/views.py` and `services.py` |
| Runner claims execution | Implemented | Internal `claim-next` route plus `claim_next_execution()` with `transaction.atomic()` and `select_for_update(skip_locked=True)` in `apps/api/apps/executions/services.py` |
| Runner executes steps | Implemented differently | `apps/runner/runner/executor.py` runs fake in-memory steps and uses `FAIL_STEP` for deterministic failure; no real sandbox or artifact flow |
| Execution status updates in DB | Implemented | `update_execution_step()`, `heartbeat_execution()`, and `complete_execution()` in `apps/api/apps/executions/services.py` |
| UI reflects real-time progress | Missing | `apps/web/src/App.tsx` is still a static placeholder; no routing, API calls, or polling |

## 5. Wiring Correctness Audit

### Frontend -> Django only

Status: Correct but mostly unexercised.

Evidence:

- `apps/web/src` contains no `fetch`, `axios`, `httpx`, or direct service URL usage.
- `.env.example` exposes `VITE_API_BASE_URL`, not `AI_BASE_URL`, to the frontend.
- There is no browser wiring to FastAPI or runner internal endpoints.

Assessment:

- The intended boundary is preserved.
- The bigger issue is missing frontend implementation, not boundary violation.

### Runner -> Django only

Status: Correct.

Evidence:

- `apps/runner/runner/client.py` only calls `/api/v1/internal/executions/...`.
- `apps/runner/runner/main.py` reads `API_BASE_URL`.
- There is no runner reference to `AI_BASE_URL`, PostgreSQL, or direct ORM/database access.
- Live runner logs show repeated `POST http://api:8000/api/v1/internal/executions/claim-next/`.

### AI not directly called by frontend

Status: Correct.

Evidence:

- No frontend use of `AI_BASE_URL`.
- No frontend FastAPI client exists.
- FastAPI traffic observed in logs came from Django API container activity during workflow tests.

### Health endpoint location

Status: Correct.

Evidence:

- Django health remains at `/health/` in `apps/api/config/urls.py`.
- FastAPI health remains at `/health` in `apps/ai/app/api/routes/health.py`.
- Neither is under `/api/v1`.

### API versioning correctness

Status: Partially implemented.

Evidence:

- Public and internal routes are prefixed under `/api/v1/`.
- Routing is performed by explicit includes in `apps/api/config/urls.py`.
- The repo does not implement DRF namespace versioning or a standardized versioning strategy beyond static URL prefixing.

Assessment:

- The externally visible path contract is correct.
- The later blueprint’s stricter versioning discipline is not fully implemented.

### Services vs views boundary

Status: Mostly correct.

Evidence:

- Create and transition flows delegate to services in `organizations/services.py`, `runbooks/services.py`, `workflows/services.py`, and `executions/services.py`.
- Views still perform some object loading and inline error mapping.
- There is no shared application-error or API-error layer.

Assessment:

- Core orchestration lives in services as intended.
- Error normalization and some HTTP-to-service translation remain thin and ad hoc.

### Execution state flow wiring

Status: Mostly correct.

Evidence:

- `create_execution_from_workflow()` materializes steps from workflow definition.
- `claim_next_execution()` sets claim metadata and returns steps.
- `update_execution_step()` enforces narrow transitions and moves execution `claimed -> running`.
- `complete_execution()` closes execution as `succeeded` or `failed`.

Assessment:

- The main state path is wired correctly.
- Ownership-loss and heartbeat failure handling are not hardened to the level planned later.

### Workflow/execution persistence wiring

Status: Correct.

Evidence:

- Workflow creation persists canonical definition JSON and version.
- Execution creation snapshots the workflow and materializes execution steps.
- PostgreSQL remains owned through Django models only.

### Docker/local runtime consistency

Status: Mostly correct.

Evidence:

- `docker compose config` resolved successfully.
- `docker compose ps` showed all five services running on 2026-04-15.
- `docker compose exec api python manage.py check` succeeded.
- `docker compose exec api pytest -q` succeeded with `31 passed`.
- `docker compose exec runner pytest -q` succeeded with `10 passed`.
- `docker compose exec web npm run build` succeeded.

Assessment:

- Docker is the operational source of truth and the current stack is viable.
- Some README files are stale relative to the actual implementation.

## 6. Drift Analysis Against Phase 2

### Domain model alignment

Status: Mostly aligned.

Aligned:

- real Django apps exist for `common`, `organizations`, `runbooks`, `workflows`, and `executions`
- UUID primary keys exist on domain models
- durable tenant ownership exists on `Runbook`, `Workflow`, and `Execution`
- `ExecutionStep` is scoped through `Execution`
- statuses broadly match the planned enums
- migrations and admin registration exist

Partial or drift:

- shared base model is named `BaseModel`, not `TimeStampedUUIDModel`
- `Organization.slug` is globally unique instead of just tenant-local, which is acceptable and not harmful here
- `Workflow.definition_schema_version` default in the model is `1.0`, but the workflow service persists `workflow.schema.v1`

Assessment:

- Domain layout is close enough to the Phase 2 blueprint to continue.
- The schema-version mismatch is a real cleanup item.

## 7. Drift Analysis Against Phase 3

### Service layer alignment

Status: Mostly aligned.

Aligned:

- create flows are delegated to services
- execution creation is transactional
- workflow generation calls FastAPI outside the DB transaction

Partial or drift:

- AI client lives in `apps/api/apps/runbooks/ai_client.py` rather than a dedicated `internal_clients.py`
- no shared service exceptions or API error envelope exists
- organization creation is minimal and does not distinguish serializer concerns from service concerns beyond one simple create helper

### Orchestration boundaries

Status: Mostly aligned.

Assessment:

- models hold row structure and enums
- services own orchestration
- views are thin enough overall
- boundary is present even if not fully formalized

### Transaction placement alignment

Status: Good.

Evidence:

- workflow AI network call happens before `transaction.atomic()`
- execution row plus step fan-out happen inside `transaction.atomic()`
- claim-next mutation happens inside `transaction.atomic()`

## 8. Drift Analysis Against Phase 4

### Route structure alignment

Status: Mostly aligned.

Aligned:

- public endpoints live under `/api/v1/`
- runner endpoints live under `/api/v1/internal/`
- public actions include publish and cancel

Partial or drift:

- route versioning is static path prefix only
- no standardized error envelope

### Public/internal endpoint separation

Status: Correct.

### Claim-next contract alignment

Status: Mostly aligned.

Aligned:

- endpoint path is correct
- result includes `execution` or `null`
- claim is atomic and uses row locking

Partial or drift:

- response shape is slimmer than the blueprint examples
- queue tests do not yet prove the full PostgreSQL concurrency matrix from the blueprint

### Serializer/view/service separation

Status: Mostly aligned.

Partial or drift:

- the split exists, but the repo does not yet have the more formal action-specific serializers and error contracts described later

## 9. Drift Analysis Against Phase 5

### Runner package layout

Status: Mostly aligned.

Aligned:

- `main.py`, `client.py`, `poller.py`, `executor.py`, `schemas.py` exist
- `log_streamer.py`, `sandbox.py`, and `artifact_uploader.py` exist as placeholders

### Poller/client/executor/logging structure

Status: Partially aligned.

Aligned:

- poller owns the claim loop
- client owns internal HTTP calls
- executor owns step sequencing and heartbeat thread
- `main.py` stays thin

Drift:

- no dedicated logging helper is in use
- runner logs are not yet structured in the planned way
- `RUNNER_POLL_INTERVAL_SECONDS` is present in env but not used as a settings object or explicit fallback configuration beyond hard-coded `5`s

### Happy path/failure path shape

Status: Partially aligned.

Aligned:

- success and failure paths exist
- runner stops later steps after a failure

Drift:

- heartbeat failures are only logged, not treated as possible claim-loss
- the runner does not distinguish ownership-loss failures the way the blueprint expects
- there are no client contract tests

## 10. Drift Analysis Against Phase 6

### Frontend routes

Status: Missing.

Evidence:

- no router file
- no route containers
- no page-level feature structure

### Django-only boundary

Status: Correct by omission.

### Execution polling behavior

Status: Missing.

### Feature-oriented structure

Status: Missing.

Assessment:

- This is the largest Phase 1 gap.
- It is missing implementation, not incorrect wiring.

## 11. Drift Analysis Against Phase 7

### AI service call path

Status: Mostly aligned.

Aligned:

- browser does not call FastAPI
- Django workflow creation calls FastAPI
- FastAPI returns a candidate and Django persists the workflow

Drift:

- Django AI client uses direct `httpx.post(...)` rather than a reusable `httpx.Client`
- workflow-create views do not convert AI transport/timeout errors into stable API errors; failures are likely 500s today

### Internal client boundary

Status: Mostly aligned.

Assessment:

- the boundary exists and is narrow
- naming and client structure are simpler than planned

### Persistence ownership

Status: Correct.

### FastAPI scope discipline

Status: Mostly aligned.

Drift:

- `enrich` and `summarize` placeholder routes are mounted even though the Phase 7 blueprint calls them out as out of scope

Assessment:

- This is acceptable scaffold drift because Django does not use those routes and they do not own state.

## 12. Drift Analysis Against Phase 8

### Testing setup

Status: Partially aligned.

Aligned:

- Django pytest stack exists
- runner pytest stack exists
- targeted tests exist in service/API/runner areas

Drift:

- frontend test setup is absent
- AI client and FastAPI route tests are absent

### Targeted critical-flow coverage

Status: Partially aligned.

Aligned:

- runbook creation tests exist
- workflow creation tests exist
- execution creation tests exist
- poller and executor tests exist

Drift:

- runner-facing transition tests for heartbeat and claim-token failures are absent
- runner HTTP client contract tests are absent
- claim-next tests are not the full PostgreSQL concurrency proof planned in the blueprint
- no frontend route/page smoke tests exist

### Gaps and risks

Status: Real.

Assessment:

- The existing suite is valuable, but it is not yet strong enough to claim Phase 8 alignment.

## 13. Findings Summary Table

| Area | Status | Severity | Finding | Recommended action | Can fix now safely? |
| --- | --- | --- | --- | --- | --- |
| Frontend product slice | Missing | High | `apps/web` is still a placeholder, so the Phase 1 vertical slice is not operator-usable through the browser | Implement the planned React route-driven slice before calling Phase 1 fully end to end | No |
| Workflow create error handling | Partially implemented | High | AI client exceptions are defined, but workflow-create views do not map them into stable API responses | Add narrow exception handling and API contract tests for unavailable/timeout/bad-response cases | Yes |
| Runner ownership-loss handling | Partially implemented | High | Heartbeat failures are only logged, so the runner may continue work after possible claim loss | Harden executor behavior for heartbeat failure and ownership rejection paths | No |
| Claim-next proof depth | Partially implemented | Medium | Current tests do not prove the full PostgreSQL concurrency matrix described in the blueprint | Add focused multi-transaction concurrency tests for one-row races and locked-row skipping | No |
| Frontend test layer | Missing | Medium | There are no frontend smoke tests | Add minimal Vitest route/page tests once the frontend slice exists | No |
| Runner client test layer | Missing | Medium | No tests verify request payloads and endpoint paths in `apps/runner/runner/client.py` | Add `httpx.MockTransport` contract tests | Yes |
| Workflow schema version consistency | Implemented differently | Medium | Model default is `1.0`, service writes `workflow.schema.v1` | Unify on one schema-version string | Yes |
| API error contract | Partially implemented | Low | Views return ad hoc `400` payloads rather than a consistent error envelope | Standardize error response shape after the critical wiring fixes | No |
| AI service scope | Implemented differently | Low | `enrich` and `summarize` placeholder routes are mounted though unused | Keep documented as placeholders or remove if they start creating confusion | Yes |
| Documentation freshness | Drifted | Low | Some READMEs still describe the stack as more scaffolded than it is | Update service READMEs after the audit docs land | Yes |

## 14. Safe Correction Opportunities

These are small and clearly safe, but they are not required to complete this audit:

- Align `Workflow.definition_schema_version` default in `apps/api/apps/workflows/models.py` with the service-written value in `apps/api/apps/workflows/services.py`.
- Add narrow exception handling in `apps/api/apps/workflows/views.py` so AI transport/timeout/contract failures do not surface as generic 500 responses.
- Add runner client contract tests for `apps/runner/runner/client.py`.
- Update stale service README files to reflect the implemented state.

No code corrections were applied in this audit pass because documentation was sufficient and the remaining issues are better handled as explicit follow-up work.

## 15. Follow-up Work

### Required before Phase 2 continues

- Close the Phase 1 browser gap by implementing the planned frontend product slice or explicitly redefining Phase 1 as backend-only.
- Add workflow-create error handling so AI dependency failures do not surface as unbounded server errors.
- Decide whether heartbeat/claim-loss handling in the runner must be corrected before more execution semantics are added.

### Should do soon

- Add runner HTTP client contract tests.
- Add runner-facing Django transition tests for wrong runner ID and wrong claim token.
- Add stronger PostgreSQL concurrency tests for `claim-next`.
- Unify schema-version naming and document which workflow schema package is canonical.

### Can defer safely

- Remove or keep unused `enrich` and `summarize` placeholders, as long as Django does not start depending on them.
- Formalize a standardized error envelope.
- Refresh service README files beyond the new audit documents.

## 16. Final Verdict

Phase 1 is mostly solid but needs a short correction pass.

Why:

- The Django domain, service, API, persistence, runner, and AI boundary layers are coherent and largely aligned with the planned architecture.
- Docker wiring is valid and the current stack passes core checks and tests.
- The biggest gap is still the missing React product slice, which means the original Phase 1 “end-to-end vertical slice” is not complete from the user-facing side.
- There are also a few real drift risks that should be corrected before piling on more complexity: AI failure handling, runner claim-loss hardening, and deeper concurrency/contract testing.

Practical conclusion:

- The repository is not in a “stop everything, architecture is wrong” state.
- It is also not honest to call Phase 1 fully complete.
- A short correction pass is the right next step before continuing broader feature work.
