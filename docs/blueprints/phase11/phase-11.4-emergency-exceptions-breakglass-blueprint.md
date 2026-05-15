# Phase 11.4: Emergency Exceptions and Breakglass Controls Blueprint

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 11.4 |
| Phase name | Emergency changes, exceptions, and breakglass controls |
| Objective | Add emergency change handling, narrow exception records, time-bounded platform breakglass sessions, and mandatory retroactive review while preserving the standard `ChangeRecord` lifecycle. |
| Status | Blueprint only - do not implement from this document without re-reading current source first |
| Depends on | Phases 11.1, 11.2, and 11.3 complete and verified; Phases 01-10.9 complete |
| Authored | 2026-05-01 |
| Primary app | `apps/api/apps/changes/` |

This document is an implementation blueprint only. It intentionally does not implement code.

## 2. Executive Summary

Phase 11.4 adds controlled emergency paths to the existing `ChangeRecord` aggregate. It does not create a parallel emergency execution system. Emergency changes are still `ChangeRecord` rows, still use operation profiles, still bind to exactly one execution, still flow through Django dispatch gates, and still require controlled closure.

The implementation adds three model families:

- `ChangeException`: a narrow, typed, auditable exception request attached to a change.
- `BreakglassSession`: a scoped, authenticated, time-bounded platform execution override attached to a change.
- `RetroReview`: a mandatory after-the-fact independent review for emergency exceptions and breakglass use.

The control intent is strict:

1. Emergency change creation uses the normal `ChangeRecord` create/submit/approval/dispatch lifecycle with emergency metadata, not a separate subsystem.
2. Exceptions are typed, scoped to a specific change, approved by someone other than the requester, and expire automatically.
3. Breakglass sessions require an authenticated actor, explicit scope, reason, fixed expiry, and a review due date.
4. The runner receives breakglass metadata only as factual scope and expiry data; it cannot grant itself permission or extend a session.
5. Django remains the authority for dispatch, step start, gated continuation, expiry enforcement, retro-review enforcement, and final closure.
6. The same actor cannot activate breakglass and complete the mandatory retro-review.
7. Final closure is blocked until all required retro-reviews are complete and accepted or explicitly marked with remediation/control-failure disposition.

This phase governs platform-level execution only. It must not implement host-level, cloud-level, SSH, IAM, Kubernetes, database-superuser, or infrastructure privilege escalation.

## 3. Current-State Inspection Checklist

The implementation must re-run this inspection after Phases 11.1-11.3 code exists. In this checkout, those phases are represented by blueprint files and `apps/api/apps/changes/` is not present yet.

- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` defines `OperationProfile`, `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`, normal change approval, execution binding, and the invariant that Django owns lifecycle transitions.
- [x] `docs/blueprints/phase-11.2-windows-freezes-target-locks-blueprint.md` defines `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`, window/freeze/lock preflight, and states that emergency breakglass belongs to Phase 11.4.
- [x] `docs/blueprints/phase-11.3-verification-closure-blueprint.md` defines `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`, controlled closure, and states that verification bypasses and emergency exceptions belong to Phase 11.4.
- [x] `apps/api/apps/changes/` is absent in this checkout. Implementation must build on the actual Phase 11.1-11.3 implementation, not only these documents.
- [x] `apps/api/apps/approvals/models.py` currently models step-scoped `ApprovalRequest` with required `execution` and `step`. Phase 11.1 is expected to add bounded change-level approval support; Phase 11.4 exception approvals must reuse that subject model or add a similarly bounded subject type.
- [x] `apps/api/apps/approvals/services.py` owns approval request creation, decision, timeout recovery, audit emission, and integration notifications. Exception approvals should integrate through service methods, not ad hoc status writes.
- [x] `apps/api/apps/authz/` is absent in this checkout. Authorization currently lives in `apps/api/apps/common/permissions.py` and organization membership roles.
- [x] `apps/api/apps/common/permissions.py` provides member, operator, admin/owner, and runner-only permission helpers. Breakglass activation should require at least organization operator and may require admin for policy overrides.
- [x] `apps/api/apps/audit/models.py` is append-only and currently lacks change, exception, breakglass, and retro-review object types.
- [x] `apps/api/apps/audit/services.py` scrubs sensitive metadata keys but should add explicit emergency/breakglass keys such as `scope_json`, `raw_scope`, `breakglass_token`, `override_payload`, and `privilege`.
- [x] `apps/api/config/api_v1_urls.py` registers public APIs under `/api/v1/` and runner-only endpoints under `/api/v1/internal/`.
- [x] `apps/runner/runner/schemas.py` allows extra fields on claimed execution responses and forbids extra fields on runner requests. Any optional heartbeat request extension must be deliberate and tested.
- [x] `apps/runner/runner/client.py` and `apps/runner/runner/executor.py` talk only to Django internal APIs. They must not receive credentials or locally decide breakglass authorization.
- [x] `apps/web/src/shared/api/client.ts` blocks browser calls to `/api/v1/internal/` and injects `X-Organization-Id`. React emergency UI must use public Django APIs only.
- [x] `apps/web/src/app/router.tsx` and `apps/web/src/app/AppLayout.tsx` currently have no changes route in this checkout. Phase 11.1-11.3 should have added change routes; Phase 11.4 must extend those actual routes.

Drift note: if any Phase 11.1-11.3 implementation differs from its blueprint, update this plan before coding.

## 4. Architecture Invariants

| Invariant | Phase 11.4 consequence |
|---|---|
| No separate emergency subsystem. | Emergency changes are normal `ChangeRecord` rows with emergency flags and child records. Do not add an `EmergencyExecution` aggregate or direct execution endpoint. |
| Django remains the control plane. | Exception state transitions, breakglass activation, expiry enforcement, step continuation, retro-review requirements, and closure blocking live in Django services. |
| No anonymous emergency execution. | All exception requests, approvals, breakglass activations, and retro-reviews require authenticated users with organization membership. |
| Breakglass is scoped and time-bounded. | `scope_json`, `started_at`, `expires_at`, and `review_due_at` are required; open-ended sessions are invalid at serializer, service, and database layers. |
| Runner cannot grant itself permissions. | Runner receives only scope and expiry facts and asks Django before each gated continuation. It never creates, extends, approves, or resolves breakglass sessions. |
| Same actor cannot self-review. | The user who activates breakglass cannot perform the mandatory retro-review for that session. The exception requester cannot approve their own exception. |
| Closure cannot bypass retro-review. | Final closure requires required retro-reviews to be submitted and dispositioned before `ChangeClosure` is created or `ChangeRecord` reaches `closed`. |
| Exceptions are narrow. | Each exception has a required type, reason, requested expiry, affected gate, and approval status. No generic "ignore all controls" exception exists. |
| Expiry is enforced synchronously. | Public and internal service calls resolve expired exceptions and breakglass sessions before evaluating dispatch, step start, heartbeat, or closure. |
| Audit remains append-only and sanitized. | Audit records contain IDs, statuses, timestamps, scope summaries, and hashes. They do not contain secrets, raw command payloads, tokens, or infrastructure credentials. |
| Platform-level only. | Do not implement host, cloud, SSH, IAM, database, Kubernetes, or network privilege elevation. This phase only governs platform dispatch and continuation gates. |

## 5. Data Model Design

All new models should live in `apps/api/apps/changes/models.py` unless the Phase 11 implementation has split change subdomains. Use the existing UUID `BaseModel` convention.

### 5.1 `ChangeException`

`ChangeException` records a narrow exception request and approval outcome for one `ChangeRecord`.

Required exception types:

- `freeze_override`
- `window_overrun`
- `late_verification`
- `policy_override`
- `missing_artifact`

Required statuses:

- `pending_approval`
- `approved`
- `rejected`
- `resolved`
- `expired`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | FK -> `ChangeRecord`, `related_name="exceptions"` | Parent aggregate. |
| `exception_type` | `CharField(32)` | One of the required exception types. |
| `status` | `CharField(32)` | One of the required statuses. |
| `reason` | `TextField` | Required operator justification; size-limited. |
| `scope_json` | `JSONField(default=dict)` | Typed scope describing the exact gate/check/target/artifact affected. |
| `requested_by` | FK -> `users.User`, nullable, `SET_NULL` | Authenticated requester. |
| `requested_at` | `DateTimeField` | Service timestamp. |
| `approval_request` | FK -> `approvals.ApprovalRequest`, nullable, `PROTECT` | Subject-specific approval request. |
| `approved_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor from approval decision, never same as `requested_by`. |
| `approved_at` | `DateTimeField(null=True, blank=True)` | Set on approval. |
| `rejected_at` | `DateTimeField(null=True, blank=True)` | Set on rejection. |
| `expires_at` | `DateTimeField` | Required for approvable exceptions. Must be after `requested_at`. |
| `resolved_at` | `DateTimeField(null=True, blank=True)` | Set when the underlying condition is repaired or the exception is consumed. |
| `resolution_note` | `TextField(blank=True)` | Bounded note; do not store secrets or raw logs. |
| `policy_evaluation` | FK -> `policies.PolicyEvaluation`, nullable, `PROTECT` | Required for `policy_override` when a policy decision is overridden. |
| `verification_check` | FK -> `VerificationCheck`, nullable, `PROTECT` | Required for `late_verification` and `missing_artifact` when applicable. |
| `artifact` | FK -> `artifacts.Artifact`, nullable, `PROTECT` | Optional reference for missing-artifact replacement evidence. |

Recommended constraints and indexes:

- check `exception_type` in the required values;
- check `status` in the required values;
- check `expires_at > requested_at`;
- index `(organization, status, expires_at)`;
- index `(change_record, exception_type, status)`;
- index `(approval_request)`;
- service invariant: `organization_id == change_record.organization_id`;
- service invariant: approved exceptions must have `approval_request`, `approved_by`, and `approved_at`;
- service invariant: rejected exceptions must have `approval_request` and `rejected_at`;
- service invariant: requester cannot approve their own exception.

Type-specific scope requirements:

| Exception type | Required scope keys | Effect |
|---|---|---|
| `freeze_override` | `freeze_rule_id`, `target_ids` | Allows a specific Phase 11.2 `allow_with_exception` freeze conflict to pass. It must not override `block` freeze rules. |
| `window_overrun` | `change_window_id`, `allowed_until` | Allows a running change to continue past the window end until the exception expiry, subject to breakglass/dispatch gates. |
| `late_verification` | `verification_plan_id`, `verification_check_ids`, `due_at` | Allows verification to remain pending past the normal due time but does not mark checks passed. |
| `policy_override` | `policy_evaluation_id`, `policy_rule_ids`, `overridden_outcome` | Allows a specific policy block or approval requirement to be overridden after approval. |
| `missing_artifact` | `verification_check_id`, `expected_artifact_kind`, `replacement_evidence` | Allows closure to proceed only with retro-review and explicit remediation/control-failure disposition. |

### 5.2 `BreakglassSession`

`BreakglassSession` records time-bounded platform-level emergency continuation authority for one change.

Recommended status values:

- `active`
- `ended`
- `expired`
- `revoked`

Required review status values:

- `pending`
- `submitted`
- `accepted`
- `overdue`
- `blocked`

Required fields from the prompt:

- `scope_json`
- `reason`
- `started_at`
- `expires_at`
- `ended_at`
- `review_due_at`
- `review_status`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | FK -> `ChangeRecord`, `related_name="breakglass_sessions"` | Parent aggregate. |
| `status` | `CharField(24)` | `active`, `ended`, `expired`, or `revoked`. |
| `scope_json` | `JSONField` | Required structured scope; never raw credentials. |
| `scope_sha256` | `CharField(64)` | Canonical hash for audit and runner payloads. |
| `reason` | `TextField` | Required emergency justification. |
| `activated_by` | FK -> `users.User`, nullable, `SET_NULL` | Authenticated activator. |
| `started_at` | `DateTimeField` | Service timestamp. |
| `expires_at` | `DateTimeField` | Required. Max TTL should be short and profile-configured. |
| `ended_at` | `DateTimeField(null=True, blank=True)` | Set on manual end, expiry, revocation, or execution terminal state. |
| `ended_by` | FK -> `users.User`, nullable, `SET_NULL` | Optional human actor for manual end/revoke. |
| `end_reason` | `CharField(64, blank=True)` | `manual_end`, `expired`, `execution_finished`, `revoked`, `closure_blocked`. |
| `review_due_at` | `DateTimeField` | Required and bounded, usually within 24 hours. |
| `review_status` | `CharField(24)` | Required review status. |
| `last_heartbeat_at` | `DateTimeField(null=True, blank=True)` | Optional internal heartbeat observation, not authority. |
| `activation_ip_hash` | `CharField(64, blank=True)` | Optional privacy-preserving source fingerprint if already collected. |
| `activation_user_agent` | `CharField(255, blank=True)` | Optional bounded user agent for audit context. |

Recommended constraints and indexes:

- check `status` in recommended status values;
- check `review_status` in required review statuses;
- check `expires_at > started_at`;
- check `review_due_at >= started_at`;
- partial unique constraint for one active breakglass session per change: unique `(change_record)` where `status = 'active'`;
- index `(organization, status, expires_at)`;
- index `(organization, review_status, review_due_at)`;
- index `(change_record, status)`;
- service invariant: `scope_json` must include at least `allowed_actions`, `target_ids`, and `gate_types`;
- service invariant: no open-ended session; `expires_at` is always required and max TTL is enforced;
- service invariant: `activated_by` cannot create the required `RetroReview`.

Breakglass scope examples:

```json
{
  "allowed_actions": ["dispatch", "continue_running"],
  "gate_types": ["window_overrun", "policy_override"],
  "target_ids": ["..."],
  "expires_at": "2026-05-01T20:00:00Z"
}
```

The scope is a platform authorization fact, not a credential bundle.

### 5.3 `RetroReview`

`RetroReview` records mandatory after-the-fact review for each breakglass session and selected severe exceptions.

Required dispositions:

- `accepted`
- `needs_remediation`
- `control_failure`

Recommended statuses:

- `pending`
- `submitted`
- `superseded`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | FK -> `ChangeRecord`, `related_name="retro_reviews"` | Parent aggregate. |
| `breakglass_session` | OneToOne -> `BreakglassSession`, nullable, `PROTECT` | Required for breakglass reviews. |
| `change_exception` | FK -> `ChangeException`, nullable, `PROTECT` | Optional exception being reviewed. |
| `status` | `CharField(24)` | `pending`, `submitted`, or `superseded`. |
| `disposition` | `CharField(32, blank=True)` | Required dispositions once submitted. |
| `reviewed_by` | FK -> `users.User`, nullable, `SET_NULL` | Authenticated independent reviewer. |
| `reviewed_at` | `DateTimeField(null=True, blank=True)` | Service timestamp. |
| `due_at` | `DateTimeField` | Copied from breakglass or exception SLA. |
| `summary` | `TextField` | Required when submitted; bounded. |
| `remediation_required` | `BooleanField(default=False)` | True for `needs_remediation` and usually `control_failure`. |
| `remediation_reference` | `CharField(255, blank=True)` | Ticket or follow-up reference. |
| `control_failure_category` | `CharField(64, blank=True)` | Required for `control_failure`. |
| `evidence_json` | `JSONField(default=dict)` | Sanitized references only, not raw logs or secrets. |

Recommended constraints and indexes:

- check `disposition` blank or in required dispositions;
- check submitted reviews have nonblank `disposition`;
- check at least one of `breakglass_session` or `change_exception` is present;
- unique `breakglass_session` where not null;
- index `(organization, status, due_at)`;
- index `(change_record, status)`;
- service invariant: reviewer cannot be `breakglass_session.activated_by`;
- service invariant: reviewer cannot be `change_exception.requested_by`;
- service invariant: reviewer must be an organization admin/owner for `policy_override`, `missing_artifact`, and `control_failure`.

### 5.4 ChangeRecord Emergency Fields

Add only bounded fields to `ChangeRecord`; do not fork the aggregate.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `is_emergency` | `BooleanField(default=False)` | Marks emergency-created changes. |
| `emergency_reason` | `TextField(blank=True)` | Required when `is_emergency=true`. |
| `emergency_declared_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor who created/submitted the emergency change. |
| `emergency_declared_at` | `DateTimeField(null=True, blank=True)` | Service timestamp. |
| `retro_review_required` | `BooleanField(default=False)` | True when emergency, exception, or breakglass rules require it. |
| `retro_review_due_at` | `DateTimeField(null=True, blank=True)` | Earliest outstanding retro-review due date. |
| `retro_review_blocking_status` | `CharField(32, blank=True)` | Empty, `pending`, `overdue`, or `control_failure`. |

Service rules:

- emergency changes still use existing statuses such as `draft`, `pending_approval`, `approved`, `dispatchable`, `running`, `verification_pending`, `verified`, and `closed`;
- emergency declaration cannot directly create an execution;
- emergency metadata is immutable after submit except through append-only exception/breakglass/review records;
- `retro_review_required` is derived by services from related records and should not be trusted from user input.

## 6. Emergency Lifecycle Design

Emergency creation must be a mode on the normal change create/submit flow.

Recommended lifecycle:

1. Operator starts a normal `ChangeRecord` through the Phase 11.1 create API with `is_emergency=true`, `emergency_reason`, operation profile, workflow, targets, requested inputs, and verification plan inputs.
2. Django validates the profile allows emergency use. Profiles should have explicit config such as `allow_emergency_changes`, `max_breakglass_seconds`, and `retro_review_sla_seconds`.
3. Submit freezes the same immutable request snapshot used by normal changes and includes sanitized emergency metadata in the snapshot hash.
4. Approval remains required unless the operation profile explicitly allows emergency dispatch with retro-review. Even then, the exception/breakglass records must be created and audited.
5. Dispatch still runs Phase 11.2 preflight. Failing gates may be addressed only by approved `ChangeException` records or active scoped `BreakglassSession` records.
6. Execution still binds through the normal `ChangeExecutionBinding`; no emergency execution binding type is introduced.
7. Verification still follows Phase 11.3. `late_verification` and `missing_artifact` exceptions do not mark checks passed; they create closure blockers and retro-review obligations.
8. Closure is denied until all mandatory retro-reviews are complete and the closure service records any remediation/control-failure outcomes.

Emergency changes should be highly visible in list/detail APIs and UI, but they must remain queryable as ordinary changes.

## 7. Exception Service Design

Add a dedicated service module or section, for example `apps/api/apps/changes/services/exceptions.py` if the Phase 11 implementation has service packages, otherwise functions in `services.py`.

Required service functions:

- `request_exception(change, actor, exception_type, reason, scope_json, expires_at) -> ChangeException`
- `approve_exception(change_exception, approval_decision, actor) -> ChangeException`
- `reject_exception(change_exception, approval_decision, actor) -> ChangeException`
- `resolve_exception(change_exception, actor, resolution_note) -> ChangeException`
- `expire_exceptions(change, now=None) -> list[ChangeException]`
- `find_applicable_exception(change, exception_type, scope) -> ChangeException | None`

Validation rules:

- requester must be an organization operator or stronger;
- `policy_override` and `missing_artifact` requests should require admin/owner approval;
- same actor cannot request and approve;
- `expires_at` is mandatory and capped by profile policy;
- scope must be type-specific and must reference objects belonging to the same change and organization;
- exceptions can be approved only from `pending_approval`;
- expired exceptions cannot satisfy dispatch, continuation, verification, or closure gates;
- resolved exceptions cannot be used for new gates after resolution;
- `freeze_override` applies only to Phase 11.2 `allow_with_exception` freeze behavior;
- `window_overrun` cannot authorize initial dispatch before the window opens;
- `late_verification` changes due dates and retro-review obligations but does not satisfy checks;
- `missing_artifact` permits closure only with explicit retro-review disposition and remediation/control-failure recording;
- `policy_override` must bind to a specific policy evaluation/rule outcome and be visible in audit.

Approval flow:

1. Public API creates `ChangeException(status=pending_approval)`.
2. Service creates or links a subject-specific `ApprovalRequest`.
3. Approval decision service callback or explicit change service method resolves the approval.
4. On approved decision, the exception moves to `approved` only if requester and approver differ.
5. On rejected decision, the exception moves to `rejected` and cannot be reused.
6. Expiry is resolved before every gate check by `expire_exceptions`.

If the Phase 11.1 approval-subject model exists, reuse it. If it does not, implement the minimal bounded approval subject support once, rather than adding exception-specific approval tables.

## 8. Breakglass Service Design

Add breakglass service methods owned by Django.

Required service functions:

- `activate_breakglass(change, actor, scope_json, reason, expires_at) -> BreakglassSession`
- `end_breakglass(session, actor=None, reason="manual_end") -> BreakglassSession`
- `expire_breakglass_sessions(change=None, now=None) -> list[BreakglassSession]`
- `assert_breakglass_allows(change, gate_type, action, target_ids, now=None) -> BreakglassSession`
- `record_breakglass_heartbeat(change, runner_id, claim_token, observed_session_id, now=None) -> BreakglassSession | None`
- `mark_breakglass_review_overdue(now=None) -> list[BreakglassSession]`

Activation flow:

1. Actor opens the change detail and requests activation through `POST /api/v1/changes/{id}/breakglass/activate/`.
2. Serializer requires `scope_json`, `reason`, and a requested duration or explicit `expires_at`.
3. Service locks the `ChangeRecord` with `select_for_update`.
4. Service expires any stale active session for the change.
5. Service validates actor membership, change status, profile emergency config, scope, target membership, and max TTL.
6. Service creates one active `BreakglassSession` and sets `ChangeRecord.retro_review_required=true`.
7. Service creates a pending `RetroReview` row with `due_at = review_due_at`.
8. Service emits audit events for activation and review requirement.

Expiry enforcement:

- before dispatch preflight, expire sessions whose `expires_at <= now`;
- before every internal step-start and approval-status continuation, expire sessions whose `expires_at <= now`;
- on runner heartbeat or optional breakglass heartbeat, record facts but do not extend expiry;
- on execution terminal state, end active session with `end_reason=execution_finished`;
- on expiry, set `status=expired`, `ended_at=now`, `review_status=pending` or `overdue` depending on due time;
- expired sessions cannot authorize any new continuation.

Scope enforcement:

- gate check must pass `gate_type`, `action`, and affected target IDs into the service;
- the service must compare canonical target IDs and action strings against `scope_json`;
- unknown actions or gate types fail closed;
- scope must never include shell commands, cloud roles, host names as credentials, SSH keys, IAM policies, kubeconfigs, or opaque privilege blobs;
- breakglass can allow Django to continue a platform operation past a control gate, but it cannot grant external privileges to the runner.

## 9. Retro-Review Service Design

Add service methods for review creation, submission, overdue detection, and closure gating.

Required service functions:

- `ensure_retro_review_for_breakglass(session) -> RetroReview`
- `ensure_retro_review_for_exception(change_exception) -> RetroReview | None`
- `submit_retro_review(review, actor, disposition, summary, evidence_json, remediation_reference="") -> RetroReview`
- `mark_overdue_retro_reviews(now=None) -> list[RetroReview]`
- `assert_retro_reviews_allow_closure(change) -> None`
- `summarize_retro_review_blockers(change) -> dict`

Mandatory review rules:

- every breakglass activation requires one retro-review;
- `policy_override` and `missing_artifact` exceptions require retro-review;
- `late_verification` requires retro-review if it is still unresolved at closure time or exceeded the configured due date;
- `freeze_override` and `window_overrun` require retro-review when the operation profile marks them severe or when breakglass was also active;
- same actor cannot activate breakglass and review it;
- same actor cannot request an exception and review/approve it;
- reviewers must be organization admin/owner for `control_failure`;
- final closure is blocked when any required review is pending, overdue, or structurally invalid.

Disposition effects:

| Disposition | Closure effect |
|---|---|
| `accepted` | Closure may proceed if all other verification and closure rules pass. |
| `needs_remediation` | Closure may proceed only with a nonblank remediation reference and closure outcome that records follow-up. |
| `control_failure` | Closure requires admin/owner reviewer and must mark the change as closed with control-failure metadata; dashboards should flag it as a violation. |

Overdue behavior:

- overdue review does not reopen execution;
- overdue review creates a violation banner and audit event;
- closure remains blocked;
- a later valid review can clear `review_status=overdue` to `submitted`, but the overdue audit event remains.

## 10. API Design

All public APIs require user JWT authentication, organization context, and organization membership. Browser calls must continue to use `apps/web/src/shared/api/client.ts`.

### 10.1 `POST /api/v1/changes/{id}/exceptions/`

Creates a typed exception request.

Request:

```json
{
  "exception_type": "freeze_override",
  "reason": "Emergency production incident mitigation.",
  "scope_json": {
    "freeze_rule_id": "...",
    "target_ids": ["..."]
  },
  "expires_at": "2026-05-01T20:00:00Z"
}
```

Response: `201 Created` with exception detail including `id`, `status`, `approval_request_id`, `expires_at`, and sanitized scope.

Errors:

- `400` invalid type, missing reason, malformed scope, open-ended expiry, max TTL exceeded;
- `403` actor lacks role;
- `404` change not in organization;
- `409` change state cannot accept the exception, duplicate active exception, or referenced object mismatch.

### 10.2 `GET /api/v1/changes/{id}/exceptions/`

Lists exceptions for the change. Include filters for `status`, `exception_type`, and `active=true`.

Response should include enough detail for the UI to show pending approval, approved expiry, resolved state, and closure blockers without exposing raw policy payloads or secrets.

### 10.3 `POST /api/v1/changes/{id}/breakglass/activate/`

Activates a scoped, time-bounded breakglass session.

Request:

```json
{
  "reason": "Service restoration requires immediate platform continuation.",
  "scope_json": {
    "allowed_actions": ["continue_running"],
    "gate_types": ["window_overrun"],
    "target_ids": ["..."]
  },
  "expires_at": "2026-05-01T19:45:00Z"
}
```

Response: `201 Created` with `id`, `status`, `scope_sha256`, `started_at`, `expires_at`, `review_due_at`, and `review_status`.

Errors:

- `400` missing scope, reason, expiry, or open-ended session;
- `403` actor lacks role or profile disallows breakglass;
- `409` active session already exists, invalid change status, scope outside change targets, or TTL exceeds profile cap.

### 10.4 `POST /api/v1/changes/{id}/retro-review/`

Submits a retro-review for a pending review item.

Request:

```json
{
  "retro_review_id": "...",
  "disposition": "needs_remediation",
  "summary": "Breakglass was justified, but monitoring delayed escalation.",
  "remediation_reference": "INC-12345",
  "evidence_json": {
    "incident_id": "INC-12345",
    "review_notes_reference": "..."
  }
}
```

Response: `200 OK` with submitted review detail and updated change retro-review summary.

Errors:

- `400` invalid disposition, missing summary, missing remediation reference, unsafe evidence;
- `403` reviewer lacks role or violates self-review rule;
- `404` review/change not found in organization;
- `409` review already submitted or change no longer accepts review.

### 10.5 Optional Internal API: `POST /internal/v1/changes/{id}/breakglass-heartbeat/`

The existing route convention is `/api/v1/internal/...`; implementation should either expose this as `/api/v1/internal/changes/{id}/breakglass-heartbeat/` or deliberately add an alias. Keep the browser block in `apiRequest` aligned with the chosen path.

Purpose:

- runner reports that it observed a breakglass session ID/scope hash while executing;
- Django records the observation and returns current authoritative status;
- heartbeat never extends expiry and never grants permission.

Request:

```json
{
  "runner_id": "runner-1",
  "claim_token": "...",
  "breakglass_session_id": "...",
  "scope_sha256": "...",
  "observed_at": "2026-05-01T19:30:00Z"
}
```

Response:

```json
{
  "status": "active",
  "expires_at": "2026-05-01T19:45:00Z",
  "server_time": "2026-05-01T19:30:05Z"
}
```

The endpoint requires runner bearer auth and must validate runner ownership through the bound execution before recording anything.

## 11. Runner Impact

Runner changes must be minimal and factual.

Claim payload additions:

- optional `change` object already introduced by Phase 11.1 should gain optional `breakglass` facts;
- include only `breakglass_session_id`, `scope_sha256`, `scope_json` or sanitized scope summary, `started_at`, `expires_at`, and `review_due_at`;
- do not include approval secrets, dispatch tokens, user emails beyond existing actor labels, or external credentials.

Execution behavior:

- runner continues to call Django before every step start;
- Django decides whether the step can run, must wait, or is blocked;
- if Django returns blocked because breakglass expired or scope does not match, runner stops/finishes according to existing failure semantics;
- runner may display/log a bounded message that a breakglass session is active and when it expires;
- runner must not alter local sandbox permissions, shell environment, SSH access, cloud identity, IAM roles, Kubernetes context, or host privileges based on breakglass metadata.

Optional heartbeat behavior:

- runner may call the internal breakglass heartbeat while a session is active;
- heartbeat failure should not itself grant or revoke permission; the next Django gate call remains authoritative;
- schema changes must keep `extra="forbid"` on runner request models and add explicit tests.

## 12. Frontend Impact

React should extend the Phase 11 change UI, not create a separate emergency console.

Required UI surfaces:

- emergency change entry point in the normal change creation flow, gated by role and operation profile;
- exception request form on change detail with type-specific fields and expiry selector;
- exception list/status panel with pending approval, approved countdown, expired/resolved/rejected states;
- breakglass activation modal requiring reason, scope, explicit duration/expiry, and confirmation;
- countdown/status display for active breakglass sessions using server timestamps from API responses;
- retro-review inbox showing pending and overdue review items across changes;
- change detail retro-review panel with disposition form;
- violation banner when breakglass review is overdue, self-review is blocked, missing-artifact exception exists, or control-failure disposition is recorded.

Recommended file additions, adjusted to the actual Phase 11.1-11.3 frontend structure:

```text
apps/web/src/features/changes/emergencyTypes.ts
apps/web/src/features/changes/emergencyApi.ts
apps/web/src/routes/changes/ChangeEmergencyCreatePage.tsx
apps/web/src/routes/changes/components/ExceptionRequestForm.tsx
apps/web/src/routes/changes/components/BreakglassActivationModal.tsx
apps/web/src/routes/changes/components/BreakglassStatusPanel.tsx
apps/web/src/routes/changes/components/RetroReviewPanel.tsx
apps/web/src/routes/changes/components/ViolationBanner.tsx
apps/web/src/routes/changes/RetroReviewInboxPage.tsx
```

UX requirements:

- never hide active/expired breakglass state behind tabs only;
- show expiry and review due timestamps in absolute time plus countdown;
- prevent submitting open-ended breakglass sessions in the client, but rely on server validation for authority;
- clearly show when the current user is ineligible to review because of self-review rules;
- never call `/api/v1/internal/` from the browser.

## 13. Audit and Security Events

Extend `AuditEvent.ObjectType` with:

- `change_exception`
- `breakglass_session`
- `retro_review`

Recommended event types:

- `change.emergency_declared`
- `change_exception.requested`
- `change_exception.approved`
- `change_exception.rejected`
- `change_exception.resolved`
- `change_exception.expired`
- `breakglass.activated`
- `breakglass.heartbeat_observed`
- `breakglass.ended`
- `breakglass.expired`
- `breakglass.revoked`
- `retro_review.required`
- `retro_review.submitted`
- `retro_review.overdue`
- `retro_review.self_review_rejected`
- `change.closure_blocked_retro_review`

Audit metadata rules:

- include IDs, statuses, exception type, scope hash, expiry timestamps, due timestamps, disposition, and boolean blocker summaries;
- do not include raw `scope_json` if it can contain sensitive target details; prefer `scope_sha256` plus safe counts and IDs;
- never include dispatch token, claim token, breakglass token, raw command, raw command output, request body, workflow snapshot, cloud account secrets, SSH material, or IAM policy documents;
- add explicit forbidden metadata keys for emergency and breakglass payloads in `apps/api/apps/audit/services.py`.

Security requirements:

- all state-changing public endpoints require authenticated user and org role checks;
- runner bearer auth is accepted only on internal endpoints;
- user JWTs must be rejected on runner-only endpoints;
- organization IDs must be checked against all referenced exception scope objects;
- use `transaction.atomic()` and `select_for_update()` around activation, expiry, approval resolution, and closure gating.

## 14. File-by-File Implementation Plan

Adjust paths to match the actual Phase 11 implementation.

Backend:

| File | Planned work |
|---|---|
| `apps/api/apps/changes/models.py` | Add `ChangeException`, `BreakglassSession`, `RetroReview`, emergency fields on `ChangeRecord`, enums, constraints, and indexes. |
| `apps/api/apps/changes/services.py` or service package | Add exception, breakglass, retro-review, expiry, and closure-gating service methods. |
| `apps/api/apps/changes/selectors.py` | Add querysets for change exceptions, active breakglass sessions, retro-review inbox, and violation summaries. |
| `apps/api/apps/changes/serializers.py` | Add request/response serializers for exception create/list, breakglass activation/status, retro-review submission, and optional internal heartbeat. |
| `apps/api/apps/changes/views.py` | Add public API views and wire them to services with organization role checks. |
| `apps/api/apps/changes/internal_views.py` | Add optional runner-only breakglass heartbeat endpoint if implemented. |
| `apps/api/apps/changes/urls.py` | Register public and internal URL patterns under the existing `/api/v1/` route convention. |
| `apps/api/apps/approvals/models.py` | If not already done by Phase 11.1, add bounded subject support for change exception approvals without breaking step approvals. |
| `apps/api/apps/approvals/services.py` | Add service integration for exception approval resolution and self-approval rejection. |
| `apps/api/apps/audit/models.py` | Add object types for exception, breakglass session, and retro-review. |
| `apps/api/apps/audit/services.py` | Add emergency/breakglass-sensitive metadata keys to the scrubber. |
| `apps/api/apps/executions/services.py` | Integrate breakglass expiry and scope checks at claim/step-start/continuation boundaries through change services. |
| `apps/api/apps/executions/internal_serializers.py` | Add optional sanitized breakglass facts to claimed execution payloads if Phase 11.1 change metadata exists there. |
| `apps/api/config/api_v1_urls.py` | Include new changes public/internal URL patterns. |
| `apps/api/apps/changes/admin.py` | Add read-focused admin registrations with no unsafe bulk state mutations. |

Runner:

| File | Planned work |
|---|---|
| `apps/runner/runner/schemas.py` | Add optional breakglass fact schemas and optional heartbeat request/response schemas if the internal heartbeat is implemented. |
| `apps/runner/runner/client.py` | Add optional internal heartbeat call; no permission decisions. |
| `apps/runner/runner/executor.py` | Surface active breakglass facts in bounded logs and continue to rely on Django gate responses. |
| `apps/runner/runner/tests/` | Add contract tests proving runner cannot self-grant and does not treat metadata as credentials. |

Frontend:

| File | Planned work |
|---|---|
| `apps/web/src/features/changes/types.ts` | Extend change types with emergency, exception, breakglass, retro-review, and violation summary shapes. |
| `apps/web/src/features/changes/api.ts` | Add public API client methods for required endpoints. |
| `apps/web/src/app/router.tsx` | Add retro-review inbox and emergency create/detail routes if not already present. |
| `apps/web/src/app/AppLayout.tsx` | Add navigation entry only if consistent with Phase 11 change navigation. |
| `apps/web/src/routes/changes/*` | Add emergency entry point, exception form, breakglass modal/status, retro-review inbox, and violation banner. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add stable query keys for exceptions, breakglass status, and retro-review inbox. |

Tests:

| File | Planned work |
|---|---|
| `apps/api/apps/changes/tests/test_emergency_lifecycle.py` | Emergency changes stay inside `ChangeRecord` aggregate. |
| `apps/api/apps/changes/tests/test_exceptions.py` | Exception request, approval, expiry, scope validation, and self-approval rejection. |
| `apps/api/apps/changes/tests/test_breakglass.py` | Activation, max TTL, no open-ended sessions, scope enforcement, expiry, and audit. |
| `apps/api/apps/changes/tests/test_retro_review.py` | Mandatory review, self-review rejection, overdue violations, and closure blocking. |
| `apps/api/apps/changes/tests/test_runner_breakglass_contract.py` | Runner metadata facts only and Django authority for gated continuation. |
| `apps/web/src/routes/changes/*.test.tsx` | UI forms, countdown/status, violation banner, and review inbox states. |

## 15. Migration Plan

Recommended migration sequence:

1. Add emergency fields to `ChangeRecord` with safe defaults: `is_emergency=false`, `retro_review_required=false`, blank nullable metadata.
2. Add `ChangeException` with enum checks, expiry check, indexes, and nullable optional FKs.
3. Add `BreakglassSession` with enum checks, expiry checks, review status checks, indexes, and partial unique active-session constraint.
4. Add `RetroReview` with disposition/status checks, indexes, unique breakglass review constraint, and cross-reference checks where feasible.
5. Add audit object type migration for `change_exception`, `breakglass_session`, and `retro_review`.
6. If necessary, add approval subject migration in approvals after confirming Phase 11.1 did not already do it.
7. Backfill existing changes as non-emergency with no required retro-review.
8. Deploy service code with expiry checks before exposing UI activation controls.

Migration safety:

- avoid non-null fields on existing large tables without defaults;
- create partial unique indexes concurrently if production migration policy requires it;
- do not backfill retro-reviews for historical changes unless a later compliance migration explicitly asks for it;
- data migration must not synthesize breakglass sessions.

## 16. Testing Plan

Required backend tests:

- emergency changes are created as normal `ChangeRecord` rows and bind to normal `ChangeExecutionBinding`;
- direct emergency execution outside `ChangeRecord` remains impossible;
- each exception type validates required scope keys;
- exception approval rejects self-approval;
- exception expiry is enforced before dispatch, continuation, verification, and closure checks;
- `freeze_override` does not override `block` freeze rules;
- `window_overrun` cannot authorize dispatch before a window opens;
- `late_verification` does not mark verification checks passed;
- `missing_artifact` blocks closure without retro-review disposition;
- `policy_override` binds to a specific policy evaluation and rule outcome;
- breakglass activation requires authenticated organization actor;
- breakglass cannot be open-ended;
- breakglass max TTL is enforced;
- only one active breakglass session can exist per change;
- breakglass scope enforcement rejects out-of-scope target/action/gate combinations;
- expired breakglass cannot authorize step start or gated continuation;
- optional heartbeat does not extend expiry;
- overdue retro-review creates violation state and audit event;
- same actor cannot activate breakglass and submit retro-review;
- final closure is blocked without required retro-review;
- closure with `needs_remediation` requires remediation reference;
- closure with `control_failure` requires admin/owner reviewer and surfaces violation metadata.

Required runner tests:

- claimed execution accepts optional breakglass facts;
- runner does not treat breakglass facts as credentials;
- runner continues to call Django step-start gates;
- runner handles Django blocked response after breakglass expiry;
- optional heartbeat request schema rejects extra fields.

Required frontend tests:

- emergency entry point sends normal change creation payload with emergency metadata;
- exception request form changes required fields by exception type;
- breakglass activation modal refuses empty reason, empty scope, and open-ended expiry;
- countdown/status display uses API timestamps and shows expired state;
- retro-review inbox lists pending and overdue reviews;
- violation banner renders for overdue review, missing artifact exception, and control failure;
- self-review rejection is displayed clearly from API errors.

## 17. Codex Implementation Batching Plan

Batch 1: Re-inspection and model foundation

- Re-read actual Phase 11.1-11.3 code.
- Confirm approval subject support and change closure implementation.
- Add models, constraints, migrations, admin read views, and model tests.

Batch 2: Exception services and APIs

- Implement exception request/list/approval-resolution/expiry services.
- Add public exception endpoints.
- Add audit events and tests.

Batch 3: Breakglass services and runner contract

- Implement activation, expiry, scope assertion, active-session uniqueness, and optional heartbeat.
- Add runner claim metadata and optional heartbeat schemas.
- Add service, API, and runner contract tests.

Batch 4: Retro-review and closure integration

- Implement retro-review creation/submission/overdue detection.
- Integrate closure blockers into Phase 11.3 closure service.
- Add self-review, overdue, and final-closure tests.

Batch 5: Frontend

- Add emergency UI entry point, exception form, breakglass modal/status, retro-review inbox, and violation banners.
- Add React tests and route/query-key integration.

Batch 6: Final audit and hardening

- Review audit metadata scrubber coverage.
- Run backend, runner, and web tests.
- Re-audit against architecture invariants and update docs if implementation details drifted.

## 18. Definition of Done

Phase 11.4 is done when:

- `ChangeException`, `BreakglassSession`, and `RetroReview` exist with required enum values, constraints, indexes, and tenant invariants.
- Emergency changes can be created only through the normal `ChangeRecord` aggregate.
- Exception request/list APIs exist and enforce approval, expiry, scope, and self-approval rules.
- Breakglass activation API exists and rejects anonymous, open-ended, over-TTL, duplicate-active, and out-of-scope sessions.
- Breakglass expiry is enforced by Django before dispatch and gated continuation.
- Runner receives only breakglass scope/expiry facts and cannot grant itself permission.
- Mandatory retro-review exists for breakglass and severe exceptions.
- Same actor cannot activate breakglass and perform mandatory retro-review.
- Final closure is blocked without required retro-review.
- Violation state is visible in API and React UI.
- Audit events are emitted for exception, breakglass, retro-review, expiry, overdue, and closure-blocked events.
- Tests cover all required scenarios listed in this blueprint.
- No host-level, cloud-level, SSH, IAM, database, Kubernetes, or infrastructure privilege escalation has been added.

## 19. Risks and Drift Traps

- Approval model drift: if Phase 11.1 added change-level approval differently than expected, do not add a second approval abstraction for exceptions. Extend the actual subject model carefully.
- Closure bypass risk: `late_verification` and `missing_artifact` exceptions must not silently convert failed/missing verification evidence into passed checks.
- Runner authority creep: any runner code that interprets breakglass as permission to skip Django step-start checks violates this phase.
- Scope ambiguity: unstructured scope makes breakglass too broad. Require typed actions, gates, targets, and expiry.
- Open-ended emergency state: every exception and breakglass session needs an expiry or resolution path.
- Self-review loopholes: compare stable user IDs, not labels or emails, and handle nullable historical actors conservatively.
- Freeze semantics confusion: `freeze_override` can satisfy only `allow_with_exception`; it must never override a hard `block` freeze rule.
- Policy override breadth: bind overrides to specific policy evaluations/rules, not all future policy checks on the change.
- Audit leakage: emergency reasons and scope may contain sensitive operational details. Keep metadata bounded and scrubbed.
- UI false authority: countdowns and disabled buttons improve UX but are not controls. Server services remain authoritative.
- Route drift: the prompt names `/internal/v1/...`, while the current app uses `/api/v1/internal/...`. Choose one deliberately and keep browser blocking/tests aligned.
- Infrastructure escalation temptation: do not add SSH, IAM, cloud role, host privilege, kubeconfig, or database-superuser flows under the name "breakglass".
