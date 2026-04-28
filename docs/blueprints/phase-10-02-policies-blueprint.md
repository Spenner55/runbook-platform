# Phase 10.2: Policies Expansion Blueprint

| Field | Value |
|---|---|
| Phase number | 10.2 |
| Phase name | Policies |
| Objective | Add organization-scoped policy rules that deterministically decide whether execution steps require approval, can auto-proceed, or must be blocked. |
| Status | Blueprint only — do not implement without re-reading current source first |
| Depends on | Phases 01–09 complete and verified; Phase 10.1 approvals complete and verified |
| Authored | 2026-04-27 |

---

## 1. Purpose and sequencing rationale

Phase 10.2 adds organization-scoped execution policies. Policies are the platform's centralized rule layer: they decide whether a step must pause for approval, may proceed automatically, or must be blocked before the runner executes it.

This phase assumes Phase 10.1 approvals are complete and verified. That assumption is mandatory because policies do not replace approvals. Policies decide when approval behavior is required, waived, or forbidden. A policy outcome of `ApprovalRequired` must route into the existing approval lifecycle (the `request_step_approval` service and the `waiting_for_approval` step state). A policy outcome of `AutoApprove` must let Django transition the step to `running` without creating an approval request. A policy outcome of `Block` must fail the step before the runner executes the command.

Policies come after approvals for four reasons:

1. Approvals provide the concrete control-plane mechanism that policies can invoke. `request_step_approval`, `get_approval_status`, `decide_approval`, and the `WAITING_FOR_APPROVAL` step status are all live before policy evaluation exists.
2. Policies need stable step states, approval request semantics, and approval timeout behavior before they can make safe decisions.
3. Centralized policy rules prevent teams from encoding approval logic manually in workflow definitions once approvals exist.
4. The policy evaluation records created in this phase become a key input to Phase 10.3 audit trail, but they are not the audit trail themselves.

Policies come before audit trail because audit needs stable event sources. Once approvals and policy evaluations exist, Phase 10.3 can record meaningful events such as "policy blocked step", "policy waived manual approval", and "policy required approval". Building audit before policies would force a second event taxonomy migration immediately afterward.

Phase 10.2 must produce a deterministic, explainable decision for every step transition that enters the execution hot path. The goal is not to build a generic rules platform. The goal is to add a small, inspectable policy layer that is safe under multi-tenant conditions and easy to test.

---

## 2. Current-state inspection checklist

Before implementation begins, inspect the repository in this order. Do not implement from this blueprint without re-reading the current source files first.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` and confirm Phase 10.2 still follows approvals and precedes audit trail.
- [ ] Read `docs/blueprints/phase-10-01-approvals-blueprint.md` and then inspect the implemented Phase 10.1 code rather than relying only on the blueprint.
- [ ] Confirm `apps/api/apps/approvals/models.py` defines `ApprovalRequest` and `ApprovalDecision` with the exact field shapes used in this blueprint.
- [ ] Confirm `apps/api/apps/approvals/services.py` exposes `request_step_approval`, `get_approval_status`, `decide_approval`, and `list_approvals`. Note the guard at line 51: `if not step.requires_approval: raise InvalidStateTransitionError(...)`. This guard must be relaxed so policy-driven approval can create requests on steps where `requires_approval=False`.
- [ ] Confirm `apps/api/apps/executions/models.py` has `ExecutionStep.Status` with values `pending`, `waiting_for_approval`, `running`, `succeeded`, `failed`, `skipped`. There is no `blocked` step status — `Block` policy outcome maps to `failed`.
- [ ] Confirm `apps/api/apps/executions/internal_views.py` contains `ExecutionStepStartView` at `POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/start/`. This view currently returns `runner_action` values `run` and `wait_for_approval` only. Phase 10.2 must add `blocked`. The current comment in the view docstring only mentions these two — update it.
- [ ] Confirm `apps/api/apps/executions/services.py` owns runner step transition logic (`update_execution_step`, `_validate_runner_ownership`) and is the correct hook point for policy evaluation.
- [ ] Confirm internal runner APIs are still defined under `/api/v1/internal/` in `apps/api/config/api_v1_urls.py`.
- [ ] Confirm public APIs are still registered under `/api/v1/` and no frontend code calls the runner or AI service directly.
- [ ] Confirm `apps/api/apps/organizations/models.py` still defines the organization tenant boundary used by workflows and executions.
- [ ] Confirm `apps/api/apps/policies/` contains only `__init__.py` (pure stub). If it has grown since this blueprint was authored, audit all content before extending.
- [ ] Confirm `packages/workflow-schema/workflow.schema.json` still includes step `risk`, `type`, and `requiresApproval` fields.
- [ ] Confirm `apps/web/src/routes/executions/ExecutionDetailPage.tsx` exposes execution step detail data that can be extended with policy evaluation visibility.
- [ ] Confirm `apps/web/src/app/router.tsx`, `apps/web/src/app/AppLayout.tsx`, and `apps/web/src/shared/lib/queryKeys.ts` are the correct places to add a policy management route and query keys.
- [ ] Run the full test suite and confirm Phase 10.1 tests pass before any Phase 10.2 code is written.

---

## 3. Architecture invariants and boundaries

These invariants are non-negotiable for Phase 10.2:

| Invariant | Phase 10.2 consequence |
|---|---|
| Django is the control plane. | Policy storage, evaluation, state-transition decisions, approval routing, blocking, and persistence all live in Django services. |
| Runner talks only to Django internal APIs. | The runner never evaluates policy rules locally and never reads policies from the database. |
| Frontend talks only to Django public APIs. | Policy CRUD and evaluation visibility use `/api/v1/policies/...` and `/api/v1/executions/...` only. |
| AI service is stateless and advisory. | AI does not author, evaluate, override, or persist policies in Phase 10.2. |
| All APIs remain under `/api/v1/`. | Public policy endpoints are registered under `/api/v1/policies/`. |
| Internal runner APIs remain under `/api/v1/internal/`. | Any runner-visible policy outcome is returned through the existing step-start endpoint under `/api/v1/internal/executions/.../steps/.../start/`. |
| UUID primary keys remain standard. | `Policy`, `PolicyRule`, and `PolicyEvaluation` inherit from `BaseModel`. |
| Business logic belongs in `services.py`. | Views validate and delegate. Serializers shape payloads. Policy evaluation lives in `apps/api/apps/policies/services.py` and execution transitions call it. |
| No queues or event infrastructure. | No Celery, Kafka, RabbitMQ, event bus, or async worker is introduced. Policy evaluation is synchronous. |
| No service routes around Django. | No direct runner-to-DB policy reads, no frontend-to-runner shortcuts, and no external service owns policy state. |

Additional Phase 10.2 boundaries:

- Policies are organization-scoped only.
- Policies apply to execution steps, not arbitrary objects.
- Policies make one of three outcomes: `ApprovalRequired`, `AutoApprove`, or `Block`.
- Policy conditions are structured enum-plus-JSON contracts, not a general DSL.
- Rule ordering is explicit and deterministic.
- Policy evaluations are recorded for visibility and future audit integration.
- Policies may decide control flow, but they must not mutate commands, rewrite workflow definitions, inject environment variables, or alter runner behavior outside the approved state-transition contract.
- `Block` outcome uses the existing `failed` step status. No new step status enum value is introduced.

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.2 |
|---|---|
| `apps/api/apps/policies/` | Implement Django app with models, migrations, admin, services, serializers, public views, URLs, and tests. |
| `apps/api/apps/approvals/services.py` | Relax the `if not step.requires_approval: raise` guard so `request_step_approval` can be called on behalf of a policy evaluation (add an optional `policy_evaluation` parameter or split into `_create_approval_request_unchecked`). |
| `apps/api/apps/executions/internal_views.py` | Hook policy evaluation into `ExecutionStepStartView` before the `if step.requires_approval` branch. Add `blocked` as a valid `runner_action` return value. |
| `apps/api/apps/executions/serializers.py` | Embed latest `PolicyEvaluation` summary into public execution step serialization. |
| `apps/api/apps/organizations/` | Reuse organization as the tenant boundary; do not add hierarchy or inheritance. |
| `apps/api/config/` | Register the policies app and include policy URLs under `/api/v1/`. |
| `apps/web/src/features/policies/` | Add frontend policy types, API client functions, hooks, form helpers, and tests. |
| `apps/web/src/routes/policies/` | Add policy list, create, edit, detail, and rule management route components. |
| `apps/web/src/routes/executions/` | Show policy evaluation results on execution detail and per-step rows. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add policy and policy evaluation query keys. |
| `packages/workflow-schema/` | No schema change expected; policies consume existing step fields. |

Likely backend files touched:

- `apps/api/apps/policies/apps.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/policies/admin.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/serializers.py`
- `apps/api/apps/policies/views.py`
- `apps/api/apps/policies/urls.py`
- `apps/api/apps/policies/tests/__init__.py`
- `apps/api/apps/policies/tests/test_models.py`
- `apps/api/apps/policies/tests/test_services.py`
- `apps/api/apps/policies/tests/test_api.py`
- `apps/api/apps/policies/migrations/0001_initial.py`
- `apps/api/apps/approvals/services.py` (relax `requires_approval` guard)
- `apps/api/apps/approvals/tests/test_policy_integration.py`
- `apps/api/apps/executions/internal_views.py` (add policy hook + `blocked` runner_action)
- `apps/api/apps/executions/serializers.py` (embed policy_evaluation)
- `apps/api/apps/executions/tests/test_policy_integration.py`
- `apps/api/apps/executions/tests/test_approval_runner_api.py` (extend existing)
- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`

Likely frontend files touched:

- `apps/web/src/features/policies/types.ts`
- `apps/web/src/features/policies/api/policiesApi.ts`
- `apps/web/src/features/policies/hooks/usePolicies.ts`
- `apps/web/src/features/policies/hooks/usePolicyDetail.ts`
- `apps/web/src/features/policies/hooks/useCreatePolicy.ts`
- `apps/web/src/features/policies/hooks/useUpdatePolicy.ts`
- `apps/web/src/features/policies/hooks/usePolicyRules.ts`
- `apps/web/src/features/executions/types.ts`
- `apps/web/src/routes/policies/PoliciesPage.tsx`
- `apps/web/src/routes/policies/PoliciesPage.test.tsx`
- `apps/web/src/routes/policies/PolicyDetailPage.tsx`
- `apps/web/src/routes/policies/PolicyDetailPage.test.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`

Files explicitly out of scope unless inspection proves otherwise:

- Runner executor code. The runner should continue to call the step-start endpoint; Django returns the resulting state. The runner should not evaluate policies locally.
- AI service code. Policies are manually managed control-plane rules in this phase.
- Infrastructure files. No new services, queues, databases, or containers are required.

---

## 5. Data model: fields, relationships, indexes, uniqueness, constraints, active/inactive behavior

### 5.1 `Policy`

`Policy` is an organization-scoped container for ordered policy rules.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Required tenant boundary. Use `CASCADE` — deleting an organization should delete its policies. |
| `name` | `CharField(255)` | Human-readable policy name. |
| `description` | `TextField(blank=True)` | Operator-facing explanation. |
| `is_active` | `BooleanField(default=True)` | Inactive policies are ignored during evaluation but remain visible for history. |
| `created_by_label` | `CharField(255, blank=True)` | Optional bridge until real auth is complete. Do not build RBAC here. |
| `updated_by_label` | `CharField(255, blank=True)` | Optional bridge until real auth is complete. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| index | `(organization, is_active, name)` | Fast management listing and active policy load. |
| index | `(organization, created_at)` | Tenant-scoped historical listing. |
| unique constraint | `(organization, name)` where enforced at service layer for active policies | Prevent ambiguous active policy names. Enforce in service, not DB, to allow inactive duplicates. |

Active/inactive behavior:

- `is_active=False` means no rules under the policy are evaluated.
- Deactivation must not delete `PolicyRule` or `PolicyEvaluation` records.
- Deactivated policies remain readable by public API so historical evaluations can still render names.
- Reactivation should validate that no other active policy in the same organization already uses the same name.
- Hard delete is not required for Phase 10.2. Prefer deactivate over delete to preserve explainability.

### 5.2 `PolicyRule`

`PolicyRule` is one structured condition and one outcome within a policy.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `policy` | FK -> `Policy` (`CASCADE`) | Related name `rules`. |
| `name` | `CharField(255)` | Human-readable rule label. |
| `description` | `TextField(blank=True)` | Why the rule exists. |
| `is_active` | `BooleanField(default=True)` | Inactive rules are ignored but remain visible. |
| `priority` | `PositiveIntegerField` | Lower number evaluates first within the organization-wide rule set. Must be > 0. |
| `condition_type` | `CharField(32)` | One of `risk_level`, `step_type`, or `time_window`. |
| `condition_params` | `JSONField(default=dict)` | Structured params validated by service and serializer. |
| `outcome` | `CharField(32)` | One of `approval_required`, `auto_approve`, or `block`. |
| `reason` | `TextField(blank=True)` | Operator-facing reason copied into evaluations. |

Use `TextChoices` classes or string constants for `condition_type` and `outcome` rather than Django enums, since these fields need to be compared against string values in the condition evaluation logic.

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| index | `(policy, is_active, priority)` | Deterministic rule loading for one policy. |
| index | `(condition_type, outcome)` | Support admin/debug queries. |
| unique constraint | `(policy, priority)` | No ambiguous ordering inside one policy. |
| unique constraint | `(policy, name)` | Prevent duplicate rule labels inside one policy. |
| check constraint (service-enforced) | `priority > 0` | Avoid zero or negative priorities. |

Priority and deterministic evaluation:

- Rules are evaluated in ascending `priority`.
- If two active policies exist, combine their active rules into one organization-scoped ordered list.
- The global sort key must be `(rule.priority, policy.created_at, policy.id, rule.id)`.
- First matching rule wins within the sorted list.
- If no rule matches, the default outcome is derived from the workflow step's `requires_approval` flag: `ApprovalRequired` when true, otherwise `AutoApprove`.
- Do not use database default ordering alone as policy semantics. The service must sort explicitly.

Conflict handling:

- Unique priority per policy prevents conflicts inside a policy.
- Cross-policy priority collisions are allowed but deterministic because the secondary sort key includes `policy.created_at`, `policy.id`, and `rule.id`.
- Do not add "stricter outcome wins" in this phase. It sounds safe but creates surprising behavior when later rules silently override earlier rules. Deterministic first-match semantics are easier to reason about and easier to audit.

### 5.3 `PolicyEvaluation`

`PolicyEvaluation` records what Django decided for a specific execution step at the policy hook point.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Denormalized tenant boundary for isolation and querying. |
| `execution` | FK -> `executions.Execution` | Execution being evaluated. Use `CASCADE`. |
| `step` | FK -> `executions.ExecutionStep` | Step being evaluated. Use `CASCADE`. |
| `policy` | FK -> `Policy`, `null=True`, `on_delete=PROTECT` | Null when no policy rule matched and the workflow default was used. Protect to preserve evaluation history when a policy is deactivated. |
| `rule` | FK -> `PolicyRule`, `null=True`, `on_delete=PROTECT` | Null when no rule matched. |
| `matched` | `BooleanField` | True when a policy rule matched. |
| `outcome` | `CharField(32)` | `approval_required`, `auto_approve`, or `block`. |
| `effective_outcome` | `CharField(32)` | The outcome after applying the `requiresApproval=True` floor. Differs from `outcome` when the floor upgrades `auto_approve` to `approval_required`. |
| `decision_source` | `CharField(32)` | `policy_rule` or `workflow_default`. |
| `condition_type` | `CharField(32, blank=True)` | Snapshot of matched condition type. |
| `condition_params_snapshot` | `JSONField(default=dict)` | Snapshot of matched rule params. |
| `context_snapshot` | `JSONField(default=dict)` | Step attributes used for evaluation: risk, type, organization, execution, step id, local evaluation time. |
| `reason` | `TextField(blank=True)` | Copied from rule or generated default reason. |
| `error_code` | `CharField(64, blank=True)` | Filled only if evaluation fails. |
| `error_message` | `TextField(blank=True)` | Debuggable but non-secret error detail. |
| `evaluated_at` | `DateTimeField` | Set at evaluation time. |

The `effective_outcome` field is the authoritative outcome from the execution service's perspective. It differs from `outcome` only when the `requiresApproval=True` floor upgrades an `auto_approve` rule outcome to `approval_required`. The evaluation record preserves the rule's raw `outcome` for auditability.

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| index | `(organization, evaluated_at)` | Tenant-scoped visibility and future audit queries. |
| index | `(execution, evaluated_at)` | Execution detail rendering. |
| index | `(step, evaluated_at)` | Per-step debugging. |
| index | `(policy, rule, evaluated_at)` | Rule impact analysis. |
| index | `(outcome, evaluated_at)` | Operational support queries. |
| service invariant | `organization_id == execution.organization_id == step.execution.organization_id` | Prevent cross-tenant leakage. |

Uniqueness:

- Do not enforce one evaluation per step at the database level.
- Runner retries and resume flows may legitimately evaluate the same step more than once.
- The execution service should avoid unnecessary duplicate evaluations by evaluating only at the transition boundary where a pending step is about to proceed.
- Execution detail should show the latest evaluation per step by default.

Retention:

- `PolicyEvaluation` records are not immutable audit records yet, but they should be treated as append-only.
- Do not expose update or delete endpoints for evaluations.

### 5.4 Outcome enum

Use storage values that are lowercase and API-friendly:

| API/storage value | Display value | Meaning |
|---|---|---|
| `approval_required` | `ApprovalRequired` | Create an approval request and pause before command execution. |
| `auto_approve` | `AutoApprove` | Proceed without creating an approval request (subject to `requiresApproval` floor). |
| `block` | `Block` | Do not execute the step. Transition step to `failed` via existing execution service. |

Do not add `warn`, `manual_review`, `escalate`, `notify`, or `require_two_approvers` in Phase 10.2.

---

## 6. Condition contract: risk level, step type, time window, structured params

Conditions must be structured contracts. Do not build an expression language, parser, embedded Python, JSONLogic, CEL, Rego, SQL fragments, or a custom DSL.

### 6.1 Shared evaluation context

The policy service evaluates rules against a normalized context derived by Django:

```json
{
  "organization_id": "uuid",
  "execution_id": "uuid",
  "step_id": "uuid",
  "step_key": "deploy",
  "step_type": "shell",
  "risk_level": "high",
  "requires_approval": false,
  "evaluated_at": "2026-04-27T20:00:00Z",
  "workflow_id": "uuid"
}
```

The service builds this context from `Execution`, `ExecutionStep`, and the materialized `step_snapshot`. The runner must not provide policy context except through the existing step transition request.

### 6.2 `risk_level`

Purpose: match a step based on its materialized risk value.

Recommended params:

```json
{
  "operator": "in",
  "values": ["high", "critical"]
}
```

Validation rules:

- `operator` must be `equals` or `in`.
- For `in`: `values` must be a non-empty list of strings.
- For `equals`: `value` must be a string.
- Comparisons are case-sensitive unless existing workflow schema normalization says otherwise.
- Unknown risk values simply fail to match unless explicitly listed.

### 6.3 `step_type`

Purpose: match based on the step's materialized type.

Recommended params:

```json
{
  "operator": "in",
  "values": ["shell", "database", "deploy"]
}
```

Validation rules:

- `operator` must be `equals` or `in`.
- For `in`: `values` must be a non-empty list of strings.
- For `equals`: `value` must be a string.
- Do not infer step type from command text.
- Do not inspect shell commands to decide policy in Phase 10.2.

### 6.4 `time_window`

Purpose: match when a step transition occurs inside or outside a configured window.

Recommended params:

```json
{
  "timezone": "America/Edmonton",
  "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
  "start_time": "09:00",
  "end_time": "17:00",
  "match_when": "inside"
}
```

Validation rules:

- `timezone` must be a valid IANA timezone name (validate with `zoneinfo.ZoneInfo` — raises `ZoneInfoNotFoundError` on invalid input).
- `days_of_week` must be a non-empty list using `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`.
- `start_time` and `end_time` must be `HH:MM` 24-hour local times.
- `match_when` must be `inside` or `outside`.
- Evaluation must use Django timezone-aware datetimes with `zoneinfo`, not hand-rolled offsets.
- If `start_time >= end_time`, reject at validation time rather than attempting overnight window support.

### 6.5 Condition validation ownership

Validation belongs in both serializers and services:

- Serializers reject malformed API payloads early (CRUD operations).
- Services revalidate before saving or evaluating so tests can call services directly without HTTP.
- `JSONField` alone is not validation.

Invalid condition params in CRUD APIs should return `400 Bad Request`. Invalid persisted rules encountered during evaluation should fail closed: record a `PolicyEvaluation` with an error and transition the step to `failed` rather than silently auto-approving.

---

## 7. API contracts for policy CRUD and evaluation visibility

All public APIs stay under `/api/v1/`. Use existing DRF patterns and the existing error envelope from `apps/common/api_errors.py`.

### 7.1 `GET /api/v1/policies/`

Query parameters:

| Param | Required | Notes |
|---|---|---|
| `organization_id` | yes until auth exists | Explicit tenant scope. |
| `is_active` | no | Optional `true`, `false`, or `all`; default `true`. |

Response:

```json
{
  "results": [
    {
      "id": "uuid",
      "organization_id": "uuid",
      "name": "Production safety policy",
      "description": "Requires approval for high-risk production steps.",
      "is_active": true,
      "rule_count": 3,
      "created_at": "2026-04-27T20:00:00Z",
      "updated_at": "2026-04-27T20:00:00Z"
    }
  ]
}
```

### 7.2 `POST /api/v1/policies/`

Request:

```json
{
  "organization_id": "uuid",
  "name": "Production safety policy",
  "description": "Requires approval for risky production steps.",
  "is_active": true
}
```

Status codes:

- `201 Created` on success.
- `400 Bad Request` for invalid fields.
- `409 Conflict` if an active policy with the same name already exists for the organization.

### 7.3 `GET /api/v1/policies/{policy_id}/`

Response includes ordered rules:

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "name": "Production safety policy",
  "description": "Requires approval for risky production steps.",
  "is_active": true,
  "rules": [
    {
      "id": "uuid",
      "name": "Block database work outside business hours",
      "description": "",
      "is_active": true,
      "priority": 10,
      "condition_type": "time_window",
      "condition_params": {
        "timezone": "America/Edmonton",
        "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
        "start_time": "09:00",
        "end_time": "17:00",
        "match_when": "outside"
      },
      "outcome": "block",
      "reason": "Database changes are blocked outside the maintenance window."
    }
  ],
  "created_at": "2026-04-27T20:00:00Z",
  "updated_at": "2026-04-27T20:00:00Z"
}
```

### 7.4 `PATCH /api/v1/policies/{policy_id}/`

Allowed fields: `name`, `description`, `is_active`. Do not allow organization changes after creation.

### 7.5 `POST /api/v1/policies/{policy_id}/rules/`

Request:

```json
{
  "name": "High risk requires approval",
  "description": "Any high or critical risk step requires a human gate.",
  "is_active": true,
  "priority": 20,
  "condition_type": "risk_level",
  "condition_params": {
    "operator": "in",
    "values": ["high", "critical"]
  },
  "outcome": "approval_required",
  "reason": "High-risk steps require human approval."
}
```

Status codes:

- `201 Created` on success.
- `400 Bad Request` for invalid condition params or outcome.
- `409 Conflict` for duplicate priority or duplicate rule name in the policy.

### 7.6 `PATCH /api/v1/policies/{policy_id}/rules/{rule_id}/`

Allowed fields: `name`, `description`, `is_active`, `priority`, `condition_type`, `condition_params`, `outcome`, `reason`. Do not move a rule to another policy.

### 7.7 `DELETE /api/v1/policies/{policy_id}/rules/{rule_id}/`

Preferred behavior: soft-deactivate by setting `is_active=False`. Hard delete is blocked if the rule has any `PolicyEvaluation` references (due to `PROTECT` on the FK). Soft deactivation is simpler and safer for Phase 10.2.

### 7.8 Execution detail policy visibility

Extend step serialization in `GET /api/v1/executions/{execution_id}/` to embed the latest `PolicyEvaluation` per step:

```json
{
  "steps": [
    {
      "id": "uuid",
      "position": 1,
      "name": "Deploy production service",
      "status": "waiting_for_approval",
      "policy_evaluation": {
        "id": "uuid",
        "outcome": "approval_required",
        "effective_outcome": "approval_required",
        "decision_source": "policy_rule",
        "matched": true,
        "policy_id": "uuid",
        "policy_name": "Production safety policy",
        "rule_id": "uuid",
        "rule_name": "High risk requires approval",
        "reason": "High-risk steps require human approval.",
        "evaluated_at": "2026-04-27T20:00:00Z"
      }
    }
  ]
}
```

For evaluation history, add an optional endpoint:

`GET /api/v1/executions/{execution_id}/policy-evaluations/`

```json
{
  "results": [
    {
      "id": "uuid",
      "step_id": "uuid",
      "step_key": "deploy",
      "outcome": "approval_required",
      "effective_outcome": "approval_required",
      "decision_source": "policy_rule",
      "matched": true,
      "policy_id": "uuid",
      "policy_name": "Production safety policy",
      "rule_id": "uuid",
      "rule_name": "High risk requires approval",
      "condition_type": "risk_level",
      "condition_params_snapshot": {
        "operator": "in",
        "values": ["high", "critical"]
      },
      "reason": "High-risk steps require human approval.",
      "evaluated_at": "2026-04-27T20:00:00Z"
    }
  ]
}
```

Do not expose policy evaluation create, update, or delete APIs.

---

## 8. Service contracts and state transitions

### 8.1 Policy service entry points

Implement policy behavior in `apps/api/apps/policies/services.py`.

Recommended service contracts:

```python
def create_policy(
    *, organization, name: str, description: str = "", is_active: bool = True
) -> Policy: ...

def update_policy(*, policy: Policy, **changes) -> Policy: ...

def create_rule(
    *,
    policy: Policy,
    name: str,
    priority: int,
    condition_type: str,
    condition_params: dict,
    outcome: str,
    description: str = "",
    reason: str = "",
    is_active: bool = True,
) -> PolicyRule: ...

def update_rule(*, rule: PolicyRule, **changes) -> PolicyRule: ...

def evaluate_step_policy(
    *, execution: Execution, step: ExecutionStep, evaluated_at=None
) -> PolicyEvaluation: ...
```

`evaluate_step_policy` must:

1. Validate tenant consistency (`step.execution_id == execution.id`, `execution.organization_id` is present).
2. Build a normalized evaluation context from Django-owned models.
3. Load active policies for `execution.organization`.
4. Load active rules for active policies.
5. Sort rules using the deterministic global sort key `(rule.priority, policy.created_at, policy.id, rule.id)`.
6. Evaluate structured conditions without using a DSL.
7. Apply the `requiresApproval=True` floor: if `step.requires_approval` is `True` and the matched rule outcome is `auto_approve`, set `effective_outcome = approval_required`.
8. Persist a `PolicyEvaluation` with both `outcome` (raw rule outcome) and `effective_outcome` (floor-applied outcome).
9. Return the persisted evaluation to the execution service.

### 8.2 Evaluation algorithm

```text
Input: execution, step

1. Assert step.execution_id == execution.id.
2. Assert execution.organization_id is present.
3. Build context from execution and step (snapshot from step_snapshot + FK fields).
4. Query active policies for organization; prefetch active rules.
5. Sort all active rules by (priority, policy.created_at, policy.id, rule.id).
6. For each rule:
   a. Validate condition params. If invalid, fail closed (see 8.3 below).
   b. If condition matches, compute effective_outcome (apply requiresApproval floor).
   c. Persist PolicyEvaluation with matched=True, outcome=rule.outcome, effective_outcome.
   d. Return the evaluation.
7. If no rule matched:
   a. outcome = approval_required if step.requires_approval else auto_approve
   b. effective_outcome = outcome (floor already satisfied since we derived from requires_approval)
   c. Persist PolicyEvaluation with matched=False, decision_source=workflow_default.
   d. Return it.
```

Failure behavior:

- If policy loading, condition validation, or evaluation raises unexpectedly, fail closed.
- Failing closed means: attempt to persist a `PolicyEvaluation` with `error_code` and `error_message`. If even that fails, return a domain error to the execution service.
- The execution service must prevent command execution and transition the step to `failed` with a `policy_evaluation_error` reason.
- Never auto-approve silently on an evaluation error.

### 8.3 `requiresApproval=True` floor

> **ARCHITECTURE DECISION (locked):** `AutoApprove` from a policy MUST NOT waive a workflow step's `requiresApproval: true` declaration. If `step.requires_approval` is `True` and a matched rule outcome is `auto_approve`, the `effective_outcome` MUST be `approval_required`. The `outcome` field on `PolicyEvaluation` still records `auto_approve` to preserve the rule's intent for audit purposes. Tests must cover both paths:
> - (a) Policy `auto_approve` on `requiresApproval=false` step → step proceeds without approval.
> - (b) Policy `auto_approve` on `requiresApproval=true` step → approval is still required; `effective_outcome=approval_required`; approval request is created.

### 8.4 Execution service hook point

Policy evaluation belongs in `ExecutionStepStartView` in `apps/api/apps/executions/internal_views.py`, immediately before the existing `if step.requires_approval:` branch. The current view flow is:

```text
Current (Phase 10.1):
  check idempotent waiting_for_approval
  if step.requires_approval → create approval request
  else → transition to running
```

Phase 10.2 replaces this with:

```text
Phase 10.2:
  check idempotent waiting_for_approval
  evaluate policy → PolicyEvaluation
  if effective_outcome == approval_required → create approval request (via request_step_approval)
  elif effective_outcome == auto_approve → transition to running
  elif effective_outcome == block → transition to failed; return runner_action=blocked
```

**Critical change to `apps/api/apps/approvals/services.py`:** The `request_step_approval` function currently has the guard:

```python
if not step.requires_approval:
    raise InvalidStateTransitionError(
        code="approval_not_required_for_step",
        detail="This step does not require approval.",
    )
```

This guard must be relaxed so that policy-driven approval can create requests on steps where `requires_approval=False`. Recommended approach: add an optional parameter `policy_driven: bool = False` and skip the guard when `policy_driven=True`. Alternatively, split into a separate internal helper `_create_approval_request_for_step(...)` that omits the guard and have `request_step_approval` call it.

Do not put policy evaluation in:

- Runner code.
- DRF serializer `validate_*` methods.
- React UI.
- Model `save()` hooks.
- Database triggers.

### 8.5 Interaction with Phase 10.1 approvals

`ApprovalRequired` calls the existing `request_step_approval` service (with `policy_driven=True` to bypass the `requires_approval` guard). The policy service must not create `ApprovalRequest` rows directly.

```python
evaluation = policies_services.evaluate_step_policy(execution=execution, step=step)

if evaluation.effective_outcome == "approval_required":
    ar, created = approval_services.request_step_approval(
        execution=execution,
        step=step,
        runner_id=runner_id,
        claim_token=claim_token,
        policy_driven=True,  # bypass requires_approval guard
    )
    # return wait_for_approval response
elif evaluation.effective_outcome == "auto_approve":
    # transition step to running
    step = services.update_execution_step(
        execution=execution, step_id=str(step_id),
        runner_id=runner_id, claim_token=claim_token,
        new_status=ExecutionStep.Status.RUNNING,
    )
    # return run response
elif evaluation.effective_outcome == "block":
    step = services.update_execution_step(
        execution=execution, step_id=str(step_id),
        runner_id=runner_id, claim_token=claim_token,
        new_status=ExecutionStep.Status.FAILED,
        failed_reason="policy_blocked",
    )
    # return blocked response
```

### 8.6 State transition effects

| Outcome | `effective_outcome` | Step transition | Approval behavior | Runner behavior |
|---|---|---|---|---|
| `auto_approve` (and `requires_approval=False`) | `auto_approve` | `pending -> running` | No approval request. | Execute command. |
| `auto_approve` (and `requires_approval=True`) | `approval_required` | `pending -> waiting_for_approval` | Create approval request. | Poll for approval. |
| `approval_required` | `approval_required` | `pending -> waiting_for_approval` | Create approval request. | Poll for approval. |
| `block` | `block` | `pending -> failed` | No approval request. | Receive `runner_action=blocked`; do not execute command. |

**`Block` uses `failed` step status** — there is no separate `blocked` status in `ExecutionStep.Status`. The `failed_reason` field (or error context in the step record) identifies the cause as `policy_blocked`.

### 8.7 Internal runner API contract

> **CRITICAL:** The runner MUST call `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/start/` for **every** step before executing any command. It must NOT inspect the local `requires_approval` workflow field and short-circuit.

Phase 10.2 adds `blocked` as a valid `runner_action`:

```json
{
  "execution_id": "uuid",
  "execution_status": "claimed",
  "step": {
    "id": "uuid",
    "status": "failed"
  },
  "runner_action": "blocked",
  "policy_evaluation": {
    "id": "uuid",
    "outcome": "block",
    "reason": "Database changes are blocked outside the maintenance window."
  },
  "poll_after_seconds": 0
}
```

`runner_action` values after Phase 10.2:

| Value | Step status | Meaning | Runner behavior |
|---|---|---|---|
| `run` | `running` | Proceed to execute command. | Execute command. |
| `wait_for_approval` | `waiting_for_approval` | Approval request created. | Enter approval poll loop. |
| `blocked` | `failed` | Policy blocked the step. | Do not execute; complete execution as failed. |

The view's docstring must be updated to document all three values.

**Required contract test:** `POST /start/` with `requiresApproval=false` workflow step + active matching policy → `runner_action=wait_for_approval`. This test must exist before Phase 10.2 is considered complete.

### 8.8 Idempotency and retries

- If a pending step is evaluated twice due to request retry, the service may create multiple `PolicyEvaluation` rows but must not create duplicate approval requests.
- If the step is already `waiting_for_approval`, return the existing approval state and latest evaluation without re-evaluating.
- If the step is already `running`, do not re-evaluate policy.
- If the step is terminal, return an invalid transition error.

### 8.9 Transaction boundaries

Use `transaction.atomic()` around the combined operation:

- Policy evaluation persistence.
- Step row lock (`select_for_update`).
- Approval request creation when required.
- Step status transition.

These must all commit together or all roll back together.

---

## 9. Frontend data contracts and policy management flows

### 9.1 Frontend types

Add policy types under `apps/web/src/features/policies/types.ts`:

```ts
export type PolicyOutcome = 'approval_required' | 'auto_approve' | 'block'
export type PolicyConditionType = 'risk_level' | 'step_type' | 'time_window'

export interface Policy {
  id: string
  organization_id: string
  name: string
  description: string
  is_active: boolean
  rule_count: number
  created_at: string
  updated_at: string
}

export interface PolicyRule {
  id: string
  name: string
  description: string
  is_active: boolean
  priority: number
  condition_type: PolicyConditionType
  condition_params: Record<string, unknown>
  outcome: PolicyOutcome
  reason: string
}

export interface PolicyDetail extends Policy {
  rules: PolicyRule[]
}

export interface PolicyEvaluationSummary {
  id: string
  outcome: PolicyOutcome
  effective_outcome: PolicyOutcome
  decision_source: 'policy_rule' | 'workflow_default'
  matched: boolean
  policy_id: string | null
  policy_name: string | null
  rule_id: string | null
  rule_name: string | null
  reason: string
  evaluated_at: string
}
```

Extend the execution step type in `apps/web/src/features/executions/types.ts` to include:

```ts
policy_evaluation: PolicyEvaluationSummary | null
```

### 9.2 Policy list flow

Route: `/policies`

- Require an organization selection using the existing organization UI pattern.
- Fetch `GET /api/v1/policies/?organization_id={id}&is_active=all`.
- Show name, active state, rule count, updated timestamp.
- Provide actions to create policy, open detail, activate/deactivate.
- Show both active and inactive policies with a visible filter.

### 9.3 Policy create/edit flow

- Create/edit only policy metadata on the policy form.
- Manage rules in a dedicated section so validation errors remain understandable.
- Do not allow changing `organization_id` after creation.
- Prefer deactivate over delete.

### 9.4 Rule create/edit flow

Rule form fields: name, description, active toggle, priority, condition type, condition params (structured controls per type), outcome, reason.

Structured controls by condition type:

- `risk_level`: operator select and values multi-input.
- `step_type`: operator select and values multi-input.
- `time_window`: timezone input, days of week selector, start/end time inputs, inside/outside selector.

Do not use a raw JSON editor as the primary UI.

### 9.5 Execution detail visibility

On `ExecutionDetailPage`:

- Show the latest policy evaluation for each step when present.
- Display `effective_outcome` as a pill: `Approval required`, `Auto approved`, or `Blocked`.
- Show policy name, rule name, reason, and evaluated timestamp.
- If `decision_source=workflow_default`, show "Workflow default" instead of policy/rule names.
- If `effective_outcome=block`, display the reason near the step error area.
- If `outcome != effective_outcome` (floor was applied), show a note: "Policy returned Auto Approve but Approval Required floor was applied."
- Do not let the frontend override, retry, or re-evaluate policy.

### 9.6 Frontend API boundaries

Frontend calls only:

- `GET /api/v1/policies/`
- `POST /api/v1/policies/`
- `GET /api/v1/policies/{id}/`
- `PATCH /api/v1/policies/{id}/`
- Rule subresource endpoints under `/api/v1/policies/{id}/rules/`
- `GET /api/v1/executions/{id}/`
- Optional: `GET /api/v1/executions/{id}/policy-evaluations/`

No frontend code calls `/api/v1/internal/...`, runner endpoints, AI service, or DB-backed direct adapters.

---

## 10. Ordered milestones

### Milestone 0: Preflight and approval gate

**Purpose:** Confirm repo state and Phase 10.1 baseline before writing code.

Files to read:

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-blueprint.md`
- `apps/api/apps/approvals/models.py`
- `apps/api/apps/approvals/services.py` (note the `if not step.requires_approval` guard at line 51)
- `apps/api/apps/executions/models.py` (confirm step status values)
- `apps/api/apps/executions/internal_views.py` (confirm `ExecutionStepStartView` structure)
- `apps/api/apps/executions/services.py`
- `apps/api/config/api_v1_urls.py`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `packages/workflow-schema/workflow.schema.json`

Commands:

```bash
docker compose exec api python manage.py test apps.executions apps.approvals
cd apps/web && npm test -- --run
cd apps/web && npm run typecheck
```

Verification:

- Phase 10.1 tests pass.
- Approval request lifecycle is implemented.
- `ExecutionStepStartView` is the confirmed policy hook point.
- `request_step_approval` guard is understood and the modification plan is approved.

Rollback: No changes in this milestone.

**Human approval gate:** Required before any Phase 10.2 code is written. Approver confirms policy outcomes, condition types, no-DSL boundary, and the plan for relaxing the `request_step_approval` guard.

---

### Milestone 1: Backend policy app skeleton and models

**Purpose:** Create persistence without wiring execution behavior yet.

Files touched:

- `apps/api/apps/policies/apps.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/policies/admin.py`
- `apps/api/apps/policies/migrations/0001_initial.py`
- `apps/api/apps/policies/tests/__init__.py`
- `apps/api/apps/policies/tests/test_models.py`
- `apps/api/config/settings/base.py` (add `apps.policies` to `INSTALLED_APPS`)

Commands:

```bash
docker compose exec api python manage.py makemigrations policies
docker compose exec api python manage.py migrate
docker compose exec api pytest apps/policies/tests/test_models.py -v
```

Verification:

- Migration creates `policies_policy`, `policies_policyrule`, and `policies_policyevaluation`.
- `(policy, priority)` unique constraint rejects duplicates.
- `(policy, name)` unique constraint rejects duplicates.
- `policy_evaluation` FK to `PolicyRule` is `PROTECT`.
- Inactive policies and rules remain queryable.

Rollback: Reverse the policies migration; remove app registration.

**Human approval gate:** Required before service behavior is added, because model fields become migration history.

---

### Milestone 2: Condition validation and policy evaluation service

**Purpose:** Implement deterministic policy evaluation without API or execution wiring.

Files touched:

- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/tests/test_services.py`

Commands:

```bash
docker compose exec api pytest apps/policies/tests/test_services.py -v
```

Verification:

- `risk_level in ["high", "critical"]` rules match expected values.
- `step_type` rules match expected values.
- `time_window` rules evaluate timezone-aware datetimes correctly using `zoneinfo`.
- Rules sort by `(priority, policy.created_at, policy.id, rule.id)` — lower priority evaluates first.
- First matching rule wins.
- No matching rule falls back to workflow default (`requires_approval` field).
- `auto_approve` on `requires_approval=True` step sets `effective_outcome=approval_required`.
- Invalid persisted condition params fail closed (evaluation returns `error_code`, does not auto-approve).
- Unknown condition type fails closed.
- Evaluation persists a `PolicyEvaluation` with full context snapshot.
- Inactive policies are excluded from evaluation.
- Inactive rules are excluded from evaluation.

Rollback: Revert service and tests only; model migration is unused but harmless.

**Human approval gate:** Required before wiring into execution transitions.

---

### Milestone 3: Approval service guard relaxation

**Purpose:** Modify `request_step_approval` to support policy-driven approval on `requires_approval=False` steps.

Files touched:

- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_services.py` (extend existing tests)

Specific change: add `policy_driven: bool = False` parameter to `request_step_approval`. Replace:

```python
if not step.requires_approval:
    raise InvalidStateTransitionError(
        code="approval_not_required_for_step",
        detail="This step does not require approval.",
    )
```

With:

```python
if not step.requires_approval and not policy_driven:
    raise InvalidStateTransitionError(
        code="approval_not_required_for_step",
        detail="This step does not require approval.",
    )
```

Commands:

```bash
docker compose exec api pytest apps/approvals/ -v
```

Verification:

- Existing Phase 10.1 tests still pass.
- `request_step_approval(policy_driven=True)` creates an approval request for a `requires_approval=False` step.
- `request_step_approval(policy_driven=False)` (default) still rejects `requires_approval=False` steps.

Rollback: Revert the guard change in `services.py`.

**Human approval gate:** Required before wiring into execution transitions, because this modifies Phase 10.1 service behavior.

---

### Milestone 4: Execution transition integration

**Purpose:** Enforce policy outcomes in the runner-controlled step transition path.

Files touched:

- `apps/api/apps/executions/internal_views.py` (main hook point)
- `apps/api/apps/executions/tests/test_policy_integration.py` (new)
- `apps/api/apps/executions/tests/test_approval_runner_api.py` (extend existing)
- `apps/api/apps/approvals/tests/test_policy_integration.py` (new)

Specific changes to `ExecutionStepStartView.post`:

1. Import `policies.services as policy_services`.
2. After the idempotent `waiting_for_approval` check, call `evaluate_step_policy`.
3. Replace the `if step.requires_approval:` branch with a dispatch on `evaluation.effective_outcome`.
4. Add `blocked` response path for `block` outcome.
5. Update the view docstring to document all three `runner_action` values.

Commands:

```bash
docker compose exec api pytest apps/executions/tests/test_policy_integration.py apps/approvals/tests/test_policy_integration.py apps/policies/ -v
```

Verification:

- `AutoApprove` transitions pending step to `running`; `runner_action=run`.
- `ApprovalRequired` transitions pending step to `waiting_for_approval`; approval request created; `runner_action=wait_for_approval`.
- Policy `AutoApprove` on `requires_approval=True` step → `effective_outcome=approval_required`; approval request created; `runner_action=wait_for_approval`.
- `Block` transitions pending step to `failed`; `runner_action=blocked`; no approval request created.
- No matching policy and `requires_approval=False` → `AutoApprove`; `runner_action=run`.
- No matching policy and `requires_approval=True` → `ApprovalRequired`; existing approval flow unchanged.
- Concurrent start attempts do not duplicate approval requests or corrupt step state.
- Policy evaluation exception → step transitions to `failed`; `runner_action=blocked`; no auto-approve.
- Existing Phase 10.1 approval tests still pass.

Rollback:

- Revert execution integration; keep policy CRUD disabled.
- If a migration added an optional `policy_evaluation` FK to approvals, reverse only if no production data exists.

**Human approval gate:** Required before exposing policy management APIs, because policies now affect execution behavior.

---

### Milestone 5: Public policy CRUD API

**Purpose:** Expose policy and rule management through Django public APIs.

Files touched:

- `apps/api/apps/policies/serializers.py`
- `apps/api/apps/policies/views.py`
- `apps/api/apps/policies/urls.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/policies/tests/test_api.py`

Commands:

```bash
docker compose exec api pytest apps/policies/tests/test_api.py apps/policies/tests/test_services.py -v
```

Verification:

- Policy list filters by `organization_id`.
- Policy detail includes rules ordered by priority.
- Create/update/deactivate policy works.
- Create/update/deactivate rule works.
- Invalid condition params return `400`.
- Duplicate active policy name returns `409`.
- Duplicate rule priority returns `409`.
- Cross-tenant policy access returns `404`.
- `policy_evaluation` FK violations on rule hard-delete return an appropriate error.

Rollback: Remove URL registration to disable public API while preserving model data.

**Human approval gate:** Required before frontend CRUD is added.

---

### Milestone 6: Execution detail policy visibility API

**Purpose:** Make policy decisions visible on execution detail.

Files touched:

- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/tests/test_api_contracts.py` (extend)
- Optional: `apps/api/apps/policies/serializers.py` (shared serializer for evaluation summary)

Commands:

```bash
docker compose exec api pytest apps/executions/tests/test_api_contracts.py apps/executions/tests/test_policy_integration.py -v
```

Verification:

- Execution detail embeds latest `PolicyEvaluation` per step.
- Steps with no evaluation serialize `policy_evaluation: null`.
- `effective_outcome` is present in the serialized shape.
- Evaluation data does not expose policies from another organization.
- Optional evaluation history endpoint is tenant-scoped.

Rollback: Remove serializer field; enforcement remains active if backend tests pass.

**Human approval gate:** Required before frontend execution detail changes.

---

### Milestone 7: Frontend policy management

**Purpose:** Add policy CRUD UI without adding new backend behavior.

Files touched (see section 4 for full list):

- `apps/web/src/features/policies/` (all files)
- `apps/web/src/routes/policies/PoliciesPage.tsx` + test
- `apps/web/src/routes/policies/PolicyDetailPage.tsx` + test
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`

Commands:

```bash
cd apps/web && npm test -- --run
cd apps/web && npm run typecheck
cd apps/web && npm run lint
```

Verification:

- Policy list renders active and inactive policies.
- Create/edit policy form calls Django public API only.
- Rule form uses structured controls per condition type.
- API errors render through existing error handling.
- Navigation exposes policies without breaking existing routes.

Rollback: Remove route and navigation entry to hide the UI.

**Human approval gate:** Required before final integration/manual testing.

---

### Milestone 8: Frontend execution detail policy visibility

**Purpose:** Show policy decisions where operators debug executions.

Files touched:

- `apps/web/src/features/executions/types.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`

Commands:

```bash
cd apps/web && npm test -- --run ExecutionDetailPage
cd apps/web && npm run typecheck
```

Verification:

- Policy evaluation summary appears under the correct step.
- `effective_outcome` is shown as the primary pill.
- `outcome != effective_outcome` case displays a floor-applied note.
- Workflow default evaluations render clearly without policy/rule names.
- Blocked evaluations show reason near failure/error status.
- Existing execution polling behavior is unchanged.

Rollback: Revert execution detail UI changes only.

**Human approval gate:** Required before declaring Phase 10.2 complete.

---

### Milestone 9: End-to-end manual gate

Commands:

```bash
docker compose up -d
docker compose exec api python manage.py migrate
docker compose exec api pytest apps/policies/ apps/executions/ apps/approvals/ -v
cd apps/web && npm run test:ci
```

Manual verification:

1. Create an organization and a workflow with `risk=critical` and `requiresApproval=false`.
2. Create an active policy rule: risk `critical` → `approval_required`.
3. Start an execution; confirm the step enters `waiting_for_approval`.
4. Approve from the Phase 10.1 approval UI; confirm runner proceeds.
5. Create an active policy rule with higher priority (lower number): same risk → `block`.
6. Start a new execution; confirm the step enters `failed` and command is not executed.
7. Deactivate the block rule; confirm the approval rule applies again.
8. Create a workflow with `risk=high` and `requiresApproval=true`; create a policy rule: risk `high` → `auto_approve`.
9. Start an execution; confirm approval is still required despite the `auto_approve` policy (floor behavior).
10. Deactivate all policies; confirm workflow default behavior applies.
11. Open execution detail; confirm policy evaluation visibility is accurate for all three outcome types.

Rollback: Deactivate policies through the public API to stop enforcement. If code rollback is needed, revert Phase 10.2 commits in reverse milestone order.

**Human approval gate:** Required sign-off from product/engineering owner after manual verification.

---

## 11. Testing strategy

### 11.1 Policy service tests

Cover:

- Active policy with matching `risk_level` returns `approval_required`.
- Active policy with matching `step_type` returns configured outcome.
- Active policy with matching `time_window` returns configured outcome.
- Inactive policies are ignored during evaluation.
- Inactive rules are ignored during evaluation.
- Lower numeric priority evaluates before higher numeric priority.
- Cross-policy priority ties are deterministic (secondary sort by `policy.created_at, policy.id, rule.id`).
- First matching rule wins.
- No matching rules fall back to `step.requires_approval`.
- `auto_approve` rule + `requires_approval=True` step → `effective_outcome=approval_required`.
- `auto_approve` rule + `requires_approval=False` step → `effective_outcome=auto_approve`.
- Evaluation creates a `PolicyEvaluation` with full context snapshot.
- Invalid persisted condition params fail closed — do not auto-approve.
- Unknown condition type fails closed.
- Timezone and DST-sensitive `time_window` cases do not crash.
- Empty policy list (no active policies) falls back to workflow default.

### 11.2 API tests

Cover:

- Policy list filters by organization.
- Policy detail includes rules ordered by priority.
- Policy create validates required fields.
- Policy update does not allow organization changes.
- Policy deactivate removes it from evaluation but not from list when `is_active=all`.
- Rule create validates structured params per condition type.
- Rule update validates priority uniqueness within the policy.
- Rule deactivate removes it from evaluation.
- Duplicate active policy names return `409`.
- Cross-tenant reads and writes return `404`.

### 11.3 Integration with approvals

These tests must exist before Phase 10.2 is considered complete:

- `ApprovalRequired` creates an approval request even when workflow step has `requires_approval=False`.
- Existing workflow `requires_approval=True` still creates an approval request when no policy matches (unchanged from Phase 10.1 behavior).
- Policy `AutoApprove` on a `requires_approval=True` step results in `ApprovalRequired` behavior: approval request is created; `policy_evaluation.outcome=auto_approve`; `policy_evaluation.effective_outcome=approval_required`; command does not execute without approval.
- Policy `AutoApprove` on a `requires_approval=False` step: step proceeds without approval; no approval request created.
- Policy `Block` on any step (regardless of `requires_approval`) prevents command execution; step transitions to `failed`.
- `runner_action=blocked` is returned when `Block` is the effective outcome.
- Approval polling behavior from Phase 10.1 remains unchanged after policy integration.
- Concurrent step-start requests do not create duplicate approval requests.

### 11.4 Failure-path tests

Cover:

- Policy service exception prevents command execution (step goes to `failed`).
- Invalid persisted condition params prevent command execution.
- Database write failure while creating `PolicyEvaluation` returns a safe error.
- Approval service failure after `ApprovalRequired` does not leave the step in `running`.
- Blocked step never enters `running`.
- Runner retry on a `waiting_for_approval` step does not create duplicate approval requests.
- Terminal step cannot be re-evaluated into `running`.

### 11.5 Multi-tenant isolation tests

Cover:

- Organization A policy does not affect Organization B execution.
- Organization A cannot list Organization B policies.
- Organization A cannot create rules under Organization B policies.
- `PolicyEvaluation` records always carry the execution's organization.
- Execution detail for Organization A never includes policy names from Organization B.
- UUIDs from another tenant return `404`.

### 11.6 Frontend tests

Cover:

- Policy list renders fetched policies including inactive ones.
- Policy list sends `organization_id`.
- Policy form submits only public API requests.
- Rule form renders structured controls by condition type.
- Invalid rule API errors render visibly.
- Execution detail renders `policy_evaluation` summary per step.
- Execution detail handles `policy_evaluation: null`.
- Execution detail shows `effective_outcome` as the primary pill.
- Floor-applied case (`outcome != effective_outcome`) shows the appropriate note.
- Query invalidation refreshes list/detail after create, update, and deactivate.

### 11.7 Manual gate

The manual gate must exercise all three effective outcomes:

- `AutoApprove`: step runs without approval.
- `ApprovalRequired` (from rule): step waits; approval UI resolves it; runner proceeds.
- `ApprovalRequired` (floor applied on `auto_approve` rule): same behavior.
- `Block`: step does not run; operator can see the policy reason on execution detail.

The manual gate must also confirm no runner or frontend request bypasses Django.

---

## 12. Failure modes and risks

### Silent policy miss

Risk: a malformed rule, bad query, or service exception results in no policy being applied and the step runs.

Mitigation:

- Fail closed on evaluation errors.
- Persist `PolicyEvaluation` records for workflow-default decisions so there is always a record.
- Add tests for invalid persisted rules.
- Log evaluation errors at ERROR level with execution context.

### Policy latency

Risk: policy evaluation runs in the execution hot path and slows step transitions.

Mitigation:

- Query active policies and rules with `prefetch_related` in a single query pair.
- Index active policy and ordered rule lookups.
- Keep condition evaluation in plain Python — no external calls.
- Do not cache policies across requests yet. Profile first if latency is observed.

### Conflicting rules

Risk: multiple rules could match and operators cannot predict which applies.

Mitigation:

- Use explicit priority with unique-per-policy constraint.
- Use deterministic global sort key.
- Use first-match semantics.
- Surface matched policy and rule on execution detail.
- Reject duplicate priorities at the service level.

### Nondeterministic ordering

Risk: database default ordering changes produce different outcomes.

Mitigation:

- Never rely on implicit database ordering.
- Sort by `(priority, policy.created_at, policy.id, rule.id)` explicitly in the service.
- Test tie cases to confirm determinism.

### Cross-tenant leakage

Risk: Organization A policies affect or appear in Organization B executions.

Mitigation:

- Scope all policy queries by `execution.organization_id`.
- Denormalize `organization` onto `PolicyEvaluation`.
- Validate organization consistency in services before any mutation.
- Add multi-tenant API and service tests.

### `requiresApproval` floor bypass

Risk: `AutoApprove` waives an explicit workflow approval flag unexpectedly.

Mitigation:

- `effective_outcome` field makes the floor application visible.
- Tests explicitly cover the floor case.
- The execution service dispatch checks `effective_outcome`, not `outcome`.

### Policy-approval service mismatch

Risk: policy says approval required, but approval service creates duplicate or mismatched requests.

Mitigation:

- Pass `policy_driven=True` to `request_step_approval` when calling from policy integration.
- Approval creation stays inside the same `transaction.atomic()` block as the step transition.
- One approval request per step is enforced by the `OneToOneField` on `step` in `ApprovalRequest`.

---

## 13. What NOT to do

- Do not build a rules engine DSL.
- Do not embed Python, JavaScript, SQL, Rego, CEL, JSONLogic, or expression strings in policy conditions.
- Do not add policy inheritance between organizations.
- Do not add global policies shared across organizations in Phase 10.2.
- Do not add team, role, or RBAC-based policy routing in this phase.
- Do not mutate commands, command arguments, environment variables, workflow definitions, or runner payloads from policies.
- Do not add policy dry-run mode unless explicitly scoped in a later blueprint.
- Do not introduce queues, Kafka, Celery, RabbitMQ, event buses, or background workers.
- Do not create a policy microservice.
- Do not let the runner read policy data or evaluate rules.
- Do not let the frontend call internal runner APIs.
- Do not call the AI service for policy decisions.
- Do not make policy evaluation asynchronous.
- Do not add WebSocket or SSE behavior for policy updates.
- Do not hard-delete policies or rules that have evaluation history (FK `PROTECT` enforces this).
- Do not put policy business logic in views, serializers, model hooks, or admin actions.
- Do not introduce a new `blocked` step status — use `failed` with a `failed_reason` of `policy_blocked`.
- Do not expose the `request_step_approval` guard relaxation as a public API parameter.

---

## 14. Definition of done

Phase 10.2 is complete when all of the following are true:

- `Policy`, `PolicyRule`, and `PolicyEvaluation` models exist with UUID primary keys, tenant scoping, indexes, constraints, and migrations.
- Policy conditions support only structured `risk_level`, `step_type`, and `time_window` contracts.
- Policy outcomes are limited to `approval_required`, `auto_approve`, and `block`.
- `PolicyEvaluation` records both `outcome` (raw rule match) and `effective_outcome` (after `requiresApproval` floor).
- Rule evaluation is deterministic and explicitly ordered by `(priority, policy.created_at, policy.id, rule.id)`.
- Policy evaluation is wired into `ExecutionStepStartView` in `apps/api/apps/executions/internal_views.py` before command execution.
- `apps/api/apps/approvals/services.py` has been modified to accept `policy_driven=True` and allow approval requests on `requires_approval=False` steps.
- `ApprovalRequired` integrates with the Phase 10.1 `request_step_approval` service without duplicating approval lifecycle logic.
- `runner_action=blocked` is returned for `Block` outcome; step transitions to `failed`.
- `AutoApprove` and `Block` behavior is explicitly tested and documented.
- Public policy CRUD APIs exist under `/api/v1/policies/`.
- Internal runner behavior remains under `/api/v1/internal/` and the runner does not evaluate policies.
- Execution detail exposes latest `PolicyEvaluation` visibility including `effective_outcome`.
- Frontend policy management CRUD exists using Django public APIs only.
- Frontend execution detail shows policy decisions per step with floor-applied cases clearly marked.
- Service, API, approval integration, failure-path, multi-tenant, and frontend tests pass.
- Manual verification covers all three effective outcomes: `ApprovalRequired`, `AutoApprove`, and `Block`.
- The floor case (`auto_approve` rule on `requires_approval=True` step) is verified manually.
- No queues, event infrastructure, microservices, DSLs, command mutation, policy inheritance, dry-run mode, or new step status enum values were introduced.
- The implementation has been reviewed against this blueprint and the Phase 10 roadmap before merge.

---

## Summary

**File created:** `docs/blueprints/phase-10-02-policies-blueprint.md`

**Major sections:** Purpose and sequencing rationale; current-state inspection checklist (including specific line references to Phase 10.1 code); architecture invariants; implementation scope; data model (Policy, PolicyRule, PolicyEvaluation with `effective_outcome` field); condition contract (risk_level, step_type, time_window with structured params); API contracts for CRUD and evaluation visibility; service contracts including the `requiresApproval=True` floor architecture decision; approval service guard relaxation plan; `runner_action=blocked` contract; frontend types and flows; nine ordered milestones with files, commands, verification, rollback, and human approval gates; testing strategy; failure modes; what not to do; definition of done.

**Key assumptions:**

- Phase 10.1 is fully implemented. `ApprovalRequest`, `ApprovalDecision`, `request_step_approval`, `get_approval_status`, `decide_approval`, and the `WAITING_FOR_APPROVAL` step status all exist and pass tests.
- `apps/api/apps/policies/` is a pure stub (only `__init__.py`) at the time Phase 10.2 implementation begins.
- There is no `blocked` step status in `ExecutionStep.Status`; the `block` policy outcome maps to the existing `failed` status.
- `ExecutionStepStartView.post` currently returns `runner_action` values `run` and `wait_for_approval` only; Phase 10.2 adds `blocked`.
- The `request_step_approval` service has an `if not step.requires_approval: raise` guard at line 51 that must be relaxed with a `policy_driven=True` parameter.
- Auth/RBAC is not complete, so organization scoping remains explicit in public policy API payloads.
