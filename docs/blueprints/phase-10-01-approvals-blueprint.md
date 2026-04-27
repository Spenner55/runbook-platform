# Phase 10.1: Approvals Expansion Blueprint

| Field | Value |
|---|---|
| Phase number | 10.1 |
| Phase name | Approvals |
| Objective | Add human approval gates that pause high-risk execution steps until explicitly approved or rejected, without breaking the Phase 01–09 control-plane architecture. |
| Status | Blueprint only |
| Depends on | Phases 01–09 complete and verified |
| Authored | 2026-04-23 |

---

## 1. Purpose and sequencing rationale

Phase 10.1 is the first platform-expansion phase because it introduces the first real operational gate in the execution lifecycle. After Phase 09, the system can create executions, let the runner claim work, execute steps sequentially, and show progress in the React UI. What it still cannot do is pause a dangerous step and require a human decision before the command is allowed to run.

That gap must be closed before the rest of Phase 10 for five reasons:

1. Policies come after approvals because policies need something concrete to control. A policy can only decide whether a step should require approval if the platform already knows how to create, list, decide, and resolve an approval request.
2. Audit comes after approvals because the first materially important human action in the platform is an approval or rejection. Audit records are most valuable once there is a real decision to capture.
3. Integrations come after approvals because there is nothing useful to notify external systems about until a step can actually enter a blocked state and wait for a human.
4. Streaming comes after approvals because live transport should carry stable lifecycle states. Building WebSockets or SSE before the system has `waiting_for_approval`, `approved`, `rejected`, and `timed_out` semantics would force a second contract migration immediately afterward.
5. Production hardening comes after approvals because hardening the wrong state machine locks in the wrong contracts. Approval gates define the hot path that later scaling, observability, and recovery work must protect.

This phase therefore establishes three foundational behaviors:

1. The execution step state machine gains `waiting_for_approval`.
2. Django persists approval requests and decisions as first-class control-plane records.
3. The runner learns how to stop before executing a protected step and poll Django until it receives a definitive next action.

---

## 2. Current-state inspection checklist

The blueprint assumes the following repo state was inspected and confirmed before planning:

- [x] `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` defines approvals as the first expansion phase and explicitly calls out the missing `waiting_for_approval` state.
- [x] `apps/api/apps/approvals/` currently contains only `__init__.py`; there are no models, services, serializers, views, URLs, tests, or migrations yet.
- [x] `apps/api/config/settings/base.py` does not include an approvals app in `INSTALLED_APPS`.
- [x] `apps/api/apps/executions/models.py` contains `Execution` and `ExecutionStep`, and `ExecutionStep.Status` currently allows only `pending`, `running`, `succeeded`, `failed`, and `skipped`.
- [x] `apps/api/apps/executions/services.py` currently allows only `pending -> running` and `running -> succeeded|failed` in `_VALID_STEP_TRANSITIONS`.
- [x] `apps/api/apps/executions/internal_views.py` exposes only `claim-next`, `heartbeat`, `step update`, and `complete` under `/api/v1/internal/...`.
- [x] `apps/api/apps/executions/internal_serializers.py` and `apps/runner/runner/schemas.py` do not define approval request or approval status contracts.
- [x] `apps/runner/runner/client.py` is POST-oriented for internal APIs and has no approval methods.
- [x] `apps/runner/runner/executor.py` executes every claimed step immediately after marking it `running`; it has no gate or pause loop.
- [x] `packages/workflow-schema/workflow.schema.json` currently supports `requiresApproval` only; it does not define approval timeout or richer approval metadata.
- [x] `apps/web/src/` currently has execution-detail polling but no approvals feature area, no approval inbox route, and no approval decision flow.
- [x] `docker-compose.yml` already has the required topology (`api`, `runner`, `web`, `ai`, `postgres`); approvals do not require any new service.

If any of these assumptions change before implementation begins, the implementation plan must be re-read against the current code before coding starts.

---

## 3. Architecture invariants and boundaries

These boundaries are mandatory for Phase 10.1:

| Invariant | Phase 10.1 consequence |
|---|---|
| Django is the control plane. | Approval creation, lifecycle, decision validation, timeout resolution, and state-transition authorization all live in Django services. |
| Runner talks only to Django internal APIs. | The runner cannot inspect the database, call the UI, call the AI service, or call external notification systems to resolve approvals. |
| Frontend talks only to Django public APIs. | The approval inbox and approve/reject actions go through `/api/v1/approvals/...` only. |
| AI service is stateless and advisory. | AI does not participate in approval routing, decisioning, timeout handling, or state transitions. |
| All APIs remain under `/api/v1/`. | Public approval APIs live under `/api/v1/approvals/...`. |
| Internal runner APIs remain under `/api/v1/internal/`. | Runner approval endpoints live under `/api/v1/internal/executions/.../steps/.../...`. |
| UUID primary keys remain standard. | `ApprovalRequest.id` and `ApprovalDecision.id` use `BaseModel`. |
| Business logic belongs in `services.py`. | Views validate and delegate. Serializers shape data. Approval and execution state changes stay out of views and serializers. |
| No queues or event infrastructure. | Approval timeout resolution is evaluated synchronously during control-plane reads and writes; no Celery, Kafka, RabbitMQ, or background jobs are introduced. |
| No service routes around Django. | There is no direct runner-to-DB path, no frontend-to-runner path, and no integration callback that mutates approval state outside Django. |

Phase 10.1 also adds the following design boundaries:

1. Approval gating is per-step, not per-execution and not multi-step.
2. One step has at most one approval request in Phase 10.1.
3. One approval request has at most one terminal decision in Phase 10.1.
4. Approval routing, delegation, escalation, quorum, and policy-based approver selection are explicitly out of scope.
5. Approval decisions are persisted in approvals tables only. They do not depend on a future audit app.
6. **Pre-auth actor labeling is informational only.** The `actor_display_name` field accepted on the decide endpoint is a client-supplied string. It MUST NOT be presented as authoritative attribution in any UI, audit event, or integration payload until Phase 10.7 auth is complete. Any record created with a client-supplied actor label must be stored with `decided_by_label` tagged as unverified (e.g., a separate `decided_by_label_source` field with value `unverified_pre_auth`). Once auth lands (Phase 10.7), the endpoint MUST ignore this field and derive the actor from the authenticated session. Phase 10.3 audit events for approvals in the pre-auth window must use `actor_type="unknown"`, not `actor_type="user"`.

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.1 |
|---|---|
| `apps/api/apps/approvals/` | New app implementation: models, migrations, services, serializers, public views, URLs, admin registration, tests. |
| `apps/api/apps/executions/` | Add `waiting_for_approval` step status, add approval-aware service helpers, extend internal runner serializers/views, expose approval state in public execution detail. |
| `apps/api/apps/common/` | Reuse existing error envelope; add new error codes through existing domain exceptions only if needed. |
| `apps/api/config/` | Register approvals app and include public approval routes under `/api/v1/`. |
| `apps/runner/runner/` | Add typed approval request/status schemas, internal client methods, executor approval loop, and tests. |
| `apps/web/src/` | Add approvals feature area, inbox route, approve/reject mutation flow, execution detail waiting-state rendering, and tests. |
| `packages/workflow-schema/` | Add `approvalTimeoutSeconds`; explicitly defer richer approval routing fields. |
| `docker-compose.yml` | No topology change. Existing services remain sufficient. |

Likely future implementation files:

- `apps/api/apps/approvals/apps.py`
- `apps/api/apps/approvals/models.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/serializers.py`
- `apps/api/apps/approvals/views.py`
- `apps/api/apps/approvals/urls.py`
- `apps/api/apps/approvals/admin.py`
- `apps/api/apps/approvals/tests/...`
- `apps/api/apps/approvals/migrations/0001_initial.py`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/tests/...`
- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/tests/...`
- `apps/web/src/features/approvals/...`
- `apps/web/src/routes/approvals/ApprovalsInboxPage.tsx`
- `apps/web/src/routes/approvals/ApprovalsInboxPage.test.tsx`
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `packages/workflow-schema/workflow.schema.json`
- `packages/workflow-schema/README.md`

---

## 5. Data model: fields, relationships, constraints, indexes, state transitions

### 5.1 `ApprovalRequest`

`ApprovalRequest` is the control-plane record that represents a step currently awaiting a human decision or already resolved by one.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `organization` | FK -> `organizations.Organization` | Denormalized for inbox queries and future tenant scoping. Must match `execution.organization`. |
| `execution` | FK -> `executions.Execution` | CASCADE is acceptable because approval history is scoped to execution lifecycle in 10.1. |
| `step` | OneToOne -> `executions.ExecutionStep` | Enforces one approval request per step in 10.1. |
| `status` | enum | `pending`, `approved`, `rejected`, `timed_out`. |
| `requested_by_runner_id` | `CharField(255)` | Snapshot of the runner identity that asked for approval. |
| `requested_at` | `DateTimeField` | Set when the request is created. |
| `timeout_seconds` | `PositiveIntegerField(null=True)` | Snapshot of the configured timeout for this request. |
| `expires_at` | `DateTimeField(null=True)` | Concrete deadline derived at request creation time. |
| `resolved_at` | `DateTimeField(null=True)` | Set when status leaves `pending`. |
| `decision_summary` | `CharField(32, blank=True)` | Optional denormalized mirror of the final decision for list rendering; if added, it must match the related `ApprovalDecision.decision`. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| unique | One-to-one on `step` | Prevent duplicate approval requests for one execution step. |
| index | `(organization, status, requested_at)` | Fast approval inbox queries. |
| index | `(execution, status)` | Fast execution-detail joins and debugging. |
| index | `(status, expires_at)` | Fast timeout resolution lookups. |
| service invariant | `organization_id == execution.organization_id` and `step.execution_id == execution.id` | Prevent cross-tenant or cross-execution corruption. |

### 5.2 `ApprovalDecision`

`ApprovalDecision` is the immutable terminal record that explains how a request left `pending`.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. |
| `approval_request` | OneToOne -> `ApprovalRequest` | Enforces one terminal decision per request in 10.1. |
| `decision` | enum | `approved`, `rejected`, `timed_out`. |
| `source_type` | enum | `human` or `system`. Timeout uses `system`. |
| `decided_by_user` | FK -> `AUTH_USER_MODEL`, null=True | Nullable bridge for future auth. |
| `decided_by_label` | `CharField(255, blank=True)` | Snapshot display name for local/dev or later denormalized history. |
| `notes` | `TextField(blank=True)` | Optional human rationale. |
| `decided_at` | `DateTimeField` | Terminal timestamp. |

Recommended indexes and constraints:

| Kind | Definition | Purpose |
|---|---|---|
| unique | One-to-one on `approval_request` | Prevent duplicate terminal decisions. |
| index | `(decision, decided_at)` | Operational reporting and support queries. |
| index | `(decided_by_user, decided_at)` | Future actor lookup once auth exists. |

### 5.3 Why two models are required

Do not collapse these into one table.

`ApprovalRequest` is the mutable lifecycle record used for inbox queries and polling. `ApprovalDecision` is the immutable terminal record used to preserve how the request ended. Keeping them separate makes the lifecycle explicit and avoids overwriting the final actor, notes, and timestamp on a mutable row.

### 5.4 Workflow schema changes

Recommended schema decision:

1. Keep `requiresApproval: boolean` as the existing gate flag.
2. Add `approvalTimeoutSeconds: integer` as an optional step field.
3. Do not add `approvalType` yet.

Rationale:

1. `approvalTimeoutSeconds` is justified immediately because `timed_out` is a required approval lifecycle state in this phase.
2. `approvalType` is not justified yet because Phase 10.1 has only one approval mode: human manual approval. Adding a one-value enum now creates schema churn without adding behavior.
3. The timeout value should be copied into `ApprovalRequest.timeout_seconds` and `ApprovalRequest.expires_at` when the request is created so in-flight executions are not affected by later workflow edits.

### 5.5 Step state transitions

`ExecutionStep.Status` gains one new value:

- `waiting_for_approval`

Resulting step transition table:

| From | To | Trigger |
|---|---|---|
| `pending` | `waiting_for_approval` | Runner reaches a protected step and Django successfully creates or reuses the approval request. |
| `pending` | `running` | Runner reaches a non-protected step. |
| `waiting_for_approval` | `running` | Approval status becomes `approved` and runner starts the command. |
| `waiting_for_approval` | `failed` | Approval status becomes `rejected` or `timed_out` and runner records terminal failure without running the command. |
| `running` | `succeeded` | Command exits successfully. |
| `running` | `failed` | Command exits unsuccessfully. |

Explicitly out of scope:

1. No `approved` step state.
2. No `rejected` step state.
3. No execution-level `waiting_for_approval` state.

The execution status can remain `claimed` while the first step waits for approval. That keeps Phase 10.1 minimal and avoids widening the top-level execution state machine before it is necessary.

### 5.6 Approval request lifecycle

Approval request state transitions:

| From | To | Trigger |
|---|---|---|
| `pending` | `approved` | Human approves via public API. |
| `pending` | `rejected` | Human rejects via public API. |
| `pending` | `timed_out` | Django resolves expiration during approval status reads or decision attempts after `expires_at`. |

All terminal states are final. There is no reopen, retract, or edit behavior in Phase 10.1.

### 5.7 Concurrency rules

Approval decision writes must follow the current official Django transaction guidance:

1. Wrap terminal decision logic in `transaction.atomic()`.
2. Lock the `ApprovalRequest` row with `select_for_update()` before checking status and writing the decision.
3. Treat already-terminal requests as `409 Conflict`.
4. Use transaction-aware tests for concurrent decision races, not plain non-transactional unit tests.

This is the correct place to be strict. A double approval is a state-corruption bug, not a cosmetic issue.

---

## 6. API contracts: request/response shapes, status codes, error envelopes

All APIs stay under `/api/v1/` and use the existing error envelope shape from `apps/common/api_errors.py`:

```json
{
  "errors": [
    {
      "code": "some_error_code",
      "detail": "Human-readable detail",
      "attr": "optional_field_name"
    }
  ]
}
```

### 6.1 Public approval inbox APIs

#### `GET /api/v1/approvals/`

Purpose: return approval requests for the inbox UI.

Recommended query parameters:

| Param | Required | Notes |
|---|---|---|
| `organization_id` | yes in 10.1 | Keeps tenant scoping explicit before auth exists. |
| `status` | no | Default `pending`; allowed `pending`, `approved`, `rejected`, `timed_out`, `all`. |
| `execution_id` | no | Optional drill-down filter. |

Recommended `200 OK` response shape:

```json
{
  "results": [
    {
      "id": "uuid",
      "organization_id": "uuid",
      "execution_id": "uuid",
      "execution_status": "claimed",
      "step": {
        "id": "uuid",
        "position": 2,
        "step_key": "deploy",
        "name": "Deploy production service",
        "step_type": "shell",
        "risk_level": "high",
        "status": "waiting_for_approval",
        "requires_approval": true
      },
      "status": "pending",
      "requested_by_runner_id": "runner-a",
      "requested_at": "2026-04-23T20:00:00Z",
      "timeout_seconds": 1800,
      "expires_at": "2026-04-23T20:30:00Z",
      "resolved_at": null,
      "decision": null
    }
  ]
}
```

Decision payload when terminal:

```json
{
  "decision": {
    "id": "uuid",
    "decision": "approved",
    "source_type": "human",
    "decided_by_label": "Local Operator",
    "decided_at": "2026-04-23T20:05:00Z",
    "notes": "Validated maintenance window."
  }
}
```

Status codes:

| Status | Meaning |
|---|---|
| `200` | Success |
| `400` | Invalid query parameters |

#### `GET /api/v1/approvals/<approval_request_id>/`

Purpose: optional detail endpoint for the inbox detail drawer or execution deep-link.

Return the same shape as the list item plus the full decision payload when present.

Status codes:

| Status | Meaning |
|---|---|
| `200` | Success |
| `404` | Approval request not found |

#### `POST /api/v1/approvals/<approval_request_id>/decide/`

Purpose: approve or reject a pending request.

Recommended request shape:

```json
{
  "decision": "approved",
  "notes": "Validated change ticket and rollback plan.",
  "actor_display_name": "Local Operator"
}
```

Notes:

1. `decision` allows only `approved` or `rejected` from the public API. `timed_out` is system-generated only.
2. Until auth exists, `actor_display_name` is the minimal bridge that lets the platform capture a human actor label without redesigning the endpoint later.
3. Once auth exists, Django should ignore client-supplied actor labels and derive the actor from the authenticated user while keeping the same response contract.

Recommended success response:

```json
{
  "id": "uuid",
  "status": "approved",
  "resolved_at": "2026-04-23T20:05:00Z",
  "decision": {
    "id": "uuid",
    "decision": "approved",
    "source_type": "human",
    "decided_by_label": "Local Operator",
    "decided_at": "2026-04-23T20:05:00Z",
    "notes": "Validated change ticket and rollback plan."
  }
}
```

Status codes:

| Status | Meaning |
|---|---|
| `200` | Decision recorded |
| `400` | Invalid payload or missing `actor_display_name` in pre-auth mode |
| `404` | Approval request not found |
| `409` | Approval request already decided or not in a decidable state |

Suggested error codes:

- `approval_request_not_found`
- `approval_request_not_pending`
- `approval_request_already_decided`
- `approval_actor_required`
- `approval_decision_invalid`

### 6.2 Internal runner approval APIs

Use POST for internal approval APIs to stay aligned with the current runner contract pattern and keep `claim_token` out of the query string.

#### `POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/approval-request/`

Purpose: atomically place the step into `waiting_for_approval` and create or reuse the `ApprovalRequest`.

Recommended request shape:

```json
{
  "runner_id": "runner-a",
  "claim_token": "uuid",
  "requested_at": "2026-04-23T20:00:00Z"
}
```

Recommended response shape:

```json
{
  "execution_id": "uuid",
  "execution_status": "claimed",
  "step": {
    "id": "uuid",
    "status": "waiting_for_approval"
  },
  "approval_request": {
    "id": "uuid",
    "status": "pending",
    "requested_at": "2026-04-23T20:00:00Z",
    "timeout_seconds": 1800,
    "expires_at": "2026-04-23T20:30:00Z"
  },
  "poll_after_seconds": 5
}
```

Status codes:

| Status | Meaning |
|---|---|
| `201` | New approval request created |
| `200` | Existing approval request reused idempotently |
| `404` | Execution or step not found |
| `409` | Runner ownership mismatch, step not pending, or step not eligible for approval |

Suggested error codes:

- `runner_ownership_mismatch`
- `claim_token_mismatch`
- `step_not_found`
- `approval_not_required_for_step`
- `approval_request_conflict`
- `invalid_state_transition`

Idempotency rule:

If the runner retries after a network ambiguity and the step already has an approval request, the endpoint must return the existing request instead of creating a duplicate or failing spuriously.

#### `POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/approval-status/`

Purpose: tell the runner whether to keep waiting, begin execution, or fail the step.

Recommended request shape:

```json
{
  "runner_id": "runner-a",
  "claim_token": "uuid",
  "observed_step_status": "waiting_for_approval",
  "sent_at": "2026-04-23T20:00:05Z"
}
```

Recommended response shape:

```json
{
  "execution_id": "uuid",
  "execution_status": "claimed",
  "step_id": "uuid",
  "step_status": "waiting_for_approval",
  "approval_request": {
    "id": "uuid",
    "status": "pending",
    "requested_at": "2026-04-23T20:00:00Z",
    "timeout_seconds": 1800,
    "expires_at": "2026-04-23T20:30:00Z",
    "resolved_at": null,
    "decision": null
  },
  "runner_action": "wait",
  "poll_after_seconds": 5
}
```

Runner-action mapping:

| Approval status | `runner_action` | Runner behavior |
|---|---|---|
| `pending` | `wait` | Sleep and poll again. |
| `approved` | `run` | Transition step to `running` and execute command. |
| `rejected` | `fail` | Transition step to `failed`, do not run command, complete execution as failed. |
| `timed_out` | `fail` | Transition step to `failed`, do not run command, complete execution as failed. |

Status codes:

| Status | Meaning |
|---|---|
| `200` | Success |
| `404` | Execution, step, or approval request not found |
| `409` | Runner ownership mismatch or step not in approval flow |

Important behavior:

This endpoint is where Django should materialize timeout resolution. If `status == pending` and `expires_at <= now`, the service should lock the request, convert it to `timed_out`, create the `ApprovalDecision`, and return `runner_action=fail`.

---

## 7. Runner contract and timeout behavior

### 7.1 Runner execution sequence for all steps (normalized contract)

> **ARCHITECTURE DECISION (required for Phase 10.2 compatibility):** The runner MUST ask Django to start every step, not only steps where `requires_approval=true` in the workflow JSON. Django returns a normalized `runner_action` field. The runner obeys the action. This allows Phase 10.2 policy evaluation to require approval even when `requiresApproval=false` in the workflow definition, without any runner code change.

For every claimed step, the runner flow is:

1. Call `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/start/` with the runner identity and claim token. Do NOT inspect the local `requires_approval` field and branch before calling.
2. Django evaluates all applicable rules (Phase 10.1: workflow flag check; Phase 10.2+: policy evaluation) and returns a response with `runner_action` set to one of: `run`, `wait_for_approval`, or `blocked`.
3. If `runner_action == "run"`: step is already transitioned to `running` by Django; execute the command.
4. If `runner_action == "wait_for_approval"`: step is already transitioned to `waiting_for_approval` by Django; enter the approval poll loop.
5. If `runner_action == "blocked"`: step has been transitioned to `failed` by Django; record failure and complete execution as failed without running the command.
6. Poll `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/approval-status/` using the existing runner identity and claim token.
7. If Django returns `runner_action=wait`, sleep `poll_after_seconds` and poll again.
8. If Django returns `runner_action=run`, execute the command.
9. If Django returns `runner_action=fail`, record step as failed and complete execution without running the command.
10. **Never run the command until Django explicitly returns `runner_action=run`.**

> **Phase 10.1 note:** The start endpoint in Phase 10.1 only needs to handle the workflow-level `requires_approval` flag. The `runner_action` response contract is designed to be forward-compatible with Phase 10.2 policy evaluation behind the same endpoint — Phase 10.2 adds logic to the Django service, not a new runner endpoint.

> **Contract test required at Phase 10.1 gate:** A test must prove that a step with `requiresApproval=false` in the workflow JSON still returns `runner_action=wait_for_approval` if a policy (Phase 10.2+) requires approval. The contract test can use a mock/stub policy hook in Phase 10.1 to verify the runner behavior is correct before policies are implemented.

### 7.2 Timeout behavior

Timeout ownership rules:

1. Workflow schema defines an optional `approvalTimeoutSeconds`.
2. Django snapshots that value onto the `ApprovalRequest`.
3. Django computes `expires_at`.
4. Django is authoritative for deciding when a request has timed out.
5. The runner never invents approval timeouts on its own.

Runner timeout behavior:

1. The runner uses `poll_after_seconds` from Django for sleeping.
2. The runner keeps polling on `pending`.
3. On the first successful poll after expiration, Django returns `timed_out` and `runner_action=fail`.
4. If transient HTTP errors occur during polling, the runner keeps retrying and relies on Django to return the terminal state once connectivity resumes.

Phase 10.1 intentionally keeps this simple. Do not add exponential backoff, retry classification matrices, or stale-claim rescue logic here. Those belong to later hardening once the approval lifecycle itself is stable.

### 7.3 Runner restart behavior

The approvals design must not rely on in-memory runner state:

1. Approval request state lives in Django.
2. Approval timeout state lives in Django.
3. The runner can reconstruct the next action by re-calling approval-status if it still owns the execution.

Residual limitation:

The broader claimed-execution recovery problem still exists in the current platform. Phase 10.1 should not attempt a general runner-takeover protocol. It should only ensure approvals do not introduce a second, approval-specific ownership model.

---

## 8. Frontend data contracts and UI flows

### 8.1 Frontend types

Add a dedicated approvals feature area instead of overloading execution types.

Recommended frontend data shapes:

```ts
type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'timed_out'

interface ApprovalDecision {
  id: string
  decision: 'approved' | 'rejected' | 'timed_out'
  source_type: 'human' | 'system'
  decided_by_label: string
  decided_at: string
  notes: string
}

interface ApprovalRequestListItem {
  id: string
  organization_id: string
  execution_id: string
  execution_status: string
  status: ApprovalStatus
  requested_by_runner_id: string
  requested_at: string
  timeout_seconds: number | null
  expires_at: string | null
  resolved_at: string | null
  step: {
    id: string
    position: number
    step_key: string
    name: string
    step_type: string
    risk_level: string
    status: string
    requires_approval: boolean
  }
  decision: ApprovalDecision | null
}
```

### 8.2 UI routes and pages

Recommended UI additions:

| Area | Change |
|---|---|
| `apps/web/src/app/router.tsx` | Add `/approvals` inbox route. |
| `apps/web/src/app/AppLayout.tsx` | Add primary navigation link for Approvals. |
| `apps/web/src/features/approvals/` | Add `types.ts`, `api/approvalsApi.ts`, `hooks/useApprovalsInbox.ts`, `hooks/useDecideApproval.ts`. |
| `apps/web/src/routes/approvals/ApprovalsInboxPage.tsx` | Add inbox page with list, filters, and approve/reject action. |
| `apps/web/src/routes/executions/ExecutionDetailPage.tsx` | Render `waiting_for_approval` status clearly and link to the inbox or request detail. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add approval query keys. |

### 8.3 Inbox flow

Recommended inbox flow:

1. User opens `/approvals`.
2. UI fetches `GET /api/v1/approvals/?organization_id=<uuid>&status=pending`.
3. Pending items render with step name, risk level, execution id, requested time, timeout deadline, and runner id.
4. User chooses one item and opens an approve/reject action panel.
5. User submits a decision with notes and actor display name in pre-auth mode.
6. UI posts to `/api/v1/approvals/<id>/decide/`.
7. On success, invalidate the approvals inbox query and the related execution detail query.

### 8.4 Execution-detail flow

Execution detail must become approval-aware:

1. `waiting_for_approval` should render as a first-class pill state, not as a generic string.
2. A protected waiting step should show a banner such as "Awaiting approval before command execution."
3. If approval is rejected or timed out, the step failure message should explain that the command was never executed.
4. The page should keep polling execution detail exactly as it does now; do not add streaming in Phase 10.1.

### 8.5 Polling behavior in the browser

Frontend polling remains the correct Phase 10.1 transport:

1. Inbox page may poll for pending approvals every few seconds while visible.
2. Execution detail page already polls active executions and should continue doing so.
3. Do not add WebSockets or SSE.

---

## 9. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### 9.1 Milestone A: execution state groundwork

| Item | Detail |
|---|---|
| Goal | Add `waiting_for_approval` to the step state machine without changing runner behavior yet. |
| Small steps | 1. Update `ExecutionStep.Status` in `apps/api/apps/executions/models.py`. 2. Extend `_VALID_STEP_TRANSITIONS` in `apps/api/apps/executions/services.py` to include approval transitions. 3. Update serializers so public execution detail can render the new state. 4. Generate the execution migration. |
| Files touched | `apps/api/apps/executions/models.py`, `apps/api/apps/executions/services.py`, `apps/api/apps/executions/serializers.py`, `apps/api/apps/executions/migrations/...`, execution tests. |
| Commands | `make makemigrations-app APP=executions`; `make test-api-v` |
| Verification | Existing execution tests still pass and new step state serializes correctly. No runner endpoints are changed yet. |
| Rollback notes | Safe to rollback before any row enters `waiting_for_approval`. If such rows exist, resolve or fail them first before removing the enum value. |
| Human approval gate | Confirm the team wants the new step state introduced before creating the approvals tables. |

### 9.2 Milestone B: approvals app data model and service layer

| Item | Detail |
|---|---|
| Goal | Introduce `ApprovalRequest` and `ApprovalDecision` plus transactional service helpers. |
| Small steps | 1. Add `apps.py`, `models.py`, `admin.py`, and initial migration. 2. Register the approvals app in `INSTALLED_APPS`. 3. Implement service functions such as `request_step_approval`, `decide_approval`, `get_approval_status`, and `list_approvals`. 4. Add transaction-aware concurrency tests. |
| Files touched | `apps/api/apps/approvals/*`, `apps/api/config/settings/base.py`, approvals tests. |
| Commands | `make makemigrations-app APP=approvals`; `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/approvals/tests -v` |
| Verification | Approval request creation is idempotent per step, terminal decisions are single-write only, and timeout resolution produces `timed_out` exactly once. |
| Rollback notes | Safe to rollback if no downstream code depends on the new tables. If real approval rows exist, export or preserve them before dropping the migration. |
| Human approval gate | Review model field names, indexes, and the one-request-per-step rule before exposing any APIs. |

### 9.3 Milestone C: public approval inbox and decision APIs

| Item | Detail |
|---|---|
| Goal | Expose approval list/detail/decision endpoints under `/api/v1/approvals/`. |
| Small steps | 1. Add public serializers and views in the approvals app. 2. Add `urls.py` for approvals. 3. Include approval routes in `apps/api/config/api_v1_urls.py`. 4. Add API contract tests for list, detail, approve, reject, and already-decided conflicts. |
| Files touched | `apps/api/apps/approvals/serializers.py`, `apps/api/apps/approvals/views.py`, `apps/api/apps/approvals/urls.py`, `apps/api/config/api_v1_urls.py`, approvals API tests. |
| Commands | `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/approvals/tests/test_api_contracts.py -v` |
| Verification | `GET /api/v1/approvals/` returns pending requests scoped by organization, and `POST /decide/` returns `409` on a second attempt. |
| Rollback notes | Public routes can be removed safely if the runner has not yet been updated to create approval requests in live flows. |
| Human approval gate | Review payload shapes and confirm the temporary `actor_display_name` bridge is acceptable until auth lands. |

### 9.4 Milestone D: internal runner approval APIs

| Item | Detail |
|---|---|
| Goal | Add the runner-facing approval request and approval status endpoints. |
| Small steps | 1. Add approval request and approval status serializers in `apps/api/apps/executions/internal_serializers.py` or a new approvals-internal serializer module. 2. Add internal views that delegate to approval services. 3. Register internal routes under `/api/v1/internal/...`. 4. Add contract tests covering ownership mismatch, idempotent request creation, pending polling, approval resolution, rejection resolution, and timeout resolution. |
| Files touched | `apps/api/apps/executions/internal_serializers.py`, `apps/api/apps/executions/internal_views.py`, `apps/api/config/api_v1_urls.py`, runner API tests, possibly approvals service tests. |
| Commands | `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/executions/tests/test_runner_api.py -v` |
| Verification | Internal endpoints remain POST-based, honor runner ownership, and return `runner_action` values that make the next runner step unambiguous. |
| Rollback notes | Safe if the runner client has not yet been deployed with approval support. |
| Human approval gate | Review the exact runner contract before changing client code so both sides implement the same payloads. |

### 9.5 Milestone E: runner client and executor approval loop

| Item | Detail |
|---|---|
| Goal | Teach the runner to pause before protected steps and poll Django for a decision. |
| Small steps | 1. Extend `apps/runner/runner/schemas.py` with approval request/status models. 2. Extend `apps/runner/runner/client.py` with `request_step_approval()` and `get_step_approval_status()`. 3. Update `apps/runner/runner/executor.py` to branch on `requires_approval`. 4. Add runner tests for approve, reject, timeout, and network retry behavior. |
| Files touched | `apps/runner/runner/schemas.py`, `apps/runner/runner/client.py`, `apps/runner/runner/executor.py`, runner tests. |
| Commands | `make test-runner`; `docker compose exec runner pytest apps/runner/runner/tests/test_executor.py -q` |
| Verification | Runner never executes a protected command before `runner_action=run`, and rejected/timed-out requests mark the step failed without invoking the command. |
| Rollback notes | Do not roll back runner support after protected workflows are active. Disable or reject approval-required workflows first, then revert runner code if necessary. |
| Human approval gate | Confirm protected workflows remain disabled until both Django and runner changes are deployed together. |

### 9.6 Milestone F: frontend inbox and execution-detail UX

| Item | Detail |
|---|---|
| Goal | Give operators a public approval inbox and clear execution visibility. |
| Small steps | 1. Add approvals feature types, API client functions, and hooks. 2. Add `/approvals` route and nav entry. 3. Implement inbox list and approve/reject form. 4. Update execution detail rendering for `waiting_for_approval`. 5. Add route tests and mutation tests. |
| Files touched | `apps/web/src/features/approvals/*`, `apps/web/src/routes/approvals/*`, `apps/web/src/app/router.tsx`, `apps/web/src/app/AppLayout.tsx`, `apps/web/src/shared/lib/queryKeys.ts`, `apps/web/src/routes/executions/ExecutionDetailPage.tsx`, web tests. |
| Commands | `make test-web`; `docker compose exec web npm test -- --run` |
| Verification | Pending approvals appear in the inbox, decisions invalidate the correct queries, and execution detail renders waiting status without streaming. |
| Rollback notes | UI can be rolled back independently if public APIs stay stable, but do not hide the inbox if approval-required steps are already live in operator workflows. |
| Human approval gate | Review UX text carefully so operators understand that approval occurs before command execution, not after. |

### 9.7 Milestone G: manual end-to-end gate

| Item | Detail |
|---|---|
| Goal | Verify the full approval path across API, runner, and UI before any later Phase 10 work starts. |
| Small steps | 1. Start the local stack. 2. Create or seed a workflow with one `requiresApproval=true` step and one normal step after it. 3. Start an execution. 4. Confirm the protected step enters `waiting_for_approval`. 5. Approve once and verify the runner resumes. 6. Re-run with rejection and timeout. |
| Files touched | No new source files. Verification only. |
| Commands | `make up-d`; `make migrate`; `make seed-dev`; `make logs-runner`; `make logs-api`; `make test-api`; `make test-runner`; `make test-web` |
| Verification | All three paths work: approved resumes execution, rejected fails without running the command, timed-out fails without running the command. |
| Rollback notes | If manual verification fails, stop here. Do not begin policies, audit, integrations, or streaming work until the approval gate is fixed. |
| Human approval gate | Explicit sign-off that Phase 10.1 is complete and that Phase 10.2 may begin. |

---

## 10. Testing strategy: Django service tests, API contract tests, transaction/concurrency tests for double approval, runner tests, frontend tests, manual end-to-end gate

### 10.1 Django service tests

Add service-level tests for:

1. `request_step_approval()` creates one request for a protected pending step.
2. Repeating `request_step_approval()` for the same step is idempotent.
3. `decide_approval(..., decision="approved")` records a terminal decision and changes request status to `approved`.
4. `decide_approval(..., decision="rejected")` records a terminal decision and changes request status to `rejected`.
5. `get_approval_status()` resolves expiration to `timed_out` once `expires_at` has passed.
6. Cross-execution and cross-organization mismatches are rejected.

### 10.2 API contract tests

Add public API tests for:

1. `GET /api/v1/approvals/` returns only the requested organization scope.
2. `POST /api/v1/approvals/<id>/decide/` with `approved` returns `200`.
3. `POST /api/v1/approvals/<id>/decide/` with `rejected` returns `200`.
4. Missing actor label in pre-auth mode returns `400`.
5. Double-decision returns `409`.

Add internal API tests for:

1. Approval request creation returns `201` on first call and `200` on idempotent retry.
2. Approval status returns `runner_action=wait` for pending.
3. Approval status returns `runner_action=run` for approved.
4. Approval status returns `runner_action=fail` for rejected and timed-out.
5. Ownership mismatches return `409`.

### 10.3 Transaction and concurrency tests

Double approval is the critical concurrency test.

Use transaction-aware tests only:

1. `pytest.mark.django_db(transaction=True)` or Django `TransactionTestCase`.
2. Two threads race to decide the same pending approval request.
3. Exactly one thread succeeds.
4. The losing thread receives `409`.
5. Exactly one `ApprovalDecision` row exists afterward.

Do not rely on plain `TestCase` semantics here. Row-locking behavior must be exercised in a real transaction boundary.

### 10.4 Runner tests

Add or extend:

1. `apps/runner/runner/tests/test_client.py` for new approval request/status methods.
2. `apps/runner/runner/tests/test_executor.py` for pending wait loop, approved resume, rejected fail, and timed-out fail.
3. `apps/runner/runner/tests/test_orchestration.py` to ensure the happy path still completes after an approved gate.

Assertions must include:

1. Protected command does not execute before approval.
2. Rejected and timed-out paths never invoke command execution.
3. Step-update calls happen in the right order.

### 10.5 Frontend tests

Add or extend:

1. Inbox page render test.
2. Approve action success test.
3. Reject action success test.
4. Error-banner test for a `409` already-decided response.
5. Execution detail waiting-state render test.

### 10.6 Manual end-to-end gate

Manual verification must include:

1. Approved path.
2. Rejected path.
3. Timed-out path.

Each path must verify the operator-facing UI, the execution-detail state, and the runner behavior.

---

## 11. Failure modes and risks: deadlock, double approval, runner restart, timeout, stale claim ownership, multi-tenancy

| Failure mode | Why it can happen | Phase 10.1 mitigation | Residual risk |
|---|---|---|---|
| Deadlock or long lock waits | Concurrent approvers or timeout resolution race on the same request | Keep transactions short, lock one `ApprovalRequest` row with `select_for_update()`, and avoid locking unrelated execution rows in the same transaction | Under heavy contention, writes can still wait briefly; acceptable in 10.1 |
| Double approval | Two humans click approve or reject at the same time | `transaction.atomic()`, `select_for_update()`, one-to-one `ApprovalDecision`, `409` on second writer | None if the service is implemented correctly |
| Runner restart during waiting | Approval loop state was only in memory | Approval state lives in Django; runner can reconstruct next action by asking approval-status again if it still owns the execution | Full claimed-execution recovery remains broader platform work |
| Timeout never fires | No queue or scheduler exists | Resolve expiration synchronously in Django when approval status is queried or when a human tries to decide an expired request | A dead runner will delay timeout observation until another control-plane read occurs. **Phase 10.9 must add a `recover_expired_approvals()` sweep alongside the stuck-execution watchdog so expired approvals are resolved even when neither the runner nor the UI is actively polling.** |
| Stale claim ownership | Runner dies after placing a step into waiting state | Do not add a second ownership model; keep using `runner_id + claim_token` and document that general stale-claim reclamation is outside 10.1 | Operational recovery for abandoned claimed executions still needs later hardening |
| Multi-tenancy leakage | Approval inbox lists requests across organizations | Store `organization_id` on `ApprovalRequest`, require organization scoping on inbox API, and validate request/execution/step organization alignment in services | Public APIs are still pre-auth; Phase 10.7 must add real authorization |
| Idempotency bug on approval-request creation | Runner retries after an HTTP timeout | One-to-one `step` relationship and idempotent service behavior | None if implemented correctly |
| Protected command accidentally runs before approval | Executor calls `update_step(running)` before checking approval | Make approval branching happen before the existing running transition | Severe bug if missed; must be covered by tests |
| UI shows stale state | Public execution detail and inbox poll at different cadences | Invalidate both approval and execution queries after decision; keep short polling in 10.1 | Small transient mismatch is acceptable under polling |

---

## 12. What NOT to do: no delegation, no routing engine, no integration notifications, no audit app dependency, no WebSockets/SSE, no queues

Phase 10.1 must stay narrow.

Do not do any of the following:

1. No approval delegation. One request, one human decision, no proxy approvers.
2. No approval routing engine. Do not assign approvers by role, policy, team, or escalation tree yet.
3. No integration notifications. Do not send Slack, PagerDuty, email, or Jira messages from this phase.
4. No audit app dependency. Persist the approval request and terminal decision in approvals tables only.
5. No WebSockets or SSE. Polling remains the transport for both the UI and the runner.
6. No queues, Kafka, Celery, RabbitMQ, cron workers, or event buses.
7. No separate orchestration service. Django remains the only control plane.
8. No command mutation. Approvals decide whether a step may run, not how the command is rewritten.
9. No general runner-recovery framework. Do not mix stale-claim reclamation into the approvals scope.
10. No execution-level routing graph redesign. This phase is about pausing a sequential step, not replacing the engine.

---

## 13. Definition of done

Phase 10.1 is done only when all of the following are true:

- `ApprovalRequest` and `ApprovalDecision` exist with migrations, tests, and service-layer ownership.
- `ExecutionStep.Status` includes `waiting_for_approval`.
- Protected steps transition into `waiting_for_approval` before command execution.
- Public APIs exist for approval inbox listing and approve/reject decisions under `/api/v1/approvals/...`.
- Internal runner APIs exist for approval-request creation and approval-status polling under `/api/v1/internal/...`.
- Runner client and executor support protected-step pause/resume/fail behavior.
- Frontend has an approvals inbox route and approve/reject flow.
- Execution detail clearly renders `waiting_for_approval` and terminal approval-driven failures.
- Workflow schema supports `approvalTimeoutSeconds`.
- Transaction-aware concurrency tests prove that double approval yields exactly one terminal decision and one `409`.
- Runner tests prove protected commands never execute before approval.
- Manual end-to-end verification proves approved, rejected, and timed-out paths all behave correctly.
- No new service was introduced.
- No queue or event infrastructure was introduced.
- No policy engine, delegation logic, audit dependency, or streaming transport was introduced.
- The team explicitly signs off that approvals are stable before beginning policies, audit, integrations, streaming, or hardening work.
