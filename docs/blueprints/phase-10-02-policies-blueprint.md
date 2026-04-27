# Phase 10.2: Policies Expansion Blueprint

| Field | Value |
|---|---|
| Phase number | 10.2 |
| Phase name | Policies |
| Objective | Add organization-scoped policy rules that deterministically decide whether execution steps require approval, can auto-proceed, or must be blocked. |
| Status | Blueprint only |
| Depends on | Phases 01-09 complete and verified; Phase 10.1 approvals complete and verified |
| Authored | 2026-04-23 |

---

## 1. Purpose and sequencing rationale

Phase 10.2 adds organization-scoped execution policies. Policies are the platform's centralized rule layer: they decide whether a step must pause for approval, may proceed automatically, or must be blocked before the runner executes it.

This phase assumes Phase 10.1 approvals are complete and verified. That assumption is mandatory because policies do not replace approvals. Policies decide when approval behavior is required, waived, or forbidden. A policy outcome of `ApprovalRequired` must route into the existing approval lifecycle. A policy outcome of `AutoApprove` must let Django transition the step without creating an approval request. A policy outcome of `Block` must fail or block the step before the runner executes the command.

Policies come after approvals for four reasons:

1. Approvals provide the concrete control-plane mechanism that policies can invoke.
2. Policies need stable step states, approval request semantics, and approval timeout behavior before they can make safe decisions.
3. Centralized policy rules prevent teams from encoding approval logic manually in workflow definitions once approvals exist.
4. The policy evaluation records created in this phase become a key input to Phase 10.3 audit trail, but they are not the audit trail themselves.

Policies come before audit trail because audit needs stable event sources. Once approvals and policy evaluations exist, Phase 10.3 can record meaningful events such as "policy blocked step", "policy waived manual approval", and "policy required approval". Building audit before policies would force a second event taxonomy migration immediately afterward.

Phase 10.2 must produce a deterministic, explainable decision for every step transition that enters the execution hot path. The goal is not to build a generic rules platform. The goal is to add a small, inspectable policy layer that is safe under multi-tenant conditions and easy to test.

---

## 2. Current-state inspection checklist

Before implementation begins, inspect the repository in this order. Do not implement from this blueprint without re-reading the current source files first.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` and confirm Phase 10.2 still follows approvals and precedes audit trail.
- [ ] Read `docs/blueprints/phase-10-01-approvals-blueprint.md` if present, then inspect the implemented Phase 10.1 code rather than relying only on the blueprint.
- [ ] Confirm `apps/api/apps/approvals/` contains implemented models, services, serializers, views, URLs, migrations, and tests.
- [ ] Confirm the approval service exposes a service-level entry point that can create an approval request from a step transition without duplicating view logic.
- [ ] Confirm `apps/api/apps/executions/models.py` includes `Execution` and `ExecutionStep`, and that `ExecutionStep` has fields equivalent to `step_type`, `risk_level`, `requires_approval`, `step_snapshot`, and status values including `waiting_for_approval`.
- [ ] Confirm `apps/api/apps/executions/services.py` owns runner step transition logic and is the correct hook point for policy evaluation.
- [ ] Confirm internal runner APIs are still defined under `/api/v1/internal/` in `apps/api/config/api_v1_urls.py`.
- [ ] Confirm public APIs are still registered under `/api/v1/` and no frontend code calls the runner or AI service directly.
- [ ] Confirm `apps/api/apps/organizations/models.py` still defines the organization tenant boundary used by workflows and executions.
- [ ] Confirm `apps/api/apps/policies/` is still a stub or contains only incomplete scaffolding; if it already contains code, audit it before extending.
- [ ] Confirm `packages/workflow-schema/workflow.schema.json` still includes step `risk`, `type`, and `requiresApproval` fields.
- [ ] Confirm `apps/web/src/features/executions/` and `apps/web/src/routes/executions/ExecutionDetailPage.tsx` expose execution step detail data that can be extended with policy evaluation visibility.
- [ ] Confirm `apps/web/src/app/router.tsx`, `apps/web/src/app/AppLayout.tsx`, and `apps/web/src/shared/lib/queryKeys.ts` are the correct places to add a policy management route and query keys.
- [ ] Confirm current tests for executions, approvals, organizations, and frontend routes are passing before adding policy work.

At blueprint authoring time, the source tree contains the expected Phase 01-09 vertical-slice shape: `apps/api/apps/policies/` exists only as a stub, execution steps already materialize risk and type fields, Django owns runner transitions through services, and the frontend has execution detail polling but no policy management UI. Because the baseline for this phase assumes Phase 10.1 has since been completed, implementation must re-inspect the source after approvals land.

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
| Internal runner APIs remain under `/api/v1/internal/`. | Any runner-visible policy outcome is returned through existing or new internal execution endpoints under `/api/v1/internal/`. |
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

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.2 |
|---|---|
| `apps/api/apps/policies/` | Implement Django app with models, migrations, admin, services, serializers, public views, URLs, and tests. |
| `apps/api/apps/approvals/` | Add a policy-aware service integration point so `ApprovalRequired` creates or reuses the Phase 10.1 approval request path. |
| `apps/api/apps/executions/` | Hook policy evaluation into step transition services before a command can run; expose policy evaluations in execution detail. |
| `apps/api/apps/organizations/` | Reuse organization as the tenant boundary; do not add hierarchy or inheritance. |
| `apps/api/config/` | Register the policies app and include policy URLs under `/api/v1/`. |
| `apps/web/src/features/policies/` | Add frontend policy types, API client functions, hooks, form helpers, and tests. |
| `apps/web/src/routes/policies/` | Add policy list, create, edit, detail, and rule management route components. |
| `apps/web/src/routes/executions/` | Show policy evaluation results on execution detail and per-step rows. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add policy and policy evaluation query keys. |
| `packages/workflow-schema/` | No schema change expected; policies consume existing step fields. Document this explicitly if README updates are included. |

Likely backend files touched:

- `apps/api/apps/policies/apps.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/policies/admin.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/serializers.py`
- `apps/api/apps/policies/views.py`
- `apps/api/apps/policies/urls.py`
- `apps/api/apps/policies/tests/test_models.py`
- `apps/api/apps/policies/tests/test_services.py`
- `apps/api/apps/policies/tests/test_api.py`
- `apps/api/apps/policies/migrations/0001_initial.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_policy_integration.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/tests/test_policy_integration.py`
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

- Runner executor code. The runner should continue to ask Django to start or transition a step; Django returns the resulting state. The runner should not evaluate policies locally.
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
| `organization` | FK -> `organizations.Organization` | Required tenant boundary. Use `PROTECT` or `CASCADE` consistently with adjacent domain models. |
| `name` | `CharField(255)` | Human-readable policy name unique per organization among active policies. |
| `description` | `TextField(blank=True)` | Operator-facing explanation. |
| `is_active` | `BooleanField(default=True)` | Inactive policies are ignored during evaluation but remain visible for history. |
| `created_by_label` | `CharField(255, blank=True)` | Optional bridge until real auth is complete. Do not build RBAC here. |
| `updated_by_label` | `CharField(255, blank=True)` | Optional bridge until real auth is complete. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| index | `(organization, is_active, name)` | Fast management listing and active policy load. |
| index | `(organization, created_at)` | Tenant-scoped historical listing. |
| unique constraint | `(organization, name)` where `is_active=True` | Prevent ambiguous active policy names while allowing inactive historical duplicates if needed. |

Active/inactive behavior:

- `is_active=False` means no rules under the policy are evaluated.
- Deactivation must not delete `PolicyRule` or `PolicyEvaluation` records.
- Deactivated policies remain readable by public API so historical evaluations can still render names.
- Reactivation should validate that no active policy in the same organization already uses the same name.
- Hard delete is not required for Phase 10.2. Prefer deactivate over delete to preserve explainability.

### 5.2 `PolicyRule`

`PolicyRule` is one structured condition and one outcome within a policy.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `policy` | FK -> `Policy` | Related name `rules`. |
| `name` | `CharField(255)` | Human-readable rule label. |
| `description` | `TextField(blank=True)` | Why the rule exists. |
| `is_active` | `BooleanField(default=True)` | Inactive rules are ignored but remain visible. |
| `priority` | `PositiveIntegerField` | Lower number evaluates first within the organization-wide rule set. |
| `condition_type` | enum | `risk_level`, `step_type`, or `time_window`. |
| `condition_params` | `JSONField(default=dict)` | Structured params validated by service and serializer. |
| `outcome` | enum | `approval_required`, `auto_approve`, or `block`. |
| `reason` | `TextField(blank=True)` | Operator-facing reason copied into evaluations. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| index | `(policy, is_active, priority)` | Deterministic rule loading for one policy. |
| index | `(condition_type, outcome)` | Support admin/debug queries. |
| unique constraint | `(policy, priority)` | No ambiguous ordering inside one policy. |
| unique constraint | `(policy, name)` | Prevent duplicate rule labels inside one policy. |
| check constraint | `priority > 0` | Avoid zero or negative priorities. |

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
- If the product later needs multiple matching rules, add a separately scoped design for conflict resolution and explainability.

### 5.3 `PolicyEvaluation`

`PolicyEvaluation` records what Django decided for a specific execution step at the policy hook point.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Denormalized tenant boundary for isolation and querying. |
| `execution` | FK -> `executions.Execution` | Execution being evaluated. |
| `step` | FK -> `executions.ExecutionStep` | Step being evaluated. |
| `policy` | FK -> `Policy`, nullable | Null when no policy rule matched and the workflow default was used. Use `PROTECT` if policies are not hard-deleted. |
| `rule` | FK -> `PolicyRule`, nullable | Null when no rule matched. |
| `matched` | `BooleanField` | True when a policy rule matched. |
| `outcome` | enum | `approval_required`, `auto_approve`, or `block`. |
| `decision_source` | enum | `policy_rule` or `workflow_default`. |
| `condition_type` | `CharField(32, blank=True)` | Snapshot of matched condition type. |
| `condition_params_snapshot` | `JSONField(default=dict)` | Snapshot of matched rule params. |
| `context_snapshot` | `JSONField(default=dict)` | Step attributes used for evaluation: risk, type, organization, execution, step id, local evaluation time. |
| `reason` | `TextField(blank=True)` | Copied from rule or generated default reason. |
| `error_code` | `CharField(64, blank=True)` | Filled only if evaluation fails and the service records the failure. |
| `error_message` | `TextField(blank=True)` | Debuggable but non-secret error detail. |
| `evaluated_at` | `DateTimeField` | Set at evaluation time. |

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
- Runner retries, service retries, and resume flows may legitimately evaluate the same step more than once.
- The execution service should avoid unnecessary duplicate evaluations by evaluating only at the transition boundary where a pending step is about to proceed.
- Execution detail should show the latest evaluation per step by default and optionally include full evaluation history if the API supports it.

Retention:

- `PolicyEvaluation` records are not immutable audit records yet, but they should be treated as append-only.
- Do not expose update or delete endpoints for evaluations.
- Phase 10.3 audit can subscribe to service-level events later; Phase 10.2 should not retrofit audit tables.

### 5.4 Outcome enum

Use storage values that are lowercase and API-friendly:

| API/storage value | Display value | Meaning |
|---|---|---|
| `approval_required` | `ApprovalRequired` | Create or reuse an approval request and pause before command execution. |
| `auto_approve` | `AutoApprove` | Proceed without creating an approval request. |
| `block` | `Block` | Do not execute the step. Mark the step failed or blocked using the execution service contract. |

Do not add `warn`, `manual_review`, `escalate`, `notify`, or `require_two_approvers` in Phase 10.2. Those require separate approval routing and audit semantics.

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
  "evaluated_at": "2026-04-23T20:00:00Z",
  "workflow_id": "uuid",
  "workflow_version": 7
}
```

The service should build this context from `Execution`, `ExecutionStep`, and the materialized step snapshot. The runner must not provide policy context except through the existing step transition request.

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
- `values` must be a non-empty list of strings for `in`.
- `value` must be a string for `equals` if that shape is used.
- Comparisons should be case-sensitive unless existing workflow schema normalization says otherwise.
- Unknown risk values should not crash evaluation; they simply fail to match unless explicitly listed.

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
- `values` must be a non-empty list of strings for `in`.
- `value` must be a string for `equals` if that shape is used.
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

- `timezone` must be an IANA timezone name.
- `days_of_week` must be a non-empty list using `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`.
- `start_time` and `end_time` must be `HH:MM` 24-hour local times.
- `match_when` must be `inside` or `outside`.
- Evaluation must use Django timezone-aware datetimes.
- Overnight windows are allowed only if explicitly implemented and tested. If not implemented in the first milestone, reject `start_time >= end_time` at validation time.
- Daylight saving transitions must not crash evaluation. Use Python `zoneinfo`, not hand-rolled offsets.

### 6.5 Condition validation ownership

Validation belongs in both serializers and services:

- Serializers reject malformed API payloads early.
- Services revalidate before saving or evaluating so tests can call services directly.
- Model `JSONField` alone is not validation.

Invalid condition params should return `400 Bad Request` for CRUD APIs. Invalid persisted rules encountered during evaluation should fail closed: record a `PolicyEvaluation` with an error and transition the step to a failed/blocked state rather than silently auto-approving.

---

## 7. API contracts for policy CRUD and evaluation visibility

All public APIs stay under `/api/v1/`. Use existing DRF patterns and the existing error envelope.

### 7.1 `GET /api/v1/policies/`

Purpose: list policies for an organization.

Query parameters:

| Param | Required | Notes |
|---|---|---|
| `organization_id` | yes until auth/RBAC exists | Explicit tenant scope. |
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
      "created_at": "2026-04-23T20:00:00Z",
      "updated_at": "2026-04-23T20:00:00Z"
    }
  ]
}
```

### 7.2 `POST /api/v1/policies/`

Purpose: create a policy.

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

Purpose: retrieve policy detail with ordered rules.

Response:

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
  "created_at": "2026-04-23T20:00:00Z",
  "updated_at": "2026-04-23T20:00:00Z"
}
```

### 7.4 `PATCH /api/v1/policies/{policy_id}/`

Purpose: update policy metadata or active state.

Allowed fields:

- `name`
- `description`
- `is_active`

Do not allow organization changes after creation.

### 7.5 `POST /api/v1/policies/{policy_id}/rules/`

Purpose: create a rule under a policy.

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

Purpose: update a rule.

Allowed fields:

- `name`
- `description`
- `is_active`
- `priority`
- `condition_type`
- `condition_params`
- `outcome`
- `reason`

Do not move a rule to another policy.

### 7.7 `DELETE /api/v1/policies/{policy_id}/rules/{rule_id}/`

Preferred behavior: soft-deactivate by setting `is_active=false`.

If a hard delete endpoint is implemented, it must be blocked once a rule has any `PolicyEvaluation` records. Soft deactivation is simpler and safer for Phase 10.2.

### 7.8 Execution detail policy visibility

Extend `GET /api/v1/executions/{execution_id}/` to include policy evaluation summaries. Keep the shape compact.

Recommended response addition:

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
        "decision_source": "policy_rule",
        "matched": true,
        "policy_id": "uuid",
        "policy_name": "Production safety policy",
        "rule_id": "uuid",
        "rule_name": "High risk requires approval",
        "reason": "High-risk steps require human approval.",
        "evaluated_at": "2026-04-23T20:00:00Z"
      }
    }
  ]
}
```

If multiple evaluations exist for a step, this embedded field should show the latest evaluation. If full history is needed, add:

`GET /api/v1/executions/{execution_id}/policy-evaluations/`

Response:

```json
{
  "results": [
    {
      "id": "uuid",
      "step_id": "uuid",
      "step_key": "deploy",
      "outcome": "approval_required",
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
      "evaluated_at": "2026-04-23T20:00:00Z"
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
def create_policy(*, organization, name: str, description: str = "", is_active: bool = True) -> Policy:
    ...

def update_policy(*, policy: Policy, **changes) -> Policy:
    ...

def create_rule(*, policy: Policy, name: str, priority: int, condition_type: str, condition_params: dict, outcome: str, **optional) -> PolicyRule:
    ...

def update_rule(*, rule: PolicyRule, **changes) -> PolicyRule:
    ...

def evaluate_step_policy(*, execution: Execution, step: ExecutionStep, evaluated_at=None) -> PolicyEvaluation:
    ...
```

`evaluate_step_policy` must:

1. Validate tenant consistency.
2. Build a normalized evaluation context from Django-owned models.
3. Load active policies for `execution.organization`.
4. Load active rules for active policies.
5. Sort rules using the deterministic global sort key.
6. Evaluate structured conditions without using a DSL.
7. Persist a `PolicyEvaluation`.
8. Return the persisted evaluation to the execution service.

### 8.2 Evaluation algorithm

Recommended algorithm:

```text
Input: execution, step

1. Assert step.execution_id == execution.id.
2. Assert execution.organization_id is present.
3. Build context from execution and step.
4. Query active policies for organization.
5. Query active rules under those policies.
6. Sort by (priority, policy.created_at, policy.id, rule.id).
7. For each rule:
   a. Validate condition params.
   b. If condition matches, persist PolicyEvaluation with rule outcome and return it.
8. If no rule matched:
   a. outcome = approval_required if step.requires_approval else auto_approve
   b. persist PolicyEvaluation with decision_source=workflow_default
   c. return it.
```

Failure behavior:

- If policy loading fails, condition validation fails, or evaluation raises unexpectedly, fail closed.
- Failing closed means the execution service must prevent command execution.
- Persist a `PolicyEvaluation` with `outcome=block` and error fields if safe to do so.
- If a database error prevents even the evaluation record from being saved, return a domain error to the execution service and transition the step to failed with a policy error message.

### 8.3 Execution service hook point

Policy evaluation belongs at the step transition boundary before a command can run.

Recommended integration shape:

```text
Runner asks Django to start pending step
  -> execution service validates runner ownership
  -> execution service locks execution/step rows as needed
  -> execution service evaluates policy for the step
  -> outcome drives state transition:
     - AutoApprove: pending -> running
     - ApprovalRequired: pending -> waiting_for_approval and create/reuse ApprovalRequest
     - Block: pending -> failed, execution fails or remains controlled according to existing execution semantics
  -> internal API returns resulting step status and policy evaluation summary
```

Do not put policy evaluation in:

- Runner code.
- DRF serializer validation.
- React UI.
- Model `save()` hooks.
- Database triggers.

### 8.4 Interaction with Phase 10.1 approvals

`ApprovalRequired` should call the existing approval service. The policy service should not create approval rows directly unless the approval service contract explicitly owns that call.

Recommended boundary:

```python
evaluation = policies.services.evaluate_step_policy(execution=execution, step=step)

if evaluation.outcome == PolicyOutcome.APPROVAL_REQUIRED:
    approval = approvals.services.create_or_get_step_approval(
        execution=execution,
        step=step,
        requested_by_runner_id=runner_id,
        policy_evaluation=evaluation,
    )
    transition_step_to_waiting_for_approval(...)
```

Approval records should optionally reference `PolicyEvaluation` if Phase 10.1 schema can be safely extended. If not, the link can be derived through step id in Phase 10.2 and formalized later.

### 8.5 State transition effects

Policy outcome behavior:

| Outcome | Step transition | Approval behavior | Runner behavior |
|---|---|---|---|
| `auto_approve` | `pending -> running` | No approval request created. | Runner executes command after Django returns `running`. |
| `approval_required` | `pending -> waiting_for_approval` | Create or reuse approval request. | Runner enters existing approval polling loop. |
| `block` | `pending -> failed` or `pending -> blocked` if 10.1 already introduced that state | No approval request created. | Runner must not execute command and should complete/fail execution using existing internal API contract. |

Prefer `pending -> failed` for `Block` unless Phase 10.1 or current source already has a distinct blocked state. Do not introduce an execution-wide policy state unless implementation inspection proves it is necessary.

### 8.6 Idempotency and retries

Runner retries must not create inconsistent state.

- If a pending step is evaluated twice due to request retry, the service may create multiple `PolicyEvaluation` rows but must not create duplicate approval requests.
- If the step is already `waiting_for_approval`, return the existing approval state and latest evaluation rather than evaluating again.
- If the step is already `running`, do not re-evaluate policy.
- If the step is terminal, return an invalid transition error.

### 8.7 Transaction boundaries

Use `transaction.atomic()` around:

- Step row lock.
- Policy evaluation persistence.
- Approval request creation when required.
- Step status transition.

Use `select_for_update()` for the execution step when applying a policy-driven transition. This prevents two runner requests from evaluating and transitioning the same step concurrently.

### 8.8 Internal runner API contract

> **CRITICAL:** The runner MUST call `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/start/` for **every** step before executing any command. It must NOT inspect the local `requires_approval` workflow field and short-circuit. The step-start endpoint is where Django performs policy evaluation (Phase 10.2+) and returns a normalized `runner_action`.

The step-start response MUST include a `runner_action` field. Policy evaluation in Phase 10.2 is purely additive behind the same endpoint the runner already calls:

```json
{
  "execution_id": "uuid",
  "execution_status": "claimed",
  "step": {
    "id": "uuid",
    "status": "waiting_for_approval"
  },
  "runner_action": "wait_for_approval",
  "policy_evaluation": {
    "id": "uuid",
    "outcome": "approval_required",
    "reason": "High-risk steps require human approval."
  },
  "approval_request": {
    "id": "uuid",
    "status": "pending",
    "expires_at": "2026-04-23T21:00:00Z"
  },
  "poll_after_seconds": 5
}
```

`runner_action` values:

| Value | Meaning | Runner behavior |
|---|---|---|
| `run` | Step is `running`; proceed to execute command | Execute command |
| `wait_for_approval` | Step is `waiting_for_approval`; approval request created | Enter approval poll loop (Phase 10.1 contract) |
| `blocked` | Step is `failed`; policy blocked the step | Do not execute; complete execution as failed |

Do NOT create a second parallel step-start path. Do NOT route through a different endpoint for policy-driven approval vs workflow-flag approval. The same endpoint does both.

**Required contract test:** `POST /start/` with `requiresApproval=false` workflow step + active matching policy → `runner_action=wait_for_approval`. This test must exist before Phase 10.2 implementation is considered complete.

---

## 9. Frontend data contracts and policy management flows

### 9.1 Frontend types

Add policy types under `apps/web/src/features/policies/types.ts`.

Recommended TypeScript contracts:

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

Extend execution step types to include:

```ts
policy_evaluation: PolicyEvaluationSummary | null
```

### 9.2 Policy list flow

Route: `/policies`

Behavior:

- Require an organization selection using the existing organization UI pattern.
- Fetch `GET /api/v1/policies/?organization_id={id}&is_active=all`.
- Show name, active state, rule count, updated timestamp, and primary outcome summary if available.
- Provide actions to create policy, open detail, activate/deactivate.
- Do not hide inactive policies by default if the UI is positioned as an admin surface; use a visible filter.

### 9.3 Policy create/edit flow

Behavior:

- Create/edit only policy metadata on the policy form.
- Manage rules in a dedicated section so validation errors remain understandable.
- Do not allow changing `organization_id` after creation.
- Prefer deactivate over delete.

### 9.4 Rule create/edit flow

Rule form fields:

- Name.
- Description.
- Active toggle.
- Priority.
- Condition type.
- Condition params rendered as structured controls for the selected type.
- Outcome.
- Reason.

Structured controls:

- `risk_level`: operator select and values multi-input.
- `step_type`: operator select and values multi-input.
- `time_window`: timezone input/select, days of week selector, start/end time inputs, inside/outside selector.

Do not use a raw JSON editor as the primary UI. A collapsible JSON preview is acceptable for debugging, but the source of truth should be structured form controls.

### 9.5 Execution detail visibility

On `ExecutionDetailPage`:

- Show the latest policy evaluation for each step when present.
- Display outcome as a pill: `Approval required`, `Auto approved`, or `Blocked`.
- Show policy name, rule name, reason, and evaluated timestamp.
- If `decision_source=workflow_default`, show "Workflow default" instead of policy/rule names.
- If `outcome=block`, display the reason near the step error area.
- Do not let the frontend override, retry, or re-evaluate policy.

### 9.6 Frontend API boundaries

Frontend calls only:

- `GET /api/v1/policies/`
- `POST /api/v1/policies/`
- `GET /api/v1/policies/{id}/`
- `PATCH /api/v1/policies/{id}/`
- Rule subresource endpoints under `/api/v1/policies/{id}/rules/`
- `GET /api/v1/executions/{id}/`
- Optional `GET /api/v1/executions/{id}/policy-evaluations/`

No frontend code calls:

- `/api/v1/internal/...`
- Runner endpoints.
- AI service.
- Database-backed direct adapters.

---

## 10. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### Milestone 0: Preflight and approval gate

Purpose: confirm the repo state and Phase 10.1 baseline before coding.

Files read:

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-blueprint.md`
- `apps/api/apps/approvals/**`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/config/api_v1_urls.py`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `packages/workflow-schema/workflow.schema.json`

Commands:

```bash
git status --short
cd apps/api && python manage.py test apps.executions apps.approvals
cd apps/web && npm test -- --run
cd apps/web && npm run typecheck
```

Verification:

- Phase 10.1 tests pass.
- Approval request lifecycle is implemented.
- Step transition service is the confirmed policy hook point.

Rollback:

- No changes in this milestone.

Human approval gate:

- Required before any Phase 10.2 code is written.
- Approver confirms policy outcomes, condition types, and no-DSL boundary.

### Milestone 1: Backend policy app skeleton and models

Purpose: create persistence without wiring execution behavior yet.

Files touched:

- `apps/api/apps/policies/apps.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/policies/admin.py`
- `apps/api/apps/policies/migrations/0001_initial.py`
- `apps/api/config/settings/base.py`
- `apps/api/apps/policies/tests/test_models.py`

Commands:

```bash
cd apps/api && python manage.py makemigrations policies
cd apps/api && python manage.py migrate
cd apps/api && python manage.py test apps.policies.tests.test_models
```

Verification:

- Migration creates `Policy`, `PolicyRule`, and `PolicyEvaluation`.
- Constraints reject duplicate active policy names per organization.
- Constraints reject duplicate rule priority per policy.
- Inactive policies and rules remain queryable.

Rollback:

- Reverse the policies migration before any execution integration exists.
- Remove policies app registration if the migration is reverted.

Human approval gate:

- Required before service behavior is added, because model fields become migration history.

### Milestone 2: Condition validation and policy evaluation service

Purpose: implement deterministic policy evaluation without API or execution wiring.

Files touched:

- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/tests/test_services.py`

Commands:

```bash
cd apps/api && python manage.py test apps.policies.tests.test_services
```

Verification:

- `risk_level` rules match expected values.
- `step_type` rules match expected values.
- `time_window` rules evaluate timezone-aware datetimes correctly.
- Rules sort deterministically.
- First matching rule wins.
- No matching rule falls back to workflow default.
- Invalid persisted condition params fail closed.
- Evaluations are persisted with context snapshots.

Rollback:

- Revert service file and tests only; model migration remains unused.

Human approval gate:

- Required before wiring into execution transitions.

### Milestone 3: Execution transition integration

Purpose: enforce policy outcomes in the runner-controlled step transition path.

Files touched:

- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/executions/tests/test_policy_integration.py`
- `apps/api/apps/approvals/tests/test_policy_integration.py`

Commands:

```bash
cd apps/api && python manage.py test apps.executions.tests.test_policy_integration apps.approvals.tests.test_policy_integration apps.policies
```

Verification:

- `AutoApprove` transitions pending step to running.
- `ApprovalRequired` transitions pending step to waiting for approval and creates/reuses approval request.
- `Block` prevents command execution and terminally marks the step according to the existing state machine.
- Runner ownership is still validated before any transition.
- Concurrent start attempts do not duplicate approval requests or corrupt step state.
- Existing Phase 10.1 approval tests still pass.

Rollback:

- Revert execution and approval integration while keeping policy CRUD unavailable or disabled.
- If a migration added an optional `policy_evaluation` FK to approvals, reverse only if no production data exists; otherwise leave nullable field unused.

Human approval gate:

- Required before exposing policy management APIs, because policies now affect execution behavior.

### Milestone 4: Public policy CRUD API

Purpose: expose policy and rule management through Django public APIs.

Files touched:

- `apps/api/apps/policies/serializers.py`
- `apps/api/apps/policies/views.py`
- `apps/api/apps/policies/urls.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/policies/tests/test_api.py`

Commands:

```bash
cd apps/api && python manage.py test apps.policies.tests.test_api apps.policies.tests.test_services
```

Verification:

- Policy list requires tenant scope until auth exists.
- Create/update/deactivate policy works.
- Create/update/deactivate rule works.
- Invalid condition params return `400`.
- Duplicate active policy name returns `409`.
- Duplicate rule priority returns `409`.
- Cross-tenant policy access is blocked or returns `404`.

Rollback:

- Remove URL registration to disable the public API while preserving model data.
- Keep execution integration disabled if API issues could create unsafe policies.

Human approval gate:

- Required before frontend CRUD is added.

### Milestone 5: Execution detail policy visibility API

Purpose: make policy decisions visible on execution detail.

Files touched:

- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/tests/test_api_contracts.py`
- Optional: `apps/api/apps/policies/serializers.py`

Commands:

```bash
cd apps/api && python manage.py test apps.executions.tests.test_api_contracts apps.executions.tests.test_policy_integration
```

Verification:

- Execution detail embeds latest policy evaluation per step.
- Evaluation history endpoint, if implemented, is tenant scoped.
- Steps with no evaluation serialize `policy_evaluation: null`.
- Evaluation data does not expose unrelated organization policies.

Rollback:

- Remove serializer field or optional endpoint. Enforcement can remain active while UI visibility is fixed if backend tests pass.

Human approval gate:

- Required before frontend execution detail changes.

### Milestone 6: Frontend policy management

Purpose: add policy CRUD UI without adding new backend behavior.

Files touched:

- `apps/web/src/features/policies/types.ts`
- `apps/web/src/features/policies/api/policiesApi.ts`
- `apps/web/src/features/policies/hooks/usePolicies.ts`
- `apps/web/src/features/policies/hooks/usePolicyDetail.ts`
- `apps/web/src/features/policies/hooks/useCreatePolicy.ts`
- `apps/web/src/features/policies/hooks/useUpdatePolicy.ts`
- `apps/web/src/features/policies/hooks/usePolicyRules.ts`
- `apps/web/src/routes/policies/PoliciesPage.tsx`
- `apps/web/src/routes/policies/PoliciesPage.test.tsx`
- `apps/web/src/routes/policies/PolicyDetailPage.tsx`
- `apps/web/src/routes/policies/PolicyDetailPage.test.tsx`
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
- Rule form uses structured controls, not raw DSL editing.
- API errors render through existing error handling.
- Navigation exposes policies without breaking existing routes.

Rollback:

- Remove route and navigation entry to hide the UI.
- Backend APIs can remain available for manual verification.

Human approval gate:

- Required before final integration/manual testing.

### Milestone 7: Frontend execution detail policy visibility

Purpose: show policy decisions where operators debug executions.

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
- Workflow default evaluations render clearly.
- Blocked evaluations show reason near failure/error status.
- Existing execution polling behavior is unchanged.

Rollback:

- Revert execution detail UI changes only.

Human approval gate:

- Required before declaring Phase 10.2 complete.

### Milestone 8: End-to-end manual gate

Purpose: verify behavior across Django, runner, approvals, and web UI.

Commands:

```bash
docker compose up -d postgres api runner web
cd apps/api && python manage.py migrate
cd apps/api && python manage.py test apps.policies apps.executions apps.approvals
cd apps/web && npm run test:ci
```

Manual verification:

- Create an organization.
- Create or use a workflow with `risk=critical` and `requiresApproval=false`.
- Create active policy rule: risk `critical` -> `approval_required`.
- Start execution and confirm the step waits for approval.
- Approve from the Phase 10.1 approval UI and confirm runner proceeds.
- Create active policy rule with higher priority: same risk -> `block`.
- Start a new execution and confirm the command is not executed.
- Deactivate the block rule and confirm the approval rule applies again.
- Deactivate all policies and confirm workflow default behavior applies.
- Open execution detail and confirm policy evaluation visibility is accurate.

Rollback:

- Deactivate policies through the public API to stop enforcement.
- If code rollback is needed, revert Phase 10.2 commits in reverse milestone order.
- Preserve `PolicyEvaluation` records unless a migration rollback is explicitly approved.

Human approval gate:

- Required sign-off from product/engineering owner after manual verification.

---

## 11. Testing strategy

### 11.1 Policy service tests

Cover:

- Active policy with matching `risk_level` returns `approval_required`.
- Active policy with matching `step_type` returns configured outcome.
- Active policy with matching `time_window` returns configured outcome.
- Inactive policies are ignored.
- Inactive rules are ignored.
- Lower numeric priority evaluates before higher numeric priority.
- Cross-policy priority ties are deterministic.
- First matching rule wins.
- No matching rules fall back to `step.requires_approval`.
- Evaluation creates a `PolicyEvaluation` with context snapshot.
- Invalid condition params fail closed.
- Unknown condition type fails closed.
- Timezone and DST-sensitive cases do not crash.

### 11.2 API tests

Cover:

- Policy list filters by organization.
- Policy detail includes ordered rules.
- Policy create validates required fields.
- Policy update does not allow organization changes.
- Policy deactivate removes it from evaluation but not from list when `is_active=all`.
- Rule create validates structured params.
- Rule update validates priority uniqueness.
- Rule deactivate removes it from evaluation.
- Duplicate active policy names return conflict.
- Cross-tenant reads and writes are blocked.

### 11.3 Integration with approvals

> **ARCHITECTURE DECISION (locked — no longer a pre-implementation question):** Workflow `requiresApproval: true` is a **minimum floor**. A policy outcome of `AutoApprove` on a step with `requiresApproval: true` MUST be silently upgraded to `ApprovalRequired`. The policy evaluation record still records the matched rule and outcome as `auto_approve` so the evaluation is auditable, but the execution service MUST override it to `ApprovalRequired` before creating the step state transition. There is no configuration option to waive this. The rationale: a workflow author who sets `requiresApproval: true` is making an explicit safety commitment. A policy that accidentally matches and returns `AutoApprove` on that step must not silently bypass the author's intent.

Cover these tests:

- `ApprovalRequired` creates an approval request even when workflow step has `requiresApproval=false`.
- Existing workflow `requiresApproval=true` still creates approval request when no policy matches.
- Policy `AutoApprove` on a `requiresApproval=true` step results in `ApprovalRequired` behavior (approval request created; policy evaluation record shows `outcome=auto_approve`, but execution service overrides to approval-required behavior; test must verify no command execution without approval).
- Policy `AutoApprove` on a `requiresApproval=false` step results in step proceeding without approval.
- Policy `Block` on any step (regardless of `requiresApproval`) prevents execution.
- Approval request includes or can be correlated to the policy evaluation.
- Approval polling behavior from Phase 10.1 remains unchanged.

### 11.4 Failure-path tests

Cover:

- Policy service exception prevents command execution.
- Invalid persisted rule prevents command execution.
- Database write failure while creating evaluation returns a safe error.
- Approval service failure after `ApprovalRequired` does not leave the step running.
- Blocked step never enters `running`.
- Runner retry on a waiting step does not create duplicate approval requests.
- Terminal step cannot be re-evaluated into running.

### 11.5 Multi-tenant isolation tests

Cover:

- Organization A policy does not affect Organization B execution.
- Organization A cannot list Organization B policies.
- Organization A cannot attach rules to Organization B policies.
- Policy evaluation records always use the execution organization.
- Execution detail for Organization A never includes policy names or rules from Organization B.
- UUIDs from another tenant return `404` or a consistent authorization-safe response.

### 11.6 Frontend tests

Cover:

- Policy list renders fetched policies.
- Policy list sends `organization_id`.
- Policy form submits only public API requests.
- Rule form renders structured controls by condition type.
- Invalid rule API errors render visibly.
- Execution detail renders policy evaluation summary per step.
- Execution detail handles `policy_evaluation: null`.
- Query invalidation refreshes list/detail after create, update, and deactivate.

### 11.7 Manual gate

The manual gate must exercise all three outcomes:

- `AutoApprove`: step runs without approval.
- `ApprovalRequired`: step waits, approval UI resolves it, runner proceeds.
- `Block`: step does not run and operator can see the policy reason.

The manual gate must also confirm no runner or frontend request bypasses Django.

---

## 12. Failure modes and risks

### Silent policy miss

Risk: a malformed rule, bad query, or service exception results in no policy being applied and the step runs.

Mitigation:

- Fail closed on evaluation errors.
- Persist `PolicyEvaluation` records for workflow-default decisions.
- Show workflow-default decisions in execution detail.
- Add tests for invalid persisted rules.

### Policy latency

Risk: policy evaluation runs in the execution hot path and slows step transitions.

Mitigation:

- Query active policies and rules efficiently with prefetches.
- Index active policy and ordered rule lookups.
- Keep condition evaluation in plain Python.
- Do not call external services during evaluation.
- Do not introduce AI policy evaluation.

### Conflicting rules

Risk: multiple rules could match and operators cannot predict which applies.

Mitigation:

- Use explicit priority.
- Use deterministic global sort.
- Use first-match semantics.
- Surface matched policy and rule on execution detail.
- Reject duplicate priorities inside a policy.

### Nondeterministic ordering

Risk: database ordering changes produce different outcomes.

Mitigation:

- Never rely on implicit database order.
- Sort by `(priority, policy.created_at, policy.id, rule.id)` in the service.
- Test tie cases.

### Cross-tenant leakage

Risk: Organization A policies affect or appear in Organization B executions.

Mitigation:

- Scope all policy queries by `execution.organization_id`.
- Denormalize `organization` onto `PolicyEvaluation`.
- Validate organization consistency in services.
- Add multi-tenant API and service tests.

### Policy/approval mismatch

Risk: policy says approval required, but approval service creates duplicate or mismatched requests.

Mitigation:

- Use existing approval service entry points.
- Keep approval creation inside the same transaction as step transition where possible.
- Use one approval request per step semantics from Phase 10.1.

### Overriding workflow `requiresApproval`

Risk: `AutoApprove` waives an explicit workflow approval flag unexpectedly.

Mitigation:

- Make this a human approval gate before implementation.
- If allowed, show `AutoApprove` policy evaluations prominently.
- If not allowed, treat workflow `requiresApproval=true` as a minimum approval floor.

---

## 13. What NOT to do

- Do not build a rules engine DSL.
- Do not embed Python, JavaScript, SQL, Rego, CEL, JSONLogic, or expression strings in policy conditions.
- Do not add policy inheritance between organizations.
- Do not add global policies shared across organizations in Phase 10.2.
- Do not add team, role, or RBAC-based policy routing unless a separate auth phase has completed.
- Do not mutate commands, command arguments, environment variables, workflow definitions, or runner payloads from policies.
- Do not add policy dry-run mode unless explicitly scoped in a later blueprint.
- Do not introduce queues, Kafka, Celery, RabbitMQ, event buses, or background workers.
- Do not create a policy microservice.
- Do not let the runner read policy data or evaluate rules.
- Do not let the frontend call internal runner APIs.
- Do not call the AI service for policy decisions.
- Do not make policy evaluation asynchronous.
- Do not add WebSocket or SSE behavior for policy updates.
- Do not hard-delete policies or rules that have evaluation history.
- Do not put policy business logic in views, serializers, model hooks, or admin actions.

---

## 14. Definition of done

Phase 10.2 is complete when all of the following are true:

- `Policy`, `PolicyRule`, and `PolicyEvaluation` models exist with UUID primary keys, tenant scoping, indexes, constraints, and migrations.
- Policy conditions support only structured `risk_level`, `step_type`, and `time_window` contracts.
- Policy outcomes are limited to `approval_required`, `auto_approve`, and `block`.
- Rule evaluation is deterministic and explicitly ordered.
- Policy evaluation is wired into Django execution step transition services before command execution.
- `ApprovalRequired` integrates with the Phase 10.1 approval service without duplicating approval lifecycle logic.
- `AutoApprove` and `Block` behavior is explicitly tested and documented.
- Public policy CRUD APIs exist under `/api/v1/policies/`.
- Internal runner behavior remains under `/api/v1/internal/` and the runner does not evaluate policies.
- Execution detail exposes latest policy evaluation visibility.
- Frontend policy management CRUD exists using Django public APIs only.
- Frontend execution detail shows policy decisions per step.
- Service, API, approval integration, failure-path, multi-tenant, and frontend tests pass.
- Manual verification covers all three outcomes: approval required, auto approve, and block.
- No queues, event infrastructure, microservices, DSLs, command mutation, policy inheritance, or dry-run mode were introduced.
- The implementation has been reviewed against this blueprint and the Phase 10 roadmap before merge.

Key assumptions:

- Phases 01-09 are complete and verified.
- Phase 10.1 approvals are complete and verified before Phase 10.2 implementation starts.
- The workflow step fields `risk`, `type`, and `requiresApproval` remain available through materialized execution step fields.
- Auth/RBAC is not complete yet, so organization scoping remains explicit in public policy API payloads until a later phase replaces it with authenticated tenant context.
