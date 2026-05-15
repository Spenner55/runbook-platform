# Phase 11.1: Change Dossier, Operation Profiles, and Execution Binding Blueprint

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 11.1 |
| Phase name | Change dossier, operation profiles, and execution binding |
| Objective | Add a first-class `ChangeRecord` aggregate that binds high-risk production operation requests, operation profiles, production targets, approval requests, policy decisions, and exactly one execution. |
| Status | Blueprint only - do not implement without re-reading current source first |
| Depends on | Phases 01-10.9 complete, tested, documented, and deployed behind the Phase 10.9 hardening constraints |
| Authored | 2026-05-01 |
| Primary new app | `apps/api/apps/changes/` |

This document is an implementation blueprint only. It intentionally does not implement code.

## 2. Executive Summary

Phase 11.1 introduces the control-plane object that operators use for high-risk production work: a `ChangeRecord`. A change record is the dossier for one requested production operation. It captures what operation is requested, which approved operation profile allows it, which production targets are affected, which immutable inputs were submitted, which approval and policy decisions authorized it, and which single execution performed it.

The implementation adds a new Django app, `apps/api/apps/changes/`, with four required models:

- `OperationProfile`
- `ChangeRecord`
- `ChangeTarget`
- `ChangeExecutionBinding`

The core behavior is:

1. An operator creates a draft change from an active `OperationProfile`.
2. The selected workflow must be allowlisted by that operation profile.
3. Every target must be explicitly production-scoped.
4. Submit freezes the request into an immutable snapshot and computes deterministic hashes.
5. Submit creates or links the approval request required for the change.
6. Approval moves the change toward scheduled or dispatchable state.
7. Dispatch creates one execution reservation and one `ChangeExecutionBinding`.
8. The runner receives change metadata in its normal claim payload and calls a Django internal bind endpoint before executing any step.
9. Django validates the dispatch token, requested input hash, operation profile key, runner ownership, and one-to-one binding before the change can enter `running`.
10. Execution completion updates the change lifecycle without changing runner execution semantics.

Phase 11.1 does not redesign workflows, workflow execution, runner step execution, step-level approvals, policy rule evaluation, audit storage, authentication, or frontend API boundaries. It adds a change lifecycle around the existing execution system and uses Django services as the only authority for all state transitions.

Important compatibility note: the current approvals implementation is step-scoped. A submit-for-approval change workflow cannot safely fake an approval by creating placeholder executions or placeholder steps. The implementation must add only the narrow approval-subject support needed for change records while keeping existing step approval behavior and APIs intact. See sections 5.6, 6.3, and 11.

## 3. Current-State Inspection Checklist

The following repository facts were inspected before writing this blueprint:

- [x] `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` preserves the core invariants: Django is the control plane, the runner talks only to Django internal APIs, the frontend talks only to Django public APIs, UUID primary keys are standard, and business logic belongs in services.
- [x] `docs/blueprints/phase-10-01-approvals-blueprint.md` established step-level approval gates, timeout behavior, and runner polling semantics.
- [x] `docs/blueprints/phase-10-02-policies-blueprint.md` established deterministic step-level policy evaluation with outcomes `approval_required`, `auto_approve`, and `block`.
- [x] `docs/blueprints/phase-10-03-audit-trail-blueprint.md` established immutable append-only audit events and explicitly safe metadata.
- [x] `docs/blueprints/phase-10-07-authentication-authorization-blueprint.md` established JWT auth, runner bearer auth, organization membership, and `X-Organization-Id` as the organization context.
- [x] `apps/api/apps/executions/models.py` defines `Execution` statuses `queued`, `claimed`, `running`, `succeeded`, `failed`, and `cancelled`; `ExecutionStep` already supports `waiting_for_approval`.
- [x] `apps/api/apps/executions/services.py` owns execution creation, runner claim, heartbeat, step updates, completion, audit emission, stream events, and integration notification.
- [x] `apps/api/apps/executions/internal_views.py` exposes runner-only endpoints under the existing `/api/v1/internal/...` tree and evaluates policy before a step is allowed to run.
- [x] `apps/api/apps/executions/internal_serializers.py` defines `ClaimedExecutionSerializer` and `InternalExecutionStepSerializer`; neither includes change metadata yet.
- [x] `apps/api/apps/approvals/models.py` defines `ApprovalRequest` and `ApprovalDecision` as execution-step-scoped records; `ApprovalRequest.execution` and `ApprovalRequest.step` are currently required.
- [x] `apps/api/apps/approvals/services.py` owns approval request creation, decision, timeout recovery, and audit emission.
- [x] `apps/api/apps/policies/models.py` defines `Policy`, `PolicyRule`, and `PolicyEvaluation`; `PolicyEvaluation` is execution-step-scoped.
- [x] `apps/api/apps/policies/services.py` owns deterministic policy evaluation and emits `policy.evaluated` audit events.
- [x] `apps/api/apps/audit/models.py` defines append-only `AuditEvent` object types but does not yet include change object types.
- [x] `apps/api/apps/audit/services.py` scrubs sensitive metadata keys, but it does not yet explicitly scrub `dispatch_token`, `dispatch_token_hash`, or requested input payload keys.
- [x] `apps/api/config/api_v1_urls.py` registers public APIs under `/api/v1/` and internal runner APIs under `/api/v1/internal/`.
- [x] `apps/api/config/settings/base.py` registers approvals, policies, audit, artifacts, integrations, executions, users, organizations, runbooks, and workflows. It does not yet register `changes`.
- [x] `apps/api/apps/common/org_context.py` enforces `X-Organization-Id` and body/query org mismatch detection.
- [x] `apps/api/apps/common/permissions.py` provides member, operator, admin, and runner permission helpers.
- [x] `apps/runner/runner/schemas.py` models claim, heartbeat, step start, approval polling, completion, and artifact upload payloads. It has no change fields yet.
- [x] `apps/runner/runner/client.py` sends runner bearer auth and talks only to `/api/v1/internal/...`.
- [x] `apps/runner/runner/executor.py` calls Django's step-start endpoint before executing commands and never evaluates policy locally.
- [x] `apps/web/src/shared/api/client.ts` blocks browser calls to `/api/v1/internal/` and automatically sends `X-Organization-Id`.
- [x] `apps/web/src/app/router.tsx` and `apps/web/src/app/AppLayout.tsx` have routes and navigation for runbooks, workflows, executions, approvals, policies, integrations, and settings, but no changes route.
- [x] `apps/web/src/routes/executions/ExecutionDetailPage.tsx` already renders approval, policy, audit, and artifact context around executions.
- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` did not exist before this blueprint was created.

If any of these facts drift before implementation, re-inspect the source and update the plan before coding.

## 4. Architecture Invariants

These invariants are mandatory for Phase 11.1:

| Invariant | Phase 11.1 consequence |
|---|---|
| Django remains the source of truth. | Change lifecycle transitions, profile enforcement, target validation, approval linkage, policy linkage, execution reservation, binding, token verification, and audit emission all live in Django services. |
| Frontend talks only to Django public APIs. | React change pages call `/api/v1/changes/...` only. They never call runner APIs or `/api/v1/internal/...`. |
| Runner talks only to Django internal APIs. | The runner receives change metadata from the normal claim response and confirms binding through a Django internal endpoint. It never reads the database. |
| Runner execution semantics are preserved. | The runner still claims executions, sends heartbeats, calls step-start, waits for approval when Django says so, reports step terminal status, uploads artifacts, and completes the execution. |
| Workflow execution is not redesigned. | Existing `Execution` and `ExecutionStep` remain the execution source of truth. A change wraps exactly one execution; it does not replace execution. |
| No workflow outside an `OperationProfile` may enter the Phase 11 lifecycle. | `POST /api/v1/changes/` and submit must reject workflows that are not allowlisted by the selected active profile. |
| High-risk profile workflows must not bypass the change lifecycle. | Direct execution creation must reject workflows currently bound to active production operation profiles unless the execution is being created by the changes service. |
| Request content is immutable after submit. | Requested inputs, operation profile, workflow, targets, schedule fields, and request snapshot cannot change after submit unless the change is canceled and a new draft is created. |
| One change binds to exactly one execution. | Enforce with one-to-one database constraints on `ChangeExecutionBinding.change_record` and `ChangeExecutionBinding.execution`. |
| Dispatch token cleartext is never stored. | Store only a nonce and hash/HMAC material sufficient for verification and regeneration. Never audit or log the clear token. |
| Requested input hashes are deterministic. | Hash canonical JSON bytes using stable key ordering and separators. Tests must prove hash stability for semantically identical input. |
| Existing approval and policy semantics remain intact. | Add only bounded integration points. Do not turn approvals or policies into general workflow engines. |
| Audit metadata remains sanitized. | Audit events include IDs, statuses, counts, hashes, and booleans. They do not include raw requested inputs, raw command text, dispatch tokens, claim tokens, secrets, request bodies, or workflow snapshots. |
| No new queues or event infrastructure. | Scheduled release can be synchronous Django service work invoked by internal claim flow and/or a management command. No Celery, Kafka, RabbitMQ, or outbox table. |

## 5. Data Model Design

### 5.1 New App Structure

Create a new Django app:

```text
apps/api/apps/changes/
  __init__.py
  apps.py
  admin.py
  models.py
  services.py
  selectors.py
  serializers.py
  urls.py
  views.py
  migrations/
    __init__.py
  tests/
    __init__.py
    conftest.py
    test_api.py
    test_models.py
    test_services.py
    test_execution_binding.py
    test_audit_integration.py
    test_hashing.py
```

Recommended module responsibilities:

- `models.py`: persistence only, enums, indexes, constraints, basic `__str__`.
- `services.py`: lifecycle transitions, validation, hashing, token handling, approval/policy/execution binding, audit.
- `selectors.py`: organization-scoped read querysets for detail/list/profile picker.
- `serializers.py`: public and internal API contracts.
- `views.py`: public views and internal runner bind view; views validate serializer input and call services.
- `urls.py`: public change routes and internal change routes exported separately if useful.

### 5.2 `OperationProfile`

`OperationProfile` is the organization-scoped allowlist entry that makes a workflow eligible for the Phase 11 change lifecycle.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Required tenant boundary. |
| `key` | `SlugField` or `CharField(96)` | Stable profile key used in APIs and runner payloads. Unique per organization. |
| `name` | `CharField(255)` | Human-readable name. |
| `description` | `TextField(blank=True)` | Operator-facing profile description. |
| `is_active` | `BooleanField(default=True)` | Inactive profiles cannot create or submit changes. |
| `risk_level` | `CharField(32)` | Expected values: `high` or `critical` for Phase 11.1. |
| `requires_approval` | `BooleanField(default=True)` | High-risk production profiles should default to approval required. |
| `verification_required` | `BooleanField(default=True)` | Controls whether successful execution moves to `verification_pending`. |
| `approval_ttl_seconds` | `PositiveIntegerField(null=True, blank=True)` | Deadline copied into the change approval request. |
| `dispatch_ttl_seconds` | `PositiveIntegerField(default=900)` | How long a dispatchable change can wait before expiring. |
| `allowed_target_types` | `JSONField(default=list)` | List of target type strings accepted for this profile. Empty means no targets are valid. |
| `requested_inputs_schema` | `JSONField(default=dict)` | Optional JSON-schema-like contract for requested inputs. Keep validation simple in v1. |
| `target_schema` | `JSONField(default=dict)` | Optional structured target validation hints. |
| `allowed_workflows` | M2M -> `workflows.Workflow` | The workflows allowed to enter the change lifecycle through this profile. |
| `created_by` | FK -> `users.User`, nullable | Use `SET_NULL`. |
| `updated_by` | FK -> `users.User`, nullable | Use `SET_NULL`. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| unique | `(organization, key)` | Stable profile lookup in public APIs and runner payloads. |
| index | `(organization, is_active, key)` | Fast profile picker and service lookup. |
| service invariant | allowed workflows must belong to the same organization | Prevent cross-tenant profile membership. |
| service invariant | allowed workflows must be `published` to submit | Draft/superseded/archived workflows cannot be dispatched through a change. |
| service invariant | `risk_level in ("high", "critical")` | Keep Phase 11.1 scoped to high-risk production work. |

Do not add profile inheritance, profile templates, or cross-organization sharing in Phase 11.1.

### 5.3 `ChangeRecord`

`ChangeRecord` is the aggregate root. It owns the request lifecycle and points to the profile, workflow, targets, approval, policy decision, and execution binding.

Required status values:

- `draft`
- `pending_approval`
- `approved`
- `scheduled`
- `dispatchable`
- `running`
- `verification_pending`
- `verified`
- `closed`
- `rejected`
- `canceled`
- `expired`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Required tenant boundary. |
| `operation_profile` | FK -> `OperationProfile`, `on_delete=PROTECT` | The profile selected at create time. |
| `workflow` | FK -> `workflows.Workflow`, `on_delete=PROTECT` | The allowlisted workflow selected for execution. |
| `requested_by` | FK -> `users.User`, nullable, `SET_NULL` | Human actor who created the draft. |
| `submitted_by` | FK -> `users.User`, nullable, `SET_NULL` | Human actor who submitted. |
| `title` | `CharField(255)` | Operator-facing change title. |
| `summary` | `TextField(blank=True)` | Request summary. |
| `justification` | `TextField(blank=True)` | Required at submit for high-risk production work. |
| `status` | `CharField(32)` | One of the required lifecycle statuses. |
| `requested_inputs` | `JSONField(default=dict)` | Draft request inputs. Immutable after submit. |
| `requested_inputs_sha256` | `CharField(64, blank=True)` | Deterministic hash of canonical requested inputs. Set on submit. |
| `request_snapshot` | `JSONField(default=dict)` | Immutable snapshot frozen on submit. |
| `request_snapshot_sha256` | `CharField(64, blank=True)` | Deterministic hash of the full immutable request snapshot. |
| `operation_profile_key_snapshot` | `CharField(96, blank=True)` | Profile key at submit. Used in runner payload verification. |
| `workflow_version_snapshot` | `PositiveIntegerField(null=True, blank=True)` | Workflow version at submit. |
| `approval_request` | FK -> `approvals.ApprovalRequest`, nullable, `PROTECT` | Change-level approval request linkage. |
| `policy_evaluation` | FK -> `policies.PolicyEvaluation`, nullable, `PROTECT` | First relevant execution policy decision linked after execution starts. |
| `policy_decision_snapshot` | `JSONField(default=dict)` | Sanitized profile/policy binding summary. |
| `scheduled_for` | `DateTimeField(null=True, blank=True)` | Optional operator-requested future dispatch time. Immutable after submit. |
| `submitted_at` | `DateTimeField(null=True, blank=True)` | Set on submit. |
| `approved_at` | `DateTimeField(null=True, blank=True)` | Set when approval resolves approved. |
| `dispatchable_at` | `DateTimeField(null=True, blank=True)` | Set when an execution reservation is created. |
| `running_at` | `DateTimeField(null=True, blank=True)` | Set by internal bind endpoint. |
| `verification_pending_at` | `DateTimeField(null=True, blank=True)` | Set after successful execution when verification is required. |
| `verified_at` | `DateTimeField(null=True, blank=True)` | Set by future verification service/API. |
| `closed_at` | `DateTimeField(null=True, blank=True)` | Set when lifecycle reaches `closed`. |
| `rejected_at` | `DateTimeField(null=True, blank=True)` | Set when approval rejects. |
| `canceled_at` | `DateTimeField(null=True, blank=True)` | Set when canceled. |
| `expired_at` | `DateTimeField(null=True, blank=True)` | Set when approval, schedule, or dispatch window expires. |
| `terminal_reason` | `CharField(64, blank=True)` | Examples: `approval_rejected`, `approval_timed_out`, `dispatch_expired`, `execution_failed`, `verified_closed`. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| index | `(organization, status, created_at)` | List/detail queries and operational queues. |
| index | `(organization, operation_profile, status)` | Profile-scoped change views. |
| index | `(approval_request)` | Approval callback lookup. |
| index | `(workflow, status)` | Bypass checks and support queries. |
| check | status in required status values | Database-level lifecycle value guard. |
| service invariant | `organization_id == operation_profile.organization_id == workflow.organization_id` | Tenant safety. |
| service invariant | status not `draft` means request content is immutable | Prevent post-submit mutation. |

Do not store clear dispatch tokens, raw approval decision notes from unrelated domains, raw workflow snapshots, or raw command output on `ChangeRecord`.

### 5.4 `ChangeTarget`

`ChangeTarget` records the production systems affected by the requested operation.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `change_record` | FK -> `ChangeRecord`, `related_name="targets"` | Parent aggregate. |
| `organization` | FK -> `organizations.Organization` | Denormalized tenant boundary for querying and validation. |
| `position` | `PositiveIntegerField` | Stable ordering in snapshots. |
| `target_type` | `CharField(64)` | Must be allowed by the operation profile. |
| `target_identifier` | `CharField(255)` | Operator-provided identifier. |
| `normalized_identifier` | `CharField(255)` | Lower/trim/canonical form used for dedupe. |
| `display_name` | `CharField(255, blank=True)` | Optional UI label. |
| `environment` | `CharField(32)` | Must be `production` in Phase 11.1. |
| `metadata` | `JSONField(default=dict)` | Sanitized non-secret target metadata. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| unique | `(change_record, target_type, normalized_identifier)` | Prevent duplicate targets on one change. |
| unique | `(change_record, position)` | Stable snapshot ordering. |
| index | `(organization, target_type, normalized_identifier)` | Support future target search. |
| check/service | `environment == "production"` | Production-only validation. |
| service invariant | `organization_id == change_record.organization_id` | Tenant safety. |

Reject changes with zero targets unless the operation profile explicitly declares `target_schema.allow_empty_targets=true`. The default must be at least one production target.

### 5.5 `ChangeExecutionBinding`

`ChangeExecutionBinding` is the one-to-one bridge between a submitted change and the one execution that performs it.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `change_record` | OneToOne -> `ChangeRecord`, `related_name="execution_binding"` | Enforces one execution per change. |
| `execution` | OneToOne -> `executions.Execution`, `related_name="change_binding"` | Enforces one change per execution. |
| `organization` | FK -> `organizations.Organization` | Denormalized tenant boundary. |
| `operation_profile_key` | `CharField(96)` | Snapshot used in runner payload and bind validation. |
| `requested_inputs_sha256` | `CharField(64)` | Snapshot used in runner payload and bind validation. |
| `dispatch_token_nonce` | `CharField(128)` | Random nonce used to regenerate the clear token with a server secret. |
| `dispatch_token_hash` | `CharField(128)` | HMAC or SHA-256 hash of the clear dispatch token. |
| `dispatch_token_expires_at` | `DateTimeField` | Dispatch window deadline. |
| `reserved_at` | `DateTimeField` | Set when the execution reservation is created. |
| `bound_at` | `DateTimeField(null=True, blank=True)` | Set when runner proves possession of token. |
| `bound_by_runner_id` | `CharField(255, blank=True)` | Runner identity from internal request. |
| `runner_payload_snapshot` | `JSONField(default=dict)` | Sanitized fields sent to runner, excluding clear token. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| unique | one-to-one `change_record` | Exactly one execution per change. |
| unique | one-to-one `execution` | One execution cannot satisfy multiple changes. |
| index | `(organization, reserved_at)` | Operational lookup. |
| index | `(dispatch_token_expires_at)` | Expiration sweeps. |
| service invariant | binding org matches change org and execution org | Tenant safety. |
| service invariant | `bound_at` can be set only once | Prevent rebinding. |

The clear dispatch token must never be persisted. Generate it on demand from:

- `CHANGE_DISPATCH_TOKEN_SECRET`
- `change_record_id`
- `execution_id`
- `dispatch_token_nonce`
- `requested_inputs_sha256`

Then compare the submitted token using constant-time comparison against the stored hash.

### 5.6 Approval Request Linkage

The current `ApprovalRequest` model is execution-step-scoped. Phase 11.1 needs a change-level approval before dispatch. Do not create placeholder executions or placeholder steps to satisfy the existing approval schema.

Recommended bounded approval extension:

1. Add subject fields to `ApprovalRequest`:
   - `subject_type`: `execution_step` or `change_record`
   - `subject_id`: UUID
2. Backfill existing rows as `subject_type="execution_step"` and `subject_id=step_id`.
3. Allow `execution` and `step` to be nullable only for `change_record` subject rows.
4. Add a database check constraint:
   - `execution_step` rows require `execution_id` and `step_id`.
   - `change_record` rows require `subject_id` and must have `execution_id IS NULL` and `step_id IS NULL`.
5. Keep existing step approval services, URLs, serializers, and runner behavior compatible.
6. Add a narrow service helper such as `approvals.services.create_change_approval_request(...)`.
7. Store the resulting approval request on `ChangeRecord.approval_request`.

Approval decisions still flow through the existing approval decision endpoint. After a change-subject approval resolves, approvals service must call a changes service hook inside the same transaction to move the `ChangeRecord` to `approved`, `rejected`, or `expired`.

### 5.7 Policy Decision Linkage

Existing `PolicyEvaluation` rows are execution-step-scoped and must remain that way. Phase 11.1 should not generalize policies into a change policy engine.

Policy linkage rules:

- The operation profile allowlist is the pre-dispatch policy gate for entering the Phase 11 lifecycle.
- When the bound execution reaches `ExecutionStepStartView`, existing policy evaluation still runs before a step can execute.
- If the execution has a `ChangeExecutionBinding`, Django must link the first relevant `PolicyEvaluation` to `ChangeRecord.policy_evaluation`.
- Emit `change.policy_bound` when that linkage is written.
- Do not duplicate policy rule evaluation logic in the runner or frontend.
- Do not store raw policy context containing requested inputs. Store IDs, outcomes, reason, and hashes only.

### 5.8 Status Lifecycle

Allowed lifecycle transitions:

| From | To | Trigger |
|---|---|---|
| none | `draft` | `POST /api/v1/changes/` creates a draft. |
| `draft` | `pending_approval` | Submit freezes the snapshot and creates/links a change approval request. |
| `draft` | `approved` | Submit on a profile that explicitly does not require approval. This should be rare and must be audited. |
| `pending_approval` | `approved` | Approval request is approved. |
| `pending_approval` | `rejected` | Approval request is rejected. |
| `pending_approval` | `expired` | Approval request times out. |
| `approved` | `scheduled` | Approved change has a future `scheduled_for`. |
| `approved` | `dispatchable` | Approved change has no future schedule and execution reservation is created. |
| `scheduled` | `dispatchable` | Schedule is due and execution reservation is created. |
| `scheduled` | `expired` | Schedule or approval validity window expires before dispatch. |
| `dispatchable` | `running` | Runner successfully binds the reserved execution with the dispatch token. |
| `dispatchable` | `expired` | Dispatch token expires before binding. |
| `running` | `verification_pending` | Bound execution succeeds and profile requires verification. |
| `running` | `closed` | Bound execution fails, or succeeds on a profile that does not require verification. |
| `verification_pending` | `verified` | Future verification action marks evidence accepted. |
| `verified` | `closed` | Future close action closes verified change. |
| `draft` | `canceled` | Draft is withdrawn. |
| `pending_approval` | `canceled` | Submitted change is withdrawn before approval. |
| `approved` | `canceled` | Approved change is withdrawn before dispatch. |
| `scheduled` | `canceled` | Scheduled change is withdrawn before dispatch. |

Phase 11.1 public APIs only require create, detail, and submit. The lifecycle should still be modeled fully so later phases can add cancel, verify, and close actions without rewriting the aggregate.

## 6. Service-Layer Design

All behavior below belongs in `apps/api/apps/changes/services.py` unless explicitly noted.

### 6.1 Canonical Hashing Helpers

Add deterministic helper functions:

- `canonical_json_bytes(value) -> bytes`
- `sha256_canonical_json(value) -> str`
- `build_request_snapshot(change_record, targets) -> dict`
- `hash_dispatch_token(token) -> str`
- `generate_dispatch_token(binding) -> str`
- `verify_dispatch_token(binding, token) -> bool`

Canonical JSON requirements:

- Use UTF-8.
- Sort object keys.
- Use compact separators.
- Treat dict key order as irrelevant.
- Reject non-JSON-serializable values at the serializer/service boundary.
- Normalize datetimes to ISO-8601 strings before hashing.
- Do not include database timestamps that can change after submit in `requested_inputs_sha256`.

`requested_inputs_sha256` hashes only requested inputs. `request_snapshot_sha256` hashes the full immutable snapshot, including profile key, workflow id/version, targets, schedule, requested inputs hash, and submit metadata.

### 6.2 `create_change_record`

Responsibilities:

1. Resolve organization from `X-Organization-Id`.
2. Assert authenticated user is an organization operator.
3. Load active `OperationProfile` by organization and key.
4. Load selected workflow through organization-scoped queryset.
5. Validate workflow is allowlisted by the profile.
6. Validate workflow is published.
7. Validate targets:
   - at least one target unless profile explicitly allows empty targets;
   - every target environment is exactly `production`;
   - every target type is allowed by the profile;
   - no duplicate `(target_type, normalized_identifier)` pairs.
8. Validate requested inputs against the profile's simple schema contract.
9. Create `ChangeRecord(status="draft")` and `ChangeTarget` rows atomically.
10. Emit `change.created`.

The service may compute a draft input hash for display, but the authoritative `requested_inputs_sha256` is set on submit.

### 6.3 `submit_change_record`

Responsibilities:

1. Lock the `ChangeRecord` with `select_for_update()`.
2. Require `status == "draft"`.
3. Re-load and validate profile, workflow, and targets because they may have changed since draft creation.
4. Require non-empty `justification`.
5. Recompute `requested_inputs_sha256`.
6. Build and store `request_snapshot`.
7. Store `request_snapshot_sha256`.
8. Store profile key and workflow version snapshots.
9. Reject if requested inputs or targets are invalid.
10. If profile requires approval:
    - create a change-subject `ApprovalRequest`;
    - link it to `ChangeRecord.approval_request`;
    - set status `pending_approval`;
    - set `submitted_at`;
    - emit `change.submitted`;
    - emit `change.approval_bound`.
11. If profile explicitly does not require approval:
    - set status `approved`;
    - set `submitted_at` and `approved_at`;
    - emit `change.submitted`;
    - emit `change.status_changed`;
    - call `schedule_or_make_dispatchable`.

Do not create an execution before approval unless the profile explicitly bypasses approval. High-risk production profiles should not bypass approval by default.

### 6.4 `handle_change_approval_decision`

Called from `apps.approvals.services.decide_approval` and approval timeout recovery when the approval request subject is `change_record`.

Responsibilities:

1. Lock `ChangeRecord` by `approval_request_id`.
2. Require `status == "pending_approval"`.
3. If approved:
   - set status `approved`;
   - set `approved_at`;
   - emit `change.status_changed`;
   - call `schedule_or_make_dispatchable`.
4. If rejected:
   - set status `rejected`;
   - set `rejected_at`;
   - set `terminal_reason="approval_rejected"`;
   - emit `change.status_changed`.
5. If timed out:
   - set status `expired`;
   - set `expired_at`;
   - set `terminal_reason="approval_timed_out"`;
   - emit `change.status_changed`.

This hook must run in the same transaction as the approval decision so approval and change state cannot diverge.

### 6.5 `schedule_or_make_dispatchable`

Responsibilities:

1. If `scheduled_for` is in the future, transition `approved -> scheduled`.
2. If no future schedule exists, call `make_dispatchable`.
3. Emit one audit event for each persisted status transition.

### 6.6 `make_dispatchable`

Responsibilities:

1. Lock the change.
2. Require status `approved` or due `scheduled`.
3. Create the execution through existing execution service using the selected workflow and actor `system_actor("Change service")`.
4. Ensure direct execution bypass checks know this call is authorized by the change service.
5. Generate dispatch token nonce and hash material.
6. Create `ChangeExecutionBinding` with one-to-one links to the change and execution.
7. Set change status `dispatchable`.
8. Set `dispatchable_at`.
9. Emit `change.execution_binding_reserved`.
10. Emit `change.status_changed`.

Execution creation and binding reservation must be atomic from the change service perspective. If binding creation fails, the execution must not remain as an unbound dispatchable production operation.

### 6.7 `promote_due_scheduled_changes`

Responsibilities:

1. Find due `scheduled` changes whose `scheduled_for <= now`.
2. Use `select_for_update(skip_locked=True)`.
3. Call `make_dispatchable` for each row.
4. Return promoted change IDs.

Call this service from the internal claim path before `claim_next_execution`, and optionally expose a management command such as `python manage.py promote_due_changes`. Do not add a queue or background worker.

### 6.8 `bind_execution`

Called by the runner internal endpoint before the runner executes any step.

Responsibilities:

1. Authenticate request with `RunnerBearerTokenAuthentication`.
2. Lock `ChangeRecord`, `ChangeExecutionBinding`, and `Execution`.
3. Require change status `dispatchable`.
4. Require binding exists and points to the submitted `execution_id`.
5. Require execution is claimed by `runner_id` and `claim_token`.
6. Require `operation_profile_key` matches binding snapshot.
7. Require `requested_inputs_sha256` matches binding snapshot.
8. Require dispatch token is not expired.
9. Verify dispatch token using constant-time comparison.
10. If already bound by the same runner/execution and the token is valid, return idempotent success.
11. If already bound differently, return conflict.
12. Set `bound_at`, `bound_by_runner_id`, and sanitized `runner_payload_snapshot`.
13. Set change status `running` and `running_at`.
14. Emit `change.execution_bound`.
15. Emit `change.status_changed`.

The runner must not be allowed to start step execution until this endpoint succeeds for change-bound executions.

### 6.9 `link_policy_evaluation`

Called after existing step policy evaluation creates a `PolicyEvaluation` for an execution that has a change binding.

Responsibilities:

1. Find `ChangeExecutionBinding` by execution.
2. Lock the associated `ChangeRecord`.
3. If `policy_evaluation` is empty, set it to the evaluation.
4. Store a sanitized `policy_decision_snapshot`:
   - policy evaluation id;
   - policy id and rule id when present;
   - outcome;
   - effective outcome;
   - decision source;
   - reason;
   - evaluated_at.
5. Emit `change.policy_bound`.

Do not overwrite the first linked policy evaluation unless a later phase explicitly defines multi-step policy binding semantics.

### 6.10 `handle_bound_execution_completed`

Called from `apps.executions.services.complete_execution` after an execution reaches a terminal status.

Responsibilities:

1. If execution has no `change_binding`, do nothing.
2. Lock the bound `ChangeRecord`.
3. Require current change status `running`; if already terminal, return idempotently.
4. If execution status is `succeeded` and profile requires verification:
   - set status `verification_pending`;
   - set `verification_pending_at`;
   - emit `change.status_changed`.
5. If execution status is `succeeded` and profile does not require verification:
   - set status `closed`;
   - set `closed_at`;
   - set `terminal_reason="execution_succeeded"`;
   - emit `change.status_changed`.
6. If execution status is `failed` or `cancelled`:
   - set status `closed`;
   - set `closed_at`;
   - set `terminal_reason="execution_failed"` or `execution_cancelled`;
   - emit `change.status_changed`.

Do not add a new execution status for changes.

### 6.11 Post-Submit Immutability

Every service that mutates request content must call `assert_change_request_mutable(change)`.

Request content includes:

- `operation_profile`
- `workflow`
- `requested_inputs`
- `title`
- `summary`
- `justification`
- `scheduled_for`
- all `ChangeTarget` rows

If `status != "draft"`, mutation must raise `InvalidStateTransitionError` with code `change_request_immutable`.

Do not silently clone and resubmit inside an update endpoint. Withdrawing and resubmitting must be an explicit future action that creates a new draft or new version.

## 7. API Design

All public APIs require JWT authentication and `X-Organization-Id`. Operators can create and submit changes. Organization members may read change detail unless product policy narrows that later.

### 7.1 `POST /api/v1/changes/`

Create a draft change record.

Request:

```json
{
  "operation_profile_key": "prod-database-maintenance",
  "workflow_id": "7f95e54e-9f3f-4ad0-96c2-f9944f373a09",
  "title": "Rotate production database credentials",
  "summary": "Rotate application credentials for the production primary database.",
  "justification": "Scheduled credential rotation under maintenance window CHG-1234.",
  "requested_inputs": {
    "rotation_window": "2026-05-03T04:00:00Z",
    "rollback_plan": "Restore previous secret version and restart service."
  },
  "scheduled_for": "2026-05-03T04:00:00Z",
  "targets": [
    {
      "target_type": "database",
      "target_identifier": "prod-primary-db",
      "display_name": "Production primary database",
      "environment": "production",
      "metadata": {
        "region": "us-west-2"
      }
    }
  ]
}
```

Response `201`:

```json
{
  "id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "status": "draft",
  "operation_profile": {
    "id": "92834f34-d452-4f85-aa10-a15fd574322d",
    "key": "prod-database-maintenance",
    "name": "Production database maintenance"
  },
  "workflow_id": "7f95e54e-9f3f-4ad0-96c2-f9944f373a09",
  "workflow_version_snapshot": null,
  "requested_inputs_sha256": "",
  "request_snapshot_sha256": "",
  "targets": [
    {
      "id": "9e51e20f-f63a-410d-9518-d5d698d2dccc",
      "target_type": "database",
      "target_identifier": "prod-primary-db",
      "display_name": "Production primary database",
      "environment": "production"
    }
  ],
  "approval_request": null,
  "policy_decision": null,
  "execution_binding": null,
  "created_at": "2026-05-01T18:00:00Z",
  "updated_at": "2026-05-01T18:00:00Z"
}
```

Important errors:

- `400 invalid_operation_profile`
- `400 workflow_not_allowlisted_for_profile`
- `400 non_production_target`
- `400 duplicate_change_target`
- `400 requested_inputs_invalid`
- `403 permission_denied`
- `409 change_profile_inactive`

### 7.2 `GET /api/v1/changes/{id}/`

Return the full change dossier.

Response must include:

- change metadata and status timestamps;
- operation profile summary;
- workflow id/version;
- immutable request snapshot fields when submitted;
- requested input hash;
- targets;
- approval request summary when linked;
- policy decision summary when linked;
- execution binding summary when reserved/bound;
- execution id and execution status when present.

Do not return:

- dispatch token;
- dispatch token hash;
- raw secret-like requested input values if a later profile schema marks them sensitive;
- claim token;
- raw workflow snapshot.

### 7.3 `POST /api/v1/changes/{id}/submit/`

Submit a draft change for approval.

Request:

```json
{
  "submitter_note": "Ready for production approval."
}
```

Response `200`:

```json
{
  "id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "status": "pending_approval",
  "submitted_at": "2026-05-01T18:05:00Z",
  "requested_inputs_sha256": "4b9f...",
  "request_snapshot_sha256": "34af...",
  "approval_request": {
    "id": "26e7c6d4-0b52-4fc7-92e0-557801596a22",
    "status": "pending",
    "requested_at": "2026-05-01T18:05:00Z",
    "expires_at": "2026-05-01T20:05:00Z"
  }
}
```

Submit is not idempotent across terminal states. Repeated submit on the same draft after the first success should return the current detail if the request already reached `pending_approval` due to a client retry with the same persisted state; otherwise incompatible statuses return `409`.

Important errors:

- `409 invalid_state_transition`
- `409 change_request_immutable`
- `400 change_requires_justification`
- `400 workflow_not_allowlisted_for_profile`
- `400 non_production_target`
- `400 duplicate_change_target`
- `409 change_profile_inactive`

### 7.4 Supporting Profile Picker API

The React operation profile picker needs a read endpoint. Recommended minimal endpoint:

```text
GET /api/v1/changes/operation-profiles/
```

Return active profiles for the current organization with allowlisted published workflow summaries:

```json
{
  "results": [
    {
      "id": "92834f34-d452-4f85-aa10-a15fd574322d",
      "key": "prod-database-maintenance",
      "name": "Production database maintenance",
      "description": "Approved production database maintenance operations.",
      "risk_level": "critical",
      "allowed_target_types": ["database"],
      "requires_approval": true,
      "verification_required": true,
      "allowed_workflows": [
        {
          "id": "7f95e54e-9f3f-4ad0-96c2-f9944f373a09",
          "name": "Rotate database credentials",
          "version": 3
        }
      ]
    }
  ]
}
```

If implementation must keep public API surface to the three required endpoints only, the create page cannot be fully dynamic. The recommended implementation is to add this read-only supporting endpoint.

### 7.5 Internal Bind API

The requirement names:

```text
POST /internal/v1/changes/{id}/bind-execution/
```

The current repository convention registers internal runner APIs under:

```text
/api/v1/internal/...
```

Implement the endpoint in the existing route tree unless the project explicitly chooses to introduce a new internal root:

```text
POST /api/v1/internal/changes/{id}/bind-execution/
```

Request:

```json
{
  "runner_id": "runner-prod-1",
  "claim_token": "a63d707a-4798-43c9-9049-19ef135ee780",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "dispatch_token": "clear-token-from-claim-payload",
  "requested_inputs_sha256": "4b9f...",
  "operation_profile_key": "prod-database-maintenance",
  "sent_at": "2026-05-01T18:10:00Z"
}
```

Response `200`:

```json
{
  "change_record_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "binding_id": "1cf06d7b-9c1a-46bb-9ca8-e195d06d1b34",
  "status": "running",
  "bound_at": "2026-05-01T18:10:01Z"
}
```

Important errors:

- `401` invalid runner token;
- `403` user JWT attempted on internal endpoint;
- `404` change or execution not found;
- `409 change_not_dispatchable`;
- `409 execution_binding_conflict`;
- `409 runner_ownership_mismatch`;
- `409 claim_token_mismatch`;
- `400 dispatch_token_invalid`;
- `400 requested_inputs_hash_mismatch`;
- `400 operation_profile_key_mismatch`;
- `410 dispatch_token_expired`.

## 8. Runner Impact

### 8.1 Claim Payload Additions

Add nullable fields to the claimed execution payload for change-bound executions:

```json
{
  "execution": {
    "id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
    "status": "claimed",
    "workflow_id": "7f95e54e-9f3f-4ad0-96c2-f9944f373a09",
    "organization_id": "39d5200d-9fd1-4afa-b078-ed8fdf907a56",
    "workflow_version": 3,
    "change_record_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
    "dispatch_token": "clear-token-generated-for-runner",
    "requested_inputs_sha256": "4b9f...",
    "operation_profile_key": "prod-database-maintenance",
    "steps": []
  },
  "claim_token": "a63d707a-4798-43c9-9049-19ef135ee780",
  "poll_after_seconds": 5
}
```

For non-change executions, the new fields must be absent or null. Existing runner tests for ordinary executions must continue to pass.

### 8.2 Runner Schema Updates

Update `apps/runner/runner/schemas.py`:

- `ClaimedExecution.change_record_id: UUID | None`
- `ClaimedExecution.dispatch_token: str | None`
- `ClaimedExecution.requested_inputs_sha256: str | None`
- `ClaimedExecution.operation_profile_key: str | None`
- new `BindChangeExecutionRequest`
- new `BindChangeExecutionResponse`

Set Pydantic/logging behavior so dispatch token is not accidentally logged through model dumps used in logs.

### 8.3 Runner Client Updates

Update `apps/runner/runner/client.py`:

- add `bind_change_execution(...)`;
- post only to Django internal API;
- include runner id, claim token, execution id, dispatch token, requested input hash, operation profile key, and timestamp;
- do not retry `400`, `403`, `409`, or `410` bind failures as transient errors.

### 8.4 Runner Executor Updates

Update `apps/runner/runner/executor.py`:

1. After claim and before iterating steps, check `execution.change_record_id`.
2. If absent, keep existing behavior.
3. If present, require all change payload fields.
4. Call `bind_change_execution`.
5. If bind fails, do not call step-start and do not execute commands.
6. Report the execution failed through existing completion endpoint only if Django still recognizes runner ownership and the error path is valid.
7. Never log dispatch token.

The runner still does not validate operation profile policy locally. It only proves to Django that it received the bound payload.

## 9. Frontend Impact

### 9.1 New Feature Area

Add:

```text
apps/web/src/features/changes/
  types.ts
  api/changesApi.ts
  hooks/useOperationProfiles.ts
  hooks/useCreateChange.ts
  hooks/useChangeDetail.ts
  hooks/useSubmitChange.ts
```

Add query keys:

- `operationProfiles(organizationId)`
- `changes(organizationId, status?)`
- `change(changeId, organizationId?)`

### 9.2 Routes

Add routes:

- `/changes/new`
- `/changes/:changeId`

Add primary navigation item:

- `Changes`

Do not remove execution routes. Executions remain the execution history; changes are the production operation dossier.

### 9.3 Operation Profile Picker

The picker must:

- load active profiles from Django;
- show profile name, key, risk level, and approval/verification requirements;
- constrain workflow choices to profile allowlisted published workflows;
- prevent manual workflow IDs outside the selected profile;
- refresh target type choices from `allowed_target_types`;
- not include explanatory marketing text.

### 9.4 Change Create Page

The page must support:

- operation profile selection;
- workflow selection from selected profile;
- title, summary, and justification fields;
- requested inputs JSON editor or profile-driven simple fields;
- target list editor;
- environment fixed to `production`;
- duplicate target prevention before submit;
- create draft action;
- submit-for-approval action after draft create;
- server error rendering through existing `getApiErrorMessage`.

Client-side validation is advisory. Django service validation remains authoritative.

### 9.5 Change Detail Page

The detail page must show:

- status and lifecycle timestamps;
- operation profile summary;
- workflow id/version and link to workflow;
- immutable requested input hash;
- immutable request snapshot summary;
- production targets;
- approval request status and link to approvals inbox/detail if available;
- policy decision summary when linked;
- execution binding and link to execution detail when available;
- submit-for-approval button only when status is `draft`;
- clear terminal status reason for `rejected`, `canceled`, `expired`, and `closed`.

The page must not show dispatch token or raw sensitive requested input values.

## 10. Audit and Security Considerations

### 10.1 Audit Object Types

Add `AuditEvent.ObjectType` values:

- `operation_profile`
- `change_record`
- `change_target`
- `change_execution_binding`

### 10.2 Required Audit Events

Emit at least:

| Event type | Object type | Trigger |
|---|---|---|
| `change.created` | `change_record` | Draft created. |
| `change.submitted` | `change_record` | Request snapshot frozen. |
| `change.approval_bound` | `change_record` | Approval request linked. |
| `change.policy_bound` | `change_record` | Policy evaluation linked. |
| `change.execution_binding_reserved` | `change_execution_binding` | Execution reservation and binding row created. |
| `change.execution_bound` | `change_execution_binding` | Runner proves dispatch token and binding is activated. |
| `change.status_changed` | `change_record` | Every lifecycle transition. |
| `operation_profile.created` | `operation_profile` | Profile created. |
| `operation_profile.updated` | `operation_profile` | Profile updated. |
| `operation_profile.deactivated` | `operation_profile` | Profile disabled. |

Metadata may include:

- change id;
- operation profile id/key;
- workflow id/version;
- target count;
- requested input hash;
- request snapshot hash;
- approval request id;
- policy evaluation id;
- execution id;
- previous status;
- new status;
- terminal reason;
- boolean flags such as `verification_required`.

Metadata must not include:

- `dispatch_token`;
- `dispatch_token_hash`;
- `claim_token`;
- raw `requested_inputs`;
- raw request snapshot;
- workflow snapshot;
- command text;
- secrets;
- artifact bytes;
- request body.

Extend audit metadata scrubbing to explicitly reject:

- `dispatch_token`
- `change_dispatch_token`
- `dispatch_token_hash`
- `requested_inputs`
- `request_snapshot`

### 10.3 Permissions

Recommended permissions:

- Organization viewers and above may read change detail.
- Organization operators, admins, and owners may create and submit changes.
- Only admins/owners should manage operation profiles unless product requirements explicitly allow operators.
- Runner bind endpoint accepts only `RunnerBearerTokenAuthentication`.
- User JWTs must be rejected on internal bind endpoint.
- Every public view must call `require_organization_id`.
- Every queryset must use `user_active_organization_scoped` or an equivalent selector.

### 10.4 Token Security

Dispatch token rules:

- Use at least 256 bits of random nonce material.
- Require `CHANGE_DISPATCH_TOKEN_SECRET` in production.
- Never store clear token.
- Regenerate clear token only for active dispatchable bindings when building the runner claim payload.
- Compare submitted tokens with `hmac.compare_digest`.
- Expire dispatch tokens after `OperationProfile.dispatch_ttl_seconds`.
- Do not include clear token in audit events, integration payloads, frontend APIs, exception messages, or logs.

### 10.5 Target Safety

Target validation must be strict:

- Environment must be exactly `production`.
- Target type must be profile-allowed.
- Identifier normalization must be deterministic.
- Duplicate targets must fail before database write where possible and still be protected by database uniqueness.
- Target metadata must be JSON object only and sanitized for secrets.

## 11. File-by-File Implementation Plan

### 11.1 Backend: Settings and Routing

- `apps/api/config/settings/base.py`
  - Add `apps.changes.apps.ChangesConfig` to `INSTALLED_APPS`.
  - Add `CHANGE_DISPATCH_TOKEN_SECRET`.
  - Add defaults for dispatch token TTL only if not profile-specific.
- `apps/api/config/api_v1_urls.py`
  - Include public changes URLs under `/api/v1/changes/`.
  - Include internal bind URL under existing `/api/v1/internal/changes/...`.

### 11.2 Backend: Changes App

- `apps/api/apps/changes/apps.py`
  - Standard app config.
- `apps/api/apps/changes/models.py`
  - Implement `OperationProfile`, `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`.
- `apps/api/apps/changes/admin.py`
  - Register read-optimized admin views.
  - Make submitted change request fields read-only.
  - Do not expose dispatch token hash as editable.
- `apps/api/apps/changes/services.py`
  - Implement lifecycle, hashing, token, target validation, profile enforcement, approval linkage, policy linkage, dispatch reservation, binding, and execution completion hooks.
- `apps/api/apps/changes/selectors.py`
  - Implement organization-scoped profile and change detail querysets with select/prefetch.
- `apps/api/apps/changes/serializers.py`
  - Public profile picker serializer.
  - Create/submit/detail serializers.
  - Internal bind request/response serializers.
- `apps/api/apps/changes/views.py`
  - Public create/detail/submit views.
  - Internal bind view with runner auth.
- `apps/api/apps/changes/urls.py`
  - Export public and internal URL patterns.

### 11.3 Backend: Approvals Integration

- `apps/api/apps/approvals/models.py`
  - Add bounded subject fields if change-level approval is implemented through `ApprovalRequest`.
  - Preserve all existing execution-step approval behavior.
- `apps/api/apps/approvals/services.py`
  - Add `create_change_approval_request`.
  - Call `changes.services.handle_change_approval_decision` when a change-subject approval resolves.
  - Keep timeout recovery compatible with change-subject approvals.
- `apps/api/apps/approvals/serializers.py`
  - Add optional subject fields to approval detail without breaking existing frontend expectations.
- `apps/api/apps/approvals/views.py`
  - No new public decision endpoint unless unavoidable.
  - Existing approval decision endpoint should continue to work for both step and change approval requests.

### 11.4 Backend: Policies Integration

- `apps/api/apps/policies/services.py`
  - After creating a `PolicyEvaluation`, call a changes hook only when the evaluation execution has a change binding.
  - Do not change rule evaluation ordering or outcomes.
- `apps/api/apps/policies/serializers.py`
  - No required public contract changes unless change detail reuses existing summary serializers.

### 11.5 Backend: Executions Integration

- `apps/api/apps/executions/services.py`
  - Add an explicit way for changes service to create an execution for a change-bound workflow.
  - Reject direct public execution creation for workflows bound to active operation profiles unless called by changes service.
  - After `complete_execution`, call `changes.services.handle_bound_execution_completed`.
- `apps/api/apps/executions/internal_serializers.py`
  - Add nullable change fields to `ClaimedExecutionSerializer`.
- `apps/api/apps/executions/internal_views.py`
  - Before claim, call `changes.services.promote_due_scheduled_changes`.
  - Ensure claim response includes change payload additions for reserved bindings.
- `apps/api/apps/executions/views.py`
  - Preserve public execution APIs.
  - Surface clear error when a profile-bound workflow must be run through changes.

### 11.6 Backend: Audit Integration

- `apps/api/apps/audit/models.py`
  - Add new object types.
- `apps/api/apps/audit/services.py`
  - Add dispatch token and requested input forbidden metadata keys.
- `apps/api/apps/audit/tests/`
  - Add tests that change metadata scrubbers reject sensitive keys.

### 11.7 Runner

- `apps/runner/runner/schemas.py`
  - Add claim payload fields and bind request/response models.
- `apps/runner/runner/client.py`
  - Add `bind_change_execution`.
- `apps/runner/runner/executor.py`
  - Bind change execution before the step loop.
  - Refuse to execute if bind fails.
- `apps/runner/runner/tests/`
  - Add tests for change payload parsing, bind success, bind failure, missing dispatch token, and no token logging.

### 11.8 Frontend

- `apps/web/src/features/changes/types.ts`
- `apps/web/src/features/changes/api/changesApi.ts`
- `apps/web/src/features/changes/hooks/useOperationProfiles.ts`
- `apps/web/src/features/changes/hooks/useCreateChange.ts`
- `apps/web/src/features/changes/hooks/useChangeDetail.ts`
- `apps/web/src/features/changes/hooks/useSubmitChange.ts`
- `apps/web/src/routes/changes/ChangeCreatePage.tsx`
- `apps/web/src/routes/changes/ChangeDetailPage.tsx`
- `apps/web/src/routes/changes/ChangeCreatePage.test.tsx`
- `apps/web/src/routes/changes/ChangeDetailPage.test.tsx`
- `apps/web/src/app/router.tsx`
  - Add routes.
- `apps/web/src/app/AppLayout.tsx`
  - Add navigation link.
- `apps/web/src/shared/lib/queryKeys.ts`
  - Add change keys.

## 12. Migration Plan

Recommended migration sequence:

1. Add `changes` app skeleton and register it.
2. Add approval subject fields in `approvals`:
   - nullable `subject_type`;
   - nullable `subject_id`;
   - data migration to backfill existing rows as `execution_step`;
   - alter fields to enforce non-null where possible;
   - make `execution` and `step` nullable only if the change-subject design requires it;
   - add check constraints.
3. Add audit object type migration for change objects.
4. Add `changes` initial migration:
   - `OperationProfile`;
   - `ChangeRecord`;
   - `ChangeTarget`;
   - `ChangeExecutionBinding`;
   - indexes and constraints.
5. Add any migration needed to support execution claim serialization if database fields are required. Prefer deriving claim fields from `ChangeExecutionBinding` rather than adding fields to `Execution`.
6. Add optional indexes after correctness is in place if query plans require them.

Migration safety rules:

- Existing `ApprovalRequest` rows must remain valid and readable.
- Existing executions must remain executable by the runner.
- Existing policy evaluations must remain immutable and readable.
- No migration should create organization-specific operation profiles. Profiles should be configured through admin, fixtures, or explicit management commands.
- Do not backfill change records from historical executions in Phase 11.1.

## 13. Testing Plan

### 13.1 Required Backend Tests

Add service and API tests for:

- invalid profile key rejected;
- inactive profile rejected;
- workflow not allowlisted by profile rejected;
- draft workflow rejected on submit;
- direct execution of active profile-bound workflow rejected outside changes service;
- non-production target rejected;
- duplicate targets rejected in serializer/service and by database uniqueness;
- post-submit mutation rejected for requested inputs;
- post-submit target mutation rejected;
- post-submit profile/workflow/schedule mutation rejected;
- submit freezes request snapshot;
- requested input hash deterministic regardless of JSON object key order;
- requested input hash changes when semantic value changes;
- approval request linked on submit;
- approval approval moves change to approved/scheduled/dispatchable;
- approval rejection moves change to rejected;
- approval timeout moves change to expired;
- dispatchable change creates exactly one execution reservation;
- one-to-one execution binding rejects a second execution for the same change;
- one-to-one execution binding rejects a second change for the same execution;
- bind endpoint validates dispatch token;
- bind endpoint validates requested input hash;
- bind endpoint validates operation profile key;
- bind endpoint validates runner ownership and claim token;
- bind endpoint is idempotent for same runner/execution/token;
- bind endpoint conflicts for different runner or execution after binding;
- policy evaluation linkage emits `change.policy_bound`;
- execution completion moves change to `verification_pending` or `closed`;
- audit event emission for create, submit, approval binding, policy binding, execution binding, and every state transition;
- audit metadata does not include clear dispatch token or raw requested inputs.

### 13.2 Runner Tests

Add runner tests for:

- claim response accepts nullable change fields for non-change executions;
- change-bound claim requires all four additions;
- runner calls bind before step-start;
- runner does not execute a step when bind fails;
- runner never logs dispatch token;
- requested input hash and operation profile key are sent unchanged to bind endpoint.

### 13.3 Frontend Tests

Add React tests for:

- operation profile picker loads profiles and workflows;
- workflow selection is constrained by selected profile;
- target environment is locked to production;
- duplicate target UI validation;
- create draft success navigates to detail or shows submit action;
- submit-for-approval action calls Django public API;
- change detail renders approval, policy, execution binding, and lifecycle status;
- browser API client still rejects `/api/v1/internal/...` calls.

### 13.4 Verification Commands

Expected verification after implementation:

- `make test-api`
- `make test-runner`
- `make test-web`
- `make lint`
- `make security-scan`
- `make hardening-check`

Run narrower tests during development, but the phase is not done until the relevant full gates pass.

## 14. Codex Implementation Batching Plan

Recommended implementation batches:

1. **Model and migration foundation**
   - Add changes app, models, audit object types, settings registration, migrations, admin registration, and model tests.
2. **Hashing, profile, target, and draft services**
   - Implement deterministic hashing, target normalization, profile allowlist enforcement, create API, selectors, serializers, and required validation tests.
3. **Submit and approval linkage**
   - Add bounded approval subject support, submit service, submit API, approval callback hook, immutability checks, and approval lifecycle tests.
4. **Dispatch reservation and execution binding**
   - Implement scheduled/dispatchable services, execution reservation, dispatch token handling, internal bind endpoint, one-to-one binding tests, and audit tests.
5. **Execution, policy, and completion hooks**
   - Add direct execution bypass guard, claim payload additions, policy linkage hook, completion hook, and integration tests with existing execution services.
6. **Runner support**
   - Add runner schemas, client bind method, executor pre-step bind call, and runner tests.
7. **Frontend support**
   - Add change feature API/hooks/types, profile picker, create/detail routes, navigation, query keys, and UI tests.
8. **Final hardening pass**
   - Run full verification, inspect audit metadata, inspect logs for token leakage, and update implementation status documentation if the repo uses one for Phase 11.1.

Do not combine all batches into one large change. The migration and approval-subject changes are the riskiest and should land with focused tests before runner/frontend work.

## 15. Definition of Done

Phase 11.1 is done when:

- `apps/api/apps/changes/` exists and is registered.
- `OperationProfile`, `ChangeRecord`, `ChangeTarget`, and `ChangeExecutionBinding` exist with migrations, constraints, indexes, admin registration, and tests.
- A draft change can be created only from an active operation profile and allowlisted published workflow.
- Non-production targets and duplicate targets are rejected.
- Submit freezes immutable request content and computes deterministic hashes.
- Post-submit request mutation is rejected.
- Submit links a change-level approval request.
- Approval decisions move change lifecycle state correctly.
- Scheduled changes can become dispatchable without a queue.
- Dispatchable changes reserve exactly one execution.
- Runner claim payload includes `change_record_id`, `dispatch_token`, `requested_inputs_sha256`, and `operation_profile_key` for change-bound executions.
- Runner binds the execution before executing any step.
- Internal bind endpoint validates runner ownership, claim token, dispatch token, requested input hash, operation profile key, and one-to-one binding.
- Existing non-change executions still run.
- Existing step approvals and policy evaluations still work.
- Policy evaluation linkage writes `change.policy_bound`.
- Execution completion updates change status.
- Audit events exist for create, submit, approval binding, policy binding, execution binding, and all state transitions.
- Audit metadata and logs do not expose dispatch tokens or raw requested inputs.
- React has an operation profile picker, change create page, change detail page, and submit-for-approval action.
- Frontend still calls only Django public APIs.
- Runner still calls only Django internal APIs.
- Required API, runner, web, lint, and security verification gates pass.

## 16. Risks and Drift Traps

- **Approval model drift:** Current approvals are step-scoped. Do not fake change approval with placeholder executions or steps. Add a narrow subject extension or stop and redesign explicitly.
- **Internal URL drift:** The requested internal endpoint label uses `/internal/v1/...`, while the repo uses `/api/v1/internal/...`. Preserve the repo route convention unless the whole API versioning scheme is intentionally changed.
- **Direct execution bypass:** If profile-bound production workflows can still be executed through `POST /api/v1/executions/`, the change lifecycle is not enforceable.
- **Mutable JSON fields:** JSONField content can be mutated accidentally in service code. Every mutation path must check status and use immutable snapshots after submit.
- **Hash nondeterminism:** Python dict order, datetime formatting, whitespace, or non-JSON values can cause hash drift. Centralize canonical hashing and test it directly.
- **Token storage mistake:** Storing clear dispatch tokens in the database, audit, logs, frontend responses, or integration payloads breaks the security model.
- **Binding race:** Runner retries and concurrent runners can race. Use `select_for_update()` and one-to-one constraints, and make same-token same-runner retries idempotent.
- **Policy overreach:** Do not build a second policy engine for changes. OperationProfile is the pre-dispatch allowlist; existing policies still evaluate execution steps.
- **Audit leakage:** Requested inputs can contain sensitive operational details. Audit only IDs, counts, statuses, and hashes.
- **Target laxness:** Accepting `prod`, `production-like`, `staging`, or blank environments weakens the phase. Phase 11.1 targets are production only.
- **Scheduler assumptions:** No queue exists. Scheduled release must be explicit Django service work invoked by internal claim path or management command.
- **Execution status confusion:** Do not add change-specific statuses to `Execution`. Change lifecycle status lives on `ChangeRecord`.
- **Frontend shortcut:** The React app must not call internal bind or runner endpoints. The shared API client already blocks `/api/v1/internal/`; keep that boundary.
- **Runner local authority:** The runner must not decide whether a profile, target, approval, or policy is valid. It only submits the bind proof and obeys Django responses.
- **Circular migrations:** If approvals add change-subject support and changes link approval requests, plan migration order carefully to avoid circular FK dependencies.
