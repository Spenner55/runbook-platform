# Phase 11.1 Readiness Audit: Change Dossier, Operation Profiles, and Execution Binding

## 1. Executive Summary

**Verdict: NO-GO for Phase 11.2.**

Phase 11.1 is partially implemented and the happy-path test gates pass, but the implementation is not safe to build Phase 11.2 on top of yet. The main issue is not missing scaffolding; it is that the control-plane invariants are still bypassable. Active operation-profile workflows can still be executed directly, runner internal step endpoints can start change-bound executions without a successful bind, approval timeout paths can leave change state divergent from approval state, and submitted change content remains mutable through admin or direct ORM paths.

Verification performed during this audit:

- `make test-api`: **654 passed**, 1 teardown warning.
- `make test-runner`: **114 passed**.
- `make test-web`: **100 passed**.

Passing tests do not imply readiness. They currently miss several mandatory Phase 11.1 invariants.

Audit dimension results:

| Dimension | Result |
|---|---|
| Data model completeness | Partial: required models exist, but approval subject shape and post-submit immutability are underconstrained. |
| State machine correctness | Not ready: states exist, but transitions are direct writes and missing centralized enforcement/audit. |
| Immutability guarantees | Not ready: service guard exists, but admin/ORM paths can mutate submitted content. |
| Execution binding integrity | Not ready: 1:1 database links exist, but bind is not mandatory before step execution and retry idempotency is broken. |
| Approval + policy integration | Not ready: approval timeout divergence and swallowed policy-link failures remain. |
| Runner contract | Partial: payload fields exist and runner calls bind, but schema validation and server-side enforcement are incomplete. |
| API contracts | Partial: public/internal endpoints exist, but invalid high-risk execution states are not consistently rejected. |
| Audit trail coverage | Partial: core events exist, but all status transitions and operation profile events are not covered. |
| Frontend consistency | Partial: UI uses public APIs, but cannot represent the full dossier contract and approvals context. |
| Test coverage | Not ready: tests pass, but they miss core invariant and bypass cases. |

## 2. Critical Gaps

### C1. Direct execution bypass remains open

`apps/api/apps/executions/services.py:42` accepts `_from_change_service`, but that flag is never used. `apps/api/apps/executions/views.py:182` still calls `create_execution()` directly for public execution creation, and there is no check rejecting workflows bound to active `OperationProfile` rows.

Impact: a high-risk production workflow can bypass the change dossier, approval linkage, dispatch token, execution binding, and change audit trail entirely.

### C2. Runner can start a change-bound execution without binding

`apps/api/apps/executions/internal_views.py:96` and `apps/api/apps/executions/internal_views.py:150` allow step update and step start based only on runner ownership and claim token. `apps/api/apps/executions/services.py:686` then allows `pending -> running` without checking whether `execution.change_binding.bound_at` exists or whether the `ChangeRecord` is already `running`.

Impact: the internal bind endpoint is advisory rather than mandatory. A buggy or malicious runner with a valid claim can execute commands before proving possession of the dispatch token.

### C3. Change approval timeout can diverge from change lifecycle

`apps/api/apps/approvals/services.py:174` resolves expired approvals in `get_approval_status()`, but does not call the change hook for `subject_type="change_record"`. `apps/api/apps/approvals/services.py:370` has the same issue when a human decision races an expired approval: it marks the approval timed out and returns before calling `_handle_change_approval_decision()`.

Impact: `ApprovalRequest.status` can become `timed_out` while `ChangeRecord.status` stays `pending_approval`.

### C4. Submitted change request content is not truly immutable

The service helper exists at `apps/api/apps/changes/services.py:106`, but immutability is not enforced at the model/admin layer. `apps/api/apps/changes/admin.py:20` leaves `status`, `operation_profile`, `workflow`, `title`, `summary`, `justification`, `requested_inputs`, and `scheduled_for` editable. `ChangeTargetAdmin` also leaves target content editable after submit.

Impact: an auditor cannot trust submitted hashes or snapshots if privileged UI/ORM paths can mutate the underlying request fields afterward.

### C5. Bind endpoint idempotency is broken

`apps/api/apps/changes/services.py:682` rejects any status other than `dispatchable` before checking `binding.bound_at`. After a successful bind, the change is `running`, so an identical retry from the same runner cannot reach the idempotent branch at `apps/api/apps/changes/services.py:747`.

Impact: runner retries after a successful bind can fail with `change_not_dispatchable`, which violates the Phase 11.1 binding contract and can cause false execution failures.

### C6. Approval subject integrity is underconstrained

`apps/api/apps/approvals/models.py:73` only checks valid subject type values. It does not enforce that `execution_step` approvals have `execution_id` and `step_id`, or that `change_record` approvals have `subject_id` and no execution/step.

Impact: invalid mixed-subject approval rows can be persisted and later misrouted.

## 3. Drift From Blueprint

- Direct execution bypass guard is absent. The blueprint explicitly flags this as a drift trap; current code still permits it.
- State transitions are scattered direct assignments in `apps/api/apps/changes/services.py` rather than a central transition helper/table. This makes missing audit events and invalid transitions easier.
- `draft -> pending_approval` does not emit `change.status_changed`; submit emits `change.submitted` and `change.approval_bound` only.
- `OperationProfile` audit events (`operation_profile.created`, `.updated`, `.deactivated`) are not implemented.
- `ApprovalRequestSerializer` omits `subject_type` and `subject_id`, so change approvals are not first-class in the approvals API response.
- `allowed_target_types=[]` is treated as “allow any type” in `apps/api/apps/changes/services.py:251`; the blueprint says empty means no target types are valid.
- `requested_inputs_schema` is stored but not enforced.
- `dispatch_token_hash` is stored but not used during verification; verification regenerates and compares the clear deterministic token.
- `CHANGE_DISPATCH_TOKEN_SECRET` has an insecure default in `apps/api/config/settings/base.py:211`.
- Policy linkage failures are swallowed in `apps/api/apps/policies/services.py:684`, so a bound execution can proceed without `change.policy_bound`.

## 4. Hidden Risks

- Execution reservation is not self-contained in one obvious outer transaction. `make_dispatchable()` creates an execution, then creates a binding, then changes status. If this service is ever called outside an existing transaction, an unbound execution can remain after a later failure.
- Dispatch-token expiry is only checked during bind. There is no service that moves stale `dispatchable` changes to `expired` before claim or on a watchdog path.
- Claim payload generation returns a dispatch token whenever a binding exists; it does not check change status or token expiry before serializing at `apps/api/apps/executions/internal_serializers.py:74`.
- Runner schema treats a claim as change-bound when `change_record_id` is present, but does not require `dispatch_token`, `requested_inputs_sha256`, and `operation_profile_key` together. The executor relies on `assert` statements at `apps/runner/runner/executor.py:159`, which are not a robust contract.
- Admin profile management can attach workflows across organizations through the M2M widget; same-org membership is only a service invariant, not enforced in admin/model validation.
- Target metadata is accepted and stored without explicit secret-key scrubbing.

## 5. Missing Tests

Required tests before Phase 11.2:

- Direct public execution of an active operation-profile workflow is rejected.
- Change service can still create the execution for a profile-bound workflow.
- Step-start and step-update reject change-bound executions until `bind_execution` succeeds.
- Bind endpoint is idempotent for the same runner, execution, token, hash, and profile key after the first success.
- Expired change approval via `get_approval_status()` transitions the change to `expired`.
- Expired change approval via `decide_approval()` race transitions the change to `expired`.
- Approval model rejects invalid subject combinations at the database level.
- Submitted `ChangeRecord` and `ChangeTarget` content cannot be changed through admin/model validation.
- Empty `allowed_target_types` rejects every non-empty target.
- `requested_inputs_schema` is enforced.
- Dispatchable token expiry moves the change to `expired`.
- Policy linkage failure for a change-bound execution fails closed or blocks step start.
- Claim payload excludes dispatch token for expired/non-dispatchable bindings.
- Frontend create page covers requested inputs, summary, schedule, multiple targets, duplicate prevention, and target-type reset when profile changes.
- Change detail renders requested input hash, request snapshot hash, policy decision, verification status, and links to approval/execution detail.

## 6. Required Fixes

1. `apps/api/apps/executions/services.py`
   - Enforce the `_from_change_service` flag in `create_execution()`.
   - Reject `OperationProfile.objects.filter(is_active=True, allowed_workflows=workflow)` unless `_from_change_service=True`.
   - Add a helper that blocks step start/update for change-bound executions unless the binding is bound and the change is `running`.

2. `apps/api/apps/executions/views.py`
   - Preserve the public API, but surface a clear `409 workflow_requires_change_record` error when direct execution is blocked.

3. `apps/api/apps/executions/internal_views.py`
   - Call the change-bound execution guard before policy evaluation, before `request_step_approval()`, and before any `update_execution_step()` path.
   - Remove or hard-restrict direct `running` updates for change-bound executions through `/steps/{id}/update/`.

4. `apps/api/apps/changes/services.py`
   - Add a central transition helper that validates allowed transitions and emits `change.status_changed` exactly once per persisted transition.
   - Move bind idempotency before the status check so already-bound same-runner retries return success when the binding and execution match.
   - Wrap `make_dispatchable()` in an explicit outer `transaction.atomic()`.
   - Add dispatch expiry handling that transitions `dispatchable -> expired`.
   - Treat empty `allowed_target_types` as no allowed target types.
   - Enforce `requested_inputs_schema` and sanitize target metadata.

5. `apps/api/apps/approvals/models.py` and migration
   - Add the missing check constraint for approval subject shape:
     `execution_step` requires `execution_id`, `step_id`, and `subject_id=step_id`; `change_record` requires `subject_id` and null execution/step.

6. `apps/api/apps/approvals/services.py`
   - In every timeout path, call `_handle_change_approval_decision()` for `change_record` subjects inside the same transaction.
   - Emit or deliberately document the change-level `approval.requested` audit behavior.

7. `apps/api/apps/approvals/serializers.py`
   - Expose `subject_type` and `subject_id`.
   - Include enough change summary/link context for approvals UI and audit review.

8. `apps/api/apps/policies/services.py`
   - Do not swallow `change_services.link_policy_evaluation()` failures for change-bound executions. Fail closed before the step can run, or make the link atomic with policy evaluation.

9. `apps/api/apps/changes/admin.py`
   - Make submitted request fields read-only dynamically based on status.
   - Prevent status edits outside service transitions.
   - Prevent target edits/deletes when parent change is not `draft`.

10. `apps/api/config/settings/base.py`
    - Remove the insecure default for `CHANGE_DISPATCH_TOKEN_SECRET` in production settings and fail startup if missing.

11. `apps/runner/runner/schemas.py` and `apps/runner/runner/executor.py`
    - Add schema validation requiring all change fields together.
    - Replace `assert` checks with explicit fatal handling that reports execution failed without leaking token material.

12. `apps/web/src/routes/changes/`
    - Bring create/detail pages up to the Phase 11.1 contract, especially requested inputs, schedule, multiple targets, duplicate target prevention, hashes, policy decision, verification state, and approval/execution links.

## 7. Suggested Improvements

- Add a small `changes.transitions` module or table to make allowed transitions auditable and testable.
- Add a read-only changes list route instead of pointing the nav item directly at `/changes/new`.
- Add an admin action or management command to inspect stuck `pending_approval`, `scheduled`, and `dispatchable` changes.
- Add structured metrics for change transitions, bind failures by reason, dispatch expiry, and direct-execution bypass rejections.
- Consider a dedicated through model for `OperationProfile.allowed_workflows` if same-organization enforcement must be database-backed.

## 8. Final Readiness Verdict

**BLOCKED.**

Phase 11.1 has a substantial implementation foundation, and the current automated suites pass, but the required control-plane guarantees are not yet enforceable. Phase 11.2 should not start until the critical gaps above are fixed and covered by tests.
