# Phase 11.2: Controlled Windows, Freeze Rules, and Target Locks Blueprint

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 11.2 |
| Phase name | Controlled windows, freeze rules, and target locks |
| Objective | Add approved change windows, freeze-rule enforcement, target conflict locks, and dispatch preflight checks for `ChangeRecord`-backed production operations. |
| Status | Blueprint only - do not implement from this document without re-reading current source first |
| Depends on | Phase 11.1 complete and verified; Phases 01-10.9 fully implemented |
| Authored | 2026-05-01 |
| Primary app | `apps/api/apps/changes/` |

This document is an implementation blueprint only. It intentionally does not implement code.

## 2. Executive Summary

Phase 11.2 makes Phase 11.1 dispatch intentionally harder to misuse. A `ChangeRecord` can no longer become dispatchable just because it is approved. It must pass an explicit Django preflight that verifies:

- the change approval is still valid;
- existing policy gates still pass;
- the approved change window is open;
- no active freeze rule blocks the affected targets;
- no active target lock conflicts with another running or dispatchable change;
- the requesting actor is authorized to dispatch the change.

The implementation adds four model families:

- `ChangeWindow`: the approved dispatch window attached to a `ChangeRecord`;
- `FreezeRule`: organization-scoped production freeze rules with either `block` or `allow_with_exception` behavior;
- `TargetLock`: database-backed active locks for production target conflict prevention;
- `DispatchEligibilityCheck`: immutable preflight result snapshots.

Dispatch remains a Django service decision. The runner receives work only after Django has completed preflight and created a bound execution reservation. The runner reports accepted, started, and finished timing back to Django internal APIs, but it never evaluates windows, freezes, locks, policies, or authorization.

This phase does not add cron, a scheduler, a distributed lock service, Redis, a queue, a sidecar, or emergency breakglass behavior. Emergency and breakglass semantics belong to Phase 11.4.

## 3. Current-State Inspection Checklist

The implementation must re-run this inspection after Phase 11.1 code exists. The current checkout inspected for this blueprint has Phase 11.1 as a blueprint file only; `apps/api/apps/changes/` and `apps/web/src/features/changes/` are not present yet.

- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` defines `OperationProfile`, `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`, change approval linkage, dispatch token handling, and runner binding.
- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` establishes statuses including `approved`, `scheduled`, `dispatchable`, and `running`, but Phase 11.2 must refine their meaning around windows and preflight.
- [x] `apps/api/apps/executions/models.py` currently has `Execution` statuses `queued`, `claimed`, `running`, `succeeded`, `failed`, and `cancelled`; Phase 11.2 must not add execution statuses.
- [x] `apps/api/apps/executions/services.py` owns execution creation, claim, heartbeat, step update, completion, audit, and watchdog behavior; Phase 11.2 must integrate without moving eligibility logic into the runner.
- [x] `apps/api/apps/executions/internal_views.py` exposes runner-only APIs under `/api/v1/internal/...`; Phase 11.2 required internal endpoints use `/internal/v1/...` in the prompt, but implementation should either follow the existing `/api/v1/internal/...` convention or explicitly add aliases.
- [x] `apps/api/apps/policies/models.py` and `apps/api/apps/policies/services.py` provide step-level policy evaluation. Phase 11.2 preflight may reuse or summarize policy gates, but must not create a parallel policy engine in the runner.
- [x] `apps/api/apps/audit/models.py` has object types for executions, approvals, policies, artifacts, and integrations, but not change objects, freeze rules, windows, locks, or preflight checks in this checkout.
- [x] `apps/runner/runner/schemas.py`, `client.py`, and `executor.py` currently claim, heartbeat, start steps, update steps, poll approvals, upload artifacts, and complete executions. Phase 11.2 runner changes must stay limited to timing reporting and internal callback calls.
- [x] `apps/web/src/features/changes/` is absent in this checkout. Phase 11.2 frontend work must build on whatever Phase 11.1 creates there.
- [x] `apps/web/src/shared/api/client.ts` blocks browser calls to internal APIs and injects `X-Organization-Id`; Phase 11.2 React must keep using public Django APIs only.

Drift note: if Phase 11.1 implementation differs from its blueprint, the Phase 11.2 implementation plan must be updated before coding.

## 4. Architecture Invariants

| Invariant | Phase 11.2 consequence |
|---|---|
| Django is the control plane. | Windows, freezes, target locks, dispatch eligibility, state transitions, and audit emission live in Django services. |
| The runner is not a policy engine. | Runner never evaluates windows, freezes, target locks, approval status, actor authorization, or policy applicability. |
| No cron, scheduler, queue, Redis, distributed lock, or sidecar service. | Window state is computed synchronously from timestamps; lock ownership is stored in Postgres; preflight and dispatch are request-driven Django service calls. |
| Locking uses Django/Postgres transactions only. | `select_for_update`, unique constraints, partial unique constraints, and `transaction.atomic()` are the only concurrency tools. |
| Frontend uses public APIs only. | React calls `/api/v1/changes/...` and `/api/v1/freeze-rules/`; it never calls `/api/v1/internal/...`. |
| Internal APIs are runner-to-Django callbacks only. | `/internal/v1/changes/{id}/execution-started/` and `/internal/v1/changes/{id}/execution-finished/` accept runner bearer auth only. |
| Approval invalidation is conservative. | Window changes after approval invalidate approval unless the change is still `draft`. |
| Active target locks are DB-enforced. | A partial unique constraint prevents two active locks for the same organization, target type, and normalized target identifier. |
| Dispatch must be preflighted. | `POST /api/v1/changes/{id}/dispatch/` runs or requires a fresh successful `DispatchEligibilityCheck` inside the same transaction before reserving execution. |
| Audit metadata remains sanitized. | Audit events include IDs, statuses, timestamps, booleans, hashes, counts, and conflict summaries. They never include dispatch tokens, claim tokens, raw secret inputs, raw command text, or unsanitized request bodies. |

## 5. Data Model Design

All models should live in `apps/api/apps/changes/models.py` unless Phase 11.1 split the app differently. Use UUID primary keys through the existing `BaseModel` convention.

### 5.1 `ChangeWindow`

`ChangeWindow` is the approved time boundary for dispatching one `ChangeRecord`.

Required states:

- `scheduled`: starts in the future;
- `open`: current time is inside `[starts_at, ends_at]`;
- `expired`: the window ended before execution started;
- `overrun`: execution started during the window but is still running after `ends_at`;
- `closed`: execution finished or the change was closed while the window was no longer needed.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | OneToOne -> `changes.ChangeRecord` | One active window per change for Phase 11.2. |
| `starts_at` | `DateTimeField` | Required. |
| `ends_at` | `DateTimeField` | Required and must be after `starts_at`. |
| `status` | `CharField(24)` | One of `scheduled`, `open`, `expired`, `overrun`, `closed`. |
| `timezone` | `CharField(64, blank=True)` | Optional display hint only; all comparisons use aware UTC datetimes. |
| `reason` | `TextField(blank=True)` | Operator-facing scheduling rationale. |
| `approved_snapshot_sha256` | `CharField(64, blank=True)` | Snapshot hash of the approved window values. |
| `approved_at` | `DateTimeField(null=True, blank=True)` | Set when change approval covers this window. |
| `opened_at` | `DateTimeField(null=True, blank=True)` | First time service observed the window as open. |
| `expired_at` | `DateTimeField(null=True, blank=True)` | Set when expired before start. |
| `overrun_at` | `DateTimeField(null=True, blank=True)` | Set when running past `ends_at`. |
| `closed_at` | `DateTimeField(null=True, blank=True)` | Set on successful close or terminal change. |
| `updated_by` | FK -> `users.User`, nullable | Last human actor that changed the window. |

Recommended constraints and indexes:

- check `status` in the required states;
- check `starts_at < ends_at`;
- unique `change_record`;
- index `(organization, status, starts_at)`;
- index `(organization, ends_at)`;
- service invariant: `organization_id == change_record.organization_id`.

Do not add recurring windows, global reusable maintenance windows, or automatic scheduled dispatch in this phase.

### 5.2 `FreezeRule`

`FreezeRule` is an organization-scoped production freeze that can apply to all production changes or to selected target types and identifiers.

Required behavior values:

- `block`: dispatch is blocked while the rule is active;
- `allow_with_exception`: dispatch is blocked unless the change has a recorded exception reference that satisfies the rule.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `name` | `CharField(255)` | Human-readable rule name. |
| `description` | `TextField(blank=True)` | Operator/admin context. |
| `is_active` | `BooleanField(default=True)` | Inactive rules are ignored. |
| `behavior` | `CharField(32)` | `block` or `allow_with_exception`. |
| `starts_at` | `DateTimeField` | Active interval start. |
| `ends_at` | `DateTimeField` | Active interval end. |
| `scope_type` | `CharField(32)` | Recommended values: `all_production`, `target_type`, `target_identifier`. |
| `target_type` | `CharField(64, blank=True)` | Required for `target_type` and `target_identifier` scopes. |
| `target_identifier` | `CharField(255, blank=True)` | Human input for identifier-scoped freezes. |
| `normalized_identifier` | `CharField(255, blank=True)` | Canonical target identifier for matching. |
| `requires_exception_reference` | `BooleanField(default=False)` | Must be true for `allow_with_exception`. |
| `created_by` | FK -> `users.User`, nullable | Admin/operator actor. |
| `updated_by` | FK -> `users.User`, nullable | Admin/operator actor. |

Recommended constraints and indexes:

- check `behavior` in `block`, `allow_with_exception`;
- check `scope_type` in `all_production`, `target_type`, `target_identifier`;
- check `starts_at < ends_at`;
- check `allow_with_exception` implies `requires_exception_reference=true`;
- index `(organization, is_active, starts_at, ends_at)`;
- index `(organization, scope_type, target_type, normalized_identifier)`.

Freeze rules are read at dispatch preflight time. They do not mutate changes by themselves and do not require a scheduler.

### 5.3 Freeze Exception Fields on `ChangeRecord`

To support `allow_with_exception` without adding emergency logic, add narrow exception metadata to `ChangeRecord` or a small child model if Phase 11.1 prefers normalized records.

Recommended bounded fields on `ChangeRecord`:

| Field | Type | Notes |
|---|---|---|
| `freeze_exception_reference` | `CharField(255, blank=True)` | Ticket or approval reference supplied by operator. |
| `freeze_exception_reason` | `TextField(blank=True)` | Sanitized operator justification. |
| `freeze_exception_recorded_by` | FK -> `users.User`, nullable | Actor that supplied it. |
| `freeze_exception_recorded_at` | `DateTimeField(null=True, blank=True)` | Timestamp. |

Rules:

- an exception reference can satisfy only `allow_with_exception`;
- it never overrides `block`;
- it is not breakglass and must not bypass approval, policy, window, target lock, or authorization checks;
- changing exception metadata after approval should invalidate approval unless the change is still `draft`, because it changes dispatch eligibility evidence.

### 5.4 `TargetLock`

`TargetLock` prevents concurrent dispatch/running operations against the same production target.

Recommended status values:

- `active`;
- `released`;
- `expired`.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | FK -> `changes.ChangeRecord` | Lock owner change. |
| `execution` | FK -> `executions.Execution`, nullable | Set when execution reservation exists. |
| `change_target` | FK -> `changes.ChangeTarget`, nullable | Source target row when available. |
| `target_type` | `CharField(64)` | Copied from target. |
| `target_identifier` | `CharField(255)` | Display identifier. |
| `normalized_identifier` | `CharField(255)` | Conflict key. |
| `status` | `CharField(24)` | `active`, `released`, or `expired`. |
| `acquired_at` | `DateTimeField` | Set on dispatch transaction. |
| `released_at` | `DateTimeField(null=True, blank=True)` | Set on execution finish or dispatch failure cleanup. |
| `expires_at` | `DateTimeField(null=True, blank=True)` | Defensive expiration after dispatch token/window end. |
| `release_reason` | `CharField(64, blank=True)` | `execution_finished`, `dispatch_failed`, `window_expired`, `manual_repair`. |

Required partial unique constraint:

```text
UNIQUE (organization_id, target_type, normalized_identifier)
WHERE status = 'active'
```

In Django, implement with `UniqueConstraint(condition=Q(status="active"), ...)` and a migration that creates the Postgres partial unique index.

Additional indexes:

- `(organization, status, acquired_at)`;
- `(change_record, status)`;
- `(execution, status)`;
- `(organization, target_type, normalized_identifier, status)`.

Service rules:

- active locks are acquired only inside dispatch;
- locks are released only by Django service methods after execution finish, dispatch failure rollback/cleanup, or expiration repair;
- lock conflict detection uses the same normalized target key as the partial unique constraint;
- do not use advisory locks or external lock services.

### 5.5 `DispatchEligibilityCheck`

`DispatchEligibilityCheck` records an immutable snapshot of a preflight attempt.

Recommended result values:

- `passed`;
- `failed`.

Recommended check item statuses:

- `passed`;
- `failed`;
- `warning`.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | FK -> `changes.ChangeRecord` | Checked change. |
| `requested_by` | FK -> `users.User`, nullable | Actor that requested preflight. |
| `result` | `CharField(16)` | `passed` or `failed`. |
| `checked_at` | `DateTimeField` | Service timestamp. |
| `expires_at` | `DateTimeField` | Short freshness TTL, recommended 30-60 seconds. |
| `approved_status_ok` | `BooleanField` | Approval check result. |
| `policy_pass_ok` | `BooleanField` | Policy/profile check result. |
| `window_open_ok` | `BooleanField` | Window check result. |
| `freeze_conflicts_ok` | `BooleanField` | Freeze check result. |
| `target_locks_ok` | `BooleanField` | Lock check result. |
| `actor_authorized_ok` | `BooleanField` | Authorization check result. |
| `checks` | `JSONField(default=list)` | Sanitized ordered check item details. |
| `conflicts` | `JSONField(default=list)` | Sanitized freeze/lock conflict summaries. |
| `input_snapshot_sha256` | `CharField(64)` | Change request snapshot hash at check time. |
| `window_snapshot_sha256` | `CharField(64, blank=True)` | Window hash at check time. |

Recommended indexes:

- `(organization, change_record, checked_at)`;
- `(organization, result, checked_at)`;
- `(expires_at)`.

Never update a `DispatchEligibilityCheck` after creation. A dispatch call may create a fresh check inside the dispatch transaction even if the UI recently called preflight.

### 5.6 Change Status Semantics

Phase 11.2 refines Phase 11.1 status transitions:

| From | To | Trigger |
|---|---|---|
| `approved` | `scheduled` | Approval completed and window starts in the future. |
| `approved` | `dispatchable` | Approval completed and window is currently open; preflight passes; locks are acquired; execution reservation is created. |
| `scheduled` | `dispatchable` | Window is open; explicit preflight/dispatch passes; locks are acquired; execution reservation is created. |
| `dispatchable` | `running` | Runner reports execution started through Django internal API. |
| `running` | `expired` | Execution did not actually start before the approved window ended, or dispatch reservation became invalid before start. |
| `running` | window `overrun` | Execution started during the window and is still active after `ends_at`; change may remain `running` while window status becomes `overrun`. |
| `running` | terminal Phase 11.1 status | Execution finished and existing Phase 11.1 completion rules run. |

Important distinction:

- `ChangeRecord.status` represents the change lifecycle.
- `ChangeWindow.status` represents time-window lifecycle.
- Running past `ends_at` should mark the window `overrun`; it should not automatically kill the execution or ask the runner to decide anything.

## 6. Locking and Transaction Strategy

### 6.1 Dispatch Transaction

`dispatch_change_record(change_id, actor)` must run in one `transaction.atomic()` block:

1. Lock the `ChangeRecord` with `select_for_update()`.
2. Lock or load the related `ChangeWindow` with `select_for_update()`.
3. Verify the change is `approved` or `scheduled`; reject `dispatchable` unless returning an idempotent existing reservation owned by the same eligible state.
4. Run a fresh dispatch preflight inside the transaction.
5. If preflight fails, persist `DispatchEligibilityCheck(result="failed")`, emit audit, and return `409`.
6. Create active `TargetLock` rows for every normalized change target.
7. Let the partial unique constraint catch races. Convert `IntegrityError` into a failed preflight/dispatch conflict response.
8. Create the execution reservation and `ChangeExecutionBinding` through Phase 11.1 services.
9. Set `ChangeRecord.status="dispatchable"` and `dispatchable_at`.
10. Persist `DispatchEligibilityCheck(result="passed")` if not already created in the transaction.
11. Emit audit events after successful state and lock writes.

If execution reservation fails after lock rows are inserted, the transaction must roll back all lock rows. Do not release locks in a separate best-effort call for normal dispatch failures.

### 6.2 Lock Acquisition

Lock acquisition should bulk create one active lock per change target. The database is the final arbiter:

- preflight queries active locks first to produce useful conflict messages;
- dispatch still attempts insert because another dispatch may win after preflight;
- `IntegrityError` from the partial unique constraint becomes `target_lock_conflict`;
- returned conflict details should include conflicting `change_record_id`, `target_type`, `target_identifier`, and active lock age, but not raw request inputs.

### 6.3 Lock Release

Release locks in Django when execution completion is reported:

1. Internal execution finished endpoint locks the change and active locks.
2. Mark active locks `released`.
3. Set `released_at` and `release_reason`.
4. Let existing Phase 11.1 completion handling move the change out of `running`.
5. Emit `target_lock.released` with lock count and execution status.

If a dispatchable execution expires before the runner starts, mark locks `expired` in the same service that marks the change/window expired.

### 6.4 Window State Without Scheduler

Window state is computed and persisted opportunistically:

- `scheduled` if `now < starts_at` and not terminal;
- `open` if `starts_at <= now <= ends_at` and execution has not finished;
- `expired` if `now > ends_at` and execution never started;
- `overrun` if `now > ends_at` and execution is still running;
- `closed` when execution is terminal or change is terminal.

Run `refresh_change_window_state(change, now)` inside:

- `PATCH /api/v1/changes/{id}/window/`;
- `POST /api/v1/changes/{id}/preflight/`;
- `POST /api/v1/changes/{id}/dispatch/`;
- internal execution started callback;
- internal execution finished callback;
- change detail serializer/selectors if persisted state is stale and the request is allowed to write, otherwise compute display-only status.

Do not add a background sweeper in this phase.

## 7. Freeze-Rule Evaluation Design

### 7.1 Applicability

Evaluate freeze rules in Django using organization, current time, and normalized change targets:

```text
is_active = true
starts_at <= now
ends_at >= now
organization_id = change.organization_id
scope matches at least one production target or all production
```

Scope matching:

- `all_production`: matches every production change;
- `target_type`: matches any target with the same `target_type`;
- `target_identifier`: matches target type plus `normalized_identifier`.

### 7.2 Outcomes

For each matching freeze rule:

- `block`: preflight fails with `active_freeze_block`;
- `allow_with_exception`: preflight passes only if the change has non-empty `freeze_exception_reference`; otherwise preflight fails with `freeze_exception_required`.

If both `block` and `allow_with_exception` rules match, `block` wins.

### 7.3 Exception Handling

Exception metadata is evidence, not breakglass:

- allowed only for `allow_with_exception`;
- must be supplied before dispatch;
- changes after approval invalidate approval unless the change is still `draft`;
- included in audit as `has_freeze_exception=true` and a sanitized reference string, not full notes if notes may contain sensitive details.

### 7.4 Service Shape

Add service helpers such as:

- `find_active_freeze_conflicts(change, now) -> FreezeEvaluationResult`;
- `serialize_freeze_conflict(rule, target) -> dict`;
- `assert_freeze_exception_satisfies(rule, change) -> bool`.

The result object should distinguish:

- hard blocks;
- exception-required failures;
- exception-satisfied warnings.

## 8. Dispatch Preflight Service Design

### 8.1 Service Contract

Add `run_dispatch_preflight(change_id, actor, *, persist=True, now=None) -> DispatchPreflightResult`.

The result should include:

- `eligible: bool`;
- `check_id: UUID | None`;
- ordered `checks`;
- ordered `conflicts`;
- current `change_status`;
- current `window_status`;
- `expires_at`;
- stable machine-readable error codes.

### 8.2 Required Checks

Preflight must evaluate these checks in order:

1. `approved_status`: change is `approved` or `scheduled`, approval request is approved, and the approved snapshot still matches current request/window/exception evidence.
2. `policy_pass`: operation profile and workflow are still valid according to Phase 11.1 policy/profile rules; no known policy block is attached to the change.
3. `window_open`: `ChangeWindow` exists, is approved, and `starts_at <= now <= ends_at`.
4. `freeze_conflicts`: no active `block` freezes match; all matching `allow_with_exception` freezes have exception evidence.
5. `target_lock_conflicts`: no active `TargetLock` exists for any change target unless it belongs to the same already-dispatchable change.
6. `actor_authorization`: actor is authenticated and authorized to dispatch production changes for the organization.

The service should accumulate all check results instead of failing fast, except for missing/unauthorized organization context where normal API permission handling can stop earlier.

### 8.3 Approval and Reapproval

Window or freeze-exception changes after approval must invalidate approval unless `ChangeRecord.status == "draft"`.

Recommended behavior:

- if draft: update fields normally;
- if pending approval: reject mutation or update and recreate approval only if Phase 11.1 already supports resubmission; prefer reject for bounded scope;
- if approved/scheduled: set status back to `pending_approval` or `draft_requires_resubmit` only if Phase 11.1 has such status; otherwise require implementation to add a bounded `pending_approval` reapproval path and create a new approval request;
- if dispatchable/running/terminal: reject mutation with `change_window_immutable`.

For this phase, prefer the simplest auditable rule: after approval, `PATCH /window/` cancels the old approval linkage, sets `status="pending_approval"`, clears `approved_at`, clears `dispatchable_at`, creates a fresh approval request, and emits `change.approval_invalidated` plus `change.approval_bound`. If Phase 11.1 does not support multiple approval requests, add a `superseded_approval_request_id` audit trail or a `ChangeApprovalHistory` table rather than overwriting history silently.

### 8.4 Dispatch Freshness

`POST /preflight/` is useful for UI feedback but must not be trusted as the only gate.

`POST /dispatch/` must either:

- run a fresh preflight inside the dispatch transaction; or
- require a still-fresh successful `DispatchEligibilityCheck` and still re-check active locks with insert-time constraints.

Recommended implementation: always run fresh preflight inside dispatch, because it is simpler and safer.

## 9. API Design

All public endpoints require JWT authentication, `X-Organization-Id`, and existing organization permissions. All internal endpoints require runner bearer authentication and must reject user JWTs.

### 9.1 `PATCH /api/v1/changes/{id}/window/`

Create or update the change window.

Request:

```json
{
  "starts_at": "2026-05-03T04:00:00Z",
  "ends_at": "2026-05-03T05:00:00Z",
  "timezone": "America/Denver",
  "reason": "Approved maintenance window CHG-1234"
}
```

Response `200`:

```json
{
  "change_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "status": "scheduled",
  "window": {
    "id": "3e5c62e7-3a0f-4ad4-b10c-86a7e3ed4a44",
    "starts_at": "2026-05-03T04:00:00Z",
    "ends_at": "2026-05-03T05:00:00Z",
    "status": "scheduled",
    "approved_at": null,
    "timezone": "America/Denver"
  },
  "approval_invalidated": true,
  "approval_request": {
    "id": "26e7c6d4-0b52-4fc7-92e0-557801596a22",
    "status": "pending"
  }
}
```

Important errors:

- `400 invalid_window_range`;
- `400 window_required_for_production_change`;
- `403 permission_denied`;
- `409 change_window_immutable`;
- `409 approval_recreation_failed`.

### 9.2 `POST /api/v1/changes/{id}/preflight/`

Run dispatch eligibility checks without dispatching.

Request:

```json
{
  "client_observed_change_status": "scheduled"
}
```

Response `200` when eligible:

```json
{
  "eligible": true,
  "check_id": "bc0672d8-c317-47a5-a646-090b6d5d5a99",
  "checked_at": "2026-05-03T04:00:10Z",
  "expires_at": "2026-05-03T04:01:10Z",
  "change_status": "scheduled",
  "window_status": "open",
  "checks": [
    {"code": "approved_status", "status": "passed"},
    {"code": "policy_pass", "status": "passed"},
    {"code": "window_open", "status": "passed"},
    {"code": "freeze_conflicts", "status": "passed"},
    {"code": "target_lock_conflicts", "status": "passed"},
    {"code": "actor_authorization", "status": "passed"}
  ],
  "conflicts": []
}
```

Response `409` when ineligible:

```json
{
  "eligible": false,
  "check_id": "bc0672d8-c317-47a5-a646-090b6d5d5a99",
  "checked_at": "2026-05-03T03:50:10Z",
  "expires_at": "2026-05-03T03:51:10Z",
  "change_status": "scheduled",
  "window_status": "scheduled",
  "checks": [
    {
      "code": "window_open",
      "status": "failed",
      "message": "Dispatch window is not open."
    }
  ],
  "conflicts": []
}
```

### 9.3 `POST /api/v1/changes/{id}/dispatch/`

Run fresh preflight, acquire locks, reserve execution, and return dispatch summary.

Request:

```json
{
  "preflight_check_id": "bc0672d8-c317-47a5-a646-090b6d5d5a99"
}
```

`preflight_check_id` is optional display correlation only; dispatch must run a fresh transactional preflight.

Response `202`:

```json
{
  "change_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "status": "dispatchable",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "dispatchable_at": "2026-05-03T04:00:12Z",
  "target_locks": [
    {
      "id": "3f59ec5b-bf3a-4261-871c-1c596b22b220",
      "target_type": "database",
      "target_identifier": "prod-primary-db",
      "status": "active"
    }
  ],
  "preflight": {
    "check_id": "7a7a4aa6-59da-42a8-a41d-c8d393d5f0f3",
    "eligible": true
  }
}
```

Important errors:

- `409 dispatch_preflight_failed`;
- `409 dispatch_outside_window`;
- `409 active_freeze_block`;
- `409 freeze_exception_required`;
- `409 target_lock_conflict`;
- `409 invalid_state_transition`;
- `403 permission_denied`.

### 9.4 `GET /api/v1/freeze-rules/`

List active and historical freeze rules for the organization.

Query params:

- `active=true|false`;
- `effective_at=<iso datetime>`;
- `target_type=<value>`;
- `target_identifier=<value>`.

Response `200`:

```json
{
  "results": [
    {
      "id": "de584feb-3182-4492-b7b1-88bb1b213b4f",
      "name": "Quarter-end production freeze",
      "behavior": "allow_with_exception",
      "scope_type": "all_production",
      "starts_at": "2026-06-28T00:00:00Z",
      "ends_at": "2026-07-02T00:00:00Z",
      "is_active": true,
      "requires_exception_reference": true
    }
  ]
}
```

The prompt only requires `GET`, but the React freeze rule management page needs mutation APIs. Add admin-only endpoints in the same router if Phase 11.2 is expected to be usable:

- `POST /api/v1/freeze-rules/`;
- `PATCH /api/v1/freeze-rules/{id}/`;
- `DELETE /api/v1/freeze-rules/{id}/` or `POST /api/v1/freeze-rules/{id}/deactivate/`.

If mutation endpoints are deferred, the management page must be read-only and the blueprint should be amended before implementation.

### 9.5 `POST /internal/v1/changes/{id}/execution-started/`

Runner callback after it accepts the dispatch and before it starts executing steps. Existing route convention may require `/api/v1/internal/changes/{id}/execution-started/`.

Request:

```json
{
  "runner_id": "runner-prod-1",
  "claim_token": "a63d707a-4798-43c9-9049-19ef135ee780",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "accepted_at": "2026-05-03T04:00:14Z",
  "started_at": "2026-05-03T04:00:16Z"
}
```

Response `200`:

```json
{
  "change_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "change_status": "running",
  "window_status": "open",
  "accepted_at": "2026-05-03T04:00:14Z",
  "actual_started_at": "2026-05-03T04:00:16Z"
}
```

Service behavior:

- verify runner ownership and claim token through existing execution service helpers;
- require change status `dispatchable`;
- stamp accepted/start timing on the change execution binding or new timing fields;
- set `ChangeRecord.status="running"`;
- refresh window status;
- never ask runner to evaluate eligibility.

### 9.6 `POST /internal/v1/changes/{id}/execution-finished/`

Runner callback after execution completion is accepted by Django. Existing route convention may require `/api/v1/internal/changes/{id}/execution-finished/`.

Request:

```json
{
  "runner_id": "runner-prod-1",
  "claim_token": "a63d707a-4798-43c9-9049-19ef135ee780",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "final_status": "succeeded",
  "finished_at": "2026-05-03T04:22:30Z"
}
```

Response `200`:

```json
{
  "change_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "change_status": "verification_pending",
  "window_status": "closed",
  "locks_released": 1,
  "actual_finished_at": "2026-05-03T04:22:30Z"
}
```

Service behavior:

- verify runner ownership and claim token;
- stamp actual end timing;
- release active target locks;
- close or overrun/close the window as applicable;
- call or coordinate with Phase 11.1 execution completion hook exactly once.

## 10. Runner Impact

Runner behavior is intentionally narrow:

- runner receives dispatch only after Django preflight and dispatch reservation;
- runner reports accepted/start/end timing;
- runner never evaluates windows, freezes, target locks, or authorization;
- runner never decides whether an overrun is allowed;
- runner never releases target locks directly.

Required runner updates:

- add client methods for `execution-started` and `execution-finished`;
- call `execution-started` after successful Phase 11.1 change bind and before first step start;
- include `accepted_at` and `started_at` timestamps from runner observation;
- call existing execution completion endpoint as today, then call `execution-finished` if a `change_record_id` exists;
- treat `400`, `403`, `409`, and `410` from change callbacks as non-retryable unless existing client retry policy explicitly handles them as safe;
- ensure logs never include dispatch token, claim token, raw requested inputs, or command secrets.

Timing fields should be stored in Django as observed values, not trusted authorization evidence.

## 11. Frontend Impact

Build on the Phase 11.1 changes feature area.

### 11.1 Schedule Panel

Add a schedule panel to change create/detail views:

- starts at and ends at controls;
- timezone display hint;
- reason field;
- current window status badge;
- approval invalidation warning before saving post-approval changes;
- disabled edits once dispatchable, running, or terminal.

The panel must call `PATCH /api/v1/changes/{id}/window/` and refresh change detail plus preflight result.

### 11.2 Conflict Drawer

Add a conflict drawer on change detail:

- active freeze conflicts;
- missing freeze exception requirement;
- target lock conflicts;
- conflicting change ID and status;
- affected target type and display identifier;
- window status problems.

Use preflight response `conflicts` as the source of truth. Do not recreate matching logic in React.

### 11.3 Preflight Result Card

Add a preflight result card:

- ordered checklist for approved status, policy pass, window open, freeze conflicts, target locks, actor authorization;
- timestamp and freshness indicator;
- top-level eligible/ineligible status;
- CTA to rerun preflight;
- dispatch button enabled only when the latest result is eligible and not stale.

Dispatch must still handle server-side rejection even if the UI shows eligible.

### 11.4 Freeze Rule Management Page

Add a page under the existing navigation pattern for freeze rules:

- list rules with active state, behavior, scope, start/end, and target summary;
- filter active/effective date/target type;
- create/edit/deactivate controls if mutation APIs are implemented;
- admin-only mutation affordances;
- read-only display for non-admins.

If only `GET /api/v1/freeze-rules/` is implemented, label the page as management in navigation only after mutation endpoints are added.

### 11.5 Disabled Dispatch Until Eligible

The dispatch button on change detail must be disabled unless:

- change is approved or scheduled;
- window is open;
- latest preflight is eligible and fresh;
- actor has dispatch permission according to API/user context;
- no dispatch request is already in flight.

Disabled UI is a convenience only. Django remains authoritative.

## 12. Audit Events

Add audit object types if Phase 11.1 has not already added them:

- `change_record`;
- `change_window`;
- `freeze_rule`;
- `target_lock`;
- `dispatch_eligibility_check`.

Emit these events:

| Event | Object | Metadata |
|---|---|---|
| `change.window_updated` | `change_window` | change id, previous hash, new hash, starts/ends, approval invalidated boolean |
| `change.approval_invalidated` | `change_record` | reason `window_changed` or `freeze_exception_changed`, old approval id |
| `freeze_rule.created` | `freeze_rule` | behavior, scope, starts/ends |
| `freeze_rule.updated` | `freeze_rule` | changed field names only, behavior, scope |
| `freeze_rule.deactivated` | `freeze_rule` | rule id, actor |
| `change.preflight_checked` | `dispatch_eligibility_check` | result, check codes, conflict count |
| `target_lock.acquired` | `target_lock` or `change_record` | lock count, target keys, execution id |
| `target_lock.conflict` | `change_record` | conflicting change ids and target keys |
| `target_lock.released` | `change_record` | lock count, release reason, execution id |
| `change.dispatched` | `change_record` | execution id, preflight check id, lock count |
| `change.execution_started` | `change_record` | execution id, runner id, accepted/start timestamps |
| `change.execution_finished` | `change_record` | execution id, final status, finished timestamp, locks released |
| `change.window_expired` | `change_window` | change id, ends_at |
| `change.window_overrun` | `change_window` | change id, ends_at, actual_started_at |
| `change.window_closed` | `change_window` | change id, closed_at |

Sanitization requirements:

- no dispatch tokens;
- no claim tokens;
- no raw requested inputs;
- no raw command text;
- no raw exception notes if they may include sensitive incident details;
- target identifiers are acceptable only after applying the same display sanitization used by `ChangeTarget`.

## 13. File-by-File Implementation Plan

This is an implementation plan only; do not code during blueprint creation.

### Backend

| File | Planned changes |
|---|---|
| `apps/api/apps/changes/models.py` | Add `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`; add enums and constraints. Add freeze exception fields and timing fields to existing Phase 11.1 models if not already present. |
| `apps/api/apps/changes/migrations/00xx_windows_freezes_locks.py` | Create tables, indexes, check constraints, and partial unique active-lock constraint. |
| `apps/api/apps/changes/services.py` | Add window mutation, approval invalidation, preflight, freeze evaluation, target lock acquisition/release, dispatch orchestration, window state refresh, and internal timing callbacks. |
| `apps/api/apps/changes/selectors.py` | Add organization-scoped selectors for change detail with window/preflight/lock summaries and freeze rule list. |
| `apps/api/apps/changes/serializers.py` | Add public serializers for window patch, preflight response, dispatch response, freeze rule list/mutation, and conflict summaries. |
| `apps/api/apps/changes/views.py` | Add `PATCH /changes/{id}/window/`, `POST /changes/{id}/preflight/`, `POST /changes/{id}/dispatch/`, and freeze rule views if routed here. |
| `apps/api/apps/changes/internal_views.py` | Add runner-only `execution-started` and `execution-finished` endpoints. |
| `apps/api/apps/changes/urls.py` | Register public and internal routes, following the existing API route convention. |
| `apps/api/config/api_v1_urls.py` | Include public change/freeze routes and internal change callback routes. Add compatibility aliases only if the project accepts both `/internal/v1` and `/api/v1/internal`. |
| `apps/api/apps/audit/models.py` | Add audit object types if Phase 11.1 did not. |
| `apps/api/apps/audit/services.py` | Extend scrub list for dispatch/preflight/window/exception sensitive fields. |
| `apps/api/apps/executions/services.py` | Call changes completion hooks at execution completion only if Phase 11.1 has not already centralized this. Avoid circular imports by using local imports or a narrow integration module. |
| `apps/api/apps/executions/internal_serializers.py` | Include any extra timing fields only if existing internal execution endpoints need them. Prefer change-specific serializers in `changes/internal_serializers.py`. |
| `apps/api/apps/executions/internal_views.py` | Do not add eligibility logic. At most ensure runner claim path only returns already-dispatchable change-bound executions. |
| `apps/api/apps/policies/services.py` | Expose a bounded policy summary/helper for preflight if Phase 11.1 policy linkage requires it. Do not duplicate freeze logic here. |

### Runner

| File | Planned changes |
|---|---|
| `apps/runner/runner/schemas.py` | Add request/response models for change execution started/finished callbacks. Ensure sensitive fields are excluded from repr/log dumps. |
| `apps/runner/runner/client.py` | Add `change_execution_started` and `change_execution_finished` methods. Use internal Django endpoints and existing bearer auth. |
| `apps/runner/runner/executor.py` | Call start/end callbacks around existing execution work for change-bound executions. Do not add eligibility decisions. |
| `apps/runner/runner/tests/` | Add tests for callback ordering, non-change execution compatibility, non-retryable callback failures, and no token logging. |

### Frontend

| File | Planned changes |
|---|---|
| `apps/web/src/features/changes/types.ts` | Add window, preflight, conflict, target lock, and freeze rule types. |
| `apps/web/src/features/changes/api.ts` | Add calls for window patch, preflight, dispatch, and freeze rules. |
| `apps/web/src/routes/changes/ChangeDetailPage.tsx` | Add schedule panel, conflict drawer, preflight card, and disabled dispatch behavior. |
| `apps/web/src/routes/changes/ChangesPage.tsx` | Show window status and dispatch eligibility summary in list if Phase 11.1 has a list page. |
| `apps/web/src/routes/changes/FreezeRulesPage.tsx` | Add freeze rule list and management controls. |
| `apps/web/src/app/router.tsx` | Register freeze rule management route and any missing change routes. |
| `apps/web/src/app/AppLayout.tsx` | Add navigation item if appropriate under operations/admin. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add query keys for change preflight and freeze rules. |

## 14. Migration Plan

1. Create schema migration for new models and fields.
2. Add `ChangeWindow` rows for existing non-terminal approved/scheduled Phase 11.1 changes only if such data exists. If no existing Phase 11.1 production data exists, document no backfill required.
3. Backfill `ChangeWindow.status` from timestamps:
   - future start -> `scheduled`;
   - current interval -> `open`;
   - past end and not running -> `expired`;
   - running past end -> `overrun`;
   - terminal changes -> `closed`.
4. Create the partial unique active-lock constraint after verifying there are no duplicate active locks. Since this is a new table, duplicates should not exist.
5. Add audit object type migration if Phase 11.1 did not already add broad change object types.
6. Deploy backend before frontend so new UI calls have APIs available.
7. Deploy runner after backend supports callback endpoints. Backend must remain compatible with older runners by preserving Phase 11.1 bind/complete behavior during rollout.

Rollback considerations:

- dropping the partial unique index removes conflict protection and should not be done while dispatch is enabled;
- rollback should disable dispatch endpoints first or gate them with a feature flag if the project has feature flags;
- target locks are operational records and should be retained for audit if possible.

## 15. Testing Plan

### Backend Unit and Service Tests

- dispatch outside window is blocked with `dispatch_outside_window`;
- dispatch before `starts_at` returns window status `scheduled`;
- dispatch after `ends_at` marks window `expired` when execution never started;
- running execution past `ends_at` marks window `overrun` without runner decision-making;
- active `block` freeze blocks dispatch;
- active `allow_with_exception` freeze without exception returns `freeze_exception_required`;
- active `allow_with_exception` freeze with exception passes freeze check;
- `block` freeze wins over exception-capable freeze;
- conflicting active target lock blocks dispatch;
- partial unique active-lock constraint rejects concurrent active locks for the same target key;
- released/expired locks do not block new dispatch;
- window changes after approval require reapproval unless the change is still draft;
- freeze exception changes after approval require reapproval unless the change is still draft;
- actual accepted/start/end timestamp stamping works through internal callbacks;
- locks release on execution finished;
- dispatch transaction rolls back locks if execution reservation fails;
- dispatch runs fresh preflight even when a stale successful preflight ID is submitted;
- actor authorization failure is represented in preflight and enforced in dispatch.

### API Tests

- `PATCH /api/v1/changes/{id}/window/` creates and updates draft windows;
- `PATCH /window/` after approval invalidates approval and creates/requires reapproval;
- `POST /api/v1/changes/{id}/preflight/` returns full ordered checklist for pass and fail cases;
- `POST /api/v1/changes/{id}/dispatch/` returns `202` with execution and locks only when eligible;
- `GET /api/v1/freeze-rules/` filters by active/effective date/target;
- internal started/finished endpoints reject user JWTs;
- internal started/finished endpoints require runner bearer auth, runner ownership, and claim token;
- internal finished endpoint is idempotent for repeated runner callback with same execution terminal status.

### Runner Tests

- change-bound execution calls `execution-started` before first step start;
- non-change execution behavior is unchanged;
- change-bound execution calls `execution-finished` after completion;
- callback payload includes accepted/start/end timing;
- runner does not inspect or evaluate window/freeze/lock fields;
- dispatch token and claim token are not logged.

### Frontend Tests

- schedule panel submits window payload and displays approval invalidation response;
- conflict drawer renders freeze and lock conflicts from preflight response;
- preflight result card renders all required checks;
- dispatch button is disabled until latest preflight is eligible and fresh;
- freeze rule page lists rules and applies filters;
- non-admin users cannot see mutation controls if mutation APIs are admin-only.

## 16. Codex Implementation Batching Plan

Implement in small, reviewable batches:

1. Backend schema batch: models, migrations, admin registration, object type additions, serializer shells.
2. Window service/API batch: window patch endpoint, window status refresh, approval invalidation, tests.
3. Freeze rule batch: model API, evaluation service, preflight freeze checks, tests.
4. Target lock batch: active lock constraint, acquisition/release services, concurrency tests.
5. Preflight and dispatch batch: complete preflight service, dispatch transaction, execution binding integration, audit events, tests.
6. Internal callback and runner batch: started/finished endpoints, runner client/executor updates, timing tests.
7. Frontend change detail batch: schedule panel, preflight card, conflict drawer, disabled dispatch.
8. Frontend freeze rules batch: list/manage page, navigation, tests.
9. Final hardening batch: race-condition tests, audit scrub verification, documentation updates, full targeted test run.

Do not mix frontend, runner, and backend transaction changes in one large batch unless unavoidable.

## 17. Definition of Done

Phase 11.2 is done when:

- `ChangeWindow`, `FreezeRule`, `TargetLock`, and `DispatchEligibilityCheck` exist with documented constraints and migrations;
- window states `scheduled`, `open`, `expired`, `overrun`, and `closed` are correctly computed and persisted at service boundaries;
- freeze behaviors `block` and `allow_with_exception` are enforced by Django preflight and dispatch;
- active target locks are protected by a Postgres partial unique constraint;
- dispatch preflight checks approved status, policy pass, window open, freeze conflicts, target lock conflicts, and actor authorization;
- `POST /api/v1/changes/{id}/dispatch/` cannot reserve execution without passing fresh Django preflight;
- runner receives dispatch only after Django eligibility succeeds;
- runner reports accepted/start/end timing and does not evaluate eligibility;
- window changes after approval invalidate approval unless the change is still draft;
- React exposes the schedule panel, conflict drawer, preflight result card, freeze rules page, and disabled dispatch behavior;
- audit events capture window, freeze, lock, preflight, dispatch, and timing changes without sensitive data;
- required tests pass, including concurrency coverage for active target locks.

## 18. Risks and Drift Traps

- Phase 11.1 may implement status names or routes differently than its blueprint. Reconcile before coding.
- `/internal/v1/...` in the prompt conflicts with the current `/api/v1/internal/...` convention. Choose one route strategy deliberately and test it.
- A UI preflight result can become stale immediately. Dispatch must run fresh server-side checks.
- Checking for active locks before insert is not sufficient. The partial unique constraint is mandatory.
- `allow_with_exception` is easy to accidentally turn into breakglass. It must only satisfy freeze exception requirements and must not bypass other checks.
- Window overrun must not be treated as runner authorization. The runner reports timing; Django classifies the window.
- Approval invalidation can corrupt audit history if old approval links are overwritten. Preserve old approval IDs through audit or history records.
- Timezone display must not affect comparisons. Store and compare aware UTC datetimes.
- Adding freeze rule management UI without mutation APIs creates a misleading product surface. Either implement admin mutations or keep the page read-only.
- Circular imports between executions and changes services are likely. Use local imports or a narrow integration module.
- Tests that pass on SQLite may miss partial unique constraint behavior. Ensure the active-lock constraint is verified against Postgres in the project test environment.
