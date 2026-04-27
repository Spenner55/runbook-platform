# Phase 10 Readiness Audit

**Date:** 2026-04-23  
**Auditor:** Claude Code (claude-sonnet-4-6)  
**Branch:** phase-9  
**Scope:** Full read-only audit of phases 01–09 implementation against all blueprints; Phase 10 readiness assessment.

---

## 1. Metadata

| Field | Value |
|---|---|
| Audit type | Pre-expansion readiness review |
| Source of truth | `docs/blueprints/phase-01-*.md` through `phase-10-*.md` |
| Files inspected | 40+ across all services |
| Code modified | None |
| New files created | This file only |

---

## 2. Executive Verdict

**CONDITIONALLY READY**

Phases 01–09 are substantially implemented with correct architecture. The execution model, service-layer patterns, runner claim protocol, and React frontend all match blueprint intent. Architecture invariants INV-1 through INV-8 all pass.

Two P1 blockers must be fixed before Phase 10 expansion begins:

1. CI never executes tests — the GitHub Actions workflow runs only lint, meaning regressions in any phase could go undetected as Phase 10 layers are added.
2. `claim_token` is missing `unique=True` — Phase 04 blueprint explicitly required this; without it, a theoretical race condition allows two runners to reference the same token value.

Three P2 issues need resolution in the first Phase 10 sprint: the AI service healthcheck gap in docker-compose, the missing `waiting_for_approval` execution step state, and undocumented stub status of the AI parser.

---

## 3. Phase-by-Phase Implementation Matrix

| Phase | Title | Status | Notes |
|---|---|---|---|
| 01 | End-to-End Vertical Slice | ✅ Complete | All boundaries established; UUID PKs, poll model, status enums all in place |
| 02 | Django Domain Foundation | ✅ Complete | BaseModel (renamed from TimeStampedUUIDModel — functionally identical); all domain apps created; PROTECT FKs; snapshot strategy correct |
| 03 | Application Service Layer | ✅ Complete | `create_runbook`, `create_workflow`, `create_execution` all in services.py; AI transform called outside transaction |
| 04 | Versioned REST APIs | ⚠️ Mostly complete | claim_token missing `unique=True`; runner_services not in separate file (merged into services.py); all endpoints correct |
| 05 | Runner Real Flow | ✅ Complete | poller.py, executor.py, schemas.py all match blueprint; FAIL_STEP marker, heartbeat thread, sequential step execution all implemented |
| 06 | React Product Slice | ✅ Complete | React 19, TanStack Query, React Router v7, feature folders; polls Django only |
| 07 | AI Service Boundary | ✅ Complete | Django calls AI via httpx; AI is stateless; frontend never touches AI; RunbookAiClient error hierarchy correct |
| 08 | Targeted Testing | ⚠️ Partially complete | Tests exist for all layers; CI never runs them (lint only) |
| 09 | Local Operational Polish | ✅ Complete | 35+ Makefile targets; seed_dev; ruff; prettier; pre-commit with all hooks |

---

## 4. Architecture Invariant Audit

Phase 10 blueprint defines INV-1 through INV-8. All pass.

| Invariant | Description | Status | Evidence |
|---|---|---|---|
| INV-1 | Django owns all orchestration and persistence | ✅ Pass | Runner has no DB access; all state changes via API |
| INV-2 | Runner calls only Django API | ✅ Pass | `runner/client.py` — all calls to `self._base` (Django API); no external calls |
| INV-3 | Frontend calls only Django API | ✅ Pass | `shared/api/client.ts` — only `VITE_API_BASE_URL` (Django API) |
| INV-4 | AI service is stateless and advisory | ✅ Pass | `workflow_parser.py` returns candidate only; no persistence; Django decides |
| INV-5 | All endpoints versioned under /api/v1/ | ✅ Pass | Public: `/api/v1/`; Internal: `/api/v1/internal/`; confirmed in url configs |
| INV-6 | UUID primary keys everywhere | ✅ Pass | `BaseModel` enforces `UUIDField(primary_key=True, default=uuid.uuid4)` |
| INV-7 | Business logic lives in services.py | ✅ Pass | Views delegate to services; no model methods with logic; no fat serializers |
| INV-8 | No premature event/queue infrastructure | ✅ Pass | Poll-based throughout; no Celery, Redis, or Kafka introduced |

---

## 5. Drift Findings

Deviations between blueprint specification and actual implementation.

### DRIFT-01 — BaseModel vs TimeStampedUUIDModel (Low, cosmetic)

**Blueprint (Phase 02):** "Create a `TimeStampedUUIDModel` abstract base class."  
**Actual:** `apps/api/apps/common/models.py` defines `class BaseModel(models.Model)`.  
**Impact:** None — fields are identical (`id`, `created_at`, `updated_at`). All domain models inherit from `BaseModel` correctly.  
**Recommendation:** Document the rename in CLAUDE.md or leave as-is; no code change required.

### DRIFT-02 — claim_token missing unique=True (Medium, correctness)

**Blueprint (Phase 04):** "claim_token: UUIDField(unique=True, null=True, blank=True)."  
**Actual:** `apps/api/apps/executions/models.py` — `claim_token = models.UUIDField(null=True, blank=True)`. Migration `0002` confirms no unique constraint.  
**Impact:** Under the current single-runner setup, no practical race condition. With multiple runners and Phase 10 scale, two runners could theoretically hold token references with the same UUID value (astronomically unlikely with UUID4, but the constraint was an explicit design requirement).  
**Recommendation:** Add `unique=True` via a new migration before Phase 10 work begins.

### DRIFT-03 — runner_services.py not separated (Low)

**Blueprint (Phase 04):** "Put runner-specific service functions in a separate `runner_services.py` file."  
**Actual:** Runner-facing service functions (`claim_next_execution`, `update_execution_step`, `complete_execution`) live in `apps/api/apps/executions/services.py` alongside public service functions.  
**Impact:** None architecturally — logic is still in the service layer. Separation improves navigability for Phase 10.1+ which will add approval-gating logic to the claim path.  
**Recommendation:** Extract to `runner_services.py` as part of the first Phase 10 sprint.

### DRIFT-04 — AI parser is a deterministic stub (Medium, expectation)

**Blueprint (Phase 07):** "FastAPI AI service" — implies LLM-backed processing.  
**Actual:** `apps/ai/app/services/workflow_parser.py` uses only `re.compile` regex to extract numbered list items. `OPENAI_API_KEY` env var is present in `.env.example` but is unused by any code path.  
**Impact:** Phase 10.6 (Real AI Integration) is explicitly listed as the upgrade path. However, the stub status is not documented anywhere visible — developers could assume AI is live.  
**Recommendation:** Add a single comment in `workflow_parser.py` header and in `.env.example` noting `OPENAI_API_KEY` is reserved for Phase 10.6.

---

## 6. Phase 10 Readiness Assessment

### Phase 10.1 — Approvals

**Untracked blueprint:** `docs/blueprints/phase-10-01-approvals-blueprint.md` exists (git untracked).

**Readiness blockers:**
- `ExecutionStep.status` choices do not include `waiting_for_approval`. This enum extension is required before any approval-gate logic can be wired to the executor.
- The runner's `executor.py` has no concept of pausing mid-execution. Phase 10.1 will require the runner to poll for approval state on steps with `requires_approval=True` — the `ClaimedStep` schema already has `requires_approval: bool` field, which is a good foundation.
- An `Approval` model needs to be created in `apps/api/apps/approvals/` (currently an empty stub — no `models.py`).

**Good foundation:** `requires_approval` field already flows from workflow definition through `ClaimedStep` schema to the runner.

### Phase 10.2 — Policies

**Untracked blueprint:** `docs/blueprints/phase-10-02-policies-blueprint.md` exists (git untracked).

**Readiness:** `apps/api/apps/policies/` is a stub. No blockers beyond Phase 10.1 completion (policies will gate approvals). The service-layer pattern is well-established for extension.

### Phase 10.3 — Audit Trail

**Untracked blueprint:** `docs/blueprints/phase-10-03-audit-trail-blueprint.md` exists (git untracked).

**Readiness:** `apps/api/apps/audit/` is a stub. Django signals or explicit service calls can trigger audit events. The `BaseModel` timestamps (`created_at`, `updated_at`) provide a baseline. No blockers — can be implemented in parallel with 10.1/10.2.

### Phase 10.4 — Artifacts

`apps/api/apps/artifacts/` is a stub; `apps/runner/runner/artifact_uploader.py` exists as a placeholder. The runner → Django API boundary is well-defined for adding artifact upload endpoints.

### Phase 10.5 — Integrations

`apps/api/apps/integrations/` is a stub. No foundation work needed beyond standard service-layer patterns already established.

### Phase 10.6 — Real AI

`OPENAI_API_KEY` env var exists; `apps/ai/app/` FastAPI structure is in place; `RunbookAiClient` in Django already handles all AI error cases. This is the most self-contained Phase 10 item — swap the regex parser for an LLM call in `workflow_parser.py`.

### Phase 10.7–10.10 — Auth, Live Streaming, Hardening, AWS

These phases require infrastructure additions (SSO/OIDC, WebSockets, secrets management, ECS/RDS). No blockers from current implementation; all are additive.

---

## 7. Dev Tooling Findings

| Tool | Status | Notes |
|---|---|---|
| Makefile | ✅ Excellent | 35+ targets, `.PHONY` correct, `help` target documents all commands |
| `seed-dev` | ✅ Working | Creates org, runbook, workflow, triggers execution for local testing |
| Ruff | ✅ Configured | `pyproject.toml` with line-length 100, import sorting, all relevant rules |
| Prettier | ✅ Configured | `.prettierrc` with project-consistent settings |
| Pre-commit | ✅ Configured | `trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`, `check-yaml`, `ruff-format`, `ruff`, `prettier` |
| `make format` | ✅ Working | Runs ruff format + prettier across all services |
| `make lint` | ✅ Working | Runs ruff check + prettier check + eslint |
| `make test-api` | ✅ Defined | Runs `docker compose exec api pytest` |
| `make test-runner` | ✅ Defined | Runs runner pytest |
| `make test-web` | ✅ Defined | Runs Vitest |

---

## 8. Test and CI Gap Analysis

### Test Coverage Assessment

| Layer | Test files | Coverage areas |
|---|---|---|
| Django API | `apps/*/tests/` | models, services, views for runbooks, workflows, executions |
| Runner | `apps/runner/tests/` | executor, client, schemas |
| Web | `apps/web/src/**/*.test.tsx` | Route-level page tests with MSW mocking |
| AI service | `apps/ai/tests/` | Parser unit tests |

Tests exist across all four service boundaries. The pytest-django + Vitest + MSW pattern from Phase 08 is implemented.

### CI Gap — CRITICAL

`.github/workflows/ci.yml` runs:

```
Python: compileall, ruff check, ruff format --check
Web:    npm run build, npm run lint, npm run format:check
```

**Tests are never executed in CI.** `pytest` is not invoked. `vitest run` is not invoked.

This means:
- Any broken service-layer logic merged to main is not caught by CI.
- Phase 10 additions could silently break Phase 01–09 execution paths.
- The Makefile has `test-api`, `test-runner`, `test-web` but they are not referenced in the CI workflow.

**Required fix:** Add pytest and Vitest jobs to `ci.yml` before Phase 10 begins.

---

## 9. Docker and Infrastructure Audit

### docker-compose.yml Service Analysis

| Service | Healthcheck | depends_on (with condition) | Notes |
|---|---|---|---|
| postgres | ✅ `pg_isready` | — | Correct |
| api | ✅ `wget /health/` | ✅ postgres (service_healthy) | Correct |
| ai | ❌ None | ❌ None | Starts before api; no readiness signal |
| runner | ✅ Via api | ✅ api (service_healthy) | Correct |
| web | ✅ Via api | ✅ api (service_started) | Acceptable for dev |

**Gap:** The `ai` service has no healthcheck and no `depends_on`. The `api` service calls the AI service on runbook parse requests. If the AI service is slow to start (e.g., cold container + model loading in future Phase 10.6), Django may receive connection errors during `POST /parse`. Currently mitigated by `RunbookAiClient` error handling, but the compose dependency should be explicit.

### Environment Variables

`.env.example` contains all required variables:
- `DJANGO_SECRET_KEY`, `DATABASE_URL` ✅
- `OPENAI_API_KEY` ✅ (present, unused until Phase 10.6)
- `RUNNER_REGISTRATION_TOKEN` ✅
- `AI_BASE_URL`, `AI_SERVICE_TIMEOUT_SECONDS` ✅
- `VITE_API_BASE_URL` ✅

---

## 10. Security and Deployment Audit

### Authentication on Internal Endpoints

`apps/api/config/settings/base.py`:
```python
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    ...
}
```

All endpoints — including internal runner endpoints — use `AllowAny`. The runner's `claim_token` provides per-execution ownership validation in the service layer, but there is **no network-level authentication** on `/api/v1/internal/` routes. Any process that can reach the API can call claim-next.

**For local/Docker development:** Acceptable — internal network only.  
**For Phase 10 / production:** Phase 10.7 (Auth hardening) must add token or mTLS authentication to internal routes before any public deployment. This is explicitly scoped to Phase 10.7, so it is not a blocker for Phase 10.1–10.6, but must be tracked.

### CORS

`django-corsheaders` is installed and in `INSTALLED_APPS`. `CORS_ALLOW_ALL_ORIGINS = True` in `base.py` — acceptable for local dev, must be tightened for production (Phase 10.9 Hardening scope).

### Secret Key

`DJANGO_SECRET_KEY` is read from env via `django-environ`. `.env` is in `.gitignore`. No hardcoded secrets found.

### SQL Injection

All database access goes through Django ORM. No raw SQL found. `select_for_update(skip_locked=True)` in claim-next service is ORM-safe.

---

## 11. Remediation Plan

Ordered by priority before starting Phase 10.1.

### P1 — Must fix before Phase 10 begins

| ID | Action | File | Effort |
|---|---|---|---|
| REM-01 | Add pytest + Vitest jobs to ci.yml | `.github/workflows/ci.yml` | 30 min |
| REM-02 | Add `unique=True` to `claim_token` field + new migration | `apps/api/apps/executions/models.py`, new migration | 15 min |

### P2 — Fix in first Phase 10.1 sprint

| ID | Action | File | Effort |
|---|---|---|---|
| REM-03 | Add `waiting_for_approval` to `ExecutionStep.Status` choices + migration | `apps/api/apps/executions/models.py`, new migration | 20 min |
| REM-04 | Add healthcheck to `ai` service in docker-compose | `docker-compose.yml` | 10 min |
| REM-05 | Add comment to `workflow_parser.py` noting stub status | `apps/ai/app/services/workflow_parser.py` | 5 min |
| REM-06 | Extract runner-facing functions to `runner_services.py` | `apps/api/apps/executions/` | 45 min |

### P3 — Before Phase 10.7 (Auth)

| ID | Action | Effort |
|---|---|---|
| REM-07 | Add token authentication to `/api/v1/internal/` routes | 2–4 hours |
| REM-08 | Restrict CORS to known origins | 15 min |

---

## 12. Suggested Next Prompts

After applying REM-01 and REM-02:

```
Implement Phase 10.1: Approvals. 
Follow docs/blueprints/phase-10-01-approvals-blueprint.md.
Start with the Approval model in apps/api/apps/approvals/,
then add waiting_for_approval to ExecutionStep.Status,
then wire approval-gate logic into the runner executor.
Run: docker compose exec api pytest apps/approvals/tests/
```

After Phase 10.1 is merged:

```
Implement Phase 10.3: Audit Trail.
This can run in parallel with Phase 10.2 (Policies).
Add AuditEvent model in apps/api/apps/audit/.
Wire Django signals on Execution and ExecutionStep status changes.
```

After Phase 10.6 (Real AI):

```
Replace the regex stub in apps/ai/app/services/workflow_parser.py
with a real OpenAI call. The OPENAI_API_KEY env var is already
wired. Keep the deterministic fallback for when the API is unavailable.
Run the AI service tests to verify contract is preserved.
```

---

## 13. Final Recommendation

**Begin Phase 10 after completing REM-01 and REM-02.**

The codebase is architecturally sound. The service-layer pattern, execution model, runner protocol, and frontend boundaries are all correctly implemented and match blueprint intent. The Phase 10 expansion areas are additive — none require breaking existing contracts.

The single most important investment before expansion is **wiring tests into CI** (REM-01). Phase 10 will touch the execution model, step state machine, and runner executor across multiple sprints. Without automated test execution on every push, regressions will be found in integration testing rather than at merge time.

`claim_token unique=True` (REM-02) is a one-migration fix that closes a known blueprint deviation before scale increases.

Implement Phase 10 in blueprint order: **10.1 Approvals → 10.2 Policies → 10.3 Audit Trail**, as these three are foundational to all subsequent phases.
