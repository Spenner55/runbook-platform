# Phase 11.1 Readiness Audit: Change Dossier, Operation Profiles, and Execution Binding

## 1. Executive Summary

**GO / NO-GO for Phase 11.2: NO-GO.**

Phase 11.1 is broadly implemented and several earlier blockers have been addressed. The required `changes` app models exist, `ChangeExecutionBinding` is structurally one-to-one, change lifecycle transitions are centralized in `apps/api/apps/changes/transitions.py`, the legacy runner step-update policy bypass is closed, workflow definition hashes are captured in the submitted dossier, approval callbacks now fail closed, and the runner receives and uses the expected change binding payload before step execution.

That is not enough for Phase 11.2. The current workspace is still **blocked** by release-gate failures and by control-plane evidence risks that would not pass a SOC2/ISO/NIST-style review. The most important remaining issues are mutable admin/model paths for approval and execution evidence, incomplete binding immutability, a dispatch-expiry race that can strand claimed executions, and non-atomic execution/change completion semantics.

Verification performed:

| Command | Result |
|---|---|
| `make test-api` | Passed: 1002 tests. One database teardown warning remained. |
| `make test-runner` | Passed: 122 tests. |
| `make test-web` | Passed: 135 tests. Existing route-isolated React Router stderr warnings remained. |
| `make check-migrations` | Passed: no model changes detected and migrate check returned success. |
| `make lint` | Failed: 10 Ruff findings across changes/executions tests and `apps/api/apps/executions/internal_serializers.py`. |
| `make check-prod` | Failed: `CHANGE_DISPATCH_TOKEN_SECRET` is required by prod settings but not provided by the Makefile target. |

Readiness by dimension:

| Dimension | Result |
|---|---|
| Data model completeness | Partial. Models exist and binding is 1:1, but approval linkage and binding immutability are under-constrained. |
| State machine correctness | Partial. Change transitions are centralized in app code, but admin/model/direct ORM paths can still bypass key lifecycle semantics. |
| Immutability guarantees | Partial. Submitted request fields and targets are guarded, but approval/execution evidence and some binding/token fields remain mutable. |
| Execution binding integrity | Partial. Normal reservation and bind paths are sound, but expiry-after-claim and mutable token fields leave unsafe edge cases. |
| Approval + policy integration | Partial. Approval is captured before execution and policy linkage exists, but approval evidence can be mutated outside the service path. |
| Runner contract | Mostly implemented. Runner receives `change_record_id`, `dispatch_token`, input hash, and profile key, and avoids DB access. |
| API contracts | Partial. Core endpoints exist and reject invalid states, but detail/profile contracts drift from the blueprint. |
| Audit trail coverage | Partial. Lifecycle events are emitted on service paths, but critical admin/model mutations are not prevented or audited. |
| Frontend consistency | Partial. Server constraints are authoritative, but change query keys are not organization-scoped and can show stale org data. |
| Test coverage | Partial. Happy path and many invariants are covered, but release gates fail and the highest-risk residual paths lack tests. |

## 2. Critical Gaps

### C1. Release gates are not clean

Phase 11.2 should not build on a workspace that fails read-only hardening gates.

- `make lint` fails with Ruff import-order, unused import, unused variable, and E402 findings.
- `make check-prod` fails because `Makefile` does not provide `CHANGE_DISPATCH_TOKEN_SECRET` even though `apps/api/config/settings/prod.py` requires it.
- `apps/api/apps/changes/migrations/0002_add_workflow_definition_sha256.py` is currently untracked in `git status`; the model depends on this migration.

### C2. Approval and execution evidence can be mutated outside services

`apps/api/apps/approvals/admin.py` leaves `ApprovalRequest` and `ApprovalDecision` editable. `apps/api/apps/executions/admin.py` leaves `Execution` and `ExecutionStep` editable. Those admin paths can change statuses, timestamps, decision records, runner ownership fields, and execution evidence without calling the approval, policy, execution, or change services.

For Phase 11.2 this is a hard blocker. Windows, target locks, and evidence bundles cannot be trusted if an admin edit can create approval/execution states that never emitted the corresponding lifecycle event or change transition.

### C3. Change binding immutability is incomplete

`ChangeExecutionBinding` uses one-to-one fields for `change_record` and `execution`, which correctly enforces structural 1:1 binding. However `apps/api/apps/changes/models.py` only freezes a subset of fields after creation. Token and timing fields such as `dispatch_token_nonce`, `dispatch_token_hash`, `dispatch_token_expires_at`, `reserved_at`, and `runner_payload_snapshot` can still be changed through model saves.

`ChangeRecord.workflow_definition_sha256` is also not included in `ChangeRecord.IMMUTABLE_AFTER_SUBMIT`, so the separate evidence field can be edited even though the request snapshot hash catches workflow definition drift.

### C4. Dispatch expiry after claim can strand executions

The claim path handles dispatch expiry before claim in `apps/api/apps/executions/services.py`, but there is still a race after an execution is claimed and before `ClaimedExecutionSerializer` builds the response. In that case `apps/api/apps/executions/internal_serializers.py` can expire the change and return a claimed execution with null change fields.

The runner then treats the payload as non-change-bound, but backend guards reject step-start and completion because a binding still exists and is not confirmed. The execution can remain claimed, and the runner has still received the command payload for an expired change-bound execution.

### C5. Execution completion and change completion are not atomic or recoverable

`apps/api/apps/executions/services.py::complete_execution()` commits the execution terminal status first, then calls `changes.services.handle_bound_execution_completed()` after that transaction. The code now re-raises hook failures for change-bound executions, which is better than swallowing them, but the execution terminal state is already persisted. A retry will hit `invalid_state_transition` before the change hook can be retried.

Phase 11.2 should not rely on this. A transient error in the change completion hook can leave `Execution.status=succeeded|failed` while the `ChangeRecord` remains `running`.

### C6. Approval linkage is not database-tight

`ChangeRecord.approval_request` is a nullable FK, not a conditional unique relation, and there is no database-level guarantee that the linked `ApprovalRequest` has `subject_type="change_record"` and `subject_id=change.id`. The service path creates the right shape, but direct ORM/admin mutations can link the wrong approval or reuse one approval across multiple changes.

## 3. Drift From Blueprint

- `GET /api/v1/changes/operation-profiles/` uses `prefetch_related("allowed_workflows")` and does not defensively filter allowed workflows to published same-organization workflows at selector/serializer time.
- Change detail omits `verified_at`, `workflow_definition_sha256`, and a sanitized immutable request snapshot summary.
- Repeated submit on an already submitted change returns `409`; the blueprint allowed returning current detail for a persisted retry.
- Operation profile controls that affect later execution, especially `dispatch_ttl_seconds`, are read from the live profile row rather than a frozen submitted snapshot.
- Published workflow immutability is enforced in admin only; direct ORM/service mutation of published workflow definition fields is still possible, relying on later change integrity checks to fail closed.
- The claim serializer mutates change lifecycle state by expiring dispatchable changes. Lifecycle mutation in serialization is a drift from service-owned state transitions.
- Frontend query keys for operation profiles, changes list, and change detail are not scoped by active organization, contrary to the blueprint query-key design.

## 4. Hidden Risks

- `OperationProfileAdmin.save_model()` can fail to persist deactivation: it calls `deactivate_operation_profile()` with an already-mutated unsaved `obj` whose `is_active` is false, and that service returns early when `not profile.is_active`.
- Direct database updates can bypass `ChangeRecord.save()` and `ChangeTarget.save()` immutability checks. `validate_request_integrity()` catches many of these at approval/dispatch/bind/completion, but not continuously and not for every evidence field.
- A `CHANGE_DISPATCH_TOKEN_SECRET` rotation invalidates all outstanding dispatch tokens; there is no documented rotation or dual-secret strategy.
- Raw `requested_inputs` are stored in the database. They are not returned in change detail or audit metadata, but there is no profile-level sensitive key policy for the stored payload.
- Approval and execution admin edits can create audit trails that look complete while the corresponding state transition never happened.
- Cross-organization frontend cache bleed can display stale changes or operation profiles after active organization changes, even though the server still enforces organization scope on requests.
- `PolicyEvaluation` linkage records only the first policy evaluation. That matches Phase 11.1, but Phase 11.2 must be careful not to infer full multi-step policy coverage from a single linked row.

## 5. Missing Tests

Add tests before Phase 11.2 for:

- `make lint` clean output and `make check-prod` including `CHANGE_DISPATCH_TOKEN_SECRET`.
- `ApprovalRequestAdmin`, `ApprovalDecisionAdmin`, `ExecutionAdmin`, and `ExecutionStepAdmin` being read-only or restricted to audited service actions.
- `ApprovalRequest` and `ApprovalDecision` model/service immutability after terminal decision.
- `ChangeExecutionBinding` rejecting edits to token, expiry, reservation, binding, and runner payload fields after reservation/bind.
- `ChangeRecord.workflow_definition_sha256` immutability after submit and integrity comparison against `request_snapshot.workflow_snapshot.definition_sha256`.
- One approval request not being linkable to more than one `ChangeRecord`.
- `ChangeRecord.approval_request` rejecting a linked approval whose subject type/id does not match the change.
- Dispatch token expiry after claim but before serialization/bind canceling or terminally resolving the execution and returning no runnable payload.
- `complete_execution()` rolling back or recoverably retrying change lifecycle updates when `handle_bound_execution_completed()` fails after execution status is set.
- `OperationProfileAdmin` deactivation persisting `is_active=False` and emitting `operation_profile.deactivated`.
- Operation profile picker excluding unpublished, archived, superseded, and cross-organization workflows.
- Frontend change/profile query keys including active organization id and invalidating on org switch.
- Change detail rendering `verified_at`, workflow definition hash, and sanitized immutable snapshot summary.

## 6. Required Fixes

### Release gates

- `Makefile`
  - Add a non-placeholder `CHANGE_DISPATCH_TOKEN_SECRET` value to `check-prod`.
  - Re-run `make check-prod`.
- Ruff failures
  - Fix import ordering in:
    - `apps/api/apps/changes/tests/test_audit_integration.py`
    - `apps/api/apps/changes/tests/test_execution_binding.py`
    - `apps/api/apps/changes/tests/test_services.py`
    - `apps/api/apps/changes/tests/test_transitions.py`
  - Remove unused imports/variables in:
    - `apps/api/apps/changes/tests/test_execution_binding.py`
    - `apps/api/apps/changes/tests/test_transitions.py`
    - `apps/api/apps/executions/tests/test_services.py`
  - Move the `apps.executions.models` import above logger initialization in `apps/api/apps/executions/internal_serializers.py`.
- Git hygiene
  - Ensure `apps/api/apps/changes/migrations/0002_add_workflow_definition_sha256.py` is committed with the Phase 11.1 changes.

### Evidence immutability

- `apps/api/apps/approvals/admin.py`
  - Make `ApprovalRequest` and `ApprovalDecision` read-only after creation, or disable admin add/change/delete entirely.
- `apps/api/apps/approvals/models.py`
  - Add model-level immutability for terminal approval requests and all approval decisions.
- `apps/api/apps/executions/admin.py`
  - Make `Execution` and `ExecutionStep` read-only in admin, or expose only explicit audited service actions.
- `apps/api/apps/changes/models.py`
  - Add `workflow_definition_sha256` to post-submit immutable fields.
  - Freeze `ChangeExecutionBinding` token, expiry, reservation, and runner payload fields after creation, with a narrow internal allowance for the initial hash/payload fill.
  - Add a conditional uniqueness constraint for non-null `ChangeRecord.approval_request`.
  - Validate that linked approval requests have matching organization, `subject_type="change_record"`, and `subject_id=change.id`.
- `apps/api/apps/changes/admin.py`
  - Fix operation profile deactivation by loading the persisted profile or using a service that handles the desired target state rather than the already-mutated form instance.

### Dispatch and completion consistency

- `apps/api/apps/executions/services.py`
  - Move post-claim dispatch-expiry handling out of serialization and into an atomic service path.
  - Ensure an execution whose dispatch expires after claim is canceled or otherwise terminally resolved before any payload is returned to the runner.
  - Make execution terminal status and bound-change lifecycle update atomic, or add a deterministic recovery/retry service that can run after execution is already terminal.
- `apps/api/apps/executions/internal_serializers.py`
  - Remove lifecycle mutation side effects from `ClaimedExecutionSerializer`.
- `apps/runner/runner/executor.py`
  - On bind failure, do not assume `complete_execution()` is valid. Either call a dedicated backend failure endpoint for unbound change dispatches or rely on backend-side expiry/cancel handling.

### API and frontend contract

- `apps/api/apps/changes/selectors.py` and `apps/api/apps/changes/serializers.py`
  - Filter operation profile allowed workflows to active organization and `Workflow.Status.PUBLISHED`.
  - Add `verified_at`, `workflow_definition_sha256`, and sanitized snapshot summary fields to detail output.
- `apps/web/src/shared/lib/queryKeys.ts`
  - Change `operationProfiles`, `changes`, and `change` keys to include active organization id.
- `apps/web/src/features/changes/hooks/`
  - Use active organization id in query keys and invalidation.
- `apps/web/src/routes/changes/ChangeDetailPage.tsx`
  - Render the added dossier fields without exposing raw requested inputs or dispatch tokens.

## 7. Suggested Improvements

- Add a static check that flags production code assigning `ChangeRecord.status` outside `apps/api/apps/changes/transitions.py` and initial creation.
- Add a management command to sweep expired dispatch bindings and claimed-but-unbound executions, with audit output.
- Add profile schema support for sensitive requested input keys and redact or reject them at create/submit time.
- Add a controlled dispatch-token secret rotation plan before production use.
- Add direct links from change detail to approval detail and audit trail views.
- Clean up route-isolated React Router warnings in web tests so future route regressions are easier to spot.
- Run `make security-scan` and `make hardening-check` after the blocking release-gate failures are fixed.

## 8. Final Readiness Verdict

**BLOCKED.**

Phase 11.1 is close in feature breadth, and the normal service/runner path is well covered. It is not yet safe to build Phase 11.2 on top of it because the release gates are failing and critical evidence/control-plane invariants remain too weak.

Minimum bar to move to **PROCEED WITH FIXES**:

1. Make `make lint` and `make check-prod` pass.
2. Commit the workflow-definition hash migration.
3. Lock down approval, execution, change, and binding evidence against admin/model mutation.
4. Resolve the dispatch-expiry-after-claim race without returning a runnable payload.
5. Make execution completion and change completion atomic or recoverable.
6. Add the missing tests for these invariants and rerun `make test-api`, `make test-runner`, `make test-web`, `make check-migrations`, `make lint`, and `make check-prod`.
