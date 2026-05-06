# Phase 11.3 Implementation Summary

Prepared: 2026-05-05  
Branch: `phase-11.2` (Phase 11.3 changes are in the working tree, not yet committed as a separate branch)

---

## 1. What Was Implemented

Phase 11.3 adds first-class post-change verification plans, verification evidence, and controlled closure to the `ChangeRecord` lifecycle.

### Data models (`apps/api/apps/changes/models.py`)

- **`VerificationPlan`** — one-to-one generated contract per `ChangeRecord`, with mode (`automated`, `manual`, `mixed`), lifecycle status, check counts, and profile snapshot + SHA-256.
- **`VerificationCheck`** — expected verification item in a plan; five check types: `runner_step`, `artifact_presence`, `manual_attestation`, `api_assertion`, `external_reference`. Unique per `(plan, key)` and `(plan, position)`. All relevant constraints and indexes present.
- **`VerificationResult`** — immutable evidence record per check attempt; `save()` rejects updates after creation. Sources: `runner`, `user`, `system`.
- **`ChangeClosure`** — immutable controlled-close record; `save()` and `delete()` both reject after creation; one-to-one with `ChangeRecord`.
- **`ChangeRecord.Status.VERIFICATION_FAILED`** — new status added to the check constraint.
- **`OperationProfile`** — extended with `verification_mode`, `verification_plan_template`, `requires_independent_reviewer`, and `verification_timeout_seconds`.

### Services (`apps/api/apps/changes/services.py`)

- `ensure_verification_plan(change, actor, activate)` — create-once plan generation from the operation profile template; validates template shape, check types, mode/composition consistency, and credential-like keys.
- `submit_verification_result(...)` — common result service. Validates by check type: `runner_step` requires runner ownership and claim token; `artifact_presence` requires real available artifact from the bound execution; `manual_attestation` enforces independent reviewer and rejects self-review; `api_assertion` rejects with `api_assertion_adapter_unavailable`; `external_reference` requires pattern match.
- `recompute_verification_state(change)` — counts accepted results, transitions `verification_pending → verified` when all required checks pass, transitions to `verification_failed` when a required check fails; emits audit events.
- `close_change(change, outcome, summary, closed_by, independent_reviewer_id)` — validates outcome compatibility with change status, requires all required checks passed for `success`/`partial_success`, enforces independent reviewer (non-self), creates immutable `ChangeClosure`, sets `ChangeRecord.status = closed`, releases target locks.
- `run_dispatch_preflight` — extended with a `_preflight_check_verification_plan` sub-check that fails if a verification-required change has no generated plan.
- `make_dispatchable` — calls `ensure_verification_plan` before the preflight gate.

### Migrations

- `changes.0005_changeclosure_verificationcheck_verificationplan_and_more` — adds all Phase 11.3 tables, constraints, indexes, `verification_failed` status, and `OperationProfile` verification config fields in one migration.

### Internal API (`apps/api/apps/changes/views.py`, `urls.py`)

- `InternalRunnerVerificationResultView` at `POST /api/v1/internal/changes/<id>/verification-results/` — runner bearer auth required; rejects user JWTs; validates runner ownership, claim token, execution binding, and artifact ownership before creating a `VerificationResult`.

### Public API (`apps/api/apps/changes/views.py`, `serializers.py`, `urls.py`)

- `GET /api/v1/changes/<id>/verification-plan/` — returns plan, checks, last accepted results, and unmet required checks.
- `POST /api/v1/changes/<id>/verification-results/` — user/manual/external-reference result submission.
- `POST /api/v1/changes/<id>/close/` — creates immutable closure, transitions change to `closed`.

### Audit scrubbing (`apps/api/apps/audit/services.py`)

Extended `FORBIDDEN_METADATA_KEYS` with Phase 11.3 verification/closure sensitive keys: `attestation_text`, `external_access_token`, `manual_attestation_text` (already present), `request_payload`, `response_body`, `verification_secret`, `api_assertion_response` (already present).

### Runner (`apps/runner/runner/`)

- `schemas.py` — `VerificationResultRequest`, `VerificationResultResponse`; optional `verification_plan_id` and `verification_keys` in claimed execution payload.
- `client.py` — `submit_change_verification_result(...)` posts to `/api/v1/internal/changes/<id>/verification-results/`.
- `executor.py` — after artifact upload and step update, submits configured verification keys when the claimed execution carries them; does not evaluate final plan state.

### Frontend (`apps/web/src/`)

- `features/changes/types.ts` — `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure` types.
- `features/changes/api/changesApi.ts` — `getVerificationPlan`, `submitVerificationResult`, `closeChange`.
- `features/changes/hooks/useVerificationPlan.ts`, `useSubmitVerificationResult.ts`, `useCloseChange.ts`.
- `routes/changes/ChangeDetailPage.tsx` — verification checklist panel, manual attestation modal, independent reviewer control, closure dialog, unmet-check blocking display.
- `shared/lib/queryKeys.ts` — `verificationPlan`, `changeClosure` query keys added.

---

## 2. Files Changed by Area

### Backend — models, migrations, admin

| File | Change |
|---|---|
| `apps/api/apps/changes/models.py` | `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`; `verification_failed` status; `OperationProfile` verification config fields |
| `apps/api/apps/changes/migrations/0005_changeclosure_verificationcheck_verificationplan_and_more.py` | All Phase 11.3 DB changes |
| `apps/api/apps/changes/admin.py` | Read-only admin for `VerificationPlan`, `VerificationCheck`, `VerificationResult`; fully locked `ChangeClosureAdmin` (no add/change/delete) |
| `apps/api/apps/changes/transitions.py` | `verification_pending → verification_failed` transition added |

### Backend — services, serializers, views, URLs

| File | Change |
|---|---|
| `apps/api/apps/changes/services.py` | Plan generation, result validation, recomputation, closure, preflight extension |
| `apps/api/apps/changes/serializers.py` | Public plan, check, result, closure serializers |
| `apps/api/apps/changes/views.py` | `ChangeVerificationPlanView`, `ChangeVerificationResultCreateView`, `ChangeCloseView`, `InternalRunnerVerificationResultView` |
| `apps/api/apps/changes/urls.py` | New public and internal routes |
| `apps/api/apps/executions/internal_serializers.py` | Optional verification metadata in claimed execution payload |
| `apps/api/apps/audit/services.py` | Extended `FORBIDDEN_METADATA_KEYS` for Phase 11.3 verification/closure keys |

### Runner

| File | Change |
|---|---|
| `apps/runner/runner/schemas.py` | `VerificationResultRequest`, `VerificationResultResponse`, claimed execution verification metadata |
| `apps/runner/runner/client.py` | `submit_change_verification_result` |
| `apps/runner/runner/executor.py` | Emits verification facts after step/artifact completion |

### Frontend

| File | Change |
|---|---|
| `apps/web/src/features/changes/types.ts` | Verification and closure types |
| `apps/web/src/features/changes/api/changesApi.ts` | Plan fetch, result submit, close functions |
| `apps/web/src/features/changes/hooks/useVerificationPlan.ts` | New |
| `apps/web/src/features/changes/hooks/useSubmitVerificationResult.ts` | New |
| `apps/web/src/features/changes/hooks/useCloseChange.ts` | New |
| `apps/web/src/routes/changes/ChangeDetailPage.tsx` | Checklist, attestation, reviewer, closure, blocking display |
| `apps/web/src/shared/lib/queryKeys.ts` | New query keys |

### Tests added / modified

| File | Change |
|---|---|
| `apps/api/apps/changes/tests/test_verification_models.py` | New — 23 tests; model constraints, immutability, tenant validation |
| `apps/api/apps/changes/tests/test_verification_plan_services.py` | New — 6 tests; plan generation, dispatch gate |
| `apps/api/apps/changes/tests/test_verification_result_services.py` | New — 8 tests; result validation paths |
| `apps/api/apps/changes/tests/test_internal_verification_callback.py` | New — 5 tests; runner auth, ownership, route convention |
| `apps/api/apps/changes/tests/test_dispatch_integration.py` | 2 tests fixed — `ensure_verification_plan` added before manual preflight calls |
| `apps/api/apps/changes/tests/conftest.py` | `operation_profile` fixture extended with `verification_plan_template` |
| `apps/api/apps/changes/tests/test_preflight_service.py` | Updated for plan-aware preflight |
| `apps/api/apps/changes/tests/test_transitions.py` | Updated for `verification_failed` transition |
| `apps/api/apps/changes/tests/test_api.py` | Updated for Phase 11.3 endpoints |
| `apps/api/apps/audit/tests/test_services.py` | 7 parametrized tests for Phase 11.3 scrub keys added |
| `apps/runner/runner/tests/test_client.py` | Runner verification callback client tests |
| `apps/runner/runner/tests/test_executor.py` | Executor verification fact emission tests |
| `apps/web/src/routes/changes/ChangeDetailPage.test.tsx` | 33 tests covering checklist, attestation, closure UI |

---

## 3. Verification Commands and Results

All gates passed on 2026-05-05.

```
docker compose exec api python manage.py check
→ System check identified no issues (0 silenced)

docker compose exec api pytest
→ 1276 passed, 1 warning in 90.29s

docker compose exec runner pytest
→ 148 passed in 7.55s

cd apps/web && npm run lint
→ (no errors)

cd apps/web && npm test -- --run
→ 19 test files, 162 tests passed

cd apps/web && npm run build
→ built in 304ms, no errors
```

---

## 4. Known Limitations Deferred to Phase 11.4 or 11.5

| Limitation | Deferred to |
|---|---|
| Emergency exceptions and breakglass bypass paths | Phase 11.4 |
| `canceled` and `failed` outcome closure paths for non-verification-failed changes | Phase 11.4 (exception semantics) |
| `api_assertion` checks always rejected with `api_assertion_adapter_unavailable` — no integration adapter implemented | Phase 11.4/11.5 or a dedicated integration batch |
| Sealed evidence bundle signing, dossier sealing, closure package hashing | Phase 11.5 |
| `ChangeWindow` status helpers do not know about `verification_failed` | Existing 11.2 drift; noted in 11.2 readiness report |
| Freeze exception public API/UI (exception fields exist on model only) | Phase 11.4 |
| Runner calls only `execution-started` and `execution-finished`; `execution-accepted` callback is server-side only | Existing 11.2 drift; acceptable for Phase 11.3 |

---

## 5. Drift From Blueprint and Why It Was Acceptable

| Blueprint expectation | Actual implementation | Why acceptable |
|---|---|---|
| Separate audit `ObjectType` values for `verification_plan`, `verification_check`, `verification_result`, `change_closure` | All verification/closure audit events use `CHANGE_RECORD` as the object type; dedicated IDs are included in metadata | Avoids another migration and audit model change; all evidence IDs are present in metadata; full audit trail still exists |
| `selectors.py` module for organization-scoped plan/check selectors | Selectors are inline functions in `services.py` | No `selectors.py` existed; the pattern was not introduced in 11.1/11.2; inline selectors maintain the existing pattern |
| `internal_views.py` / `internal_serializers.py` split for changes | Internal view and serializer are co-located in `views.py` and `serializers.py` | The readiness report identified this drift before implementation and deemed it acceptable; the project has no `internal_views.py` convention yet |
| Two migrations — one for main models, a second for `VerificationCheck.last_result` circular FK | One migration covers everything | Django handles the `self-referential FK through` the `"VerificationResult"` string reference cleanly in a single migration |
| `artifact_uploader.py` changes for verification artifact ID/checksum return | Not changed | `executor.py` accesses artifact IDs/checksums from the upload response already returned by the existing uploader API; no change required |
| Preflight check passes without verification plan (Phase 11.2 behavior) | Preflight check now fails if verification-required change lacks a plan | Correct Phase 11.3 behavior; 2 dispatch integration tests required a one-line fixture call (`ensure_verification_plan`) to fix |
