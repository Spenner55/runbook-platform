# Phase 11.4 Completeness Audit

## 1. Executive summary

Phase 11.4 is **not complete**. The repository has substantial scaffolding for emergency changes, `ChangeException`, `BreakglassSession`, `RetroReview`, public APIs, runner schemas, and frontend UI, but the implementation does not yet make those records authoritative at the control gates they are supposed to govern.

The highest-risk gap is that approved exceptions are mostly inert: dispatch preflight still uses the older Phase 11.2 `freeze_exception_reference` string and does not consult approved `ChangeException` rows, while policy/window/verification/closure exception semantics are not implemented as gate behavior. Breakglass has the same problem in the opposite direction: activation, expiry, and scope assertion services exist, but `assert_breakglass_allows()` is not called from dispatch, step-start, approval-continuation, or policy-block paths. The runner receives factual metadata and continues to call Django gates, which is good, but Django does not yet apply the active breakglass session to those gates.

The model and migration foundation is directionally strong, and the audit scrubber includes most emergency-sensitive keys. The remaining work is primarily service-layer ownership, gate integration, approval callback integration, closure semantics, and coverage for end-to-end bypass attempts.

## 2. Overall readiness verdict

**NOT READY**

## 3. Completeness score

**58 / 100**

Rationale: model/API/UI scaffolding is present, migrations exist, admin is read-focused, Docker `manage.py check` passes, and runner metadata is factual. The score is held down by missing authoritative gate integration, incomplete approval lifecycle integration, weak type-specific scope validation, incomplete closure disposition handling, and gaps in end-to-end tests.

## 4. Blocking issues

| ID | Severity | Area | Finding | Evidence from repo | Required fix |
|---|---|---|---|---|---|
| B-01 | Critical | ChangeException behavior | Approved `ChangeException` rows do not satisfy dispatch gates. Freeze preflight still accepts only `ChangeRecord.freeze_exception_reference`; `find_applicable_exception()` is not used there. | `apps/api/apps/changes/services.py:4435-4441` checks `change.freeze_exception_reference`; `apps/api/apps/changes/services.py:5085-5107` defines `find_applicable_exception()` but no dispatch preflight caller uses it. | Replace string-reference dispatch bypass with scoped approved `ChangeException` lookup. Validate `freeze_rule_id`, `target_ids`, status, expiry, and `allow_with_exception`; hard `block` freezes must still fail. |
| B-02 | Critical | Breakglass behavior | Breakglass scope assertion is implemented but not integrated into dispatch or runner continuation gates. Active sessions therefore do not authorize intended gates, and scoped denial is not systematically enforced. | `apps/api/apps/changes/services.py:5420-5473` defines `assert_breakglass_allows()`. `apps/api/apps/executions/internal_views.py:230-331` evaluates policy and starts/fails steps without breakglass scope checks. | Call breakglass assertion from dispatch/preflight, step start, approval-status continuation, and any window/policy continuation gate with explicit `gate_type`, `action`, and target IDs. Unknown/out-of-scope values must fail closed. |
| B-03 | Critical | Exception approval lifecycle | Generic approval decisions for `CHANGE_EXCEPTION` do not update `ChangeException`. The public approvals API can mark the linked `ApprovalRequest` approved while the exception remains `pending_approval`; only the bespoke exception approve endpoint updates both. | `apps/api/apps/approvals/services.py:510-520` handles only `CHANGE_RECORD` after `decide_approval()`. `apps/api/apps/changes/services.py:4774-4786` creates a linked `CHANGE_EXCEPTION` approval request. | Add approval service callback/integration for `CHANGE_EXCEPTION` approvals and rejections, with self-approval checks and rollback on divergence. Prefer one approval path instead of parallel approval endpoints. |
| B-04 | High | Scope validation | Exception scopes only check required key presence; referenced objects are not consistently proven to belong to the same change and organization. | `apps/api/apps/changes/services.py:4662-4673` only checks missing keys. `apps/api/apps/changes/services.py:4676-4683` fetches `FreezeRule` by PK and returns on missing rule, despite comment claiming organization check elsewhere. | Add per-type scope validators for freeze rules, windows, verification plans/checks, artifacts, policy evaluations/rules, target IDs, and due timestamps. Reject missing/cross-org/cross-change references. |
| B-05 | High | Policy/window/verification exceptions | `policy_override`, `window_overrun`, `late_verification`, and `missing_artifact` have creation/approval scaffolding but no implemented control effects. | Required keys are listed at `apps/api/apps/changes/services.py:4633-4648`, but dispatch policy gate `apps/api/apps/changes/services.py:4360-4378`, window gate `apps/api/apps/changes/services.py:4360-4394`, and closure `apps/api/apps/changes/services.py:2558-2708` do not evaluate approved exception records. | Implement bounded gate behavior for each exception type: specific policy evaluation/rules only, window continuation only, late verification due-date extension without passing checks, and missing artifact closure only with retro-review disposition/remediation rules. |
| B-06 | High | Closure blockers | Non-success closure can close a `RUNNING` or `VERIFICATION_FAILED` change even with unmet verification checks, and `control_failure` accepted by retro-review is not specially required or recorded in closure outcome/metadata. | `apps/api/apps/changes/services.py:2624-2649` only enforces verification for `SUCCESS`; `apps/api/apps/changes/services.py:5861-5907` blocks pending reviews and missing remediation refs only, not control-failure closure handling. | Encode Phase 11.4 closure rules: missing-artifact and control-failure dispositions require explicit closure metadata/outcome, admin reviewer proof, and dashboard-visible violation data. Avoid letting non-success closure become a generic verification bypass. |
| B-07 | High | Role and self-approval controls | Severe exception approvals are allowed to any operator, and the approval inbox path has no exception self-approval guard. | `apps/api/apps/changes/views.py:1000-1004` uses `OPERATOR_ROLES` for all exception approvals. `apps/api/apps/approvals/services.py:420-520` has no `CHANGE_EXCEPTION` self-approval handling. | Require admin/owner approval for `policy_override` and `missing_artifact`; enforce requester != approver in the central approval service for all exception approval paths. |
| B-08 | High | Breakglass terminal handling | Active breakglass sessions are not ended on execution terminal state unless they expire or are manually ended. | `apps/api/apps/changes/services.py:3605-3695` updates change lifecycle after execution completion but does not call `end_breakglass(..., end_reason="execution_finished")`; `end_breakglass()` exists at `apps/api/apps/changes/services.py:5320-5361`. | End active sessions during execution completion, cancellation, watchdog failure, and closure with deterministic `end_reason` and audit events. |
| B-09 | Medium | Runner heartbeat | The optional breakglass heartbeat API/client exist, but executor never calls it, so `last_heartbeat_at` and `breakglass.heartbeat_observed` are effectively dead code in normal runner operation. | Runner logs breakglass facts at `apps/runner/runner/executor.py:85-94`; client method exists at `apps/runner/runner/client.py:419-450`; no executor call to `breakglass_heartbeat()` was found. | Either wire periodic/bounded heartbeat when `execution.breakglass` is present, or explicitly mark heartbeat out of scope and remove required DoD claims/tests for it. |

## 5. Non-blocking issues

| ID | Severity | Area | Finding | Evidence from repo | Required fix |
|---|---|---|---|---|---|
| N-01 | Medium | Audit taxonomy | Self-approval rejection for exceptions emits `retro_review.self_review_rejected`, which is semantically wrong for exception approval. | `apps/api/apps/changes/services.py:4815-4837` emits `retro_review.self_review_rejected` while rejecting exception self-approval. | Add/use `change_exception.self_approval_rejected` or similar event type. |
| N-02 | Medium | Audit metadata | Scrubber coverage is mostly good, but does not include every blueprint example key such as `raw_command`, `command_output`, `cloud_account`, `iam_policy_document`, or `kubeconfig` variants beyond exact `kubeconfig`. | `apps/api/apps/audit/services.py:18-64`. | Extend exact and recursive sensitive-key lists for emergency/breakglass payloads and add tests for nested metadata. |
| N-03 | Medium | Frontend profile gating | Emergency create UI shows all operation profiles; API rejects profiles that disallow emergency, but the UI is not profile-gated as required. | `OperationProfileSerializer` omits `allow_emergency_changes` in `apps/api/apps/changes/serializers.py:18-38`; emergency page maps all profiles in `apps/web/src/routes/changes/ChangeEmergencyCreatePage.tsx`. | Expose safe emergency capability metadata and filter/disable unsupported profiles client-side while keeping server enforcement. |
| N-04 | Medium | Browser internal boundary | Browser client blocks `/api/v1/internal/` but not `/internal/v1/`. No `/internal/v1` route is registered, so this is not exploitable today, but route drift is explicitly called out by the blueprint. | `apps/web/src/shared/api/client.ts:191-193`; route convention test rejects `/internal/v1/...` in `apps/api/apps/changes/tests/test_internal_verification_callback.py:143-153`. | Block both internal path families in the browser client, or document that `/internal/v1` is intentionally unsupported and covered by routing tests. |
| N-05 | Low | Runner payload | Claimed execution exposes only `scope_summary`, not `scope_json`. This is safer than the blueprint's optional sanitized scope, but it limits runner heartbeat verification to hash/session only. | `apps/api/apps/executions/internal_serializers.py:186-193`. | Keep as-is if intentional, and update documentation/tests to state the runner receives summary plus hash only. |
| N-06 | Low | Frontend validation | Exception and breakglass forms accept free-form comma-separated action/gate IDs, so malformed values reach the server often. Server authority is correct, but UX is weak. | `apps/web/src/routes/changes/components/ExceptionRequestForm.tsx` and `BreakglassActivationModal.tsx`. | Use controlled option sets and target selectors from actual change data where possible. |

## 6. Blueprint requirement coverage checklist

| Requirement | Status | Notes |
|---|---|---|
| Emergency changes remain normal `ChangeRecord` rows | Partial | `is_emergency` fields exist and create path supports them, but emergency-created changes do not automatically create the mandatory retro-review promised by UI copy. |
| `ChangeException` model, enums, constraints, indexes | Mostly met | Model/migration include required enum checks, expiry check, and indexes. Type-specific reference constraints remain service-only and incomplete. |
| Exception approval, expiry, scope, self-approval | Partial | Bespoke approval endpoint works for basic path; central approval integration and type-specific scope enforcement are incomplete. |
| `BreakglassSession` model, TTL, one-active constraint | Mostly met | Model and activation TTL exist. Scope assertion is not wired into control gates. |
| Runner receives factual breakglass metadata only | Mostly met | Runner receives session ID, hash, summary, and timestamps; no credential fields. |
| Runner cannot grant itself permission | Met at runner layer, partial overall | Runner keeps using step-start gates, but Django gates do not yet apply breakglass authorization semantics. |
| Breakglass expiry before dispatch/continuation | Partial | Expiry is called in several places, but active sessions are not checked for authorization at the gate being bypassed. |
| RetroReview model and submission | Partial | Model/API exist; severe exception coverage and admin/control-failure semantics are incomplete. |
| Same actor cannot activate/request and review | Partial | Service checks exist when actor is present; central approval and nullable historical actor handling need tightening. |
| Closure blocked until retro-reviews complete | Partial | Pending reviews block closure; control-failure and missing-artifact closure semantics are incomplete. |
| Audit object types and events | Partial | Object types and many events exist; taxonomy has naming gaps and not all required events are reachable. |
| Frontend emergency/exception/breakglass/retro UI | Partial | UI files exist and call public APIs only; role/profile gating and safe selectors need work. |
| Tests cover all required scenarios | Partial | Many unit/API tests exist, but core end-to-end gate-integration tests are missing. |

## 7. Security and audit-safety review

The audit scrubber includes important Phase 11.4 keys such as `breakglass_token`, `override_payload`, `privilege`, `raw_scope`, and `scope_json`, and model/admin choices avoid direct mutable admin state changes. That is a good foundation.

Security is not yet acceptable because exception and breakglass records are not the source of truth for the gates they are meant to override. A future engineer or UI user can see an approved exception or active breakglass session and assume it controls dispatch/continuation when it does not. Conversely, the old `freeze_exception_reference` string can still satisfy an `allow_with_exception` freeze rule without an approved `ChangeException`.

The central approval service does not route `CHANGE_EXCEPTION` decisions to change services, so approval state can diverge. Severe exception approval also needs admin/owner enforcement in the service layer, not only view-layer branches.

Audit event metadata generally avoids raw scope and tokens, but event taxonomy should distinguish exception self-approval from retro-review self-review. Add regression tests for nested forbidden metadata keys and all emergency event types.

## 8. Runner boundary review

The runner boundary is mostly sound. Runner schemas keep request models `extra="forbid"` and breakglass facts do not contain credential-like fields. The executor logs breakglass status and still calls Django step-start before running commands.

The gap is on the Django side: step-start and approval-continuation only enforce binding/expiry and policy outcome, not breakglass scope. The runner cannot self-grant, but Django also cannot yet use active breakglass as controlled authorization for a blocked gate. The optional heartbeat is implemented in client/API but not invoked by the executor.

## 9. Frontend boundary review

The change UI uses public `/api/v1/changes/...` APIs and tests assert no `/api/v1/internal/` calls. `apps/web/src/shared/api/client.ts` blocks `/api/v1/internal/` calls.

Remaining issues are frontend capability and safety, not internal route leakage: emergency profile filtering is absent because the public profile serializer does not expose emergency capability, breakglass scope input is raw text, and route-drift blocking does not cover `/internal/v1/`.

## 10. Test coverage gaps

- No end-to-end backend test proves an approved `freeze_override` `ChangeException` satisfies only a matching `allow_with_exception` freeze rule.
- No test proves `freeze_exception_reference` alone is insufficient after Phase 11.4.
- No test proves `policy_override` changes only the specific blocked policy evaluation/rules.
- No test proves `window_overrun` allows continuation but not initial dispatch before the window opens.
- No test proves `late_verification` extends due dates without marking checks passed and still creates closure blockers when unresolved.
- No test proves `missing_artifact` closure requires retro-review disposition and remediation/control-failure metadata.
- No test proves central `/api/v1/approvals/{id}/decide/` updates or rejects `CHANGE_EXCEPTION` approval requests.
- No test proves active breakglass is evaluated at dispatch, step-start, and approval-status continuation gates.
- No test proves breakglass is ended on execution terminal states.
- No test proves frontend hides/disables emergency creation for profiles that disallow emergency changes.

Verification attempted: local `python apps/api/manage.py check --settings=config.settings.test` failed because Django is not installed locally. Docker `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api python manage.py check` passed with no system-check issues.

## 11. Exact implementation fix plan

Batch 1: centralize exception approval ownership

- Add `CHANGE_EXCEPTION` handling to `apps/api/apps/approvals/services.py`.
- Move requester/approver self-check and severe-type admin/owner checks into `apps/api/apps/changes/services.py`.
- Update exception approve/reject views to delegate through the central approval path or make both paths share one service.
- Add tests for public approval inbox decisions and direct exception endpoints.

Batch 2: implement type-specific exception validators

- Add validators for every scope object and tenant/change relationship.
- Store or link resolved FK fields where applicable (`policy_evaluation`, `verification_check`, `artifact`).
- Reject duplicate active exceptions for the same gate scope.
- Add tests for cross-org/cross-change references.

Batch 3: wire exceptions into gates

- Replace `freeze_exception_reference` gate behavior with approved scoped `ChangeException`.
- Add policy override evaluation in policy gate code.
- Add window overrun and late verification services at the exact continuation/verification checks.
- Add missing-artifact closure handling with required retro-review disposition.

Batch 4: wire breakglass into Django authority points

- Call `assert_breakglass_allows()` from dispatch/preflight and runner step-start/approval-continuation paths where a gate can be bypassed.
- Pass canonical action/gate/target IDs into that service.
- End active sessions on execution terminal state and closure.
- Wire or remove optional heartbeat; if wired, call it from the executor while an active session exists.

Batch 5: close retro-review/control-failure gaps

- Enforce admin/owner reviewer for `control_failure` in service layer.
- Require remediation reference for `control_failure` if policy demands it, or record explicit violation metadata.
- Ensure closure summary includes retro-review dispositions and violation markers.

Batch 6: frontend hardening

- Expose safe profile emergency capability and gate emergency UI accordingly.
- Replace raw scope text fields with selectors where API data is available.
- Block `/internal/v1/` in `apiRequest`.
- Add tests for profile gating and server error display for self-review/self-approval.

Batch 7: final integration verification

- Add backend integration tests that run full change lifecycle with exception and breakglass gate behavior.
- Add runner tests with Django blocked/allowed responses after active and expired breakglass.
- Add web tests for all Phase 11.4 UI states and public-only API calls.

## 12. Recommended verification commands

```bash
git status --short
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api python manage.py check
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/changes/tests/test_exceptions.py apps/api/apps/changes/tests/test_breakglass.py apps/api/apps/changes/tests/test_retro_review.py -q
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/changes/tests/test_preflight_service.py apps/api/apps/changes/tests/test_execution_binding.py apps/api/apps/executions/tests/test_approval_runner_api.py -q
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/approvals/tests -q
docker compose exec runner pytest apps/runner/runner/tests/test_runner_breakglass_contract.py apps/runner/runner/tests/test_executor.py -q
docker compose exec web npm test -- --run apps/web/src/routes/changes apps/web/src/shared/api/client.test.ts
make lint
make check-migrations
```

## 13. Fix Implementation Summary

### Fixes completed

- Central `CHANGE_EXCEPTION` approval decisions now update linked `ChangeException` rows, enforce requester != approver, and require admin/owner approval for `policy_override` and `missing_artifact`.
- Exception scope validation now proves referenced freeze rules, windows, verification plans/checks, policy evaluations/rules, and target IDs belong to the same organization/change where applicable.
- Dispatch preflight now uses approved, non-expired `ChangeException` rows for freeze overrides and ignores legacy `freeze_exception_reference` as authority.
- Policy dispatch gates can be satisfied only by a matching approved `policy_override` exception or scoped active breakglass.
- Breakglass scope assertion is wired into dispatch/preflight policy/window gates and runner policy continuation paths; out-of-scope active sessions fail closed.
- Active breakglass sessions are ended on execution terminal handling and closure; the runner now reports a bounded breakglass heartbeat observation when a claimed change execution includes breakglass facts.
- Retro-review closure checks now include `control_failure` remediation/reference enforcement, admin/owner reviewer enforcement, and closure summary violation markers.
- Audit metadata scrubber now covers additional emergency-sensitive keys including raw command/output, cloud account, IAM policy document, and kubeconfig variants.
- Public operation profile API exposes `allow_emergency_changes`; emergency create UI filters unsupported profiles client-side while preserving server authority.
- Browser API client now blocks both `/api/v1/internal/` and `/internal/v1/` route families.
- Repository lint drift discovered during this work was corrected in Phase 11.4 files and runner test imports so `make lint` passes.

### Tests added/updated

- Updated backend exception tests to use real same-change/same-org scope objects and to cover central approval decisions, self-approval rejection, admin-only severe exception approval, and legacy freeze reference rejection.
- Updated preflight tests for approved scoped `freeze_override` behavior.
- Updated retro-review tests for admin-only control-failure handling and strict policy/freeze exception scopes.
- Added runner executor coverage for breakglass heartbeat observation.
- Added frontend tests for emergency profile filtering and `/internal/v1/` browser request blocking.

### Commands run

```bash
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api python manage.py check
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/changes/tests apps/approvals/tests apps/executions/tests/test_approval_runner_api.py -q
docker compose exec runner pytest runner/tests/test_runner_breakglass_contract.py runner/tests/test_executor.py -q
docker compose exec web npm test -- --run
docker compose exec web npm run build
make lint
make check-migrations
```

### Remaining risks

- Phase 11.4 is now functionally ready against the audited blocking items, but broader production rollout should still monitor real emergency flows for policy/window scope mismatches because exception and breakglass scopes are intentionally strict.
- Frontend breakglass and exception forms still use some free-form scope entry patterns; server-side authority rejects malformed scope, but selector-based UX remains a follow-up hardening improvement.
