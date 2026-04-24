# Phase 10.3: Audit Trail Expansion Blueprint

| Field | Value |
|---|---|
| Phase number | 10.3 |
| Phase name | Audit Trail |
| Objective | Add an immutable, append-only audit trail for state-changing domain actions across executions, steps, approvals, and policy evaluations. |
| Status | Blueprint only |
| Depends on | Phases 01-09 complete and verified; Phase 10.1 approvals complete and verified; Phase 10.2 policies complete and verified |
| Authored | 2026-04-23 |

---

## 1. Purpose and sequencing rationale

Phase 10.3 adds the system of record for operational accountability. The audit trail answers who or what changed domain state, which object was affected, when it happened, and what safe metadata explains the change.

This phase must focus on state-changing domain actions, especially:

- Execution creation, claim, cancellation, completion, and failure.
- Execution step state transitions.
- Approval request creation, timeout, approval, and rejection.
- Policy evaluation outcomes, including approval-required, auto-approve, and block decisions.
- Policy and approval management mutations if Phase 10.1 and 10.2 expose those public APIs.

Audit comes after approvals and policies because those phases introduce the first operationally meaningful decisions. An approval decision is a human authorization record. A policy evaluation can pause, waive, or block command execution. Those are precisely the events that need an immutable trail. Building audit before approvals and policies would either produce low-value execution-only records or force a second event taxonomy migration as soon as approvals and policies land.

Audit comes before artifacts and integrations because later phases depend on trustworthy event history:

1. Artifacts should emit audit events when files are uploaded, made visible, or downloaded through controlled URLs. Artifact storage introduces evidence, and evidence access must be traceable.
2. Integrations should emit audit events when credentials, destinations, and dispatch settings change. Integration notifications are external effects, so the internal decision trail must exist first.
3. Audit defines the stable domain event vocabulary that integrations can later consume or mirror without inventing their own event semantics.

This phase does not add event infrastructure. Audit writes are normal Django database writes, executed synchronously through explicit service calls inside the same transaction as the action being audited.

---

## 2. Current-state inspection checklist

Before implementation begins, inspect the repository in this order. Do not implement from this blueprint without re-reading the current source files first.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` and confirm Phase 10.3 still follows approvals/policies and precedes artifacts/integrations.
- [ ] Read `docs/blueprints/phase-10-01-approvals-blueprint.md` if present, then inspect the implemented approvals source rather than relying only on the blueprint.
- [ ] Read `docs/blueprints/phase-10-02-policies-blueprint.md` if present, then inspect the implemented policies source rather than relying only on the blueprint.
- [ ] Confirm `apps/api/apps/audit/` is still a stub or audit any existing implementation before extending it.
- [ ] Confirm `apps/api/apps/common/models.py` still provides UUID primary keys through `BaseModel`.
- [ ] Confirm `apps/api/apps/common/api_errors.py` still defines the API error envelope used by public audit endpoints.
- [ ] Confirm `apps/api/apps/executions/services.py` owns execution creation, cancellation, runner claim, heartbeat, step update, and completion behavior.
- [ ] Confirm execution service mutations are already wrapped in `transaction.atomic()` where multi-row state changes occur.
- [ ] Confirm `apps/api/apps/approvals/services.py` owns approval request creation, decision, timeout resolution, and any approval state transitions.
- [ ] Confirm `apps/api/apps/policies/services.py` owns policy CRUD and policy evaluation persistence.
- [ ] Confirm `PolicyEvaluation` records exist and include enough fields to link evaluations back to organization, execution, step, policy, rule, and outcome.
- [ ] Confirm public APIs are still registered under `/api/v1/` in `apps/api/config/api_v1_urls.py`.
- [ ] Confirm internal runner APIs are still under `/api/v1/internal/` and remain separate from public routes.
- [ ] Confirm `apps/web/src/routes/executions/ExecutionDetailPage.tsx` is still the right place for an execution-detail audit panel.
- [ ] Confirm `apps/web/src/features/executions/types.ts`, `apps/web/src/features/executions/api/executionsApi.ts`, and `apps/web/src/shared/lib/queryKeys.ts` are still the right frontend data-contract integration points.
- [ ] Confirm current execution, approval, policy, organization, and frontend tests pass before adding audit.

At blueprint authoring time, `apps/api/apps/audit/`, `apps/api/apps/approvals/`, and `apps/api/apps/policies/` are stubs in the checked-out source tree, while Phase 10.1 and 10.2 blueprints exist as planning documents. This blueprint intentionally assumes the baseline requested for implementation: Phases 01-09, approvals, and policies are complete and verified before Phase 10.3 work starts.

Latest official docs should be reviewed only where directly relevant during implementation, such as Django transaction behavior, Django admin permissions, and Django REST Framework filtering/pagination. No external documentation is required to understand this blueprint.

---

## 3. Architecture invariants and boundaries

These invariants are non-negotiable for Phase 10.3:

| Invariant | Phase 10.3 consequence |
|---|---|
| Django is the control plane. | Audit event creation, persistence, filtering, and authorization boundaries live in Django. |
| Runner talks only to Django internal APIs. | The runner never writes audit records directly and never reads audit tables. Runner identity is captured by Django from internal API payloads. |
| Frontend talks only to Django public APIs. | Audit panels and organization trails use `/api/v1/audit/...` or execution public APIs only. |
| AI service is stateless and advisory. | AI does not emit, store, query, or mutate audit events. |
| All APIs remain under `/api/v1/`. | Public audit APIs live under `/api/v1/audit/`. |
| Internal runner APIs remain under `/api/v1/internal/`. | Runner-originated actions continue through internal execution APIs; audit is emitted by Django services behind those endpoints. |
| UUID primary keys remain standard. | `AuditEvent` inherits from `BaseModel`, preserving UUID primary keys. |
| Business logic belongs in `services.py`. | `AuditService.emit(...)` and integration calls from domain services own audit behavior. Views and serializers do not decide audit semantics. |
| No premature event infrastructure. | No queues, Kafka, Celery, RabbitMQ, event bus, outbox table, or separate event store. |
| No service routes around Django. | No direct runner, frontend, AI, or integration write path to audit persistence. |

Additional Phase 10.3 boundaries:

- Audit is append-only. There are no update or delete service methods.
- Audit writes are explicit service calls, not Django signals.
- Audit writes are synchronous and same-transaction with the domain mutation.
- Audit metadata must be intentionally shaped and must not contain secrets, raw command output, claim tokens, API keys, webhook URLs, or full request bodies.
- Audit is for state-changing domain actions only. Do not audit normal GET requests, health checks, frontend polling, or no-op reads.
- Audit records are not a replacement for domain state. Domain models remain the source of current state; audit explains how state changed over time.

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.3 |
|---|---|
| `apps/api/apps/audit/` | Implement app config, `AuditEvent` model, migration, append-only service, serializers, read-only public views, URLs, admin, and tests. |
| `apps/api/apps/executions/` | Emit audit events for execution creation, cancellation, claim, step transitions, and execution completion/failure. Add execution-detail audit visibility if embedded there. |
| `apps/api/apps/approvals/` | Emit audit events for approval request creation, timeout, approval, and rejection. |
| `apps/api/apps/policies/` | Emit audit events for policy/rule CRUD and policy evaluation outcomes. |
| `apps/api/apps/common/` | Reuse domain exceptions and error envelope. Add audit-specific exception codes only if existing exceptions are insufficient. |
| `apps/api/config/` | Register the audit app and include audit URLs under `/api/v1/`. |
| `apps/web/src/features/audit/` | Add audit TypeScript types, API client functions, hooks, and tests. |
| `apps/web/src/routes/executions/` | Add execution-detail audit panel. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add audit query keys. |

Likely backend files touched:

- `apps/api/apps/audit/apps.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/admin.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/audit/serializers.py`
- `apps/api/apps/audit/views.py`
- `apps/api/apps/audit/urls.py`
- `apps/api/apps/audit/tests/test_models.py`
- `apps/api/apps/audit/tests/test_services.py`
- `apps/api/apps/audit/tests/test_api.py`
- `apps/api/apps/audit/tests/test_admin.py`
- `apps/api/apps/audit/migrations/0001_initial.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/tests/test_audit_integration.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_audit_integration.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/tests/test_audit_integration.py`
- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`

Likely frontend files touched:

- `apps/web/src/features/audit/types.ts`
- `apps/web/src/features/audit/api/auditApi.ts`
- `apps/web/src/features/audit/hooks/useObjectAuditTrail.ts`
- `apps/web/src/features/executions/types.ts`
- `apps/web/src/features/executions/api/executionsApi.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`

Out of scope unless explicitly approved:

- Runner code changes beyond adapting to any existing internal API response shape. The runner does not emit audit events.
- AI service changes.
- Artifact or integration implementation.
- Infrastructure changes.
- Full organization-wide audit UI outside the minimal execution-detail panel, unless already required by product scope.

---

## 5. Data model: fields, indexes, constraints, immutability rules

### 5.1 `AuditEvent`

`AuditEvent` is an immutable, append-only record of a completed state-changing domain action.

Required fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `actor_type` | enum string | Required. Recommended values: `user`, `runner`, `system`, `api_client`, `unknown`. |
| `actor_id` | `CharField(255, blank=True)` | Stable actor identifier when available. User UUID, runner ID, service identifier, or blank if unknown. |
| `actor_label` | `CharField(255, blank=True)` | Denormalized display label at event time. Required when knowable. |
| `event_type` | enum string | Required dotted event type, such as `execution.created`. |
| `object_type` | enum string | Required object category, such as `execution`, `execution_step`, `approval_request`, `approval_decision`, `policy`, `policy_rule`, `policy_evaluation`. |
| `object_id` | UUID | Required UUID of the primary object affected. Store as `UUIDField`, not FK, to preserve history if domain rows are later deleted. |
| `organization_id` | UUID | Required tenant boundary. Store as `UUIDField` or FK with `PROTECT`; UUID field is safer for long-term append-only history. |
| `metadata` | `JSONField(default=dict)` | Event-specific sanitized metadata. |
| `occurred_at` | `DateTimeField` | Required event timestamp. Set by service using `timezone.now()` unless a domain timestamp must be preserved. |

`BaseModel.created_at` and `updated_at` will also exist if `AuditEvent` inherits `BaseModel`. Treat `occurred_at` as the event time used for sorting and API filtering. `created_at` is the database insertion time.

### 5.2 Enums

Actor type values:

- `user`: a human user from a public API action.
- `runner`: the runner identity from internal API actions.
- `system`: Django system behavior such as timeout resolution or policy-driven automatic blocking.
- `api_client`: future service token or integration client when auth exists.
- `unknown`: temporary fallback only when the actor cannot be determined.

Object type values:

- `organization`
- `runbook`
- `workflow`
- `execution`
- `execution_step`
- `approval_request`
- `approval_decision`
- `policy`
- `policy_rule`
- `policy_evaluation`

Do not use Python class paths as object types. Public audit contracts should remain stable if models move.

### 5.3 Indexes

Recommended indexes:

| Index | Purpose |
|---|---|
| `(organization_id, occurred_at)` descending where supported | Organization-wide trail, newest first. |
| `(object_type, object_id, occurred_at)` | Object-specific trail. |
| `(event_type, occurred_at)` | Support operational filtering by event type. |
| `(actor_type, actor_id, occurred_at)` | Actor activity investigation. |
| `(organization_id, event_type, occurred_at)` | Tenant-scoped event filtering. |

If the database backend does not support descending index syntax consistently across dev/test/prod, use normal ascending fields and order by `-occurred_at` in queries.

### 5.4 Constraints

Recommended constraints:

- `actor_type` must be one of the declared enum values.
- `event_type` must be non-empty and max length should allow dotted names, e.g. 128 chars.
- `object_type` must be one of the declared enum values.
- `object_id` must be non-null.
- `organization_id` must be non-null.
- `metadata` must default to `{}` and must always be a JSON object at the service boundary.
- `occurred_at` must be non-null.

Do not enforce uniqueness on audit events. Retried operations and repeated state transitions can legitimately create multiple events with the same object and event type at different times.

### 5.5 Immutability rules

Application-level rules:

- The only write service is `AuditService.emit(...)`.
- There is no `update`, `delete`, `bulk_update`, or `purge` service method in Phase 10.3.
- Public APIs expose list/retrieve only.
- Admin is read-only.
- Domain services must not mutate `AuditEvent` after creation.

Model-level guardrails:

- Override `AuditEvent.save()` to reject updates when `self.pk` already exists.
- Override `AuditEvent.delete()` to raise a domain or `ValidationError` exception.
- Prefer service-level creation over direct model usage in tests, but keep model guardrails to catch accidental writes.

Admin read-only behavior:

- Register `AuditEvent` in Django admin for support inspection.
- Set all fields as `readonly_fields`.
- `has_add_permission()` returns `False`.
- `has_change_permission()` may return `True` for viewing existing objects in admin, but `get_readonly_fields()` must include all fields and `save_model()` must not allow edits.
- `has_delete_permission()` returns `False`.
- `has_module_permission()` can remain default so staff can find the audit area.

Database-level immutability:

- Do not add triggers in Phase 10.3. They complicate migrations and tests.
- Do not add separate append-only storage. The service and model/admin guardrails are sufficient for this phase.

---

## 6. Event taxonomy and metadata contracts

### 6.1 Naming rules

Event types use dotted lowercase strings:

`{domain}.{past_tense_action}`

Examples:

- `execution.created`
- `execution.claimed`
- `execution.cancelled`
- `execution.completed`
- `execution.failed`
- `execution_step.started`
- `execution_step.waiting_for_approval`
- `execution_step.succeeded`
- `execution_step.failed`
- `approval.requested`
- `approval.approved`
- `approval.rejected`
- `approval.timed_out`
- `policy.created`
- `policy.updated`
- `policy.deactivated`
- `policy_rule.created`
- `policy_rule.updated`
- `policy_rule.deactivated`
- `policy.evaluated`

Use a single canonical event type for each domain action. Do not create aliases such as both `step.started` and `execution_step.started`.

### 6.2 Metadata rules

Metadata must be intentionally shaped per event type. It should help operators understand the event without leaking secrets or storing large blobs.

Allowed metadata examples:

- Previous and new status.
- Step position, step key, risk level, and step type.
- Workflow ID and version.
- Runner ID when actor is runner.
- Approval request ID and decision ID.
- Policy ID, rule ID, outcome, and reason.
- Error code and safe error message.
- Timeout seconds and expiration timestamp.

Forbidden metadata:

- Claim tokens.
- Raw command output.
- Full shell command text unless product explicitly approves it as non-sensitive.
- Secrets, API keys, webhook URLs, bearer tokens, cookies, or authorization headers.
- Full HTTP request bodies.
- Full workflow snapshots.
- Large artifacts or logs.
- AI prompts or raw LLM responses.

Metadata should stay small. As a practical first limit, keep serialized metadata below 16 KB. If an event needs more context than that, store the context on the domain model or artifact system and link to it by ID.

### 6.3 Execution events

`execution.created`

Object:

- `object_type`: `execution`
- `object_id`: execution ID
- `actor_type`: `user` or `system`

Metadata:

```json
{
  "workflow_id": "uuid",
  "workflow_version": 7,
  "initial_status": "queued"
}
```

`execution.claimed`

Actor:

- `actor_type`: `runner`
- `actor_id`: runner ID
- `actor_label`: runner ID

Metadata:

```json
{
  "previous_status": "queued",
  "new_status": "claimed",
  "claimed_at": "2026-04-23T20:00:00Z"
}
```

Do not include claim token.

`execution.completed` and `execution.failed`

Metadata:

```json
{
  "previous_status": "running",
  "new_status": "succeeded",
  "started_at": "2026-04-23T20:00:00Z",
  "finished_at": "2026-04-23T20:05:00Z"
}
```

Use `execution.failed` when final status is failed. Use `execution.completed` when final status is succeeded.

### 6.4 Execution step events

Emit for meaningful status transitions:

- `execution_step.started`
- `execution_step.waiting_for_approval`
- `execution_step.succeeded`
- `execution_step.failed`
- Optional `execution_step.skipped` if skip semantics exist.

Metadata:

```json
{
  "execution_id": "uuid",
  "step_id": "uuid",
  "step_key": "deploy",
  "position": 2,
  "step_type": "shell",
  "risk_level": "high",
  "previous_status": "pending",
  "new_status": "running",
  "exit_code": 0,
  "error_code": "",
  "error_message": ""
}
```

Do not include raw command text by default. If later product requirements demand command visibility, add a separate reviewed metadata field with redaction tests.

### 6.5 Approval events

`approval.requested`

Object:

- `object_type`: `approval_request`
- `object_id`: approval request ID

Actor:

- Usually `runner` if triggered by runner reaching a step.
- `system` if created by policy or recovery behavior without a direct runner action.

Metadata:

```json
{
  "execution_id": "uuid",
  "step_id": "uuid",
  "policy_evaluation_id": "uuid",
  "timeout_seconds": 1800,
  "expires_at": "2026-04-23T20:30:00Z"
}
```

`approval.approved`, `approval.rejected`, and `approval.timed_out`

Object:

- `object_type`: `approval_decision` if a decision row exists.
- `object_id`: approval decision ID.

Metadata:

```json
{
  "approval_request_id": "uuid",
  "execution_id": "uuid",
  "step_id": "uuid",
  "decision": "approved",
  "notes_present": true
}
```

Do not store full approval notes in audit metadata unless product explicitly approves it. Notes already live on the approval decision model.

### 6.6 Policy events

Policy CRUD:

- `policy.created`
- `policy.updated`
- `policy.deactivated`
- `policy_rule.created`
- `policy_rule.updated`
- `policy_rule.deactivated`

Metadata:

```json
{
  "policy_id": "uuid",
  "rule_id": "uuid",
  "changed_fields": ["name", "is_active"],
  "previous_is_active": true,
  "new_is_active": false
}
```

Do not store full condition params if they could become large. Store condition type and a short hash or summary unless the Phase 10.2 contract has already established sanitized snapshots.

`policy.evaluated`

Object:

- `object_type`: `policy_evaluation`
- `object_id`: policy evaluation ID

Actor:

- `system` for normal evaluation.
- `runner` only if the implementation intentionally treats the runner transition request as the actor. Prefer `system` with runner ID in metadata because Django performs the decision.

Metadata:

```json
{
  "execution_id": "uuid",
  "step_id": "uuid",
  "policy_id": "uuid",
  "rule_id": "uuid",
  "matched": true,
  "outcome": "approval_required",
  "decision_source": "policy_rule",
  "reason": "High-risk steps require human approval."
}
```

### 6.7 Actor derivation

Recommended actor helper:

```python
def actor_from_request(request) -> AuditActor:
    ...

def actor_from_runner(runner_id: str) -> AuditActor:
    ...

def system_actor(label: str = "Django system") -> AuditActor:
    ...
```

Until auth/RBAC is complete:

- Public API actions can use `actor_type="user"` only if `request.user.is_authenticated`.
- Otherwise use `actor_type="unknown"` with `actor_label="Unauthenticated public API"` for public mutations that still exist in the current dev phase.
- Runner actions use `actor_type="runner"` and the runner ID from validated internal API payloads.
- Timeout and policy evaluation actions use `actor_type="system"`.

When auth lands later, do not rewrite historical events. Actor labels are intentionally denormalized snapshots.

---

## 7. API contracts for audit listing and filtering

All audit APIs are read-only and public under `/api/v1/`. Use existing DRF error envelopes and pagination conventions. If the repo has no common pagination yet, implement a small limit/offset or page-number approach for audit only, then consolidate later.

### 7.1 `GET /api/v1/audit/`

Purpose: list audit events by object trail or organization trail.

Supported filters:

| Param | Required | Notes |
|---|---|---|
| `organization_id` | required unless `object_type` + `object_id` can infer organization safely | Tenant boundary. Prefer required until auth exists. |
| `object_type` | optional | Required with `object_id` for object trail. |
| `object_id` | optional | Required with `object_type` for object trail. |
| `event_type` | optional | Exact match only. |
| `actor_type` | optional | Exact match only. |
| `occurred_after` | optional | ISO timestamp lower bound. |
| `occurred_before` | optional | ISO timestamp upper bound. |
| `limit` | optional | Default 50, max 200. |
| `offset` | optional | Default 0. |

Validation rules:

- `object_type` and `object_id` must be provided together.
- `organization_id` should be required until authentication supplies tenant scope.
- `limit` above max is rejected or clamped consistently.
- No arbitrary metadata filtering.
- No full-text search.
- No query language.

Default ordering:

- Newest first by `occurred_at`, then `id` as a deterministic tiebreaker.

Response:

```json
{
  "count": 124,
  "next": "/api/v1/audit/?organization_id=uuid&limit=50&offset=50",
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "actor_type": "runner",
      "actor_id": "runner-dev-01",
      "actor_label": "runner-dev-01",
      "event_type": "execution_step.started",
      "object_type": "execution_step",
      "object_id": "uuid",
      "organization_id": "uuid",
      "metadata": {
        "execution_id": "uuid",
        "step_key": "deploy",
        "previous_status": "pending",
        "new_status": "running"
      },
      "occurred_at": "2026-04-23T20:00:00Z"
    }
  ]
}
```

### 7.2 Object-specific trail

Use the same endpoint:

`GET /api/v1/audit/?organization_id={org_id}&object_type=execution&object_id={execution_id}`

The service should include direct object events only. For execution detail, the API may need a domain-specific convenience endpoint that includes related step, approval, and policy evaluation events.

Recommended convenience endpoint:

`GET /api/v1/executions/{execution_id}/audit/`

Purpose: return the execution timeline, including execution events and related step, approval, and policy evaluation events.

Response shape can match `GET /api/v1/audit/`.

This endpoint is allowed because it is a public Django API under `/api/v1/` and keeps execution-detail UI simple. It must still delegate filtering to audit services.

### 7.3 Organization-wide trail

`GET /api/v1/audit/?organization_id={org_id}`

Purpose: organization-wide support trail, newest first.

This endpoint should be backend-ready in Phase 10.3 even if the frontend only adds execution-detail audit panel. Later admin UI can reuse it.

### 7.4 Retrieve endpoint

Optional:

`GET /api/v1/audit/{audit_event_id}/`

If implemented, require `organization_id` query param until auth exists, or enforce tenant through authenticated context after auth. Do not expose update, patch, post, or delete actions.

### 7.5 Status codes

- `200 OK` for list and retrieve.
- `400 Bad Request` for invalid filter combinations or malformed timestamps.
- `404 Not Found` for inaccessible object trails or audit IDs.
- `405 Method Not Allowed` for write methods if using read-only viewsets.

---

## 8. Service integration points and transaction behavior

### 8.1 Audit service contract

Implement audit behavior in `apps/api/apps/audit/services.py`.

Recommended public service:

```python
class AuditService:
    @staticmethod
    def emit(
        *,
        organization_id,
        actor_type: str,
        actor_id: str = "",
        actor_label: str = "",
        event_type: str,
        object_type: str,
        object_id,
        metadata: dict | None = None,
        occurred_at=None,
    ) -> AuditEvent:
        ...
```

Optional module-level wrapper is acceptable if the repo does not use classes:

```python
def emit(...): ...
```

The key invariant is append-only emission through one service entry point.

`emit(...)` must:

1. Validate actor type, event type, object type, object ID, organization ID, and metadata shape.
2. Sanitize metadata using allowlisted keys per event type or a centralized scrubber.
3. Set `occurred_at` to `timezone.now()` if absent.
4. Create and return `AuditEvent`.
5. Never update or delete existing events.

### 8.2 Same-transaction writes

Audit writes must happen inside the same `transaction.atomic()` block as the domain mutation.

Correct pattern:

```python
with transaction.atomic():
    previous_status = execution.status
    execution.status = Execution.Status.CLAIMED
    execution.save(update_fields=[...])
    AuditService.emit(
        organization_id=execution.organization_id,
        actor_type="runner",
        actor_id=runner_id,
        actor_label=runner_id,
        event_type="execution.claimed",
        object_type="execution",
        object_id=execution.id,
        metadata={
            "previous_status": previous_status,
            "new_status": execution.status,
        },
    )
```

If `AuditService.emit(...)` raises, the domain mutation rolls back. If the domain mutation raises before audit emit, no audit event is written unless the service intentionally catches and records a failure event in a separate safe transaction. Phase 10.3 should prioritize atomic consistency over best-effort failure logging.

### 8.3 Error-path behavior

Some failure paths are domain actions and must be audited:

- Runner reports step failed.
- Policy blocks a step.
- Approval is rejected.
- Approval times out.
- Execution is marked failed.

Unhandled exceptions are different. Do not try to audit every exception thrown by Django. If a state transition fails validation and no domain state changes, no audit event is required.

For service methods that catch an exception and then persist a failed state, emit the failure event in the same transaction as that failed-state persistence.

### 8.4 Execution service integration

Emit from `apps/api/apps/executions/services.py` for:

- `create_execution`: `execution.created`
- `cancel_execution`: `execution.cancelled`
- `claim_next_execution`: `execution.claimed`
- Step transition to running: `execution_step.started`
- Step transition to waiting for approval: `execution_step.waiting_for_approval`
- Step transition to succeeded: `execution_step.succeeded`
- Step transition to failed: `execution_step.failed`
- `complete_execution` with succeeded outcome: `execution.completed`
- `complete_execution` with failed outcome: `execution.failed`

Do not emit on heartbeat by default. Heartbeats are high-volume liveness updates, not business events. If a future operational need requires heartbeat auditing, design it separately with retention limits.

### 8.5 Approval service integration

Emit from `apps/api/apps/approvals/services.py` for:

- Approval request creation: `approval.requested`
- Approval approval: `approval.approved`
- Approval rejection: `approval.rejected`
- Approval timeout: `approval.timed_out`

Approval decision audit should occur in the same transaction as decision persistence and approval request status update.

### 8.6 Policy service integration

Emit from `apps/api/apps/policies/services.py` for:

- Policy create/update/deactivate.
- Policy rule create/update/deactivate.
- Policy evaluation persistence.

For policy evaluation, emit `policy.evaluated` in the same transaction as the `PolicyEvaluation` record creation. If policy evaluation leads to a step state transition, both the `policy.evaluated` and step event should be in the same surrounding transaction when practical.

### 8.7 Actor propagation

Domain services need actor context without depending on HTTP request objects.

Recommended approach:

- Views derive an actor DTO from request or runner payload.
- Views pass the actor DTO to service methods.
- Service methods pass the actor DTO to `AuditService.emit(...)`.
- Lower-level services may use `system_actor()` when Django itself makes the decision.

Avoid importing DRF request objects into services. Services should receive plain values.

### 8.8 Avoiding circular imports

Audit service may need no imports from domain services. Domain services import `apps.audit.services`.

To reduce circular import risk:

- Keep `AuditService.emit(...)` independent of execution, approval, and policy models.
- Pass primitive IDs and strings into audit service.
- Keep event-type constants in `apps/api/apps/audit/events.py` if needed.
- Do not make audit service inspect domain objects.

---

## 9. Frontend data contracts and audit panel flow

### 9.1 Frontend types

Add audit types under `apps/web/src/features/audit/types.ts`.

Recommended TypeScript contracts:

```ts
export type AuditActorType = 'user' | 'runner' | 'system' | 'api_client' | 'unknown'

export interface AuditEvent {
  id: string
  actor_type: AuditActorType
  actor_id: string
  actor_label: string
  event_type: string
  object_type: string
  object_id: string
  organization_id: string
  metadata: Record<string, unknown>
  occurred_at: string
}

export interface AuditEventListResponse {
  count: number
  next: string | null
  previous: string | null
  results: AuditEvent[]
}
```

### 9.2 API client

Add audit API functions under `apps/web/src/features/audit/api/auditApi.ts`.

Recommended functions:

```ts
export function getObjectAuditTrail(input: {
  organizationId: string
  objectType: string
  objectId: string
  limit?: number
  offset?: number
}) {
  ...
}

export function getExecutionAuditTrail(input: {
  executionId: string
  organizationId?: string
  limit?: number
  offset?: number
}) {
  ...
}
```

If the backend implements `GET /api/v1/executions/{id}/audit/`, prefer that for execution detail. Otherwise use `GET /api/v1/audit/?object_type=execution&object_id=...` and document whether it includes related step/approval/policy events.

### 9.3 Execution-detail audit panel

Add an audit panel to `ExecutionDetailPage`.

Behavior:

- Fetch audit trail once execution detail has loaded and an execution ID is known.
- Use the execution's `organization_id` for tenant-scoped audit queries until auth exists.
- Show newest-first or timeline order consistently. For execution detail, oldest-first is easier to read as a timeline; backend can return newest-first and frontend can reverse only for display.
- Render event time, actor label, event type, object type, and a short metadata summary.
- Provide clear empty state: "No audit events recorded yet."
- Provide clear error state using existing API error rendering.
- Keep the panel read-only.

Recommended display rows:

- `20:00:00 runner-dev-01 claimed execution`
- `20:00:05 runner-dev-01 started step Verify prerequisites`
- `20:01:12 Django system evaluated policy High risk requires approval`
- `20:01:12 runner-dev-01 requested approval`
- `20:02:44 user@example.com approved request`
- `20:03:10 runner-dev-01 completed execution`

### 9.4 Metadata rendering

Do not dump raw JSON by default. Render known metadata keys with labels:

- `previous_status` -> "From"
- `new_status` -> "To"
- `step_key` -> "Step"
- `risk_level` -> "Risk"
- `outcome` -> "Outcome"
- `reason` -> "Reason"

A collapsible "Details" JSON view is acceptable for support users if metadata is already sanitized by the backend.

### 9.5 Query keys and polling

Add query keys:

```ts
auditTrail: (organizationId: string, objectType: string, objectId: string) =>
  ['audit', organizationId, objectType, objectId] as const,
executionAuditTrail: (executionId: string) =>
  ['execution', executionId, 'audit'] as const,
```

Polling:

- If execution status is active, audit panel may refetch at the same cadence as execution detail or a slower cadence such as 3000 ms.
- If execution is terminal, disable polling.
- Do not use WebSockets or SSE in Phase 10.3.

---

## 10. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### Milestone 0: Preflight and approval gate

Purpose: confirm baseline and final event taxonomy before code starts.

Files read:

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-blueprint.md`
- `docs/blueprints/phase-10-02-policies-blueprint.md`
- `apps/api/apps/audit/**`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/common/models.py`
- `apps/api/config/api_v1_urls.py`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`

Commands:

```bash
git status --short
cd apps/api && python manage.py test apps.executions apps.approvals apps.policies
cd apps/web && npm test -- --run
cd apps/web && npm run typecheck
```

Verification:

- Approvals and policies are implemented and passing.
- Service integration points are confirmed.
- Event taxonomy and metadata allowlist are reviewed.

Rollback:

- No changes in this milestone.

Human approval gate:

- Required before model/migration work.
- Approver confirms event taxonomy, metadata safety rules, and same-transaction behavior.

### Milestone 1: Audit app model, migration, and read-only admin

Purpose: create append-only persistence and support visibility without domain integration.

Files touched:

- `apps/api/apps/audit/apps.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/admin.py`
- `apps/api/apps/audit/migrations/0001_initial.py`
- `apps/api/apps/audit/tests/test_models.py`
- `apps/api/apps/audit/tests/test_admin.py`
- `apps/api/config/settings/base.py`

Commands:

```bash
cd apps/api && python manage.py makemigrations audit
cd apps/api && python manage.py migrate
cd apps/api && python manage.py test apps.audit.tests.test_models apps.audit.tests.test_admin
```

Verification:

- `AuditEvent` uses UUID primary key.
- Required fields and indexes exist.
- Updating an existing audit event is rejected.
- Deleting an audit event is rejected.
- Admin has no add/delete and no editable fields.

Rollback:

- Reverse the audit migration before any domain services emit audit events.
- Remove audit app registration if migration is reverted.

Human approval gate:

- Required before implementing emit service, because the migration becomes durable schema history.

### Milestone 2: Append-only audit service

Purpose: implement `AuditService.emit(...)` and metadata validation/sanitization.

Files touched:

- `apps/api/apps/audit/services.py`
- Optional: `apps/api/apps/audit/events.py`
- `apps/api/apps/audit/tests/test_services.py`

Commands:

```bash
cd apps/api && python manage.py test apps.audit.tests.test_services
```

Verification:

- Valid emit creates one `AuditEvent`.
- Invalid actor type is rejected.
- Invalid object type is rejected.
- Metadata must be a JSON object.
- Forbidden metadata keys are removed or rejected.
- Service exposes no update/delete path.

Rollback:

- Revert service files and tests; model can remain unused.

Human approval gate:

- Required before wiring audit into domain mutations.

### Milestone 3: Execution service audit integration

Purpose: audit execution and step state changes.

Files touched:

- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/views.py` if actor context must be passed from public actions.
- `apps/api/apps/executions/internal_views.py` if runner actor context must be passed explicitly.
- `apps/api/apps/executions/tests/test_audit_integration.py`

Commands:

```bash
cd apps/api && python manage.py test apps.executions.tests.test_audit_integration apps.executions
```

Verification:

- Execution create emits `execution.created`.
- Runner claim emits `execution.claimed` without claim token metadata.
- Step transitions emit correct step events.
- Execution completion emits `execution.completed` or `execution.failed`.
- Heartbeat does not emit audit events.
- Audit events roll back when the surrounding state transition rolls back.

Rollback:

- Revert execution service audit calls. Audit app remains available for later milestones.

Human approval gate:

- Required before approval and policy audit integration.

### Milestone 4: Approval and policy audit integration

Purpose: audit the highest-risk control-plane decisions.

Files touched:

- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_audit_integration.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/tests/test_audit_integration.py`

Commands:

```bash
cd apps/api && python manage.py test apps.approvals.tests.test_audit_integration apps.policies.tests.test_audit_integration apps.audit
```

Verification:

- Approval request creation emits `approval.requested`.
- Approval decision emits `approval.approved` or `approval.rejected`.
- Approval timeout emits `approval.timed_out`.
- Policy CRUD emits policy events.
- Policy evaluation emits `policy.evaluated`.
- Policy blocking a step produces both policy and step failure/block events in a consistent transaction.

Rollback:

- Revert approval and policy service audit calls.
- Leave execution audit integration in place if tests remain green.

Human approval gate:

- Required before exposing public audit APIs.

### Milestone 5: Public audit query API

Purpose: expose read-only audit listing and filtering under `/api/v1/`.

Files touched:

- `apps/api/apps/audit/serializers.py`
- `apps/api/apps/audit/views.py`
- `apps/api/apps/audit/urls.py`
- `apps/api/apps/audit/tests/test_api.py`
- `apps/api/config/api_v1_urls.py`
- Optional: `apps/api/apps/executions/views.py` for `GET /executions/{id}/audit/`

Commands:

```bash
cd apps/api && python manage.py test apps.audit.tests.test_api apps.executions.tests.test_api_contracts
```

Verification:

- `GET /api/v1/audit/?organization_id=...` returns paginated events.
- Object filter requires both `object_type` and `object_id`.
- Invalid timestamps return `400`.
- Write methods are not allowed.
- Cross-tenant audit events are not returned.
- Execution audit endpoint includes related step, approval, and policy evaluation events if implemented.

Rollback:

- Remove URL registration to disable public audit API while preserving events.

Human approval gate:

- Required before frontend audit panel work.

### Milestone 6: Frontend audit data layer

Purpose: add frontend types, API functions, hooks, and query keys.

Files touched:

- `apps/web/src/features/audit/types.ts`
- `apps/web/src/features/audit/api/auditApi.ts`
- `apps/web/src/features/audit/hooks/useObjectAuditTrail.ts`
- `apps/web/src/shared/lib/queryKeys.ts`
- Frontend tests adjacent to the new hook/API if existing conventions support them.

Commands:

```bash
cd apps/web && npm test -- --run
cd apps/web && npm run typecheck
```

Verification:

- Audit API calls target Django public APIs only.
- Query keys are stable and include tenant/object identifiers.
- Types match backend response shape.

Rollback:

- Revert frontend audit feature directory and query key additions.

Human approval gate:

- Required before adding the UI panel.

### Milestone 7: Execution-detail audit panel

Purpose: make audit events visible where operators inspect executions.

Files touched:

- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- Optional: `apps/web/src/features/executions/types.ts`

Commands:

```bash
cd apps/web && npm test -- --run ExecutionDetailPage
cd apps/web && npm run typecheck
cd apps/web && npm run lint
```

Verification:

- Execution detail renders audit events.
- Empty and error states render correctly.
- Active executions refetch audit at a bounded cadence.
- Terminal executions do not continue polling.
- Metadata is summarized safely and raw JSON is not dumped by default.

Rollback:

- Revert execution detail panel only. Backend audit remains active.

Human approval gate:

- Required before final end-to-end sign-off.

### Milestone 8: Manual end-to-end gate

Purpose: verify audit trail behavior across executions, policies, approvals, and UI.

Commands:

```bash
docker compose up -d postgres api runner web
cd apps/api && python manage.py migrate
cd apps/api && python manage.py test apps.audit apps.executions apps.approvals apps.policies
cd apps/web && npm run test:ci
```

Manual verification:

- Create an organization, runbook, workflow, policy, and approval-gated execution.
- Start an execution and let the runner claim it.
- Trigger a policy evaluation that requires approval.
- Approve the request.
- Let the step and execution complete.
- Open execution detail and verify timeline includes created, claimed, policy evaluated, approval requested, approval approved, step started/succeeded, and execution completed.
- Trigger a blocked policy path and verify audit explains why the step did not run.
- Confirm claim token, secrets, raw command output, and full request bodies are absent from audit metadata.

Rollback:

- Disable public audit URL registration if UI/API issues are found.
- Revert service audit calls in reverse milestone order if audit write failures block critical mutations.
- Do not delete emitted audit records unless a non-production database reset is explicitly approved.

Human approval gate:

- Required sign-off from engineering/product owner before Phase 10.3 is considered complete.

---

## 11. Testing strategy

### 11.1 Model and service tests

Cover:

- `AuditEvent` requires actor, event, object, organization, metadata, and occurred timestamp.
- `AuditEvent` has UUID primary key.
- Existing event update is rejected.
- Event delete is rejected.
- `AuditService.emit(...)` creates exactly one event.
- `AuditService.emit(...)` defaults `occurred_at`.
- Invalid enum values are rejected.
- Metadata must be a JSON object.
- Forbidden keys are rejected or scrubbed.
- Event ordering is deterministic when timestamps tie.

### 11.2 Transaction rollback tests

Cover:

- Domain mutation and audit event commit together.
- If audit emit raises inside the transaction, the domain mutation rolls back.
- If domain mutation raises before audit emit, no audit event is written.
- Approval decision rollback removes both decision and audit event.
- Policy evaluation rollback removes both evaluation and audit event.
- Execution step update rollback leaves both step status and audit trail unchanged.

Use transaction-aware tests where row locks and rollback behavior matter.

### 11.3 API tests

Cover:

- Organization trail list returns only that organization's events.
- Object trail requires valid `object_type` and `object_id`.
- Object trail returns expected events ordered by `occurred_at`.
- Event type filtering works as exact match.
- Actor type filtering works as exact match.
- Timestamp filters work and reject malformed values.
- Pagination limit and offset work.
- Write methods return `405`.
- Retrieve endpoint, if implemented, is tenant scoped.
- Execution audit endpoint, if implemented, includes related step, approval, and policy events.

### 11.4 Immutability and admin tests

Cover:

- Admin add permission is false.
- Admin delete permission is false.
- Admin fields are read-only.
- Admin cannot persist changed field values.
- Service exposes no update/delete method.
- Queryset update is not used by app code for audit events.

### 11.5 Multi-tenant tests

Cover:

- Organization A audit endpoint never returns Organization B events.
- Organization A object trail cannot retrieve Organization B execution events.
- Service rejects emit calls where organization ID does not match the domain object context if helper wrappers provide that validation.
- Execution-detail audit panel uses the loaded execution's organization ID.
- UUID guessing does not leak event existence across tenants.

### 11.6 Frontend tests

Cover:

- Audit panel renders events.
- Audit panel renders empty state.
- Audit panel renders API error state.
- Audit panel summarizes known metadata fields.
- Audit panel does not show forbidden metadata if backend sends sanitized data.
- Active execution refetch behavior is bounded.
- Terminal execution disables audit polling.
- Frontend calls only Django public endpoints.

### 11.7 Manual end-to-end gate

Manual verification must cover:

- Happy path execution with no approval.
- Approval-required execution.
- Policy-blocked execution.
- Approval rejection path.
- Approval timeout path if timeout behavior exists.
- Audit metadata safety review.
- Admin read-only verification.

---

## 12. Failure modes and risks

### Missing audit on error path

Risk: failed steps, rejected approvals, blocked policies, or handled exceptions change domain state without audit events.

Mitigation:

- Audit every service branch that persists a terminal or blocked state.
- Add failure-path integration tests.
- Keep event emission near the state mutation in the same service method.
- Do not rely on views or serializers to remember audit.

### Audit write failure

Risk: audit insert fails and blocks operational actions.

Mitigation:

- Same-transaction failure is intentional for audited state-changing actions.
- Keep audit metadata small and validation predictable.
- Avoid external dependencies in `AuditService.emit(...)`.
- Monitor DB constraint errors during manual gates.
- If audit write failures become frequent, fix the metadata contract rather than making audit best-effort.

### Audit table bloat

Risk: table grows quickly if too many low-value events are recorded.

Mitigation:

- Audit state-changing domain actions only.
- Do not audit GET requests, health checks, polling, or heartbeats.
- Add indexes aligned to expected query patterns.
- Do not add partitioning in Phase 10.3; document it as a future option when row counts justify it.

### Actor denormalization

Risk: actor labels become stale after users or runners are renamed.

Mitigation:

- This is intentional. Audit records must preserve what was known at the time.
- Store both stable actor ID and denormalized label.
- Do not backfill or rewrite labels when users change.

### Sensitive metadata leakage

Risk: audit metadata stores secrets, command output, claim tokens, or full request bodies.

Mitigation:

- Use allowlisted metadata builders per event type.
- Add forbidden-key scrubber tests.
- Do not pass arbitrary serializer data or request data into audit metadata.
- Review audit payloads during manual gate.

### Incomplete event taxonomy

Risk: implementation invents inconsistent event names over time.

Mitigation:

- Centralize event constants.
- Test expected event names.
- Require blueprint update or small design note for new audited domains.

### Circular imports

Risk: audit service imports domain services and creates dependency loops.

Mitigation:

- Keep audit service primitive and model-independent.
- Domain services import audit, not the reverse.
- Put constants in `apps.audit.events` if needed.

---

## 13. What NOT to do

- Do not use Django signals for audit emission.
- Do not write audit events asynchronously.
- Do not add Celery, Kafka, RabbitMQ, queues, event buses, outbox workers, or streaming infrastructure.
- Do not create a separate audit database, separate event store, or audit microservice.
- Do not let runner, frontend, AI, or integrations write audit events directly.
- Do not retroactively synthesize audit events from historical executions.
- Do not build a full audit query language.
- Do not add arbitrary metadata JSON filtering.
- Do not audit GET requests, health checks, frontend polling, runner heartbeat, or other no-op reads.
- Do not store claim tokens, secrets, webhook URLs, API keys, raw command output, cookies, authorization headers, or full request bodies in metadata.
- Do not hard-delete audit events.
- Do not expose public create/update/delete audit endpoints.
- Do not make audit admin editable.
- Do not use database triggers in Phase 10.3.
- Do not treat audit as the source of current domain state.

---

## 14. Definition of done

Phase 10.3 is complete when all of the following are true:

- `AuditEvent` exists with UUID primary key and required fields: `actor_type`, `actor_id`, `actor_label`, `event_type`, `object_type`, `object_id`, `organization_id`, `metadata`, and `occurred_at`.
- `AuditEvent` has indexes for organization trail, object trail, event type, and actor investigation.
- Audit events are append-only through model guardrails, service design, public API shape, and read-only admin.
- `AuditService.emit(...)` is the only supported audit write path.
- Audit writes occur synchronously in the same transaction as audited domain mutations.
- Execution service emits audit events for creation, claim, cancellation, step transitions, completion, and failure.
- Approval service emits audit events for request creation, approval, rejection, and timeout.
- Policy service emits audit events for policy/rule mutations and policy evaluations.
- Public read-only audit listing exists under `/api/v1/audit/` with object and organization filters.
- Execution-detail audit trail is available through either `/api/v1/executions/{id}/audit/` or a clearly documented audit query.
- Frontend execution detail includes a read-only audit panel.
- Tests cover model/service behavior, rollback semantics, API filtering, immutability/admin behavior, multi-tenant isolation, frontend rendering, and manual end-to-end flows.
- No Django signals, async audit writes, separate event store, retroactive synthetic audit, full query language, or GET/health-check auditing were introduced.
- Manual gate confirms the audit trail for approval-required, policy-blocked, and normal execution paths without leaking sensitive metadata.

Key assumptions:

- Phases 01-09 are complete and verified.
- Phase 10.1 approvals are complete and verified before audit implementation starts.
- Phase 10.2 policies are complete and verified before audit implementation starts.
- Auth/RBAC may still be incomplete, so actor fields support runner, system, unknown, and denormalized labels until authenticated user context is consistently available.
- Audit is authoritative for historical accountability, not for current domain state reconstruction.
