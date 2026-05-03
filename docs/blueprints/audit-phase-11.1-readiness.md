# Phase 11.1 Readiness Audit: Change Dossier, Operation Profiles, and Execution Binding

## 1. Executive Summary

**GO / NO-GO for Phase 11.2: NO-GO.**

Phase 11.1 is substantially implemented, but it is not safe to build Phase 11.2 on top of the current controls. The required models, migrations, public change APIs, internal runner bind API, runner contract, approval subject extension, policy linkage, request hashing, target validation, audit object types, and frontend create/list/detail surfaces are present. The main happy path is covered by tests and the local verification gates pass.

The remaining gaps are control-plane safety gaps, not cosmetic issues. A runner with internal API access can still transition a step to `running` through the legacy step-update endpoint without going through the step-start policy gate. Approved changes also do not prove that the workflow definition executed at dispatch is the same definition that was approved. Several admin/model surfaces can mutate approval, policy, and execution binding fields after submit. Those are not acceptable foundations for Phase 11.2 controlled windows, target locks, or auditor-facing evidence.

Verification performed during this audit:

- `make test-api` passed: 985 tests, 1 database teardown warning.
- `make test-runner` passed: 122 tests.
- `make test-web` passed: 135 tests, with existing route-isolated React Router stderr warnings.
- `make check-migrations` passed: no model changes detected; migration check returned success.

Readiness by dimension:

| Dimension | Result |
|---|---|
| Data model completeness | Partial. Required models exist and `ChangeExecutionBinding` is structurally 1:1, but binding immutability and approval/policy linkage integrity are not fully protected outside service conventions. |
| State machine correctness | Partial. A central transition helper exists and current change services mostly use it, but model/admin/direct ORM paths can still bypass transition audit and validation. |
| Immutability guarantees | Partial. Submitted request fields and targets are checked in service paths, but workflow definitions and some binding/approval fields are not frozen strongly enough for production change control. |
| Execution binding integrity | Partial. Reservation and bind are mostly correct, but admin/model mutation and expiry-after-claim behavior leave weak operational invariants. |
| Approval + policy integration | Blocked. Change approval is linked before execution, but the legacy step-update path can bypass policy evaluation before command execution. |
| Runner contract | Mostly implemented. The runner receives `change_record_id`, dispatch token, input hash, and profile key; it avoids DB access and binds before its own step loop. Backend still accepts a bypass path. |
| API contracts | Mostly implemented. Create/list/detail/submit/profile-picker/bind exist. Detail output is missing some dossier fields expected by the blueprint. |
| Audit trail coverage | Partial. Core events exist, but admin/model changes to critical binding and linkage fields are not prevented or audited as lifecycle changes. |
| Frontend consistency | Mostly safe because Django remains authoritative. The UI can still present stale/unpublished allowlisted workflows and lacks some dossier detail. |
| Test coverage | Partial. The passing tests do not cover the most important bypass, workflow-definition drift, admin mutability, or divergence failure modes. |

## 2. Critical Gaps

### C1. Internal step update can bypass policy and approval gates

`apps/api/apps/executions/internal_views.py` exposes `ExecutionStepUpdateView`, and `apps/api/apps/executions/internal_serializers.py` still accepts `status="running"`. `apps/api/apps/executions/services.py` allows `pending -> running` and `waiting_for_approval -> running` in `_VALID_STEP_TRANSITIONS`.

That means a runner with internal API credentials can start a step through `/api/v1/internal/executions/{execution_id}/steps/{step_id}/update/` without `ExecutionStepStartView`, without policy evaluation, and without `change.policy_bound`. The first-party runner does the right thing, but the backend does not enforce the contract.

This must be fixed before Phase 11.2.

### C2. Approved changes do not freeze or verify workflow definitions

`ChangeRecord.request_snapshot` captures workflow id, name, version, and status, but not a deterministic hash of `workflow.definition`. `apps/api/apps/executions/services.py::create_execution()` snapshots the live `workflow.definition` at dispatch time. `apps/api/apps/workflows/admin.py` leaves workflow fields editable by default, including published workflow definitions.

An approved change can therefore execute a modified workflow definition under the same workflow id/version if the workflow row is changed after submit and before dispatch. That violates the core Phase 11.1 premise that the submitted dossier freezes what was approved.

This must be fixed before Phase 11.2.

### C3. Admin/model surfaces can mutate critical submitted-change bindings

`apps/api/apps/changes/admin.py` makes submitted request fields read-only, but it still leaves fields such as `approval_request`, `policy_evaluation`, `policy_decision_snapshot`, and `terminal_reason` editable on `ChangeRecord`. `ChangeExecutionBindingAdmin` leaves `change_record`, `execution`, `organization`, `operation_profile_key`, `requested_inputs_sha256`, and `bound_by_runner_id` editable.

`apps/api/apps/changes/models.py::ChangeExecutionBinding.save()` only blocks rebinding when `bound_by_runner_id` changes after `bound_at`; it does not freeze `bound_at`, binding links, token material, or hash/profile snapshots after creation.

For SOC2/ISO/NIST style evidence, these fields must be service-owned and effectively immutable through admin/model paths.

### C4. Change approval callback can allow approval/change divergence

`apps/api/apps/changes/services.py::handle_change_approval_decision()` logs and returns when no change is found for an approval request or when the change is not `pending_approval`. Because it is called inside `apps/api/apps/approvals/services.py::decide_approval()`, returning instead of raising can let an approval become terminal while the corresponding change does not transition.

The Phase 11.1 blueprint explicitly requires the approval and change state updates to be in the same transaction so they cannot diverge.

### C5. Execution completion can diverge from change completion

`apps/api/apps/executions/services.py::complete_execution()` commits the execution terminal status, then calls `changes.services.handle_bound_execution_completed()` and catches all exceptions. The watchdog and approval-timeout paths use the same catch-and-log pattern.

If the change completion hook fails unexpectedly, the execution can be terminal while the `ChangeRecord` remains `running`. Phase 11.2 should not build additional lifecycle controls on a hook that can silently diverge.

## 3. Drift From Blueprint

- The backend still supports direct step `running` transitions through the legacy update endpoint, contrary to the runner contract that Django step-start is the only pre-command policy gate.
- `request_snapshot` does not include a workflow definition hash, and workflow immutability is not enforced for published workflows.
- Change detail does not expose a sanitized request snapshot summary or `verified_at`, even though the blueprint calls for full dossier timestamps and immutable snapshot fields.
- The operation profile picker returns allowlisted workflows via plain prefetch and does not defensively filter to published same-organization workflows at serialization time.
- Operation profile allowed workflow tenant safety relies on services/signals; the implicit M2M table has no database-level organization invariant.
- Change approval request linkage is not database-unique on `ChangeRecord.approval_request`, and the FK does not prove `ApprovalRequest.subject_type="change_record"` / `subject_id=change.id`.
- State transition centralization is currently a code convention plus tests. The model/database do not prevent direct status writes that skip `change.status_changed` audit.
- Dispatch TTL and verification behavior are derived from the live `OperationProfile` row in some paths instead of an explicit frozen control snapshot.

## 4. Hidden Risks

- A compromised or stale runner can call the step-update endpoint to set a step `running` after bind and before any policy evaluation. This is the highest-risk bypass.
- A dispatch token that expires after claim but before claim serialization can expire the change while leaving the execution claimed; backend guards prevent command execution, but the execution can become operationally stranded.
- If `CHANGE_DISPATCH_TOKEN_SECRET` is rotated while changes are dispatchable, existing dispatch tokens cannot be regenerated or verified. Rotation behavior is undefined.
- Admin edits to workflow, change, approval, policy, and binding fields can create audit evidence that no longer matches lifecycle reality.
- Raw `requested_inputs` are stored on `ChangeRecord`; there is no profile-level sensitive-field redaction contract yet.
- `validate_request_integrity()` skips rows whose current status is `draft`, so a direct status rollback can disable integrity checks until another service rejects the invalid state.
- Operation profile changes after submit can either alter later behavior or cause integrity failure, depending on the field. The system needs an explicit frozen profile-control contract.

## 5. Missing Tests

Add tests before Phase 11.2 for:

- `POST /api/v1/internal/executions/{id}/steps/{step_id}/update/` rejecting `status="running"` for pending and waiting steps.
- Change-bound executions proving no policy evaluation means no step can become `running`.
- Published workflow `definition`, `name`, `version`, `runbook`, and `organization` mutation after change submit being rejected or detected before dispatch.
- Change dispatch refusing when the workflow definition hash no longer matches the submitted snapshot.
- `WorkflowAdmin` and `ChangeExecutionBindingAdmin` critical fields being read-only or change-disabled.
- `ChangeRecordAdmin` preventing edits to approval, policy, status, terminal reason, and snapshot-owned fields after submit.
- `handle_change_approval_decision()` rolling back the approval decision when the change is missing or in an invalid state.
- `complete_execution()` not leaving a bound change in `running` if the change completion hook fails.
- Operation profile picker excluding unpublished, archived, superseded, or cross-organization workflows.
- Change detail returning `verified_at` and a sanitized immutable snapshot summary.
- Dispatch expiry after claim canceling or otherwise terminally resolving the reserved execution.
- Static or unit checks that no production code assigns `ChangeRecord.status` outside `transition_change()` except initial creation.

## 6. Required Fixes

### Backend execution gate

- `apps/api/apps/executions/internal_serializers.py`
  - Remove `running` and `skipped` from `StepUpdateSerializer.status`; the update endpoint should accept terminal runner reports only.
- `apps/api/apps/executions/services.py`
  - Split step start from step update. Keep `pending/waiting_for_approval -> running` in a service callable only by `ExecutionStepStartView` and `ApprovalStatusView` after policy/approval checks.
  - Make ordinary `update_execution_step()` terminal-only: `running -> succeeded/failed`.
- `apps/api/apps/executions/internal_views.py`
  - Ensure `ExecutionStepUpdateView` cannot start a step. `ExecutionStepStartView` must remain the only internal route that can authorize command execution.
- `apps/runner/runner/schemas.py`, `apps/runner/runner/client.py`, and runner tests
  - Update the runner client contract so `update_step()` cannot send `running`.

### Workflow immutability and hashing

- `apps/api/apps/workflows/models.py` / `apps/api/apps/workflows/services.py`
  - Enforce immutability for published/superseded workflow definition fields, or provide an explicit service-only versioning path.
- `apps/api/apps/workflows/admin.py`
  - Make published workflow definition/version/identity fields read-only or disable admin edits for published/superseded workflows.
- `apps/api/apps/changes/models.py`
  - Add a `workflow_definition_sha256` snapshot field or include this hash in the immutable request snapshot with tests.
- `apps/api/apps/changes/services.py`
  - Compute the workflow definition hash at submit.
  - Verify it before approval dispatch, execution reservation, bind, and completion.
  - Ensure dispatch cannot create an execution from a workflow definition that differs from the approved hash.

### Change and binding immutability

- `apps/api/apps/changes/admin.py`
  - Make submitted `ChangeRecord` approval, policy, terminal, and actor linkage fields read-only.
  - Make `ChangeExecutionBinding` fully read-only after creation, or disable add/change/delete entirely.
  - Fix `OperationProfileAdmin.save_model()` deactivation so it persists the deactivation and emits `operation_profile.deactivated`.
- `apps/api/apps/changes/models.py`
  - Freeze `ChangeExecutionBinding.change_record`, `execution`, `organization`, `operation_profile_key`, `requested_inputs_sha256`, dispatch token fields, and `bound_at` after creation/bind.
  - Consider a non-null unique constraint on `ChangeRecord.approval_request` to prevent one approval request from being linked to multiple changes.

### Approval and completion consistency

- `apps/api/apps/changes/services.py`
  - Make `handle_change_approval_decision()` fail closed. Missing change linkage or invalid change state must raise inside the approval transaction.
  - Freeze profile controls that affect post-submit behavior, including dispatch TTL and verification requirement, or intentionally validate against immutable snapshot values.
- `apps/api/apps/executions/services.py`
  - Do not swallow `handle_bound_execution_completed()` failures for change-bound executions.
  - Prefer updating execution terminal status and change lifecycle in one transaction, or add a deterministic recovery path with tests and audit events.
- `apps/api/apps/changes/services.py`
  - When bind fails because of expiry after claim, cancel or terminally resolve the reserved execution as well as expiring the change.

### API and frontend consistency

- `apps/api/apps/changes/selectors.py` / `apps/api/apps/changes/serializers.py`
  - Return only active profile workflows that are published and same-organization.
  - Add sanitized request snapshot summary and `verified_at` to change detail.
- `apps/web/src/features/changes/` and `apps/web/src/routes/changes/`
  - Render the new sanitized snapshot fields.
  - Keep client validation advisory only; server rejection remains authoritative.

## 7. Suggested Improvements

- Add a management command to sweep expired dispatchable/claimed change executions and emit a compact audit summary.
- Add a CI/static check that rejects direct `ChangeRecord.status` writes outside `apps/api/apps/changes/transitions.py` and test setup.
- Add profile-schema support for sensitive requested input keys so API/detail/admin views can redact intentionally.
- Add direct links from change detail to the exact approval request and audit event list, not only the approvals inbox.
- Add a web test harness route wrapper to eliminate current React Router stderr noise.
- Run `make lint`, `make security-scan`, and `make hardening-check` after fixes; they were not run in this audit.

## 8. Final Readiness Verdict

**BLOCKED.**

Phase 11.1 is not safe to build Phase 11.2 on yet. The implementation is close in breadth and the normal path is well tested, but the remaining bypass and immutability gaps are fundamental control failures for high-risk production change management.

Minimum bar to move to **PROCEED WITH FIXES**:

1. Close the step-update policy bypass.
2. Freeze or verify workflow definitions for approved changes.
3. Lock down admin/model mutation of submitted changes and execution bindings.
4. Make approval and execution-completion hooks fail closed instead of allowing divergence.
5. Add the missing tests above and rerun `make test-api`, `make test-runner`, `make test-web`, and `make check-migrations`.
