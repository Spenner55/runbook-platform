# Phase 11.3 Implementation Readiness

Prepared: 2026-05-05

Scope: read the Phase 11.1, 11.2, and 11.3 blueprints, inspected current source, and wrote this readiness note only. No application code was modified.

## 1. Prerequisite Readiness

Phase 11.1 appears complete enough to start Phase 11.3. The `changes` app exists, `OperationProfile`, `ChangeRecord`, `ChangeTarget`, and `ChangeExecutionBinding` are implemented, change-level approval subjects exist, direct execution creation is blocked for active operation-profile workflows, runner bind uses the existing internal API tree, and successful verification-required executions move to `verification_pending`.

Phase 11.2 is structurally complete enough to begin Phase 11.3 backend model and service work, but not clean enough to call fully verified without caveats. The window/freeze/lock/preflight models and APIs exist, dispatch acquires DB target locks, and runner timing callbacks exist. Before releasing Phase 11.3 runner verification callbacks, address or explicitly accept these 11.2 drifts:

- `run_dispatch_preflight` passes when no `ChangeWindow` exists, while the blueprint expects an approved open window gate.
- `make_dispatchable` reuses a fresh passed preflight instead of always running a fresh transactional preflight; 11.3 plan enforcement must not be bypassable by an older passed preflight.
- timing callbacks validate bound runner id but do not require `claim_token`; 11.3 callbacks should include and validate `claim_token`.
- `execution-accepted` exists server-side, but the runner currently calls only `execution-started` and `execution-finished`.
- freeze exception fields exist, but there is no public API/UI to record them and no approval invalidation path when they change after approval.

## 2. Blueprint Drift

- The Phase 11.3 blueprint says `apps/api/apps/changes/` and web change features may be absent; they are present now with Phase 11.1 and 11.2 migrations through `changes.0004`.
- Current internal change views and serializers are co-located in `apps/api/apps/changes/views.py` and `apps/api/apps/changes/serializers.py`; there is no `changes/internal_views.py` or `changes/internal_serializers.py`.
- `OperationProfile` has only `verification_required`; it lacks `verification_mode`, `verification_plan_template`, `requires_independent_reviewer`, and `verification_timeout_seconds`.
- `ChangeRecord.Status` lacks `verification_failed`, and `transitions.py` lacks `verification_pending -> verification_failed`.
- `handle_bound_execution_completed` already moves failed/cancelled executions to terminal `closed`; closure service must account for that existing closed failure path.
- `ChangeWindow` terminal/running status helpers do not know about `verification_failed`.
- Artifact storage is ready for verification evidence: `Artifact` has execution, step, kind, checksum, upload status, runner id, and metadata. No required artifact app change is apparent for Phase 11.3; verification services can validate against `Artifact` directly.
- `AuditEvent.ObjectType` already includes Phase 11.1/11.2 change objects but not `verification_plan`, `verification_check`, `verification_result`, or `change_closure`.
- `apps/web/src/shared/api/client.ts` already blocks `/api/v1/internal/`; keep verification UI on public APIs only.

## 3. Files To Change

Must change:

- `apps/api/apps/changes/models.py`
- `apps/api/apps/changes/migrations/0005_phase113_verification_closure.py` and possibly a second migration for `VerificationCheck.last_result`
- `apps/api/apps/changes/admin.py`
- `apps/api/apps/changes/transitions.py`
- `apps/api/apps/changes/services.py`
- `apps/api/apps/changes/selectors.py`
- `apps/api/apps/changes/serializers.py`
- `apps/api/apps/changes/views.py`
- `apps/api/apps/changes/urls.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/audit/migrations/0009_phase113_object_types.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/artifact_uploader.py`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/features/changes/types.ts`
- `apps/web/src/features/changes/api/changesApi.ts`
- new hooks under `apps/web/src/features/changes/hooks/`
- `apps/web/src/routes/changes/ChangeDetailPage.tsx`
- `apps/web/src/routes/changes/ChangesPage.tsx`

Tests to add or update:

- `apps/api/apps/changes/tests/test_verification_models.py`
- `apps/api/apps/changes/tests/test_verification_services.py`
- `apps/api/apps/changes/tests/test_verification_api.py`
- `apps/api/apps/changes/tests/test_closure.py`
- `apps/api/apps/changes/tests/test_runner_verification_callbacks.py`
- existing `apps/api/apps/changes/tests/test_transitions.py`
- existing `apps/api/apps/changes/tests/test_preflight_service.py`
- existing `apps/api/apps/changes/tests/test_dispatch_integration.py`
- existing `apps/api/apps/changes/tests/test_audit_integration.py`
- `apps/runner/runner/tests/test_verification_callbacks.py`
- existing runner client/schema/executor/artifact tests
- existing `apps/web/src/routes/changes/ChangeDetailPage.test.tsx`
- existing `apps/web/src/routes/changes/ChangesPage.test.tsx`

Should not need application changes unless the implementation deliberately changes route roots or artifact ownership helpers:

- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/artifacts/models.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/web/src/shared/api/client.ts`

## 4. Runner Callback Route Convention

Use the existing convention:

```text
POST /api/v1/internal/changes/<uuid:change_id>/verification-results/
```

Do not introduce `/internal/v1/...` for Phase 11.3 unless the whole API versioning scheme is intentionally changed. The runner already posts to `/api/v1/internal/...`, `api_v1_urls.py` already includes `change_internal_urlpatterns` under `internal/changes/`, and the browser client already blocks `/api/v1/internal/`.

The internal verification payload should include `runner_id`, `claim_token`, `execution_id`, check key, verification key, outcome, optional source step key, artifact ids/checksums, and small observed facts. Django should validate runner bearer auth, current execution ownership, claim token, bound change, artifact ownership, and check membership before creating any `VerificationResult`.

## 5. Small-Batch Order And Verification

1. Model/audit/status batch: add verification models, `verification_failed`, profile verification config, audit object types, admin read-only closure behavior, and migration tests.
   - `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api python manage.py makemigrations --check --dry-run`
   - `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests/test_verification_models.py apps/changes/tests/test_transitions.py apps/audit/tests/test_models.py apps/audit/tests/test_services.py -q`

2. Plan generation and dispatch gate batch: add template validation, `ensure_verification_plan`, preflight/dispatch plan requirement, and execution-completion plan activation/evaluation hooks.
   - `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests/test_verification_services.py apps/changes/tests/test_preflight_service.py apps/changes/tests/test_dispatch_integration.py -q`

3. Public result API batch: add plan read endpoint and public result submission endpoint with manual, artifact, external-reference, and rejection paths.
   - `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests/test_verification_api.py apps/changes/tests/test_verification_services.py apps/artifacts/tests/test_services.py -q`

4. Closure batch: add `ChangeClosure`, `close_change_record`, closure API, independent reviewer enforcement, and remaining lock/window cleanup.
   - `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests/test_closure.py apps/changes/tests/test_audit_integration.py apps/changes/tests/test_timing_callbacks.py -q`

5. Internal runner verification batch: add internal verification-result endpoint and runner schemas/client/executor artifact-result plumbing.
   - `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests/test_runner_verification_callbacks.py apps/executions/tests/test_runner_api.py apps/artifacts/tests/test_internal_api.py -q`
   - `docker compose exec runner pytest runner/tests/test_verification_callbacks.py runner/tests/test_client.py runner/tests/test_executor.py runner/tests/test_artifact_uploader.py -q`

6. Web batch: add public API functions, hooks, checklist, attestation, close dialog, `verification_failed` display, and cache invalidation.
   - `docker compose exec web npm test -- --run src/routes/changes/ChangeDetailPage.test.tsx src/routes/changes/ChangesPage.test.tsx`
   - `docker compose exec web npm run build`

7. Final gate:
   - `make lint`
   - `make test-api`
   - `make test-runner`
   - `make test-web`
   - `make check-migrations`
   - `make hardening-check`
