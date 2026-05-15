# Phase 11.3: Verification Plans, Attestations, and Controlled Closure Blueprint

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 11.3 |
| Phase name | Verification plans, attestations, and controlled closure |
| Objective | Add first-class post-change verification plans, verification results, independent attestation, and controlled closure for `ChangeRecord`-backed production operations. |
| Status | Blueprint only - do not implement from this document without re-reading current source first |
| Depends on | Phase 11.1 and Phase 11.2 complete and verified; Phases 01-10.9 complete |
| Authored | 2026-05-01 |
| Primary app | `apps/api/apps/changes/` |

This document is an implementation blueprint only. It intentionally does not implement code.

## 2. Executive Summary

Phase 11.3 turns post-change verification into a controlled Django workflow instead of an informal note on a change. Every dispatchable production `ChangeRecord` must have a generated `VerificationPlan`. The plan contains required `VerificationCheck` rows derived from the selected `OperationProfile`, and verification can complete only when Django has accepted valid `VerificationResult` evidence for all required checks.

The implementation adds four model families:

- `VerificationPlan`: one generated plan for a change;
- `VerificationCheck`: expected automated, manual, artifact, API, or external-reference checks;
- `VerificationResult`: immutable submitted evidence for a check;
- `ChangeClosure`: immutable closure record for the final controlled close action.

This phase also adds a new `verification_failed` change state. The runner may report factual verification keys and artifact references, but it cannot mark a change verified, close a change, or satisfy checks with free text. Django remains the only authority that validates evidence, enforces independent reviewer rules, moves `running -> verification_pending -> verified`, and creates the final closure object.

Phase 11.3 does not implement emergency exceptions, verification bypasses, breakglass behavior, or sealed evidence bundles. Exception semantics belong to Phase 11.4. Sealed evidence bundle logic belongs to Phase 11.5.

## 3. Current-State Inspection Checklist

The implementation must re-run this inspection after Phase 11.1 and Phase 11.2 code exists. In this checkout, those phases are represented by blueprints, while `apps/api/apps/changes/` and `apps/web/src/features/changes/` are not present yet.

- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` defines `OperationProfile`, `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`, change approval linkage, runner binding, `verification_pending`, `verified`, and `closed`.
- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` requires successful executions on verification-required profiles to move to `verification_pending`.
- [x] `docs/blueprints/phase-11.2-windows-freezes-target-locks-blueprint.md` adds `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`, dispatch preflight, and internal runner timing callbacks.
- [x] Phase 11.2 says the runner reports timing facts only and does not evaluate windows, freezes, locks, policy, or authorization. Phase 11.3 must preserve that pattern for verification.
- [x] `apps/api/apps/artifacts/models.py` defines `Artifact` with organization, execution, optional step, kind, upload status, checksum, storage key, runner id, and metadata.
- [x] `apps/api/apps/artifacts/services.py` validates runner ownership, checksum shape, execution terminal status, quota, metadata size, MIME type, and storage writes.
- [x] `apps/api/apps/audit/models.py` defines append-only `AuditEvent` object types but this checkout does not yet include change, verification, or closure object types.
- [x] `apps/api/apps/audit/services.py` scrubs sensitive metadata keys and must be extended for verification evidence payloads, external references, assertion payloads, and attestation notes.
- [x] `apps/api/apps/executions/models.py` has execution statuses `queued`, `claimed`, `running`, `succeeded`, `failed`, and `cancelled`; Phase 11.3 must not add execution statuses.
- [x] `apps/api/apps/executions/internal_views.py` exposes runner-only endpoints under `/api/v1/internal/...`; the requested internal verification endpoint uses `/internal/v1/...`, so implementation must choose route strategy deliberately.
- [x] `apps/runner/runner/schemas.py`, `client.py`, and `executor.py` model claim, bind, heartbeat, step start/update, artifact upload, and completion behavior. Phase 11.3 runner changes must be limited to factual verification reporting.
- [x] `apps/web/src/shared/api/client.ts` blocks browser calls to `/api/v1/internal/` and injects `X-Organization-Id`. React verification UI must keep using public Django APIs only.

Drift note: if Phase 11.1 or Phase 11.2 implementation differs from their blueprints, update this blueprint before coding.

## 4. Architecture Invariants

| Invariant | Phase 11.3 consequence |
|---|---|
| Django is the control plane. | Verification plan generation, evidence validation, independent reviewer checks, state transitions, closure rules, and audit emission live in Django services. |
| AI cannot satisfy verification checks. | AI output may help draft operator text outside this workflow, but no AI actor, AI service, or AI-generated result can pass a verification check. |
| Free text alone cannot satisfy structured checks. | `artifact_presence`, `api_assertion`, `runner_step`, and configured `external_reference` checks require structured evidence fields. Notes are supplemental only. |
| Runner reports facts only. | Runner may report `verification_key`, result status, observed values, artifact IDs, and checksums. Django decides whether that satisfies a check. |
| Runner cannot close a change. | Closure is public API, human/user initiated, and evaluated in Django. No internal runner endpoint can create `ChangeClosure`. |
| Runner cannot mark verification final. | Internal results are provisional evidence. Django recomputes plan satisfaction and performs the `verification_pending -> verified` or `verification_failed` transition. |
| Closure cannot bypass verification. | `POST /api/v1/changes/{id}/close/` requires `verified` for successful closure unless Phase 11.4 exception records exist. Phase 11.3 does not add exceptions. |
| Verification plans exist before dispatch. | Dispatch/preflight must reject a change that does not have a generated active `VerificationPlan`. |
| Plan and result objects are append-friendly. | Checks can be evaluated repeatedly through immutable `VerificationResult` attempts. Do not overwrite historical evidence. |
| Closure is immutable. | `ChangeClosure` is create-once, append-only from the application perspective, and protected by model/service constraints. |
| Frontend uses public APIs only. | React calls `/api/v1/changes/{id}/verification-plan/`, `/api/v1/changes/{id}/verification-results/`, and `/api/v1/changes/{id}/close/`. |
| Internal APIs are runner-to-Django only. | Runner verification callbacks require runner bearer auth and ownership checks and must reject user JWTs. |
| No sealed evidence bundle logic. | Do not hash/package/sign the complete closure dossier in this phase. That belongs to Phase 11.5. |

## 5. Data Model Design

All new models should live in `apps/api/apps/changes/models.py` unless Phase 11.1 split the app differently. Use the existing UUID `BaseModel` convention.

### 5.1 `VerificationPlan`

`VerificationPlan` is the generated expected-verification contract for one `ChangeRecord`.

Required mode values:

- `automated`
- `manual`
- `mixed`

Recommended status values:

- `generated`
- `active`
- `satisfied`
- `failed`
- `canceled`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | OneToOne -> `ChangeRecord`, `related_name="verification_plan"` | One active verification plan per change in Phase 11.3. |
| `operation_profile` | FK -> `OperationProfile`, `on_delete=PROTECT` | Profile used for generation. |
| `mode` | `CharField(16)` | `automated`, `manual`, or `mixed`. |
| `status` | `CharField(24)` | Generated lifecycle value. |
| `generated_from_profile_snapshot` | `JSONField(default=dict)` | Sanitized profile verification config snapshot. |
| `generated_from_profile_sha256` | `CharField(64)` | Hash of the sanitized profile verification config. |
| `required_check_count` | `PositiveIntegerField(default=0)` | Denormalized count for UI and closure checks. |
| `optional_check_count` | `PositiveIntegerField(default=0)` | Optional checks do not block verification. |
| `satisfied_required_count` | `PositiveIntegerField(default=0)` | Recomputed by service after accepted results. |
| `failed_required_count` | `PositiveIntegerField(default=0)` | Recomputed by service after accepted failed results. |
| `generated_at` | `DateTimeField` | Set by generation service. |
| `activated_at` | `DateTimeField(null=True, blank=True)` | Set before dispatch or when execution starts. |
| `satisfied_at` | `DateTimeField(null=True, blank=True)` | Set when all required checks pass. |
| `failed_at` | `DateTimeField(null=True, blank=True)` | Set when a required check fails terminally. |

Recommended constraints and indexes:

- unique `change_record`;
- check `mode` in the required values;
- check `status` in the recommended values;
- index `(organization, status, generated_at)`;
- index `(operation_profile, status)`;
- service invariant: `organization_id == change_record.organization_id == operation_profile.organization_id`.

Do not store raw requested inputs, raw command output, raw API responses, or clear runner tokens in the plan snapshot.

### 5.2 `VerificationCheck`

`VerificationCheck` is one expected verification item in a plan.

Required check types:

- `runner_step`
- `artifact_presence`
- `manual_attestation`
- `api_assertion`
- `external_reference`

Recommended check status values:

- `pending`
- `passed`
- `failed`
- `not_applicable`

`not_applicable` should be reserved for optional checks or checks generated from profile rules that no longer apply because target/profile conditions exclude them. It must not be used as an exception bypass for required checks in this phase.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `plan` | FK -> `VerificationPlan`, `related_name="checks"` | Parent plan. |
| `change_record` | FK -> `ChangeRecord`, `related_name="verification_checks"` | Denormalized for selectors. |
| `position` | `PositiveIntegerField` | Stable display/evaluation order. |
| `key` | `SlugField` or `CharField(128)` | Stable generated check key, unique in plan. |
| `name` | `CharField(255)` | Operator-facing label. |
| `description` | `TextField(blank=True)` | Optional context. |
| `check_type` | `CharField(32)` | One of the required check types. |
| `required` | `BooleanField(default=True)` | Required checks block verification and closure. |
| `status` | `CharField(24)` | Current derived status. |
| `verification_key` | `CharField(128, blank=True)` | Expected key emitted by runner step/artifact or submitted result. |
| `source_step_key` | `CharField(128, blank=True)` | Expected execution step key for `runner_step` checks. |
| `artifact_kind` | `CharField(32, blank=True)` | Optional expected artifact kind. |
| `artifact_name_pattern` | `CharField(255, blank=True)` | Optional exact name or anchored safe pattern. |
| `expected_checksum_sha256` | `CharField(64, blank=True)` | Optional checksum pin. |
| `api_assertion` | `JSONField(default=dict)` | Sanitized assertion config, never credentials. |
| `external_reference_config` | `JSONField(default=dict)` | Sanitized URL/ticket rules, never secret tokens. |
| `manual_attestation_config` | `JSONField(default=dict)` | Required role/reviewer/statement configuration. |
| `last_result` | FK -> `VerificationResult`, nullable, `SET_NULL` | Last accepted result. Define after model exists or add in a second migration. |
| `satisfied_at` | `DateTimeField(null=True, blank=True)` | Set when status first becomes `passed`. |
| `failed_at` | `DateTimeField(null=True, blank=True)` | Set when status first becomes `failed`. |

Recommended constraints and indexes:

- unique `(plan, key)`;
- unique `(plan, position)`;
- check `check_type` in the required values;
- check `status` in the recommended values;
- index `(organization, check_type, status)`;
- index `(change_record, required, status)`;
- service invariant: artifact-specific fields are used only for `artifact_presence`;
- service invariant: API assertion config is used only for `api_assertion`;
- service invariant: manual attestation config is used only for `manual_attestation`.

### 5.3 `VerificationResult`

`VerificationResult` is immutable evidence submitted for one check. Results are attempts. A check's current status is derived from the latest accepted result according to Django service rules.

Recommended source values:

- `runner`
- `user`
- `system`

Recommended outcome values:

- `passed`
- `failed`

Recommended validation status values:

- `accepted`
- `rejected`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | FK -> `ChangeRecord`, `related_name="verification_results"` | Parent change. |
| `plan` | FK -> `VerificationPlan`, `related_name="results"` | Parent plan. |
| `check` | FK -> `VerificationCheck`, `related_name="results"` | Checked item. |
| `source` | `CharField(16)` | `runner`, `user`, or `system`. |
| `outcome` | `CharField(16)` | `passed` or `failed`. |
| `validation_status` | `CharField(16)` | Accepted or rejected by Django. |
| `submitted_by` | FK -> `users.User`, nullable, `SET_NULL` | Required for public/manual submissions. |
| `runner_id` | `CharField(255, blank=True)` | Required for internal runner submissions. |
| `verification_key` | `CharField(128, blank=True)` | Submitted key. |
| `artifact` | FK -> `artifacts.Artifact`, nullable, `PROTECT` | Required for artifact-backed evidence. |
| `artifact_checksum_sha256` | `CharField(64, blank=True)` | Submitted or resolved checksum. |
| `external_reference` | `CharField(1024, blank=True)` | Sanitized external URL/ticket id if applicable. |
| `api_assertion_snapshot` | `JSONField(default=dict)` | Sanitized evaluated facts, not credentials or full response bodies. |
| `manual_attestation_text` | `TextField(blank=True)` | Required only for manual attestation, size-limited and scrubbed in audit. |
| `observed_value` | `JSONField(default=dict)` | Small structured fact payload. No secrets or raw logs. |
| `validation_errors` | `JSONField(default=list)` | Machine-readable reject reasons. |
| `submitted_at` | `DateTimeField` | Source submission timestamp. |
| `validated_at` | `DateTimeField` | Django validation timestamp. |

Recommended constraints and indexes:

- check `source` in source values;
- check `outcome` in outcome values;
- check `validation_status` in validation status values;
- index `(change_record, validation_status, submitted_at)`;
- index `(check, validation_status, submitted_at)`;
- index `(organization, runner_id, submitted_at)`;
- service invariant: `plan_id == check.plan_id` and all organization IDs match;
- service invariant: accepted artifact results must point to an available artifact for the bound execution.

Never update a `VerificationResult` after creation. To correct a rejected or failed result, submit a new result.

### 5.4 `ChangeClosure`

`ChangeClosure` is the immutable controlled-close record for one `ChangeRecord`.

Required outcome values:

- `success`
- `rolled_back`
- `partial_success`
- `failed`
- `canceled`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Standard `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Tenant boundary. |
| `change_record` | OneToOne -> `ChangeRecord`, `related_name="closure"` | Exactly one closure object per change. |
| `outcome` | `CharField(32)` | One of the required closure outcomes. |
| `closed_by` | FK -> `users.User`, nullable, `SET_NULL` | Human actor that closed the change. |
| `independent_reviewer` | FK -> `users.User`, nullable, `SET_NULL`, related_name distinct | Required for success/partial/rolled-back closure when profile requires independent review. |
| `summary` | `TextField` | Closure summary, not evidence by itself. |
| `verification_plan` | FK -> `VerificationPlan`, `on_delete=PROTECT` | Plan used for closure. |
| `verification_summary` | `JSONField(default=dict)` | Counts and accepted result IDs only. |
| `execution_summary` | `JSONField(default=dict)` | Execution id/status/timestamps. No raw logs. |
| `closed_at` | `DateTimeField` | Closure timestamp. |

Recommended constraints and indexes:

- unique `change_record`;
- check `outcome` in required closure outcomes;
- index `(organization, outcome, closed_at)`;
- service invariant: closure object is immutable after creation;
- service invariant: `closed_by != independent_reviewer` when reviewer is required;
- service invariant: closure outcome must be compatible with execution and verification status.

## 6. Verification Plan Generation Design

### 6.1 OperationProfile Configuration

Phase 11.3 should extend `OperationProfile` with a sanitized verification configuration. Recommended fields if not already present:

| Field | Type | Notes |
|---|---|---|
| `verification_mode` | `CharField(16, default="mixed")` | `automated`, `manual`, or `mixed`. |
| `verification_plan_template` | `JSONField(default=dict)` | Declarative check template. |
| `requires_independent_reviewer` | `BooleanField(default=True)` | Enforces non-requester/non-operator attestation. |
| `verification_timeout_seconds` | `PositiveIntegerField(null=True, blank=True)` | Optional SLA display/alert input, not auto-failure unless product chooses. |

Recommended `verification_plan_template` shape:

```json
{
  "checks": [
    {
      "key": "runner-health-check",
      "name": "Runner health check completed",
      "type": "runner_step",
      "required": true,
      "source_step_key": "health-check",
      "verification_key": "postdeploy.health.ok"
    },
    {
      "key": "diagnostic-artifact",
      "name": "Diagnostic report uploaded",
      "type": "artifact_presence",
      "required": true,
      "artifact_kind": "report",
      "artifact_name_pattern": "postdeploy-diagnostics.json",
      "verification_key": "postdeploy.diagnostics"
    },
    {
      "key": "operator-attestation",
      "name": "Independent operator attestation",
      "type": "manual_attestation",
      "required": true,
      "requires_independent_reviewer": true
    }
  ]
}
```

Template validation rules:

- reject unknown check types;
- require stable unique check keys;
- require at least one required check when `OperationProfile.verification_required=true`;
- require `verification_key` for `runner_step` and `artifact_presence` checks unless a specific step/artifact matcher is sufficient;
- reject credentials, bearer tokens, API keys, raw request bodies, and secret-like fields in API or external-reference config;
- reject templates whose mode and check composition conflict, for example `automated` mode with only manual checks.

### 6.2 Generation Timing

Generate the plan before dispatch, not after execution completes.

Recommended integration points:

1. On submit or approval: optionally generate a draft plan for UI preview.
2. During Phase 11.2 dispatch preflight: require an active generated plan before creating execution/bindings.
3. Before `ChangeRecord.status` becomes `dispatchable`: call `ensure_verification_plan(change)`.
4. If plan generation fails, dispatch fails with `409 verification_plan_missing_or_invalid`.

This satisfies the test requirement that every change has a verification plan before dispatch.

### 6.3 Generation Algorithm

`ensure_verification_plan(change_record)` responsibilities:

1. Lock the `ChangeRecord` with `select_for_update()`.
2. Require the change is submitted or later and not terminal.
3. Load the current `OperationProfile` and frozen profile key snapshot.
4. Validate `OperationProfile.verification_required`.
5. If verification is not required, create no blocking checks and mark the plan `satisfied`, or skip plan generation only if Phase 11.1 explicitly allows non-verification profiles. High-risk profiles should normally require verification.
6. Validate the profile template against targets, workflow snapshot, and operation profile constraints.
7. Expand target-scoped template checks into concrete `VerificationCheck` rows when a check applies per target.
8. Compute the plan mode:
   - `automated` if all required checks are automated types;
   - `manual` if all required checks are manual or external-reference checks requiring user submission;
   - `mixed` if both automated and manual/user-submitted checks are required.
9. Persist `VerificationPlan` and `VerificationCheck` rows in one transaction.
10. Emit `change.verification_plan_generated`.

Regeneration should be conservative. After a change is dispatchable or running, do not regenerate checks except through a future explicit versioned plan model. In Phase 11.3, treat plan generation as create-once for the change.

## 7. Verification Result Validation Design

All result submission must flow through `changes.services.submit_verification_result(...)` or a narrow wrapper. The service validates evidence, creates an immutable `VerificationResult`, updates the corresponding `VerificationCheck`, recomputes plan status, and then evaluates change state transitions.

### 7.1 Common Validation Rules

For every result:

1. Load `ChangeRecord`, `VerificationPlan`, and `VerificationCheck` by organization.
2. Require `ChangeRecord.status == "verification_pending"` unless the request is a runner fact arriving before execution completion. Early runner facts can be accepted as evidence, but final plan evaluation must wait for `verification_pending`.
3. Require check belongs to the active plan for the change.
4. Require submitted `verification_key` matches the check when the check defines one.
5. Reject AI actors and AI service identities as submitters.
6. Reject free-text-only evidence for structured check types.
7. Validate evidence against check type rules.
8. Create `VerificationResult(validation_status="accepted")` or `rejected` with validation errors.
9. Emit `change.verification_result_accepted` or `change.verification_result_rejected`.
10. Recompute check and plan status from accepted results.

Rejected results should not mutate check status.

### 7.2 `runner_step`

Accepted evidence must include:

- runner source;
- runner ownership validated through the bound `Execution`;
- matching `verification_key`;
- matching `source_step_key` when configured;
- a succeeded execution step or a structured runner-reported passed result tied to an execution step.

Failure evidence may mark the check failed if:

- the runner owns the execution;
- the key and step match;
- the submitted outcome is `failed` or the associated execution step failed.

Do not let the runner decide final plan status. It only submits facts.

### 7.3 `artifact_presence`

Accepted evidence must include:

- an `artifact_id`;
- the artifact belongs to the same organization;
- the artifact belongs to the bound execution;
- the artifact upload status is `available`;
- step linkage matches `source_step_key` when configured;
- artifact kind/name/checksum match configured expectations;
- submitted checksum equals `Artifact.checksum_sha256`.

If the artifact is missing, unavailable, attached to another execution, checksum-mismatched, or name/kind-mismatched, reject the result with a structured error such as `artifact_not_found`, `artifact_execution_mismatch`, or `artifact_checksum_mismatch`.

Free text like "artifact uploaded" never satisfies this check.

### 7.4 `manual_attestation`

Accepted evidence must include:

- authenticated user source;
- non-empty attestation text or required attestation confirmation fields;
- user is an organization member with the required role;
- user is not the change requester, submitter, approver, dispatch actor, runner identity, or closure actor when independent review is required;
- user is not an AI/system/API-client actor.

Recommended independent reviewer rule:

```text
attester_id not in {
  requested_by_id,
  submitted_by_id,
  approval_decision_actor_id,
  dispatch_requested_by_id,
  closed_by_id when known
}
```

If the product lacks a normalized approval decision actor field after Phase 11.1, resolve it through the linked `ApprovalDecision` rows in the approvals app.

Manual attestation can satisfy only `manual_attestation` checks. It cannot satisfy artifact, API, or runner checks.

### 7.5 `api_assertion`

Phase 11.3 should keep API assertions narrow and Django-owned. Recommended behavior:

- Django executes or verifies an allowlisted assertion adapter based on `VerificationCheck.api_assertion`.
- Credentials must come from existing integration connection services or server-side configuration, never from the plan template or client payload.
- Store only sanitized evaluated facts in `VerificationResult.api_assertion_snapshot`.
- Reject arbitrary URLs, arbitrary headers, raw request bodies, and user-supplied executable expressions.

If the repository does not yet have a safe integration adapter for the required assertion, implement the data model and API shape but keep `api_assertion` checks rejected with `api_assertion_adapter_unavailable` until a safe adapter exists.

### 7.6 `external_reference`

External-reference checks are evidence that a required external ticket, monitoring incident, dashboard, or record exists. They are not free text.

Accepted evidence must include:

- `external_reference` matching the configured pattern or allowlisted host;
- optional structured fields such as ticket id, status, or URL;
- authenticated user source unless a future integration adapter verifies it as `system`;
- independent reviewer validation if configured.

Do not fetch arbitrary external URLs in this phase unless the target host is allowlisted and the existing integrations architecture supports it.

### 7.7 Plan Status Evaluation

`recompute_verification_state(change)` responsibilities:

1. Count required checks by status.
2. If any required check is failed, set plan `failed`.
3. If every required check is passed, set plan `satisfied`.
4. If plan satisfied and change status is `verification_pending`, set change status `verified` and `verified_at`.
5. If plan failed and change status is `verification_pending`, set change status `verification_failed`.
6. Emit `change.status_changed` for state transitions.
7. Emit `change.verification_plan_satisfied` or `change.verification_plan_failed` once.

Failing required checks prevent `verified`. Optional failed checks should display but not block `verified`.

## 8. Closure Service Design

Add `changes.services.close_change_record(...)`.

### 8.1 Closure Outcomes

| Outcome | Required change state | Required evidence | Notes |
|---|---|---|---|
| `success` | `verified` | All required checks passed; independent reviewer satisfied if required | Normal successful closure. |
| `rolled_back` | `verified` or `verification_failed` | Rollback evidence checks passed or manual reviewer attests rollback completed | Use when execution completed but rollback restored desired state. |
| `partial_success` | `verified` | All required checks passed or accepted partial-success policy in profile | Requires explicit summary and independent reviewer. |
| `failed` | `verification_failed` or `closed` from failed execution path | Failure evidence and summary | Does not bypass verification for successful execution. |
| `canceled` | `canceled`, `expired`, or pre-running terminal state | No verification required if execution never ran | For withdrawn or never-executed changes only. |

For Phase 11.3, `success` must require `ChangeRecord.status == "verified"`. A successful execution that is still `verification_pending` cannot be closed.

### 8.2 Closure Rules

`close_change_record` responsibilities:

1. Lock the `ChangeRecord`, `VerificationPlan`, and optional existing `ChangeClosure`.
2. Reject if a closure already exists, returning idempotent detail only for exact duplicate safe retries if the API supports idempotency keys.
3. Require outcome is one of the allowed closure outcomes.
4. Require outcome is compatible with current change status and execution status.
5. Require all required verification checks are passed for `success` and normal `partial_success`.
6. Reject if any required check is pending for `success`.
7. Reject if a required check failed and outcome is `success`.
8. Require independent reviewer when profile or manual checks require it.
9. Reject self-review.
10. Create `ChangeClosure` in one transaction.
11. Set `ChangeRecord.status="closed"`, `closed_at`, and a terminal reason such as `verified_closed`, `rolled_back_closed`, `failed_closed`, or `canceled_closed`.
12. Release any remaining active `TargetLock` rows through the Phase 11.2 service if not already released.
13. Emit `change.closed`.
14. Emit `change.status_changed`.

Closure cannot call a bypass path. Emergency closure exceptions are intentionally out of scope until Phase 11.4.

### 8.3 Closure Immutability

Enforce immutability at both service and model levels:

- no public update or delete endpoint for `ChangeClosure`;
- model `save()` rejects updates to existing closure rows, or a service-level guard plus tests if the project avoids model overrides;
- queryset update/delete protections if consistent with `AuditEventQuerySet`;
- admin should expose read-only closure fields after creation.

## 9. API Design

All public APIs require JWT authentication, `X-Organization-Id`, and existing organization permissions. All internal APIs require runner bearer authentication and must reject user JWTs.

### 9.1 `GET /api/v1/changes/{id}/verification-plan/`

Return the active verification plan and checklist for a change.

Response `200`:

```json
{
  "id": "49ea421a-7f0e-492c-bd9b-42b80fbc00fd",
  "change_record_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "mode": "mixed",
  "status": "active",
  "required_check_count": 3,
  "satisfied_required_count": 1,
  "failed_required_count": 0,
  "checks": [
    {
      "id": "a0790bde-bc8e-4565-9366-c9f61cf066d8",
      "key": "diagnostic-artifact",
      "name": "Diagnostic report uploaded",
      "check_type": "artifact_presence",
      "required": true,
      "status": "passed",
      "verification_key": "postdeploy.diagnostics",
      "last_result": {
        "id": "78c49ec6-0341-479e-9d0c-56ce90b8d3bc",
        "outcome": "passed",
        "source": "runner",
        "validated_at": "2026-05-01T18:30:00Z"
      }
    }
  ],
  "unmet_required_checks": [
    {
      "id": "f357f2b8-cdd4-4678-a96f-f45fedb2ac85",
      "key": "operator-attestation",
      "name": "Independent operator attestation",
      "check_type": "manual_attestation"
    }
  ]
}
```

Important errors:

- `404 verification_plan_not_found`;
- `403 permission_denied`.

### 9.2 `POST /api/v1/changes/{id}/verification-results/`

Submit public verification evidence. This endpoint is for user/manual/system-mediated checks, not runner-owned callbacks.

Request examples:

Manual attestation:

```json
{
  "check_id": "f357f2b8-cdd4-4678-a96f-f45fedb2ac85",
  "outcome": "passed",
  "manual_attestation_text": "I verified production metrics and customer traffic after the change.",
  "verification_key": "operator.independent.review"
}
```

External reference:

```json
{
  "check_id": "e42e3c84-b40a-4efc-8854-19f40c18efe5",
  "outcome": "passed",
  "external_reference": "CHG-1234",
  "verification_key": "servicenow.change.closed"
}
```

Response `201`:

```json
{
  "id": "78c49ec6-0341-479e-9d0c-56ce90b8d3bc",
  "check_id": "f357f2b8-cdd4-4678-a96f-f45fedb2ac85",
  "outcome": "passed",
  "validation_status": "accepted",
  "change_status": "verified",
  "plan_status": "satisfied",
  "validated_at": "2026-05-01T18:35:00Z",
  "unmet_required_checks": []
}
```

Important errors:

- `400 verification_key_mismatch`;
- `400 evidence_required`;
- `400 free_text_not_sufficient`;
- `400 artifact_required`;
- `400 external_reference_invalid`;
- `403 ai_actor_not_allowed`;
- `403 permission_denied`;
- `409 invalid_change_state`;
- `409 self_review_rejected`;
- `409 check_not_in_active_plan`;
- `422 verification_result_rejected`.

### 9.3 `POST /api/v1/changes/{id}/close/`

Create an immutable closure record and move the change to `closed`.

Request:

```json
{
  "outcome": "success",
  "summary": "Change completed successfully. Required post-change verification passed.",
  "independent_reviewer_id": "2895b365-2b1e-4a09-ae4a-572e67451f5d"
}
```

Response `201`:

```json
{
  "id": "8b2e0cb0-4102-4be7-b116-3ce438f2fd43",
  "change_record_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
  "outcome": "success",
  "closed_at": "2026-05-01T18:40:00Z",
  "closed_by": {
    "id": "6bc0f932-e4cb-4730-acfb-d4a669f42a12",
    "username": "operator@example.com"
  },
  "independent_reviewer": {
    "id": "2895b365-2b1e-4a09-ae4a-572e67451f5d",
    "username": "reviewer@example.com"
  },
  "change_status": "closed"
}
```

Important errors:

- `400 closure_summary_required`;
- `400 invalid_closure_outcome`;
- `403 permission_denied`;
- `409 closure_already_exists`;
- `409 closure_requires_verified_change`;
- `409 required_verification_checks_unmet`;
- `409 verification_failed_cannot_close_success`;
- `409 independent_reviewer_required`;
- `409 self_review_rejected`.

### 9.4 `POST /internal/v1/changes/{id}/verification-results/`

The prompt requires:

```text
POST /internal/v1/changes/{id}/verification-results/
```

The current repository convention uses:

```text
/api/v1/internal/...
```

Recommended implementation: register the endpoint under `/api/v1/internal/changes/{id}/verification-results/` and add `/internal/v1/changes/{id}/verification-results/` only if the project deliberately supports both internal roots.

Request:

```json
{
  "runner_id": "runner-prod-1",
  "claim_token": "a63d707a-4798-43c9-9049-19ef135ee780",
  "execution_id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
  "check_key": "runner-health-check",
  "verification_key": "postdeploy.health.ok",
  "outcome": "passed",
  "step_key": "health-check",
  "artifact_ids": ["9c2f7c0b-45e7-406e-8e1d-5ea01af4a0e5"],
  "artifact_checksums": {
    "9c2f7c0b-45e7-406e-8e1d-5ea01af4a0e5": "7b3f..."
  },
  "observed_value": {
    "exit_code": 0
  },
  "sent_at": "2026-05-01T18:29:00Z"
}
```

Response `201`:

```json
{
  "result_id": "78c49ec6-0341-479e-9d0c-56ce90b8d3bc",
  "check_id": "a0790bde-bc8e-4565-9366-c9f61cf066d8",
  "validation_status": "accepted",
  "check_status": "passed",
  "plan_status": "active",
  "change_status": "verification_pending"
}
```

Important errors:

- `401` invalid runner token;
- `403` user JWT attempted on internal endpoint;
- `404 change_or_check_not_found`;
- `409 runner_ownership_mismatch`;
- `409 claim_token_mismatch`;
- `409 execution_binding_mismatch`;
- `400 verification_key_mismatch`;
- `400 artifact_not_found`;
- `400 artifact_checksum_mismatch`;
- `422 verification_result_rejected`.

## 10. Runner Callback Contract

### 10.1 Claim Payload and Step Metadata

Phase 11.1 already adds change binding fields to claimed executions. Phase 11.3 should add only optional verification metadata:

```json
{
  "execution": {
    "id": "1152b6d6-67f5-4543-b289-24c7c44f6b63",
    "change_record_id": "3eb40fd5-faf4-408f-8c07-ffcbcebd39cc",
    "verification_plan_id": "49ea421a-7f0e-492c-bd9b-42b80fbc00fd",
    "verification_keys": [
      {
        "check_key": "runner-health-check",
        "verification_key": "postdeploy.health.ok",
        "step_key": "health-check",
        "check_type": "runner_step"
      }
    ]
  }
}
```

For non-change executions, these fields must be absent or null.

### 10.2 Runner Responsibilities

The runner may:

- include `verification_key` in step completion metadata if the step produced a verification fact;
- call the internal verification-results endpoint with check key, verification key, outcome, step key, artifact IDs, and checksums;
- attach artifact IDs and checksums already created through the existing artifact upload API;
- retry transient `502`, `503`, or `504` responses according to existing client retry rules.

The runner must not:

- evaluate whether all checks are complete;
- mark `VerificationPlan.status` final;
- set `ChangeRecord.status` to `verified` or `verification_failed`;
- create `ChangeClosure`;
- satisfy checks with logs or text alone;
- log dispatch tokens, claim tokens, or secret-like verification payloads.

### 10.3 Runner Code Touch Points

Expected files:

- `apps/runner/runner/schemas.py`: add `VerificationResultRequest`, `VerificationResultResponse`, and optional claimed execution verification metadata.
- `apps/runner/runner/client.py`: add `submit_change_verification_result(...)` using the internal endpoint.
- `apps/runner/runner/executor.py`: after artifact upload and step update, submit configured verification facts when present. Do not block command execution on optional verification callback failure unless Django returns a non-retryable ownership/security error.
- `apps/runner/runner/artifact_uploader.py`: return artifact IDs/checksums in a shape the executor can pass to the verification callback.

## 11. Frontend Impact

Add to the Phase 11 changes feature area:

```text
apps/web/src/features/changes/
  types.ts
  api/changesApi.ts
  hooks/useVerificationPlan.ts
  hooks/useSubmitVerificationResult.ts
  hooks/useCloseChange.ts
```

Add or extend route components under the Phase 11.1 changes routes:

- `VerificationChecklistPanel`
- `ManualAttestationModal`
- `IndependentReviewerControl`
- `ClosureDialog`
- `UnmetChecksBlockingDisplay`

### 11.1 Verification Checklist Panel

The panel should show:

- plan mode and status;
- required vs optional checks;
- check type, name, status, last accepted result, and validation errors;
- artifact-backed evidence links through existing public artifact download APIs;
- unmet required checks grouped at the top when the change is `verification_pending` or `verification_failed`.

Do not expose internal runner endpoint fields or dispatch tokens.

### 11.2 Manual Attestation Modal

The modal should:

- open only for `manual_attestation` or allowed `external_reference` checks;
- require attestation text or configured confirmation fields;
- show server-side rejection messages such as self-review or missing role;
- submit to `POST /api/v1/changes/{id}/verification-results/`;
- refresh the plan after success.

### 11.3 Independent Reviewer Control

The control should:

- list eligible organization users if an existing users/members API supports it;
- otherwise accept reviewer ID through a constrained existing user picker pattern;
- prevent selecting the current operator client-side when known;
- rely on Django for authoritative self-review enforcement.

### 11.4 Closure Dialog

The dialog should:

- show allowed closure outcomes based on current change status;
- block `success` until the plan is satisfied and change is `verified`;
- require summary text;
- require independent reviewer when the profile requires it;
- show unmet-check blocking display before submit;
- call `POST /api/v1/changes/{id}/close/`.

## 12. Audit Event Taxonomy

Add audit object types if Phase 11.1/11.2 have not already added broad change object types:

- `verification_plan`
- `verification_check`
- `verification_result`
- `change_closure`

Recommended audit events:

| Event type | Object type | Safe metadata |
|---|---|---|
| `change.verification_plan_generated` | `verification_plan` | change id, profile key, mode, check counts, profile config hash |
| `change.verification_plan_activated` | `verification_plan` | change id, status |
| `change.verification_result_accepted` | `verification_result` | change id, check id/key/type, outcome, source, artifact id/checksum if present |
| `change.verification_result_rejected` | `verification_result` | change id, check id/key/type, source, error codes |
| `change.verification_check_passed` | `verification_check` | change id, check key/type, result id |
| `change.verification_check_failed` | `verification_check` | change id, check key/type, result id |
| `change.verification_plan_satisfied` | `verification_plan` | change id, required count, accepted result ids |
| `change.verification_plan_failed` | `verification_plan` | change id, failed check ids |
| `change.closed` | `change_closure` | change id, outcome, verification plan id, reviewer id, check counts |
| `change.status_changed` | `change_record` | from status, to status, reason |

Extend audit scrubbing for:

- `attestation_text`;
- `manual_attestation_text`;
- `api_assertion_response`;
- `raw_response`;
- `request_payload`;
- `response_body`;
- `external_access_token`;
- `verification_secret`;
- `dispatch_token`;
- `dispatch_token_hash`;
- `claim_token`.

Audit metadata may include artifact checksums, verification keys, check IDs, result IDs, statuses, counts, and booleans.

## 13. File-by-File Implementation Plan

| File | Required work |
|---|---|
| `apps/api/apps/changes/models.py` | Add `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`; add `verification_failed` to `ChangeRecord` statuses; add `OperationProfile` verification config fields if not already present. |
| `apps/api/apps/changes/services.py` | Add plan generation, result validation, plan recomputation, independent reviewer checks, closure service, audit helpers, and dispatch preflight hook requiring a plan. |
| `apps/api/apps/changes/selectors.py` | Add organization-scoped plan/detail selectors and unmet-check selectors. |
| `apps/api/apps/changes/serializers.py` | Add public serializers for plan, checks, result submission, result response, closure request/response. |
| `apps/api/apps/changes/internal_serializers.py` | Add runner verification result request/response serializers. |
| `apps/api/apps/changes/views.py` | Add public `verification-plan`, `verification-results`, and `close` views/actions. |
| `apps/api/apps/changes/internal_views.py` | Add runner-only verification-results endpoint with runner auth and ownership checks. |
| `apps/api/apps/changes/urls.py` | Register public and internal routes following the repo route convention. |
| `apps/api/config/api_v1_urls.py` | Include public change routes and internal verification callback routes; decide whether to add `/internal/v1` compatibility aliases. |
| `apps/api/apps/audit/models.py` | Add verification and closure object types if missing. |
| `apps/api/apps/audit/services.py` | Extend forbidden metadata key scrub list for verification and closure evidence payloads. |
| `apps/api/apps/executions/services.py` | Ensure successful change-bound completion moves to `verification_pending` and triggers plan activation/evaluation. Preserve execution statuses. |
| `apps/api/apps/executions/internal_serializers.py` | Include optional verification metadata in claimed execution payload if Phase 11.3 chooses to send plan keys at claim time. |
| `apps/api/apps/artifacts/services.py` | No broad rewrite. Add small selector/helper if changes service needs a canonical available-artifact validation helper. |
| `apps/runner/runner/schemas.py` | Add optional verification metadata and internal verification result request/response models. |
| `apps/runner/runner/client.py` | Add internal verification result submission method. |
| `apps/runner/runner/executor.py` | Emit verification facts after relevant steps/artifacts are reported; do not evaluate final status. |
| `apps/runner/runner/tests/` | Add runner verification callback contract tests. |
| `apps/web/src/features/changes/types.ts` | Add verification plan/check/result/closure types. |
| `apps/web/src/features/changes/api/changesApi.ts` | Add functions for plan fetch, result submission, closure. |
| `apps/web/src/features/changes/hooks/` | Add hooks for plan, submit result, and close. |
| `apps/web/src/routes/changes/ChangeDetailPage.tsx` | Add checklist panel, attestation modal, independent reviewer control, closure dialog, and unmet-check display. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add verification plan/change closure query keys if not already present. |

## 14. Migration Plan

1. Add audit object type migration for `verification_plan`, `verification_check`, `verification_result`, and `change_closure` if missing.
2. Add `verification_failed` to the `ChangeRecord.status` check constraint.
3. Add `OperationProfile` verification config fields with conservative defaults:
   - `verification_mode="mixed"`;
   - `verification_plan_template={}`;
   - `requires_independent_reviewer=True`;
   - `verification_timeout_seconds=NULL`.
4. Create `VerificationPlan`, `VerificationCheck`, `VerificationResult`, and `ChangeClosure` tables.
5. Add constraints and indexes, including one-to-one `VerificationPlan.change_record` and `ChangeClosure.change_record`.
6. Add `VerificationCheck.last_result` in a second migration if circular FK ordering makes the initial migration awkward.
7. Backfill plans only for non-terminal existing changes that are not yet dispatchable/running. For already terminal changes in non-production dev data, leave plans absent unless the deployment needs reporting consistency.
8. Deploy backend before runner and frontend changes.
9. Deploy runner after backend accepts verification callbacks.
10. Deploy frontend after public APIs are available.

Rollback note: adding `verification_failed` and closure tables is forward-only for production data once real verification results exist. Avoid deleting evidence rows in rollback scripts.

## 15. Testing Plan

### Model and Migration Tests

- `VerificationPlan` one-to-one constraint prevents multiple plans for one change.
- `VerificationCheck` key and position are unique per plan.
- `VerificationResult` cannot be mutated through service paths after creation.
- `ChangeClosure` one-to-one constraint prevents duplicate closure.
- `ChangeClosure` update/delete is rejected.
- `verification_failed` is accepted by `ChangeRecord` status constraints.

### Service Tests

- every change has verification plan before dispatch;
- plan generation from `OperationProfile` creates expected checks and mode;
- invalid profile template rejects dispatch;
- required checks block closure;
- failing required checks prevent `verified` state;
- optional failing checks do not block `verified`;
- missing artifact rejects artifact-backed check;
- artifact from another execution rejects artifact-backed check;
- checksum mismatch rejects artifact-backed check;
- free text alone rejects artifact/API-backed checks;
- self-review rejected;
- AI/system actor rejected for manual attestation;
- manual plus automated mixed-mode verification reaches `verified` only after both pass;
- runner fact accepted but does not mark verification final until Django recomputes state;
- closure object immutability;
- `success` closure requires `verified`;
- `verification_failed` cannot close as `success`;
- closure cannot bypass verification without Phase 11.4 exception record.

### API Tests

- `GET /api/v1/changes/{id}/verification-plan/` returns plan, checks, last result, and unmet checks.
- public result endpoint accepts manual attestation for eligible independent reviewer.
- public result endpoint rejects structured checks with text-only payload.
- public close endpoint creates closure and moves change to `closed`.
- public close endpoint rejects unmet checks.
- internal verification endpoint rejects user JWTs.
- internal verification endpoint requires runner bearer auth.
- internal verification endpoint validates runner ownership and claim token.
- internal verification endpoint rejects missing artifact and checksum mismatch.

### Runner Tests

- runner may report `verification_key` after step/artifact completion;
- runner includes artifact IDs/checksums when available;
- runner does not call close endpoint;
- runner does not mark verification final;
- non-change executions remain compatible;
- dispatch token and claim token are not logged in verification paths.

### Web Tests

- verification checklist renders required, optional, passed, failed, and pending checks;
- manual attestation modal submits to the public API;
- independent reviewer control rejects current user client-side when possible and displays server self-review errors;
- closure dialog blocks success when unmet checks exist;
- unmet-check blocking display shows required pending/failed checks;
- browser API client still rejects `/api/v1/internal/...` calls.

Expected verification after implementation:

- targeted Django tests for changes, artifacts, audit, and executions;
- targeted runner tests;
- targeted web tests;
- `make test-api`;
- `make test-runner`;
- `make test-web`;
- `make lint`;
- `make security-scan` if the repository uses it for production gates.

## 16. Codex Implementation Batching Plan

1. Backend model batch: add statuses, models, migrations, audit object types, admin read-only closure behavior, and model tests.
2. OperationProfile/template batch: add verification config validation and plan generation from profile templates with service tests.
3. Dispatch integration batch: require/generate plan before dispatch and activate plan when execution enters verification flow.
4. Result validation batch: implement common result service, runner/artifact/manual validation, recomputation, and state transitions.
5. Closure batch: implement closure service/API, independent reviewer enforcement, lock release integration, immutability tests.
6. Internal runner API batch: add internal serializers/views/URLs and runner ownership tests.
7. Runner batch: add schemas/client/executor reporting without final-state authority.
8. Frontend batch: add types/hooks/API functions and UI components for checklist, attestation, reviewer, closure, and blockers.
9. Hardening batch: audit scrubbing tests, mixed-mode end-to-end tests, route convention tests, and full targeted verification.

Do not mix backend transaction changes, runner callback behavior, and frontend UI in one large patch unless unavoidable.

## 17. Definition of Done

- `VerificationPlan`, `VerificationCheck`, `VerificationResult`, and `ChangeClosure` exist with migrations, constraints, indexes, admin registration, and tests.
- `OperationProfile` can define verification mode and check templates.
- Every dispatchable verification-required change has a generated verification plan before dispatch.
- Runner can report verification keys, structured results, artifact IDs, and checksums through an internal Django endpoint.
- Runner cannot close a change or mark verification final.
- Artifact-backed checks require real available artifacts from the bound execution.
- Manual attestations enforce independent reviewer rules and reject self-review.
- Mixed manual and automated verification works.
- Required failed checks prevent `verified`.
- Required unmet checks block `success` closure.
- `ChangeClosure` is immutable after creation.
- Closure cannot bypass verification except through future Phase 11.4 exception semantics, which are not implemented here.
- React exposes checklist, manual attestation, reviewer, closure, and unmet-check blocking flows through public APIs only.
- Audit events capture verification and closure actions without sensitive payloads.
- Required API, runner, web, lint, and security verification gates pass.

## 18. Risks and Drift Traps

- **Route convention drift:** The prompt names `/internal/v1/...`, while the repo currently uses `/api/v1/internal/...`. Choose one deliberately and test it.
- **Runner authority creep:** Do not let runner callbacks set plan final status, change `verified`, or close changes.
- **Free-text bypass:** Notes are useful context but must not satisfy artifact, API, runner, or external-reference checks by themselves.
- **Self-review gaps:** Approval actor, requester, submitter, dispatcher, verifier, and closer identity must be compared consistently, or independent review becomes cosmetic.
- **Artifact mismatch:** Artifact evidence must be tied to the bound execution, not merely the same organization.
- **Closure before verification:** The close endpoint must not recreate emergency/breakglass behavior before Phase 11.4.
- **Sealed bundle scope creep:** Do not add evidence bundle signing, dossier sealing, or closure package hashing in Phase 11.3.
- **Audit leakage:** Attestation text, API assertion payloads, raw external references with tokens, dispatch tokens, and claim tokens must not leak into audit metadata.
- **Plan regeneration ambiguity:** Regenerating checks after dispatch can invalidate evidence. Phase 11.3 should treat plans as create-once after dispatch.
- **Execution status confusion:** Keep verification and closure lifecycle on `ChangeRecord`; do not add verification-specific execution statuses.
