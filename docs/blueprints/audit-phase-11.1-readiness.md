# Phase 11.1 Readiness Audit: Change Dossier, Operation Profiles, and Execution Binding

## 1. Executive Summary

**GO / NO-GO for Phase 11.2: NO-GO.**

Phase 11.1 is partially implemented, but it is not safe to build Phase 11.2 on top yet. The main objects, public APIs, runner bind flow, approval subject extension, policy linkage, and 1:1 execution binding exist. The happy path is covered and the current test suites pass.

The blocking issue is not absence of the feature; it is weakness of the invariants. The change lifecycle is not governed by a central state machine, post-submit immutability is not enforceable outside selected service/admin paths, dispatch expiry is incomplete on the runner claim path, stale runner ownership is not tied to the successful change bind, and operation profile governance is not audited or strongly tenant-constrained.

Verification performed during this audit:

- `make test-api` passed: 660 tests, 1 database teardown warning.
- `make test-web` passed: 100 tests.
- `make test-runner` passed: 114 tests.

Audit dimension results:

| Dimension | Result |
|---|---|
| Data model completeness | Partial. Required models exist; key org, immutability, timestamp, and profile/workflow tenant invariants are not database-enforced. |
| State machine correctness | Not ready. States exist, but transitions are direct field assignments across services, not centralized. |
| Immutability guarantees | Not ready. Submitted request content can still be mutated through direct ORM/DB paths, and frozen hash integrity is not revalidated before dispatch/bind. |
| Execution binding integrity | Partial. `ChangeExecutionBinding` is structurally 1:1, but stale runner and dispatch-expiry paths can break lifecycle integrity. |
| Approval + policy integration | Partial. Change approval and first policy linkage exist, but change-level approval request audit and service validation are incomplete. |
| Runner contract | Partial. Runner receives the required change fields and avoids DB access, but token/claim edge cases are unsafe. |
| API contracts | Partial. Required public and internal endpoints exist; invalid states are rejected on common paths, but the service layer can still be called into invalid transitions. |
| Audit trail coverage | Partial. Core change events exist; operation profile events and all lifecycle transitions are not fully covered. |
| Frontend consistency | Partial. UI cannot bypass backend validation, but it can submit stale/invalid target data and does not expose the full dossier contract. |
| Test coverage | Partial. Existing suites pass, but several SOC2/ISO/NIST-relevant invariants are untested. |

## 2. Critical Gaps

### C1. Change lifecycle transitions are not centralized or fully enforced

`apps/api/apps/changes/services.py` writes `change.status = ...` directly in submit, approval, scheduling, dispatch, bind, expiry, and completion paths. There is no transition table, no single transition helper, and no service-level guard for every status change.

`schedule_or_make_dispatchable()` is especially weak: when `scheduled_for` is in the future, it can move whatever object it receives to `scheduled` without first asserting the current state is `approved`.

Impact: Phase 11.2 would build on a lifecycle that cannot be proven complete or consistently audited. Direct service calls can persist invalid transitions.

### C2. Submitted change immutability is not strong enough

`assert_change_request_mutable()` exists, and admin blocks some edits, but there is no model-level validation, no database-level guard, no update service boundary, and no pre-dispatch integrity check comparing current request content to `requested_inputs_sha256` and `request_snapshot_sha256`.

The frozen snapshot is also incomplete. `build_request_snapshot()` omits `title`, `summary`, `justification`, target `metadata`, and any documented redacted representation of requested input values.

Impact: auditors cannot rely on the submitted dossier hash as proof of what was approved. Direct ORM/DB writes can mutate the approved request without failing dispatch or bind.

### C3. Runner bind readiness is not tied to the runner that successfully bound

`apps/api/apps/executions/internal_views.py` uses `_assert_change_bound_execution_ready()` before step start/update/complete, but the guard only checks `binding.bound_at is not None` and `change.status == running`.

If a stale already-bound execution is reclaimed by another runner, that new runner can own the execution claim while not being the runner that successfully bound the change. The bind endpoint rejects that second runner, but the internal execution endpoints can still pass the readiness guard after the execution has been claimed by the second runner.

Impact: a reclaimed or malicious runner can complete or potentially operate on a change-bound execution without its own successful change bind. That violates the runner contract.

### C4. Dispatch expiry is incomplete on the claim path

`bind_execution()` transitions `dispatchable -> expired` when an expired token is submitted, but expiration is not handled before or during `claim_next_execution()`.

`ClaimedExecutionSerializer.get_dispatch_token()` returns `None` for an expired binding while still returning `change_record_id`, `requested_inputs_sha256`, and `operation_profile_key`. The runner schema rejects partial change fields, so the runner can fail parsing the claim, leave the execution claimed, and never call bind. Watchdog recovery can then fail the execution while `handle_bound_execution_completed()` leaves the change in `dispatchable`.

Impact: expired dispatchable changes can strand executions and remain incorrectly active.

### C5. Dispatch token verification does not use the stored token hash as an integrity control

`ChangeExecutionBinding.dispatch_token_hash` is stored, but `verify_dispatch_token()` ignores it and compares the submitted token to a regenerated value. Tampering with the stored hash is not detected. Idempotent bind retries also do not check `dispatch_token_expires_at`.

The service fallback secret is `"insecure-change-me"` even though production settings require `CHANGE_DISPATCH_TOKEN_SECRET`. The runner models store `dispatch_token` as a plain `str`, so broad `repr()`, `model_dump()`, or error logging could expose it.

Impact: the stored hash gives a false impression of enforced integrity, token TTL semantics are ambiguous after bind, and accidental token disclosure risk remains.

### C6. Operation profile governance is not audit-ready

`OperationProfile` exists, but profile management is admin/direct-ORM driven. There is no service for create/update/deactivate, no `operation_profile.created`, `operation_profile.updated`, or `operation_profile.deactivated` audit event emission, and same-organization workflow allowlisting is not database-enforced.

`OperationProfileAdmin.save_related()` removes cross-organization workflows after save, but that is not a reliable control for API, shell, migration, or direct ORM paths. `executions.services.create_execution()` also checks active operation profiles without scoping the profile to `workflow.organization`, making corrupted cross-tenant allowlists capable of affecting execution behavior.

Impact: the allowlist that controls high-risk production execution can change without an authoritative audit trail or strong tenant integrity.

### C7. Requested input and target metadata validation is incomplete

`OperationProfile.requested_inputs_schema` is stored but not enforced in `create_change_record()` or `submit_change_record()`. Target `metadata` is accepted as arbitrary JSON and omitted from the submitted snapshot. Sensitive metadata keys are not rejected at the change input boundary.

Impact: invalid or sensitive operational data can enter the dossier, and the frozen snapshot does not fully describe the approved target state.

### C8. Change-level approval audit is incomplete

`approvals.services.create_change_approval_request()` creates the change-level `ApprovalRequest`, but it does not emit `approval.requested`, does not validate that the passed organization matches the change organization, and does not notify integrations for change-level approval requests.

`change.approval_bound` provides some evidence, but the approval subsystem itself lacks the same request audit coverage it has for step approvals.

Impact: approval evidence is split and weaker for change-level approvals than for existing step-level approvals.

## 3. Drift From Blueprint

- The required models exist: `OperationProfile`, `ChangeRecord`, `ChangeTarget`, and `ChangeExecutionBinding`.
- `ChangeExecutionBinding` is implemented with one-to-one fields on both `change_record` and `execution`, satisfying the structural 1:1 requirement.
- The approval subject extension exists, including the subject integrity check constraint.
- Public change endpoints exist for profile list, create, detail, and submit; the internal bind endpoint exists.
- Runner claim payload includes `change_record_id`, `dispatch_token`, `requested_inputs_sha256`, and `operation_profile_key`.
- Direct public execution of workflows allowlisted by an active operation profile is blocked, but the bypass check is not tenant-scoped to the workflow organization.
- Lifecycle transitions are not centralized despite the blueprint requiring Django services to be the only authority.
- Post-submit immutability is a helper convention, not an enforced model/database invariant.
- `request_snapshot` is not a complete immutable dossier snapshot.
- `dispatch_token_hash` is persisted but not used by verification.
- Dispatch expiry is handled only during bind, not before runner claim.
- Operation profile management audit events are missing.
- Audit metadata scrubbers silently drop forbidden keys instead of explicitly rejecting the newly forbidden metadata keys listed by the blueprint.
- Cancel, verify, and close actions are modeled as statuses but have no service/API implementation.
- The frontend has create/detail pages but no list page, incomplete create fields, and incomplete detail rendering.

## 4. Hidden Risks

- A stale change-bound execution can be reclaimed by a different runner. The new runner receives claim ownership, fails bind because `bound_by_runner_id` differs, then can still hit execution endpoints whose guard only checks that some bind happened previously.
- An expired dispatchable execution can be claimed with no dispatch token in the serialized response, causing runner schema validation failure before the bind endpoint has a chance to expire the change.
- Watchdog recovery of a claimed-but-never-bound expired dispatch can fail the execution while leaving the change `dispatchable`.
- `schedule_or_make_dispatchable()` can persist invalid transitions if called from future code without careful prechecks.
- Direct ORM updates can alter `requested_inputs`, `operation_profile`, `workflow`, `scheduled_for`, or `ChangeTarget` rows after submit without invalidating dispatch.
- Cross-organization `OperationProfile.allowed_workflows` rows can exist outside admin save paths and can distort both allowlist checks and direct execution bypass behavior.
- Changing `CHANGE_DISPATCH_TOKEN_SECRET` changes regenerated dispatch tokens while existing stored hashes are not the verification source of truth.
- Change approval timeout and approval decision hooks silently return if the change is not `pending_approval`, which may hide divergence instead of surfacing an operational error.

## 5. Missing Tests

Required tests before Phase 11.2:

- Central transition table tests for every allowed and forbidden `ChangeRecord` lifecycle transition.
- Direct service-call test proving `schedule_or_make_dispatchable()` cannot move `draft`, `pending_approval`, terminal, or already running changes to `scheduled`.
- Model/service tests proving submitted `ChangeRecord` request fields cannot be changed through full-clean/admin/service paths.
- Model/service tests proving submitted `ChangeTarget` rows cannot be added, changed, or deleted.
- Integrity tests proving dispatch refuses when current requested inputs, target rows, or request snapshot no longer match frozen hashes.
- Snapshot tests proving `title`, `summary`, `justification`, target metadata, schedule, profile/workflow snapshots, and approved input representation are covered.
- Claim-path expiry tests proving expired dispatchable changes transition to `expired` before any runner receives the execution.
- Runner schema/client tests proving partial change claim fields cannot strand a claimed execution.
- Stale reclaim tests proving a different runner cannot start, update, upload artifacts for, or complete a change-bound execution without a successful bind for that runner.
- Bind idempotency tests for expired tokens and tampered `dispatch_token_hash`.
- Cross-organization profile/workflow M2M tests outside admin paths.
- Direct execution bypass tests for same-org and corrupted cross-org operation profile data.
- `requested_inputs_schema` positive and negative validation tests.
- Target metadata secret-key rejection tests.
- `approval.requested` audit tests for change-level approvals.
- `operation_profile.created`, `operation_profile.updated`, and `operation_profile.deactivated` audit tests.
- Audit scrubber tests proving forbidden metadata keys are rejected if that remains the required behavior.
- Frontend tests for profile target-type reset, multiple targets, duplicate prevention, requested inputs, scheduling, hashes, policy decisions, and execution/approval links.

## 6. Required Fixes

1. `apps/api/apps/changes/services.py`
   - Add a central transition helper with an explicit allowed-transition table.
   - Route every persisted status change through that helper.
   - Make the helper emit exactly one `change.status_changed` event for every transition.
   - Add current-state assertions to `schedule_or_make_dispatchable()` and every lifecycle entry point.
   - Add a request integrity verifier used before approval dispatch, execution reservation, bind, and completion hooks.
   - Complete `request_snapshot` so it covers the full approved dossier.
   - Enforce `requested_inputs_schema` and target metadata validation at create and submit.
   - Change dispatch token verification to compare against the stored hash with constant-time comparison, or remove/redefine the hash field so it is not a false control.
   - Define and enforce post-bind token-expiry behavior.

2. `apps/api/apps/changes/models.py` and migrations
   - Add model validation for organization consistency across change, profile, workflow, target, binding, approval request, policy evaluation, and execution.
   - Add feasible timestamp/status consistency constraints.
   - Consider replacing `OperationProfile.allowed_workflows` with a through model that can enforce same-organization membership.
   - Add constraints or validation hooks that prevent submitted dossier mutation outside the approved service boundary.

3. `apps/api/apps/executions/internal_views.py`
   - Parse runner identity before the change-bound guard and require `binding.bound_by_runner_id == runner_id` for step start, step update, completion, approval polling, and artifact upload flows.
   - If runner reclaim is intended, define a safe rebind protocol instead of relying on the old bind.

4. `apps/api/apps/executions/services.py`
   - Expire or skip expired change-bound queued executions before `claim_next_execution()` returns them.
   - Scope the direct execution bypass check to `OperationProfile.organization == workflow.organization`.
   - Ensure watchdog recovery of unbound or expired change-bound executions moves the change to a terminal state consistently.

5. `apps/api/apps/executions/internal_serializers.py`
   - Never serialize partial change fields.
   - Return change claim metadata only when the binding is unexpired and eligible for the claiming runner.

6. `apps/api/apps/approvals/services.py`
   - Emit `approval.requested` for change-level approval requests.
   - Validate `organization_id == change_record.organization_id`.
   - Add tests for change approval request creation, timeout, and decision races.

7. `apps/api/apps/audit/services.py`
   - Align behavior with the blueprint requirement to explicitly reject forbidden sensitive metadata keys, or update the blueprint if silent scrubbing is the chosen control.
   - Add tests for nested forbidden keys and Phase 11.1-specific keys.

8. `apps/api/apps/changes/admin.py`
   - Treat admin controls as secondary defense only.
   - Add admin tests for same-org workflow allowlisting and submitted target immutability.
   - Move operation profile mutation through audited services rather than relying on `save_related()`.

9. `apps/runner/runner/schemas.py`, `apps/runner/runner/client.py`, and `apps/runner/runner/executor.py`
   - Treat `dispatch_token` as a secret value excluded from repr/dumps/logs by default.
   - Add explicit handling for partial or expired change claims that reports a safe terminal condition without depending on bind.
   - Ensure bind failure cannot be followed by execution completion unless Django records a consistent change terminal transition.

10. `apps/web/src/features/changes/` and `apps/web/src/routes/changes/`
    - Add requested inputs, summary, schedule, multiple production targets, duplicate target prevention, and profile-driven target-type reset.
    - Render requested input hash, request snapshot hash, policy decision, verification state, and links to approval/execution detail.
    - Add a changes list route or change navigation so operators are not sent only to `/changes/new`.

## 7. Suggested Improvements

- Add `apps/api/apps/changes/transitions.py` and test it independently.
- Add a management command that reports stuck `pending_approval`, `scheduled`, `dispatchable`, and `running` changes.
- Add an audit consistency command that recomputes submitted hashes and reports drift.
- Add metrics for change transition counts, bind failures by reason, dispatch expiry, direct-execution bypass rejections, and stale runner reclaims.
- Add a read-only admin/report view that joins change, approval, policy, execution, and audit evidence for audit sampling.
- Add a clear policy for secret rotation effects on outstanding dispatchable changes.

## 8. Final Readiness Verdict

**BLOCKED.**

Phase 11.1 is not fully implemented, not fully correct, and not yet safe as the foundation for Phase 11.2.

The implementation has a usable happy path and passing tests, but SOC2/ISO/NIST-grade readiness requires the critical gaps above to be fixed first. The minimum bar to move forward is: centralized state transitions, enforceable immutability/hash integrity, safe dispatch expiry before runner claim, runner bind ownership tied to current claims, audited operation profile governance, schema/metadata validation, and tests covering those invariants.
