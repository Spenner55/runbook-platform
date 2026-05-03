# Phase 11.1 Readiness Audit: Change Dossier, Operation Profiles, and Execution Binding

## 1. Executive Summary

**GO / NO-GO for Phase 11.2: NO-GO.**

Phase 11.1 has been materially remediated since the previous readiness audit. The core objects, public and internal APIs, runner bind flow, approval subject extension, policy linkage, one-to-one execution binding, operation profile audit events, dispatch expiry handling, dispatch token secret treatment, and runner ownership checks now exist with meaningful test coverage.

The remaining blockers are narrower but still foundational for Phase 11.2. Controlled windows, freeze rules, and target locks must not be built on top of a dossier whose live request fields or target rows can drift from the approved snapshot without detection. The frontend also exposes a changes list route that calls an API method the backend does not implement.

Verification performed during this audit:

- `make test-api` passed: 967 tests, 1 database teardown warning.
- `make test-runner` passed: 122 tests.
- `make test-web` passed: 135 tests, with existing React Router "No routes matched" stderr warnings in route-isolated tests.

Readiness dimension results:

| Dimension | Result |
|---|---|
| Data model completeness | Mostly ready. Required Phase 11.1 models exist; operation profile and binding constraints are present. Live target-row drift is still not covered by integrity verification. |
| State machine correctness | Ready for Phase 11.1. Central transition table and helper exist, and tests cover allowed and forbidden transitions. |
| Immutability guarantees | Partial. Instance-level model/admin/service guards exist, but bulk ORM/DB mutation of live request fields and target rows can still bypass detection. |
| Execution binding integrity | Mostly ready. One-to-one binding, token expiry, stored-hash verification, and runner ownership checks are covered. |
| Approval + policy integration | Mostly ready. Change-level approval request creation, audit, org validation, timeout/decision hooks, and first policy linkage exist. |
| Runner contract | Mostly ready. Runner treats dispatch tokens as secrets, rejects partial change payloads, binds before step execution, and backend guards step/update/complete/artifact paths. |
| API contracts | Partial. Create/detail/submit/bind exist, but frontend calls `GET /api/v1/changes/` and backend currently implements only `POST /api/v1/changes/`. |
| Audit trail coverage | Mostly ready. Core change events, operation profile governance events, approval events, and sensitive metadata rejection are covered. |
| Frontend consistency | Partial. Create/detail/list routes exist and expose the main dossier fields, but the list route is backed by a missing backend endpoint. |
| Test coverage | Partial. Most previously required tests exist; additional drift tests are required for live dossier and target-row integrity. |

## 2. Remaining Blockers

| ID | Blocker | Evidence | Required fix |
|---|---|---|---|
| B1 | Frozen dossier integrity does not prove live request fields still match what was approved. | `validate_request_integrity()` re-hashes `requested_inputs` and the stored `request_snapshot`, but it does not recompute current `title`, `summary`, `justification`, `scheduled_for`, `operation_profile`, `workflow`, or workflow/profile snapshots from live fields before dispatch, bind, or completion. Dispatch still uses live `workflow` and `operation_profile` rows. | Add a live submitted-dossier verifier that rebuilds the current submitted dossier from live `ChangeRecord` fields and compares it to the frozen `request_snapshot` / `request_snapshot_sha256`. Run it before approval dispatch, execution reservation, bind, and completion. |
| B2 | `ChangeTarget` rows are not integrity-checked after submit when bypassing instance methods. | `ChangeTarget.save()` and `delete()` block submitted changes, but bulk ORM/DB updates, inserts, or deletes can alter target rows. Current request integrity validation does not compare live ordered targets against the frozen target snapshot. Phase 11.2 target locks would trust those rows. | Extend the live dossier verifier to include ordered target count, positions, target type, identifiers, display name, environment, and metadata. Add tests for bulk target add/update/delete after submit. |
| B3 | Frontend/backend changes list contract is broken. | React calls `GET /api/v1/changes/`, but `ChangeRecordListCreateView` currently implements only `post()`. The web tests mock the endpoint and do not catch the missing backend `GET`. | Implement org-scoped `GET /api/v1/changes/` with API tests, or remove/disable the changes list UI and route until a backend list endpoint exists. |

## 3. Confirmed Remediations

These previous critical gaps appear remediated in the current checkout:

- Centralized lifecycle transition table exists in `apps/api/apps/changes/transitions.py`.
- Service lifecycle paths now route status changes through `transition_change()`.
- `schedule_or_make_dispatchable()` asserts the current state is `approved`.
- Submitted `ChangeRecord` instance saves reject documented request-field mutation.
- Submitted `ChangeTarget` instance saves/deletes reject mutation.
- Request hashes are checked in approval decision handling, dispatch reservation, bind, and completion paths.
- Dispatch expiry is handled before runner claim through `claim_next_execution()` integration.
- Claim serialization no longer returns partial change metadata for expired/ineligible bindings.
- Stored `dispatch_token_hash` participates in verification.
- Dispatch token secret fallback placeholders are rejected.
- Runner schemas use secret handling for dispatch tokens and reject partial change payloads.
- Runner readiness is tied to current successful bind ownership and current claim token.
- Operation profile create/update/deactivate audit events exist, including direct ORM signal coverage.
- Operation profile workflow allowlisting rejects cross-organization workflows through M2M validation.
- Direct execution bypass checks are scoped to `OperationProfile.organization == workflow.organization`.
- Change-level approval creation validates organization, emits `approval.requested`, and notifies integrations.
- Audit metadata rejects Phase 11.1 forbidden keys such as `dispatch_token`, `dispatch_token_hash`, `requested_inputs`, and `request_snapshot`.
- Frontend exposes create, detail, and list route surfaces for the Phase 11.1 dossier.

## 4. Required Tests Before Phase 11.2

Add or update tests for:

- Bulk `ChangeRecord.objects.filter(...).update(...)` drift for `operation_profile`, `workflow`, `title`, `summary`, `justification`, `scheduled_for`, `operation_profile_key_snapshot`, `workflow_version_snapshot`, and frozen hashes.
- Bulk `ChangeTarget.objects.filter(...).update(...)` drift after submit.
- Bulk `ChangeTarget.objects.create(...)` or through direct SQL/ORM insertion after submit where constraints allow it.
- Bulk `ChangeTarget.objects.filter(...).delete()` after submit.
- Approval decision refuses when live dossier fields or targets no longer match the approved snapshot.
- `make_dispatchable()` refuses when live dossier fields or targets no longer match the approved snapshot.
- `bind_execution()` refuses when live dossier fields or targets no longer match the approved snapshot.
- `handle_bound_execution_completed()` closes or fails safely when live dossier integrity no longer matches.
- `GET /api/v1/changes/` returns an organization-scoped list and rejects missing or mismatched org context, if the list UI remains.
- Web tests that fail if the changes list route points at a backend method that does not exist.

## 5. Residual Risks

- Operation profile tenant safety still relies on application services and Django signals. Direct writes to the implicit M2M through table can bypass that control unless the model is replaced with a through model that can enforce same-organization membership.
- Operation profile picker serialization should filter allowlisted workflows to published same-organization workflows for defense in depth.
- Dispatch-token secret rotation behavior for already dispatchable changes is still undefined.
- Cancel, verify, and close statuses exist but remain future lifecycle APIs.
- The test suite passes despite route-isolated React Router stderr warnings; these are not Phase 11.2 blockers, but they reduce test signal quality.

## 6. Minimum Fix Plan

1. Add a live dossier integrity helper in `apps/api/apps/changes/services.py`.
2. The helper must rebuild the submitted dossier from live fields and ordered target rows, excluding mutable database timestamps, and compare it against the stored `request_snapshot` and `request_snapshot_sha256`.
3. Call the helper before change approval dispatch, execution reservation, bind, and completion. Keep the existing stored-snapshot hash check.
4. Add focused drift tests for bulk ORM changes to every submitted request field and target-row mutation path.
5. Implement `GET /api/v1/changes/` or remove the frontend list route and navigation until it exists.
6. Re-run `make test-api`, `make test-runner`, and `make test-web`.

## 7. Final Readiness Verdict

**BLOCKED.**

Phase 11.1 is close, but Phase 11.2 should not start until live dossier integrity and target-row integrity are enforced. Phase 11.2 target locks and dispatch preflight checks depend on the current target set being the same target set that was approved. That is not yet proven.

Recommended first implementation prompt:

```text
Do not implement Phase 11.2 yet. First, close the remaining Phase 11.1 readiness blockers: add a live submitted-dossier integrity verifier that recomputes current ChangeRecord request fields plus ordered ChangeTarget rows and compares them to the frozen request_snapshot/request_snapshot_sha256 before approval decision, execution reservation, bind, and completion; add tests proving bulk ORM mutation of workflow/profile/title/summary/justification/scheduled_for and target add/update/delete is detected; implement or remove the broken GET /api/v1/changes/ frontend/backend contract. Run make test-api, make test-runner, and make test-web.
```
