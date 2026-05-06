# Phase 11.2 Windows, Freezes, And Target Locks

Phase 11.2 is implemented as a Django-controlled dispatch safety layer for
Phase 11.1 change records. It adds approved change windows, production freeze
rules, target conflict locks, dispatch preflight snapshots, runner execution
timing callbacks, and React screens for change preflight and freeze-rule
operations.

This document records the implemented state only. Phase 11.3 has not been
started.

## Implemented Surface

| Area | Implemented behavior |
| --- | --- |
| Change windows | `ChangeWindow` stores one approved window per change with `scheduled`, `open`, `expired`, `overrun`, and `closed` states. |
| Freeze rules | `FreezeRule` supports organization-scoped `block` and `allow_with_exception` rules over all production, target type, or target identifier scopes. |
| Freeze exceptions | `ChangeRecord` has bounded freeze exception reference fields. These satisfy only `allow_with_exception` rules and do not bypass approval, policy, window, target lock, or authorization checks. |
| Target locks | `TargetLock` uses a Postgres partial unique constraint so only one active lock can exist for a given organization, target type, and normalized identifier. |
| Dispatch preflight | `DispatchEligibilityCheck` persists immutable `passed` or `failed` snapshots for approval status, policy, window, freeze, target-lock, and actor checks. |
| Dispatch gate | Dispatch reuses a fresh passed preflight or reruns preflight in the dispatch transaction. Failed preflight blocks dispatch. |
| Runner timing callbacks | Change-bound executions report accepted, started, and finished timestamps to Django. Finished callbacks release active target locks and close or overrun windows. |
| Frontend | Change detail exposes preflight state/actions. Freeze rules have list/create/deactivate UI under `/freeze-rules`. |

## Route Choices

The implementation keeps the repository's existing versioned API convention:
all v1 endpoints live under `/api/v1/...`.

Public user-facing routes:

| Route | Purpose |
| --- | --- |
| `GET /api/v1/changes/operation-profiles/` | List active operation profiles for the selected organization. |
| `GET, POST /api/v1/changes/` | List and create change records. |
| `GET /api/v1/changes/{change_id}/` | Retrieve a change dossier. |
| `POST /api/v1/changes/{change_id}/submit/` | Submit a draft change for approval or approval-free dispatch flow. |
| `POST /api/v1/changes/{change_id}/dispatch/` | Run the dispatch gate and reserve execution if eligible. |
| `GET, PATCH /api/v1/changes/{change_id}/window/` | Retrieve or update the change window. |
| `POST /api/v1/changes/{change_id}/preflight/` | Run dispatch preflight. |
| `GET /api/v1/changes/{change_id}/preflight/latest/` | Retrieve latest preflight snapshot. |
| `GET, POST /api/v1/freeze-rules/` | List or create freeze rules. |
| `GET, PATCH /api/v1/freeze-rules/{rule_id}/` | Retrieve or update a freeze rule. |
| `POST /api/v1/freeze-rules/{rule_id}/deactivate/` | Deactivate a freeze rule. |

Internal runner-only routes:

| Route | Purpose |
| --- | --- |
| `POST /api/v1/internal/changes/{change_id}/bind-execution/` | Bind claimed runner execution to a change using the dispatch token. |
| `POST /api/v1/internal/changes/{change_id}/execution-accepted/` | Store runner-observed acceptance time. |
| `POST /api/v1/internal/changes/{change_id}/execution-started/` | Store runner-observed execution start time. |
| `POST /api/v1/internal/changes/{change_id}/execution-finished/` | Store runner-observed finish time and release locks. |

The prompt mentioned `/internal/v1/...`, but this repo already standardizes
runner endpoints under `/api/v1/internal/...` in `config/api_v1_urls.py`, the
runner client, API docs, README, and frontend API guard. Phase 11.2 follows
that convention instead of introducing a second internal namespace. Browser
code still rejects `/api/v1/internal/` calls.

## Migration And Backfill Status

Applied migrations:

| Migration | Status | Notes |
| --- | --- | --- |
| `changes.0003_windows_freezes_locks` | Applied | Adds freeze exception fields, `ChangeWindow`, `FreezeRule`, `TargetLock`, and `DispatchEligibilityCheck`. |
| `changes.0004_execution_timing_fields` | Applied | Adds accepted, started, and finished timing fields to `ChangeExecutionBinding`. |
| `audit.0007_add_phase112_object_types` and `audit.0008_update_object_type_constraint_phase112` | Applied | Adds Phase 11.2 audit object type support. |

Backfill status:

- No data backfill is required for the current local database.
- New `ChangeRecord` freeze exception fields are nullable or blank by default.
- New Phase 11.2 tables start empty and are populated by operator/API activity.
- Existing Phase 11.1 changes do not automatically receive windows, freeze
  exceptions, target locks, or preflight records.
- Existing execution bindings do not receive historical accepted, started, or
  finished timestamps.

`docker compose exec api python manage.py migrate` reports no unapplied
migrations as of May 5, 2026.

## Manual Verification

Manual verification steps for Phase 11.2:

1. Sign in as an owner/admin/operator and select an organization.
2. Open `/changes` and create a high-risk production change from an operation profile.
3. Add or update the change window at `/changes/{id}` so the current time is inside the approved window.
4. Run preflight from the change detail page and confirm the latest preflight shows all checks passing.
5. Create a freeze rule at `/freeze-rules` that matches the change target and rerun preflight; confirm dispatch is blocked.
6. Change the freeze rule to `allow_with_exception`, add a freeze exception reference to the change through the API/admin path, rerun preflight, and confirm the freeze check can pass.
7. Dispatch the change and confirm an execution reservation is created and target locks are active.
8. Let the runner claim the execution. Confirm it calls the bind, started, and finished internal callbacks.
9. After completion, confirm target locks are released and the window is closed or marked overrun if the finish time is past `ends_at`.
10. Confirm audit events exist for preflight, lock acquisition/release, freeze-rule actions, and timing callbacks without dispatch tokens or raw requested inputs.

Automated verification run for this closure pass:

| Command | Result |
| --- | --- |
| `docker compose exec api python manage.py check` | Passed. |
| `docker compose exec api python manage.py migrate` | Passed, no migrations to apply. |
| `docker compose exec api pytest -v` | Passed: 1191 tests. One teardown warning reported a lingering test database session. |
| `docker compose exec runner pytest -v` | Passed: 144 tests. Runner service had to be started first. |
| `cd apps/web && npm run lint` | Passed. |
| `cd apps/web && npm run test:ci` | Passed: 19 files, 148 tests. |
| `cd apps/web && npm run build` | Passed. |

## Known Limitations

- There is no scheduler, cron, queue, Redis lock manager, sidecar, or automatic dispatch. Dispatch remains request-driven.
- Window status is computed and updated by service calls, not by a background process.
- Freeze exception metadata is not emergency breakglass. Breakglass behavior is deferred to Phase 11.4.
- Existing historical changes and executions are not backfilled with Phase 11.2 records or timing values.
- Internal runner endpoints are authenticated in Django, but production deployments should still keep `/api/v1/internal/` private or blocked at the network edge.
- The runner treats started and finished timing callback failures as non-fatal after binding; Django remains the source of truth, but transient callback failures can leave timing fields absent until manually reconciled.
- Target locks are released by execution-finished handling. Manual repair may be needed if a change-bound execution never reaches that callback and no operator repair path has been run.
