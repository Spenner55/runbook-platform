# Phase 10: Platform Expansion Roadmap Blueprint

| Field | Value |
|---|---|
| Phase number | 10 |
| Objective | Define the correct sequencing and architectural constraints for expanding the runbook platform from working vertical slice to a production-grade multi-tenant system. |
| Status | Strategic planning |
| Depends on | Phases 01–09 complete and passing all verification gates |
| Authored | 2026-04-15 |

---

## 1. Phase Overview

This document is not an implementation plan. It is a sequencing strategy.

After phases 01–09, the system has:

- A working end-to-end vertical slice: runbook → workflow → execution → runner → UI
- A clean Django control plane with all domain app stubs in place
- A runner that polls Django and executes steps without touching the database directly
- An AI service boundary that Django calls over HTTP, not the frontend
- Targeted tests covering critical seams
- A polished local developer environment

What the system does **not** have yet is any of the features that make it a **platform** rather than a demo:

- Real approval gates that halt execution
- Policies that encode organizational rules
- An immutable audit trail
- Artifact storage and retrieval
- External integrations (Slack, PagerDuty, Jira)
- AI that actually parses real runbooks
- Authentication and authorization
- Live execution status (no polling)
- Production-grade infrastructure
- AWS deployment

This blueprint defines in what order to build those things, why that order is correct, and what will go wrong if you deviate from it.

---

## 2. Why Expansion Must Wait

The most dangerous moment in a new platform's lifecycle is right after the vertical slice works. The demo feels real. The architecture is clean. The temptation is to start shipping features fast.

Three things are not yet true that must be true before expanding:

**2.1 The service contracts are not hardened.**

The workflow schema (`packages/workflow-schema/workflow.schema.json`) is minimal. It has `requiresApproval: boolean` but no concept of approval type, timeout, fallback, or escalation. The execution state machine has no `waiting_for_approval` state. The runner client is a stub. The executor is a stub. The sandbox is a stub. Expanding horizontally onto a foundation this thin means every new feature you ship will require retroactive surgery to the core.

Phases 01–09 must be fully implemented and passing before phase 10 begins. "Fully implemented" means: the runner actually polls, claims, executes shell steps, streams logs, reports status, and handles failures. Not stub code.

**2.2 The domain model is not validated under real conditions.**

Until you have run real executions through the system — including failures, retries, and partial completions — you do not know whether your `Execution` and `Step` models have the right fields. Adding features like artifacts or approvals on top of a model that hasn't been exercised means you will discover structural gaps mid-feature and face painful migrations.

**2.3 There is no auth.**

Every feature you build before auth exists will need to be revisited when auth arrives. However, adding auth too early (before the domain model is stable) creates a different problem: every new model and endpoint requires immediate RBAC wiring, which doubles the implementation burden at a stage where you still need fast iteration. The correct resolution is documented in section 4.7 (auth comes seventh, not first).

---

## 3. Architecture Invariants

These rules must never be violated by any expansion phase. If a proposed implementation requires breaking one of these, the implementation approach is wrong — not the rule.

**INV-1: Django is the control plane.**
All business logic, all state transitions, all persistence, all orchestration live in Django. No service is allowed to route around it.

**INV-2: The runner talks only to the Django API.**
The runner cannot read from or write to the database. It cannot call the AI service. It cannot call external integrations. It has one dependency: the Django `/api/v1/internal/` endpoints. This is what makes the runner replaceable and testable without infrastructure.

**INV-3: The frontend talks only to the Django API.**
The React app is a display layer. It calls `/api/v1/...` and nothing else. It cannot call the AI service, the runner, external services, or the database. This rule exists to preserve backend authority over authorization and data shape.

**INV-4: The AI service is stateless and advisory.**
FastAPI processes requests and returns results. It does not store state. Django decides whether to use the AI result, validate it, or discard it. The AI service is a callable dependency, not a source of truth.

**INV-5: API versioning is non-negotiable.**
All endpoints live under `/api/v1/...`. Internal runner endpoints live under `/api/v1/internal/...`. When breaking changes are needed, a new version prefix is introduced rather than mutating v1 contracts.

**INV-6: UUID primary keys everywhere.**
No sequential integer IDs exposed in URLs. This is enforced by `BaseModel` in `apps/api/apps/common/`.

**INV-7: Business logic lives in `services.py`, not in views or serializers.**
Views validate the request and call the service. Serializers serialize. Services contain logic. This makes every feature testable without HTTP overhead.

**INV-8: No premature event infrastructure.**
Do not introduce Kafka, RabbitMQ, Celery, or any asynchronous task queue before production load requires it. Django database transactions + runner polling is the correct architecture for this scale. Event infrastructure adds operational complexity, failure modes, and debugging overhead that dwarfs its benefits at this stage.

---

## 4. Expansion Roadmap

> **Canonical expansion label to blueprint file mapping** — use the filename when referencing a phase in implementation prompts. The §4.x labels in this document are sequential outline numbers, not version numbers.

| Roadmap label | Canonical blueprint filename |
|---|---|
| 4.1 / Phase 10.1 | `phase-10-01-approvals-blueprint.md` |
| 4.2 / Phase 10.2 | `phase-10-02-policies-blueprint.md` |
| 4.3 / Phase 10.3 | `phase-10-03-audit-trail-blueprint.md` |
| 4.4 / Phase 10.4 | `phase-10-04-artifacts-blueprint.md` |
| 4.5 / Phase 10.5 | `phase-10-05-integrations-blueprint.md` |
| 4.6 / Phase 10.6 | `phase-10-06-richer-ai-parsing-blueprint.md` |
| 4.7 / Phase 10.7 | `phase-10-07-authentication-authorization-blueprint.md` |
| 4.8 / Phase 10.8 | `phase-10-08-live-event-streaming-blueprint.md` |
| 4.9 / Phase 10.9 | `phase-10-09-production-hardening-blueprint.md` |
| 4.10 / Phase 10.10 | `phase-10-10-aws-deployment-workflows-blueprint.md` |

### 4.1 Approvals

**Purpose**

Approval gates are the reason operators use a runbook platform instead of running scripts directly. A high-risk step — deploying to production, deleting data, restarting a cluster — must pause and wait for a named human to explicitly authorize it before the runner proceeds. Without this, the platform is just a fancy cron job runner.

**Why it comes first**

The workflow schema already expresses `requiresApproval: boolean` on steps. This is a contract that the system has promised to honor. The execution state machine currently has no `waiting_for_approval` state, which means the runner has no mechanism to pause. Every other platform feature (policies, audit, integrations) either depends on approvals or is significantly simpler once approvals exist. Building policies before approvals is impossible — policies decide approval routing. Building integrations before approvals means you have nothing useful to notify about.

**Dependencies**

- Phases 01–05 must be complete: runner polling, execution state machine, step execution
- `apps/api/apps/approvals/` stub must be scaffolded into full models
- Execution state machine must support `waiting_for_approval` as a valid step state

**Affected parts of repo**

- `apps/api/apps/approvals/` — new models (`ApprovalRequest`, `ApprovalDecision`), service, serializer, views
- `apps/api/apps/executions/` — step state machine gains `waiting_for_approval` state
- `apps/runner/runner/executor.py` — must detect `requiresApproval` steps, transition to `waiting_for_approval` via API, then poll for resolution before proceeding
- `apps/web/src/` — approval inbox UI, approval action (approve/reject) flow
- `packages/workflow-schema/workflow.schema.json` — may need `approvalType` field added (manual, timeout-auto-approve, etc.)

**Key design decisions**

*Approval model*: An `ApprovalRequest` is created by Django when the runner reports a step entering `waiting_for_approval`. The `ApprovalRequest` stores: `execution_id`, `step_id`, `requested_at`, `requested_by_runner` (the runner identity), `status` (pending/approved/rejected/timed_out), `decided_by` (user FK, nullable), `decided_at`, `decision_notes`.

*Who can approve*: In phase 10.1, any authenticated user can approve. Policy-based routing of approvals to specific users or roles is a phase 10.2 concern. Do not design a complex permission model for approvals in this phase.

*Approval timeout*: Workflows can specify `approvalTimeoutSeconds` on a step. If no decision is made within the timeout, the execution fails with `timed_out` rather than waiting indefinitely. The runner must implement a timeout check in its polling loop.

*Runner behavior*: The runner calls `POST /api/v1/internal/steps/{id}/start`, receives `waiting_for_approval` as the response status, and enters an approval-poll loop: `GET /api/v1/internal/steps/{id}/approval-status` every N seconds. When the approval resolves to `approved`, the runner proceeds. When `rejected` or `timed_out`, the runner marks the step `failed` and the execution `failed`.

*Approval is blocking per-step*: The runner processes one step at a time in sequence. Parallel step execution is a future concern and must not be designed for here.

**What NOT to do**

- Do not build an approval delegation system (user A approves on behalf of user B) in phase 10.1.
- Do not send approval notifications via integrations yet — integrations don't exist. Log to Django; the UI inbox is sufficient.
- Do not add approval workflow routing (route to on-call team, escalate after N minutes) — that is policy territory.
- Do not store approval decisions in the `audit` app yet — the audit app is phase 10.3. Write approval decisions to the `ApprovalDecision` model for now.
- Do not add WebSocket or SSE for real-time approval notifications — polling from the UI is fine at this stage.

**Major risks**

- *Deadlock*: If the runner's approval polling loop does not have a timeout guard, a network partition between runner and Django will permanently stall the execution. Guard every poll with a hard timeout.
- *State corruption*: If a step is marked `waiting_for_approval` and then the runner restarts, the runner must be able to resume the approval-poll loop by re-reading step state from the API on startup. The runner must be stateless between crashes.
- *Double-approval*: If two operators approve the same request concurrently, Django must use a DB-level select_for_update to prevent two decisions on one request.

**Suggested milestone breakdown**

1. Add `waiting_for_approval` to step status enum in models and migration.
2. Add `ApprovalRequest` and `ApprovalDecision` models and migration.
3. Implement approval service: `create_approval_request`, `decide_approval` (with `select_for_update`), `get_pending_approvals`.
4. Add internal runner endpoints: `POST /internal/steps/{id}/approval-request`, `GET /internal/steps/{id}/approval-status`.
5. Add public API endpoints: `GET /approvals/`, `POST /approvals/{id}/decide/`.
6. Update runner executor to detect `requiresApproval`, poll for resolution, respect timeout.
7. Add approval inbox page to React UI.
8. Add approval action (approve/reject form with notes) to React UI.

**Testing / verification approach**

- Django service tests: `create_approval_request` creates one request per step; `decide_approval` with `approved` transitions step to `running`; concurrent `decide_approval` calls produce exactly one decision (use `TestCase` with transaction isolation).
- API contract tests: `POST /approvals/{id}/decide/` with approved payload returns 200 and triggers step state change; double-decide returns 409.
- Runner integration test: mock Django API; executor detects `requiresApproval=true`, enters polling loop, receives `approved` response, continues execution.
- Manual gate: create a workflow with one `requiresApproval` step; start execution; confirm it pauses; approve from UI; confirm runner resumes; confirm step shows `succeeded`.

---

### 4.2 Policies

**Purpose**

Policies encode organizational rules about execution behavior. Which runbooks require multi-party approval? Which step types are forbidden outside a maintenance window? Which risk levels require manager sign-off vs. peer approval? Without policies, every team that uses the platform must implement approval logic manually in their runbooks. With policies, the platform enforces rules automatically.

**Why it comes second**

Policies are the decision layer on top of approvals. They cannot exist without the approval mechanism (4.1). Policies answer the question: "given this step, in this context, should approval be required at all, and if so, who must approve?" That question requires approvals to be a working system before policies can route, override, or automate them.

**Dependencies**

- 4.1 (approvals) must be complete
- `apps/api/apps/policies/` stub must be scaffolded
- Organization model must exist (policies are organization-scoped)
- Risk field on workflow steps is already in the schema

**Affected parts of repo**

- `apps/api/apps/policies/` — new models (`Policy`, `PolicyRule`, `PolicyEvaluation`), service, serializer, views
- `apps/api/apps/approvals/` — approval service gains a policy evaluation hook: before creating an `ApprovalRequest`, evaluate applicable policies
- `apps/api/apps/executions/` — execution service calls policy evaluation when transitioning steps
- `apps/web/src/` — policy management UI (CRUD for policies and rules)
- `packages/workflow-schema/workflow.schema.json` — no changes needed; policy evaluation uses existing `risk` field

**Key design decisions**

*Policy model*: A `Policy` has a `name`, `organization_id`, `is_active`, and ordered list of `PolicyRule` objects. A `PolicyRule` has a condition expression (e.g., `step.risk == "high"` or `step.type == "database"`) and an action (e.g., `require_approval_from_role("manager")`). Rules are evaluated in order; first match wins.

*Condition language*: Do not design a full expression language. Start with a `condition_type` enum (e.g., `RISK_LEVEL`, `STEP_TYPE`, `TIME_WINDOW`) and structured `condition_params` JSON. The service evaluates conditions using plain Python if/else, not a DSL. This keeps the system testable and auditable without introducing a parser.

*Policy evaluation point*: Policy evaluation happens in Django, triggered at step transition time (when the runner reports a step is about to run). If policy evaluation determines approval is required, Django creates the `ApprovalRequest` even if `requiresApproval` is `false` in the workflow definition. **Policy can escalate to `ApprovalRequired` or `Block` regardless of the workflow schema. Policy cannot remove or waive `requiresApproval: true` — that is a minimum floor that policy may only strengthen, not weaken.**

*Evaluation logging*: Every policy evaluation produces a `PolicyEvaluation` record: `policy_id`, `rule_id`, `step_id`, `outcome`, `evaluated_at`. This is the precursor to the audit trail (4.3) and provides debugging when an execution is unexpectedly gated.

*Conflict resolution*: When multiple active policies have rules that could apply to the same step, the **first matching rule wins** using the deterministic global sort key `(rule.priority, policy.created_at, policy.id, rule.id)`. Lower priority number evaluates first. Do not implement "stricter outcome wins" — it sounds safe but creates surprising behavior when later rules silently override earlier explicit choices, and it makes policy outcomes non-auditable.

> **ARCHITECTURE DECISION (locked):** `AutoApprove` from a policy MUST NOT waive a workflow step's `requiresApproval: true` declaration. The workflow-level `requiresApproval: true` is a minimum gate (floor). A policy can only escalate to `ApprovalRequired` or `Block` on such steps; it cannot remove the approval requirement. `requiresApproval: false` in the workflow is the only case where policy can choose `AutoApprove`. Tests must cover both paths: (a) policy returns `AutoApprove` on `requiresApproval: false` step → step proceeds without approval; (b) policy returns `AutoApprove` on `requiresApproval: true` step → approval is still required, policy outcome is upgraded to `ApprovalRequired`.

**What NOT to do**

- Do not build a general-purpose rules engine, DSL, or policy templating system. Three condition types with structured params are enough for a first version.
- Do not build policy inheritance between organizations at this stage.
- Do not allow policies to modify step commands or inject shell code — policies govern approval routing only.
- Do not add policy dry-run mode in phase 10.2. Add it later when organizations actually need to test policies before activating them.

**Major risks**

- *Policy evaluation adding latency to execution hot path*: Policy evaluation queries the DB on every step transition. With N active policies and M rules each, this can be slow. Mitigation: load all active policies for the execution's organization once at execution start and cache them in memory for the duration of the execution (pass them through the execution context). Do not re-query per step.
- *Silent policy miss*: If the policy evaluation service has a bug and raises an exception, the step must not silently auto-approve. Fail loudly: log the error, transition the step to `failed` with a `policy_evaluation_error` reason, and require manual intervention.
- *Policy ordering ambiguity*: Rules evaluated in a non-deterministic order produce non-deterministic outcomes. Enforce ordering with an explicit `priority` integer field on `PolicyRule` and sort before evaluation.

**Suggested milestone breakdown**

1. Define `Policy`, `PolicyRule`, `PolicyEvaluation` models and migrations.
2. Implement `PolicyService.evaluate(step, execution_context)` — returns `ApprovalRequired | AutoApprove | Block`.
3. Wire policy evaluation into the step transition service (before creating `ApprovalRequest`).
4. Add policy CRUD API endpoints under `/api/v1/policies/`.
5. Add policy management UI: list, create, edit, deactivate.
6. Add `PolicyEvaluation` detail to execution detail view (show which policy gated a step).

**Testing / verification approach**

- Service unit tests: high-risk step with matching active policy returns `ApprovalRequired`; no matching policy returns `AutoApprove`; conflicting policies return stricter outcome.
- Integration test: create execution with high-risk step, activate matching policy, trigger step, assert `ApprovalRequest` created even though `requiresApproval=false` in schema.
- Manual gate: create policy for `risk == "critical"`, create workflow with one critical step and `requiresApproval: false`, start execution, verify it pauses for approval.

---

### 4.3 Audit Trail

**Purpose**

An audit trail is an immutable, append-only record of who did what to which entity, when, and why. It is the paper trail that answers "why did this production runbook approve itself at 2am?" It is also a compliance requirement for any serious enterprise deployment.

**Why it comes third**

Approvals and policy evaluations are the first actions in this system that carry legal and operational weight. The moment a human approves a destructive operation, that decision needs to be recorded. The moment a policy silently waives an approval, that waiver needs to be recorded. You cannot add audit after the fact without replaying history — so the audit system must exist before more high-stakes features are added.

Additionally, audit depends on stable domain models. After phases 01–09 and 10.1–10.2, the `Execution`, `Step`, `ApprovalRequest`, and `PolicyEvaluation` models are stable. Auditing unstable models generates garbage records that will be misleading.

**Dependencies**

- 4.1 (approvals) and 4.2 (policies) must be complete — audit must record their events
- `apps/api/apps/audit/` stub must be scaffolded
- Auth (4.7) does not need to be complete — record the runner's identity token as `actor` when there is no user session

**Affected parts of repo**

- `apps/api/apps/audit/` — new models (`AuditEvent`), service, serializer, views
- `apps/api/apps/executions/` — execution service emits audit events at each state transition
- `apps/api/apps/approvals/` — approval service emits audit events on creation and decision
- `apps/api/apps/policies/` — policy evaluation service emits audit events per evaluation
- `apps/web/src/` — audit trail view on execution detail page

**Key design decisions**

*Audit event model*: `AuditEvent` is append-only. Fields: `id` (UUID), `occurred_at` (auto), `actor_type` (user / runner / system), `actor_id` (UUID or string), `actor_label` (display name at time of event — denormalized intentionally), `event_type` (enum string, e.g., `execution.created`, `step.approval_requested`, `approval.decided`, `policy.evaluated`), `object_type` (e.g., `execution`), `object_id` (UUID), `metadata` (JSONB — event-specific details), `organization_id`.

*Immutability*: The `AuditEvent` model must have no `update` method in its service. The service has only `emit(...)`. No view or endpoint allows updating or deleting audit events. The Django admin must have `has_change_permission` and `has_delete_permission` returning `False` for `AuditEvent`.

*Denormalized actor label*: Store the human-readable actor name at the time of the event. Don't just store the FK — users can be renamed, deleted, or anonymized. The label in the audit record must survive those changes.

*Synchronous writes*: Write audit events synchronously within the same database transaction as the triggering action. Do not write them asynchronously or in a background task. If the audit write fails, the triggering action must also roll back. Async audit introduces a window where the action happened but the record doesn't exist.

*Querying*: Provide `GET /api/v1/audit/?object_type=execution&object_id={id}` to fetch the audit trail for a specific execution. Provide `GET /api/v1/audit/?organization_id={id}` for organization-wide trail (paginated, newest-first). Do not build complex filter UIs in phase 10.3 — basic per-object and per-org queries are sufficient.

*Partition strategy*: PostgreSQL does not need partitioning at this scale. If audit volume becomes a concern in the future, partition `audit_auditevent` by `occurred_at` month using declarative partitioning. Do not pre-build this.

**What NOT to do**

- Do not write audit events to a separate database or event store. The same Postgres instance is correct at this scale. The operational complexity of a separate audit store is not justified until you have compliance requirements that mandate it.
- Do not use Django signals to emit audit events. Signals decouple the write from the transaction, making rollback behavior unpredictable. Call `AuditService.emit(...)` explicitly in service methods.
- Do not build a full audit query language. Three filter params (object_type, object_id, organization_id) are enough.
- Do not retroactively synthesize audit events from existing execution history. Audit records are only trustworthy if they were written at the moment of the event.

**Major risks**

- *Audit table bloat*: A busy system creates one audit event per step transition. With 10 steps per execution, 100 executions per day, that's 1,000 events per day. At five years, that's 1.8M rows — trivially manageable for Postgres. The risk is adding audit events indiscriminately to low-value operations (every API GET request, every health check). Only audit state-changing operations on domain entities.
- *Missing audit on error path*: If a step fails with an unhandled exception and the audit write is inside the try block, the audit event is never written. Use a try/finally pattern or a context manager that ensures the audit write happens even when the action raises.

**Suggested milestone breakdown**

1. Define `AuditEvent` model with immutable constraint and migration.
2. Implement `AuditService.emit(...)` — synchronous, within-transaction.
3. Wire audit emission into execution service state transitions.
4. Wire audit emission into approval service create/decide.
5. Wire audit emission into policy service evaluation.
6. Add `GET /api/v1/audit/` with object_type/object_id/org filter.
7. Add audit trail panel to execution detail UI.

**Testing / verification approach**

- Model test: assert `AuditEvent` objects have no `save` or `update` callable via the service; only `emit`.
- Service tests: `execution.created` event emitted when `ExecutionService.create()` called; `approval.decided` event emitted inside the same DB transaction as `ApprovalService.decide()`.
- Transaction rollback test: simulate service failure after action but before audit emit; assert neither action nor audit record persists (demonstrates synchronous write behavior).
- Manual gate: create and run an execution with an approval gate; view the audit trail for that execution in the UI; verify it shows: created → step started → approval requested → approval decided → step completed → execution completed.

---

### 4.4 Artifacts

**Purpose**

Artifacts are the outputs of execution: stdout/stderr logs, generated files, screenshots, reports, database query results, anything the runner produces during a step. Without artifact storage, executions are black boxes — you can see the status but not the evidence. When a step fails, you need the output to debug it. When an audit requires proof of what a runbook did, artifacts provide it.

**Why it comes fourth**

Artifacts depend on executions being stable and trusted, which they are after phases 01–09. Artifacts depend on audit trail being active (4.3) because the act of uploading an artifact should be audited. Artifacts introduce a new infrastructure dependency — file storage (local volumes in dev, S3 in prod) — that should only be added after the control plane is trustworthy. The runner already has `apps/runner/runner/artifact_uploader.py` as a stub, indicating this was always planned.

**Dependencies**

- 4.3 (audit) must be active
- Runner `executor.py` must be fully implemented (phases 01–05)
- File storage must be configured: `django-storages` with local file backend for dev, S3 backend for prod
- `apps/api/apps/artifacts/` stub must be scaffolded

**Affected parts of repo**

- `apps/api/apps/artifacts/` — new models (`Artifact`), service, serializer, views
- `apps/api/apps/executions/` — execution detail endpoint gains artifact list
- `apps/runner/runner/artifact_uploader.py` — implement upload logic: `POST /api/v1/internal/executions/{id}/steps/{step_id}/artifacts`
- `apps/runner/runner/executor.py` — after step completes, collect outputs and call artifact uploader
- `apps/web/src/` — artifact list and download UI on execution detail page
- Storage config in `apps/api/config/settings/`

**Key design decisions**

*Artifact model*: `Artifact` stores metadata, not the file. Fields: `id` (UUID), `execution_id` (FK), `step_id` (FK, nullable — some artifacts are per-execution), `name` (filename), `mime_type`, `size_bytes`, `storage_key` (path in the storage backend), `uploaded_at`, `uploaded_by_runner` (runner identity).

*Upload flow*: The runner does not call an S3 pre-signed URL directly. It calls `POST /api/v1/internal/steps/{step_id}/artifacts` with the file as multipart form data. Django receives the upload, stores it using `django-storages`, creates the `Artifact` record, and emits an audit event. This preserves INV-2 (runner only talks to Django) and allows Django to enforce size limits, MIME type restrictions, and authorization.

*Pre-signed download URLs*: When the UI requests an artifact, Django generates a time-limited pre-signed URL (local dev: direct file serve; S3 prod: pre-signed GET URL) and returns it to the frontend. The frontend never holds permanent storage credentials.

*Artifact retention*: For phase 10.4, store indefinitely. Add a configurable retention policy in a later phase. Do not build retention logic now.

*Log artifacts*: Stdout/stderr captured by the runner during a step should be stored as text artifacts (`mime_type: text/plain`). The existing `apps/runner/runner/log_streamer.py` stub should buffer output and upload it after step completion, not stream it line-by-line (streaming is a phase 10.8 concern).

**What NOT to do**

- Do not generate pre-signed upload URLs for the runner to upload directly to S3. The runner must go through Django. When you add auth (4.7), Django can enforce which runner is allowed to upload to which execution.
- Do not store file contents in the `Artifact` model's database record. Store only the metadata and storage key.
- Do not build artifact search or indexing in phase 10.4.
- Do not add artifact compression or deduplication. Store files as-is.

**Major risks**

- *Large artifact uploads blocking Django*: If a step produces a 500MB log file and the runner streams it to Django via HTTP, the Django process is blocked for the duration of the upload. Mitigation: enforce a hard size limit on artifact uploads (e.g., 50MB) and document it. For large outputs, truncate or compress before upload.
- *Storage key collision*: If two concurrent runners upload an artifact with the same filename to the same step, the storage keys will conflict. Use a storage key pattern that includes the artifact UUID: `artifacts/{execution_id}/{step_id}/{artifact_id}/{filename}`.
- *Missing artifacts on step failure*: If a step fails mid-execution and the runner crashes before uploading artifacts, those outputs are lost. Mitigation: the runner should upload stdout/stderr artifacts before reporting step failure to Django, not after. Write artifacts first, then transition state.

**Suggested milestone breakdown**

1. Add `django-storages` to `apps/api/requirements/` with local file backend config in `dev.py`.
2. Define `Artifact` model and migration.
3. Implement `ArtifactService.create(...)` with file write + DB record creation in a transaction.
4. Add internal runner endpoint `POST /api/v1/internal/steps/{id}/artifacts` (multipart upload).
5. Add public endpoint `GET /api/v1/executions/{id}/artifacts/` and `GET /api/v1/artifacts/{id}/download/` (returns pre-signed URL).
6. Implement `artifact_uploader.py` in runner: collect step output, POST to Django after each step.
7. Add artifact list and download links to execution detail UI.

**Testing / verification approach**

- Service test: `ArtifactService.create(...)` with a 1KB file creates `Artifact` record and writes file to storage backend; `get_download_url(artifact_id)` returns a non-expired URL.
- Upload size limit test: upload beyond the limit returns 413.
- Runner integration test: mock Django API; executor runs a step that produces stdout; artifact uploader calls the upload endpoint with correct payload.
- Manual gate: run an execution; confirm stdout artifact appears in UI; download it; verify content matches what the step printed.

---

### 4.5 Integrations

**Purpose**

Integrations emit events from the platform to external systems. When an execution fails, Slack should be notified. When a step requires approval, PagerDuty can page the on-call team. When an execution completes, a Jira ticket can be auto-closed. Integrations turn the runbook platform from a standalone tool into something embedded in an organization's operational workflow.

**Why it comes fifth**

Integrations notify about events. You need those events to be stable, meaningful, and audited before you wire external systems to them. After 4.1–4.4, executions have approval gates, policy evaluations, audit records, and artifacts — there is now enough context in a completed execution to send a genuinely useful notification.

Integrations also require storing and securing API keys and webhooks for external services. This requires the `organizations` model to be fully in place (org-scoped integrations) and the audit trail to be active (every credential rotation should be audited).

**Dependencies**

- 4.3 (audit) must be active — integration create/update/delete must be audited
- 4.4 (artifacts) optional but useful (include artifact download links in notifications)
- `apps/api/apps/integrations/` stub must be scaffolded
- Organizations model must be complete
- Secrets must be stored encrypted at rest (use `django-environ` to read an encryption key; use `cryptography.fernet` to encrypt stored tokens)

**Affected parts of repo**

- `apps/api/apps/integrations/` — new models (`Integration`, `IntegrationEvent`), service, serializer, views
- `apps/api/apps/executions/` — execution service calls `IntegrationService.dispatch(event_type, context)` at key transitions (execution started, step failed, execution completed, execution failed)
- `apps/api/apps/approvals/` — approval service dispatches `approval.requested` event when creating an `ApprovalRequest`
- `apps/web/src/` — integrations management UI (add Slack webhook, PagerDuty key, etc.)

**Key design decisions**

*Integration model*: `Integration` stores: `id`, `organization_id`, `type` (enum: `SLACK_WEBHOOK`, `PAGERDUTY`, `GENERIC_WEBHOOK`), `name`, `config` (JSONB — type-specific config like the webhook URL), `encrypted_credentials` (Fernet-encrypted blob — API keys), `is_active`, `created_at`.

*Dispatch model*: `IntegrationService.dispatch(event_type, context)` queries all active integrations for the execution's organization, formats a payload per integration type, and sends it via `httpx`. Dispatch is **fire-and-forget with logging**: if the external call fails, log the failure to `IntegrationEvent` (with status `failed`) but do not fail the execution. External system availability must never affect execution outcome.

*`IntegrationEvent`*: Every outbound call produces a record: `integration_id`, `event_type`, `payload_sent`, `response_status`, `sent_at`, `latency_ms`. This provides debugging without requiring you to reproduce the exact webhook payload.

*Retry policy*: For phase 10.5, no retries. Log the failure and move on. Add retry with backoff in a later phase when delivery guarantees become a requirement. Don't build retry logic before you know how often delivery fails in practice.

*Synchronous vs. async dispatch*: Dispatch is synchronous within the request-response cycle for phase 10.5. The HTTP call to Slack/PagerDuty happens inline. Set a hard timeout of 3 seconds on all outbound integration calls. This is acceptable latency for the current scale. If dispatch latency becomes a problem, move it to a background worker — but only then.

**What NOT to do**

- Do not store API keys or webhook URLs in plaintext. Always encrypt credentials at rest using Fernet or a KMS integration.
- Do not let integration failures propagate as exceptions into the execution flow. Wrap all dispatch calls in try/except and record failures without raising.
- Do not build a full integration marketplace or plugin system. Three integration types (Slack webhook, PagerDuty Events API, generic webhook) cover 80% of use cases.
- Do not allow the frontend to provide the raw integration credentials — only the backend should handle them. The UI submits credentials once; the backend stores them encrypted; subsequent UI reads return a masked representation.

**Major risks**

- *Secret leakage via API responses*: If `Integration` serializer includes `encrypted_credentials` in the response, frontend code can inadvertently log or expose it. The serializer must never return the credential blob. Return only a `credentials_configured: boolean` flag.
- *Integration event volume*: A busy execution that dispatches to five active integrations generates five `IntegrationEvent` rows per execution state change. With frequent executions, this table can grow fast. Add a database index on `(integration_id, sent_at)` and periodically purge events older than 90 days (simple management command, not an automated job yet).
- *Outbound calls to internal hosts*: A malicious user could create a `GENERIC_WEBHOOK` integration pointing to `http://169.254.169.254/latest/meta-data/` (AWS metadata endpoint) or to `http://localhost:8000/internal/`. Django must validate outbound URLs against a blocklist of private IP ranges before dispatching.

**Suggested milestone breakdown**

1. Define `Integration` and `IntegrationEvent` models; add Fernet encryption utility.
2. Implement `IntegrationService.dispatch(event_type, context)` with 3-second timeout and failure logging.
3. Add integration CRUD API endpoints with credentials write-once, masked-read behavior.
4. Wire dispatch into execution service (4 trigger points) and approval service (1 trigger point).
5. Add integrations management UI: list, add (type picker + config form), deactivate.
6. Add `IntegrationEvent` history to integration detail view.

**Testing / verification approach**

- Service test: `dispatch(...)` with a mocked `httpx.AsyncClient`; verify `IntegrationEvent` record created on success and on failure; verify execution state is not affected by dispatch failure.
- Credential storage test: credentials written to DB are not equal to the plaintext value (assert Fernet-encrypted).
- SSRF prevention test: create integration with `url: "http://127.0.0.1:8000/internal/"`, call dispatch, assert HTTP call is rejected before leaving Django.
- Manual gate: create Slack webhook integration; run a failing execution; verify Slack message received with correct execution details.

---

### 4.6 Richer AI Parsing

**Purpose**

The AI service routes (`/parse`, `/enrich`, `/summarize`) are stubs. The actual value proposition of the platform is that an operator can paste in a runbook document (Confluence page, Google Doc, Markdown file) and the AI produces a structured, executable workflow — complete with step types, risk classifications, and approval requirements. Without real AI parsing, users must author workflows manually, which defeats a primary differentiator.

**Why it comes sixth**

Real AI parsing requires the workflow schema to be stable. If `/parse` outputs a workflow definition and that definition can contain approvals, risk levels, and step types, the schema must already support all of those concepts — and those concepts must already be implemented in the control plane. Adding richer AI output before the schema is locked means every schema change requires updating the AI prompts, the parser, the schema validator, and potentially the migration strategy for previously parsed workflows.

After phases 01–09 and 10.1–10.5, the schema is stable, the control plane handles all the concepts the AI might produce, and the AI output has a clear contract to conform to.

**Dependencies**

- Workflow schema must be stable and versioned
- Django executes AI-produced workflows (not just hand-authored ones) through the full stack
- `OPENAI_API_KEY` is in `.env` (already required in bootstrap)
- `/parse`, `/enrich`, `/summarize` routes must be wired to real LLM calls

**Affected parts of repo**

- `apps/ai/app/api/routes/parse.py` — implement real LLM-backed parsing
- `apps/ai/app/api/routes/enrich.py` — implement risk classification and approval flag enrichment
- `apps/ai/app/api/routes/summarize.py` — implement execution summary generation
- `apps/ai/app/prompts/` — system and user prompts for each route
- `apps/ai/app/schemas/` — Pydantic output schemas matching `workflow.schema.json`
- `apps/ai/app/services/` — LLM client wrapper with retry, token budget, and structured output handling
- `apps/api/apps/runbooks/` — runbook service calls `/parse` and `/enrich` when creating a runbook from raw text
- `packages/workflow-schema/workflow.schema.json` — may add `parsedFrom` provenance field

**Key design decisions**

*Structured output*: Use the LLM's structured output mode (JSON schema enforcement) rather than asking for JSON and hoping. Pass the `WorkflowDefinition` JSON schema directly to the model's response format parameter. This eliminates output parsing failures.

*Parse → Enrich pipeline*: `/parse` takes raw text and produces a `WorkflowDefinition` with step names and types. `/enrich` takes a `WorkflowDefinition` and adds `risk` classification and `requiresApproval` suggestions. These are separate calls so Django can store the intermediate parse result and only proceed to enrichment if the parse succeeds.

*Human review gate*: AI-parsed workflows must not be automatically executed. Django must set a `requires_review: boolean` flag on AI-generated workflows. The UI must present a review step where the operator can inspect, edit, and approve the parsed workflow before it is executable. This is not a policy gate — it is a hard UI requirement.

*Prompt versioning*: Prompts are strings in Python files, not in the database. Version them with the code. When a prompt changes, test the change against a fixture set of known inputs and expected outputs (golden tests) before merging.

*Cost and latency*: The `/parse` call for a 10-page runbook document can be expensive. Set a max token budget per call and enforce it. Cache parse results by input hash in Django (use Postgres or a simple in-memory cache, not Redis yet). Don't parse the same document twice.

*Error handling*: If the LLM returns malformed output that fails Pydantic validation, the AI service must return a structured error with the raw LLM output included. Django logs this, marks the runbook parse as `failed`, and surfaces the error to the user — do not silently discard malformed output.

**What NOT to do**

- Do not let the AI service call the Django API or the database. It is a pure transformer: text in, structured data out.
- Do not add streaming LLM responses in phase 10.6. Full response first; streaming is a UX optimization for later.
- Do not add multi-model routing or fallback chains in phase 10.6. One model, one prompt set.
- Do not let AI-generated content bypass the workflow schema validator. All AI output must pass schema validation before Django stores it.

**Major risks**

- *Schema drift between AI output and Django expectations*: If the AI service's Pydantic schemas and Django's workflow schema fall out of sync, parsed workflows will fail validation. Mitigation: the `packages/workflow-schema/workflow.schema.json` is the canonical schema; the AI service's Pydantic models must be generated from or validated against it, not authored independently.
- *Hallucinated steps*: The AI may produce plausible-sounding but operationally nonsensical steps. The human review gate (required before execution) is the primary mitigation. Do not rely on the AI to get it right.
- *Token cost blowup*: Without input limits, a user can submit a 200-page document and trigger a $50 LLM call. Enforce input character limits before the API call and return a clear error if exceeded.

**Suggested milestone breakdown**

1. Implement `LLMClient` wrapper in `apps/ai/app/services/` with structured output, retry, and token budget.
2. Implement `/parse` with system prompt and golden test fixtures.
3. Implement `/enrich` with risk classification prompt and golden test fixtures.
4. Implement `/summarize` for post-execution summary.
5. Wire Django's runbook service to call `/parse` + `/enrich` when processing raw runbook text input.
6. Add human review UI: diff view of AI-parsed workflow, edit-before-execute affordance, approve-to-execute button.
7. Add input hash caching in Django (simple `parse_cache` dict keyed by sha256 in the runbook service).

**Testing / verification approach**

- Golden tests: fixture inputs (raw runbook text) paired with expected `WorkflowDefinition` outputs; assert AI output matches expected schema structure.
- Schema validation test: AI service output is validated against `workflow.schema.json`; malformed output raises a structured error.
- Django integration test: call runbook service with raw text; mock AI service responses; assert `Workflow` record created with `requires_review=True`.
- Manual gate: paste a 3-step real runbook; verify parsed workflow appears in UI with correct steps and risk levels; edit one step; approve; start execution; verify it runs.

---

### 4.7 Auth

**Purpose**

Authentication establishes identity. Authorization controls what an identity can do. Without auth, every API endpoint is wide open and the concept of "which user approved this step" is meaningless. Auth is the layer that makes all previous features trustworthy: audit records reference real actors, approval decisions are binding, policies can be scoped to roles, and multi-tenancy is enforced.

**Why it comes seventh**

Auth is listed seventh, which will seem wrong to engineers with a security background. The reasoning: auth is a cross-cutting concern that touches every model, every endpoint, and every service. Adding it before the domain model is stable means reworking every permission decision twice — once when you build the feature and once when the model changes. The vertical-slice-first philosophy says: prove the domain model works without auth, then add auth as a layer.

The risk mitigated by this ordering is wasted work. The risk introduced is that phases 10.1–10.6 are built with `AllowAny` permissions. This is acceptable because: (a) the system is not production-deployed yet (AWS deployment is phase 10.10), (b) the dev environment is not publicly reachable, and (c) adding auth after a stable domain model is straightforward — it's a matter of replacing `AllowAny` with `IsAuthenticated` and adding object-level permissions.

**Dependencies**

- All previous expansion phases (10.1–10.6) must be complete
- `apps/api/apps/users/` stub must be fully scaffolded
- `apps/api/apps/organizations/` must have full multi-tenancy support
- All domain models must have `organization_id` foreign keys
- Runner authentication must be defined (token-based, not session-based)

**Affected parts of repo**

- `apps/api/apps/users/` — custom `User` model extending `AbstractBaseUser`, with organization membership
- `apps/api/config/settings/base.py` — `AUTH_USER_MODEL`, DRF auth classes, JWT settings
- `apps/api/` — every view switches from `AllowAny` to appropriate permission class
- `apps/runner/runner/client.py` — runner sends `Authorization: Bearer <token>` on all internal requests
- `apps/web/src/` — login/logout UI, token storage, authenticated API client

**Key design decisions**

*JWT for user sessions, token for runner*: Users authenticate via JWT (short-lived access token + refresh token). The runner uses a long-lived static bearer token stored in `.env` as `RUNNER_REGISTRATION_TOKEN`. These are distinct credential types with distinct permission scopes.

*Custom User model*: Django's `AbstractBaseUser` gives full control over user fields without carrying baggage from `AbstractUser`. Fields: `id` (UUID), `email` (unique, used as username), `full_name`, `is_active`, `is_staff`, `created_at`.

*Organization membership*: A `Membership` join model connects `User` to `Organization` with a `role` field (enum: `owner`, `admin`, `operator`, `viewer`). Role determines what a user can do within an org. This is the authorization primitive — not Django groups.

*Object-level permissions*: Use `django-rules` or a custom `has_object_permission` on each view. The rule: a user can only access objects belonging to an organization they are a member of. Apply this at the queryset level (`.filter(organization=user.current_org)`), not just at the permission check level.

*DRF auth class ordering*: `DEFAULT_AUTHENTICATION_CLASSES = [JWTAuthentication, RunnerTokenAuthentication]`. `RunnerTokenAuthentication` is a custom class that checks for `Authorization: Bearer <runner-token>` and returns a synthetic `RunnerUser` principal. This keeps the runner's internal endpoints distinct from user-facing endpoints without requiring the runner to have a user account.

*Frontend auth*: Store JWT access token in memory (not localStorage). Store refresh token in an `httpOnly` cookie. Implement token refresh on 401 responses using an axios/fetch interceptor. This is the standard pattern for preventing XSS-based token theft.

**What NOT to do**

- Do not use session-based auth for the API. Sessions don't compose well with the runner's machine-to-machine access patterns.
- Do not use `django-allauth` or `dj-rest-auth` without understanding what they add. `djangorestframework-simplejwt` is sufficient and explicit.
- Do not add SSO (SAML, OIDC) in phase 10.7. That is a sales requirement, not an MVP requirement.
- Do not store JWT tokens in localStorage. XSS vulnerabilities in the React app would expose all stored tokens.
- Do not add row-level security in PostgreSQL. Enforce tenancy at the Django queryset layer.

**Major risks**

- *Retrofitting auth breaks existing tests*: All service tests written in phases 01–09 and 10.1–10.6 assumed `AllowAny`. After adding auth, those tests will fail with 401. Mitigation: update test fixtures to create authenticated test clients. This is expected work, not a regression.
- *Token leakage via runner token rotation*: `RUNNER_REGISTRATION_TOKEN` is a long-lived credential. If it leaks, any process can call the internal API. Mitigation: the internal endpoints only accept requests from within the Docker network (enforce with a middleware that checks `REMOTE_ADDR` against the Docker subnet). Token rotation support should be added in the same phase.
- *Missing org-filter on queryset*: If a developer forgets `.filter(organization=user.current_org)` on one queryset, an authenticated user can read another org's data. This is a multi-tenancy leak. Mitigate with a base `OrganizationQuerySet` mixin that every domain model's queryset inherits, which automatically scopes all queries.

**Suggested milestone breakdown**

1. Add `User` model and `Membership` model; update `AUTH_USER_MODEL`; migration.
2. Add `JWTAuthentication` config; login/refresh/logout endpoints.
3. Add `RunnerTokenAuthentication` custom class; update internal endpoints.
4. Add `OrganizationQuerySet` mixin; apply to all domain models.
5. Replace `AllowAny` with `IsAuthenticated` + object-level permissions across all views.
6. Fix all existing tests to use authenticated test clients.
7. Add login/logout UI to React; authenticated API client with token refresh.

**Testing / verification approach**

- Auth unit tests: unauthenticated request to any non-health endpoint returns 401; runner token accepted on internal endpoints; user JWT rejected on internal endpoints.
- Tenancy isolation test: user in org A cannot GET, PATCH, or DELETE any object belonging to org B.
- Token refresh test: expire the access token; verify the React client transparently refreshes and retries the original request.
- Manual gate: log in as a new user; create an org; create a runbook; log out; log in as a different user with no org membership; verify no data from the first user is visible.

---

### 4.8 Live Event Streaming

**Purpose**

Today the UI polls for execution status. Polling works and is correct for the current scale, but it introduces UI lag (up to the poll interval) and unnecessary database load (every open UI tab issues periodic requests). Live event streaming replaces polling with server-push updates: the runner reports a step completion, Django pushes the update to connected UI clients in real time.

**Why it comes eighth**

Live streaming requires auth (4.7) — you need to know who is connected to scope what updates they receive. It also requires stable execution and step models — the event payloads must match the serialized shapes the UI already knows about. Streaming before auth means any browser tab can subscribe to any execution's updates.

This is also explicitly a UX enhancement, not a correctness requirement. The system works correctly with polling. Streaming makes it feel faster and reduces DB load. Those are valuable improvements, but they are improvements — not foundations. Build them after the foundations are solid.

**Dependencies**

- 4.7 (auth) must be complete
- Execution and step models must be fully stable
- `config/asgi.py` already exists (Django 5 supports ASGI natively)
- Django Channels or native Django ASGI SSE handler

**Affected parts of repo**

- `apps/api/config/asgi.py` — update to support WebSocket or SSE routes
- `apps/api/apps/executions/` — execution service emits in-process events at state transitions
- `apps/api/` — new SSE or WebSocket consumer for execution updates
- `apps/web/src/` — replace polling with EventSource (SSE) or WebSocket connection
- `docker-compose.yml` — may need a Redis or in-memory channel layer if using Django Channels

**Key design decisions**

*SSE vs. WebSocket*: Use Server-Sent Events (SSE), not WebSockets. Execution updates are unidirectional (server to client). WebSockets are bidirectional and require more infrastructure. SSE is a regular HTTP response with `Content-Type: text/event-stream` — it works through any proxy, requires no special client library, and is supported natively in all modern browsers via `EventSource`.

*Channel layer*: For a single-server deployment, use Django's in-process event system (Django `dispatch` or a simple asyncio queue per connection). Do not add Redis as a channel layer until horizontal scaling requires it. Django Channels with an in-memory layer works for one server. When you scale to multiple API servers, the channel layer must be externalized — that is a production hardening (10.9) concern.

*Event payload*: SSE events are small JSON payloads: `{"type": "step.completed", "step_id": "...", "status": "succeeded", "timestamp": "..."}`. The client already has the full execution state from initial load; SSE updates are patches, not full re-fetches.

*Reconnection*: The `EventSource` API handles reconnection automatically. Include `id:` fields in SSE events so the browser can request missed events after reconnection using `Last-Event-ID`. Store the last 60 seconds of events per execution in Django (a simple in-memory deque per execution, not DB-persisted).

*Fallback*: Keep polling as a fallback. If the SSE connection fails three times, the client reverts to polling. This ensures the system degrades gracefully if the ASGI server is misconfigured.

**What NOT to do**

- Do not add Kafka, Redis Pub/Sub, or any external broker in phase 10.8. In-process event dispatch is the correct solution at this scale. The broker is a future concern.
- Do not push audit events or integration events through the SSE channel — only execution/step status updates.
- Do not add bidirectional communication (clients pushing events back to server via the stream). Use regular REST endpoints for user actions.

**Major risks**

- *ASGI worker management*: Switching from WSGI to ASGI changes the server model. Gunicorn with sync workers will not support SSE connections longer than a request timeout. You must use `uvicorn` with an ASGI entrypoint. Verify `config/asgi.py` is correct and the docker-compose command uses `uvicorn`.
- *Connection accumulation*: Each open browser tab holds one open SSE connection. With N executions running simultaneously and M users watching, there are N×M open connections. Django must close SSE streams immediately when the execution reaches a terminal state (`succeeded`, `failed`, `cancelled`). Don't leave streams open indefinitely.
- *Event ordering*: In-process event dispatch does not guarantee order if multiple coroutines emit events concurrently. Because the runner executes steps sequentially (one at a time), this is not a real risk — but document it as a constraint.

**Suggested milestone breakdown**

1. Update `config/asgi.py` to route SSE paths through ASGI.
2. Update docker-compose `api` command to use `uvicorn` instead of `gunicorn`.
3. Implement in-process event bus: `ExecutionEventBus.emit(execution_id, event)` and `ExecutionEventBus.subscribe(execution_id)`.
4. Wire `emit` calls into execution and step service state transitions.
5. Add SSE endpoint: `GET /api/v1/executions/{id}/stream/` — streams events as `text/event-stream`.
6. Replace polling in React execution detail page with `EventSource`; add polling fallback on connection failure.
7. Add reconnection with `Last-Event-ID` support.

**Testing / verification approach**

- SSE endpoint test: open stream for execution ID; trigger step state change; assert event received within 100ms.
- Reconnection test: drop the SSE connection mid-stream; reconnect with `Last-Event-ID`; assert missed events are replayed.
- Terminal state test: execution reaches `succeeded`; assert SSE stream closes within 1 second.
- Manual gate: run a multi-step execution; watch execution detail page; confirm step statuses update in real time without polling.

---

### 4.9 Production Hardening

**Purpose**

Production hardening is the phase where the system is made safe, reliable, and observable at real-world scale. It covers: connection pooling, rate limiting, proper error boundaries, structured logging, health checks, graceful shutdown, query optimization, secret rotation patterns, and the operational runbook for common failure scenarios.

**Why it comes ninth**

You cannot harden what doesn't exist. Every previous phase may introduce new queries, new connection patterns, new failure modes. Hardening a moving target wastes effort. Once the full feature set (10.1–10.8) is locked, you have a stable picture of every service's resource consumption, every query's frequency, every external dependency's failure profile. Only then can you make informed decisions about connection pool sizes, rate limit thresholds, and circuit breaker configuration.

**Dependencies**

- All previous phases must be complete and tested
- Production-like load test data must exist (use `seed_dev` from phase 09 extended with realistic volumes)
- Observability tools must be chosen (Prometheus + Grafana or DataDog — decide before this phase)

**Affected parts of repo**

- `apps/api/requirements/prod.txt` — add `gunicorn`, `psycopg2-binary` (or `psycopg[binary]`), `pgbouncer` config
- `apps/api/config/settings/prod.py` — security headers, HSTS, CSP, DB connection pool settings
- `apps/api/` — structured logging middleware, request ID middleware, health check endpoint expansion
- `docker-compose.yml` — PgBouncer service for connection pooling
- `apps/runner/runner/main.py` — graceful shutdown on SIGTERM (drain in-flight execution before exit)
- `apps/web/` — production build optimization, CDN-ready asset paths

**Key design decisions**

*Connection pooling*: Run PgBouncer in transaction-pooling mode between Django and PostgreSQL. This is critical when the API scales to multiple workers — each Gunicorn worker holds a persistent connection without PgBouncer, which exhausts PostgreSQL's `max_connections` limit at low scale. PgBouncer as a Docker sidecar is the correct dev-to-prod approach.

*Structured logging*: Replace `print()` statements and default Django logging with `structlog`. Every log line must be a JSON object with: `timestamp`, `level`, `service`, `request_id`, `user_id` (if available), `execution_id` (if available), `message`, `extra fields`. This makes logs machine-parseable and searchable.

*Request ID propagation*: Generate a `X-Request-ID` header on every incoming request (if not present). Propagate it through every `httpx` call to the AI service and every internal API call from the runner. Include it in every log line. When debugging cross-service issues, the request ID is the correlation key.

*Graceful shutdown*: The runner must handle `SIGTERM` by: stopping the poll loop, waiting for the current step to complete (with a 30-second hard timeout), reporting the current step status back to Django, and exiting cleanly. Without graceful shutdown, a runner restart mid-execution leaves a step in `running` state with no one to finish it.

*Query optimization*: Run `django-debug-toolbar` against the test environment to identify N+1 queries. The most likely offenders: execution list endpoint (N queries for step counts), audit trail (N queries for actor labels). Fix with `select_related` and `prefetch_related`. Do not add indexes speculatively — add them based on `EXPLAIN ANALYZE` output from real query patterns.

*Rate limiting*: Add `django-ratelimit` on public API endpoints. Start conservative: 100 requests per minute per IP for unauthenticated endpoints, 1,000 per minute per authenticated user. Adjust based on observed traffic.

**What NOT to do**

- Do not add Celery, Redis, or any async task queue as part of production hardening. If there is no task queue requirement surfaced by phases 10.1–10.8, don't add one now.
- Do not add a CDN configuration until AWS deployment (10.10) — there is no CDN to configure in local Docker.
- Do not add database replicas or read replicas. Single-primary is correct until you have measured a read throughput problem.

**Major risks**

- *PgBouncer misconfiguration invalidating LISTEN/NOTIFY*: If Django Channels is using the database channel layer with `LISTEN/NOTIFY`, PgBouncer in transaction mode will break it (Postgres notifications require a persistent connection). Mitigation: if you added in-process SSE (4.8) correctly, you are not using `LISTEN/NOTIFY`. Document this constraint explicitly.
- *Gunicorn worker count*: The default Gunicorn worker formula is `2 * CPU_count + 1`. For the API, this is correct for sync workers handling short requests. SSE endpoints require async workers — confirm ASGI/uvicorn worker configuration handles both.

**Suggested milestone breakdown**

1. Add PgBouncer to docker-compose and prod settings; verify connection pool behavior under load.
2. Add `structlog` and request ID middleware to all services.
3. Add rate limiting to public API endpoints.
4. Add graceful shutdown to runner (SIGTERM handler).
5. Profile and fix top-3 N+1 queries identified by `EXPLAIN ANALYZE`.
6. Add security headers to production Django settings: HSTS, CSP, X-Frame-Options, Referrer-Policy.
7. Expand health check endpoint to include DB and AI service connectivity.
8. Write operational runbook: what to do when execution is stuck in `claimed`, when runner crashes mid-step, when AI service is unavailable.

**Testing / verification approach**

- Load test: `locust` or `k6` — simulate 50 concurrent users browsing executions; assert P99 latency < 200ms; assert no 5xx responses.
- Graceful shutdown test: start a multi-step execution; send SIGTERM to runner mid-step; assert step completes cleanly; assert execution can be resumed by a new runner instance.
- Security headers test: `curl -I` production endpoint; assert all required headers present.
- Connection pool test: simulate 100 concurrent Django requests; assert Postgres `pg_stat_activity` shows ≤ PgBouncer pool_size connections from Django.

---

### 4.10 AWS Deployment Workflows

**Purpose**

Deploy the platform to AWS in a way that is secure, cost-appropriate for the current scale, and operationally maintainable by a small team. The `infra/aws/` directory already exists as a placeholder.

**Why it comes last**

AWS deployment is the final phase because every architectural decision that affects infrastructure requirements is made in earlier phases:
- Artifact storage (4.4) requires S3
- Integrations (4.5) require outbound internet access with egress policies
- Auth (4.7) requires HTTPS and proper TLS termination
- Live streaming (4.8) requires a WebSocket/SSE-capable load balancer (ALB)
- Production hardening (4.9) requires decisions about connection pooling and logging infrastructure

Designing AWS infrastructure before these decisions are made results in infrastructure that doesn't fit the system it's supposed to run. You cannot design a correct ECS task definition for the runner until you know what IAM permissions the runner needs. You cannot design the S3 bucket policy until you know the artifact upload flow.

**Dependencies**

- All previous phases complete
- AWS account with appropriate IAM permissions
- `infra/aws/` directory scaffold

**Affected parts of repo**

- `infra/aws/` — Terraform or CDK definitions for: VPC, ECS clusters, RDS instance, ElastiCache (if needed), S3 bucket, ALB, ACM cert, Route 53, ECS task definitions, IAM roles, security groups
- `docker-compose.yml` — must have a production-equivalent compose file that mirrors ECS task configs
- `apps/api/config/settings/prod.py` — must read all secrets from AWS Secrets Manager or SSM Parameter Store via `boto3` at startup
- `.github/workflows/ci.yml` — add deployment job: build images, push to ECR, update ECS service

**Key design decisions**

*Compute*: ECS Fargate for all services (API, AI, runner, web build). Fargate removes EC2 instance management. Start with the smallest feasible task sizes: API at 0.5 vCPU / 1GB RAM, runner at 0.25 vCPU / 512MB RAM. Scale task count, not task size, when load increases.

*Database*: RDS PostgreSQL 17 in a private subnet. Multi-AZ standby for production. Use `db.t4g.micro` to start — it is sufficient for the current workload and costs ~$15/month.

*Object storage*: One S3 bucket for artifacts, prefixed by organization ID. Server-side encryption with SSE-S3 (upgrade to SSE-KMS when compliance requires it). Lifecycle policy: move objects older than 90 days to S3 Glacier Instant Retrieval.

*Secrets*: All credentials (Django secret key, DB password, OpenAI API key, runner registration token) stored in AWS Secrets Manager. Django reads them at startup via `boto3`. Never store secrets in ECS task environment variables (they appear in the ECS console in plaintext) or in ECR image layers.

*Network topology*: Public subnets contain only the ALB. API, AI, runner, and RDS are in private subnets. Only the ALB has an internet-facing security group. The runner communicates with the API over the VPC internal network.

*CI/CD*: GitHub Actions builds Docker images on every push to `main`, pushes to ECR, and triggers an ECS rolling deployment. Rolling deployment ensures zero-downtime. The runner must handle graceful shutdown (4.9) for rolling deploys to work without dropping executions.

*Infra-as-code choice*: Use Terraform. CDK requires Node.js knowledge that the team may not have uniformly. Terraform's declarative model is easier to review in pull requests. Use `terraform-aws-modules` for VPC, ECS, and RDS to reduce boilerplate.

**What NOT to do**

- Do not use EKS. Kubernetes is operationally expensive for a team that does not already run it. ECS Fargate is the correct abstraction at this scale.
- Do not put RDS in a public subnet, even for cost savings.
- Do not store the `RUNNER_REGISTRATION_TOKEN` in the ECS task definition environment. Use Secrets Manager.
- Do not skip the staging environment. Deploy to staging first, run the test suite against it, then promote to production.
- Do not use a single availability zone for production. At minimum, deploy across two AZs.

**Major risks**

- *ECS runner task count*: ECS can run multiple runner tasks simultaneously. Two runners polling `claim-next` concurrently is correct (each claims a different execution), but two runners claiming the same execution is a bug. Verify that `claim-next` uses `SELECT ... FOR UPDATE SKIP LOCKED` to prevent double-claim. If it doesn't, fix it before multi-runner deployment.
- *Cold start latency*: Fargate containers have a cold start time of 20-60 seconds. The runner must poll `claim-next` only after it's fully initialized. Add a startup probe to the ECS task definition.
- *Cost overrun*: Fargate billing is per vCPU-second. A runner that polls every 5 seconds and runs continuously accumulates billing even when idle. Implement adaptive polling: back off to 30-second intervals when no executions are queued.

**Suggested milestone breakdown**

1. Write Terraform modules: VPC, security groups, RDS, S3 bucket with lifecycle policy.
2. Write ECS task definitions for all services; test locally with `ecs-local`.
3. Write ALB + ACM + Route 53 Terraform; configure HTTPS termination.
4. Write Secrets Manager integration in Django prod settings; verify secrets rotation does not require container restart.
5. Write GitHub Actions workflow: build → ECR push → ECS rolling deploy.
6. Deploy to staging; run full test suite against staging environment.
7. Smoke test end-to-end: create org, create runbook, parse with AI, execute with approval, view artifact, check Slack notification.
8. Deploy to production; monitor for 48 hours; write incident response runbook.

**Testing / verification approach**

- Terraform plan review: `terraform plan` must show no unexpected resource deletions before every `apply`.
- Staging smoke test: automated test suite (from phase 08) runs against staging after each deploy.
- Chaos test: kill the runner ECS task mid-execution; verify a new task starts and can resume the execution.
- Security scan: `trivy` image scan on all container images before ECR push; no critical CVEs.

---

## 5. Cross-Cutting Concerns

### 5.1 Scaling Risks

The first scaling risk is not throughput — it is correctness under concurrency. Before worrying about requests per second, verify that:

- `claim-next` uses row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`) and handles concurrent runners without double-claim
- `ApprovalService.decide()` uses `select_for_update()` to prevent concurrent decisions on one request
- Artifact uploads are idempotent (the same runner can retry without creating duplicate records)

The second scaling risk is the approval poll loop. If the runner polls `GET /internal/steps/{id}/approval-status` every 2 seconds and there are 20 concurrent executions awaiting approval, that is 10 requests per second to Django just for approval polling. Use exponential backoff in the approval poll loop (start at 2 seconds, cap at 30 seconds).

The third scaling risk is audit table size. As noted in 4.3, audit events accumulate quickly. Add a database index on `(organization_id, occurred_at)` before the table has more than 100k rows.

### 5.2 Data Integrity

Every state transition in the execution state machine must be a single database transaction: update the status field and write the audit event in the same `atomic()` block. Never update status in one request and write the audit event in another. This is the strongest guarantee of data integrity available without a distributed transaction coordinator.

Foreign key constraints must be enforced at the database level, not just the application level. Do not use `on_delete=SET_NULL` on required relationships — use `PROTECT` and handle deletion explicitly in the service layer.

The workflow definition is stored as a JSONB column on the `Workflow` model. Add a database check constraint or a pre-save signal that validates the JSONB against `workflow.schema.json` before storage. Do not rely solely on application-layer validation.

### 5.3 Observability

By phase 10.9, every service must emit three signals:

*Logs*: Structured JSON, via `structlog`, including `request_id`, `execution_id`, and `organization_id` on every relevant log line. Shipped to CloudWatch Logs in production.

*Metrics*: Key application metrics exposed at `/metrics` in Prometheus format: execution count by status, step execution latency by type, approval decision latency, AI service call latency and error rate, artifact upload size distribution. Use `django-prometheus` for automatic Django metrics.

*Traces*: Distributed traces connecting a frontend request through Django to the AI service. Use OpenTelemetry with `OTLP` export to a collector. This is the lowest-priority of the three signals — add it after logs and metrics are working.

### 5.4 Failure Modes

Document and handle these explicitly:

| Failure | Effect | Recovery |
|---|---|---|
| Runner crashes mid-step | Step stuck in `running` | Watchdog: Django marks steps as `failed` if `running` for > N minutes with no heartbeat |
| AI service unavailable | Runbook parse fails | Django returns error to user; user can retry; no execution impact |
| Integration delivery fails | Notification not sent | `IntegrationEvent` logged as failed; no execution impact |
| Approval timeout | Step fails | Runner detects timeout; transitions step to `failed`; execution fails |
| Database connection lost | Django returns 503 | PgBouncer retries; ALB health check removes unhealthy instances |

---

## 6. Release Gating Strategy

Before moving from one expansion phase to the next, all of the following must be true:

**Gate for moving from approvals → policies (10.1 → 10.2):**
- Approval-gated step pauses execution and resumes after approval: verified manually
- Concurrent approval attempt returns 409: covered by test
- Approval timeout causes step failure: covered by test
- **Approval decision and approval-state transition occur in the same DB transaction: covered by test**
- Runner calls a step-start endpoint and receives a normalized `runner_action` field (`run`, `wait_for_approval`, or `blocked`) rather than inferring behavior from workflow JSON: covered by contract test
- Contract test proves `requiresApproval=false` step + policy that returns `ApprovalRequired` → runner receives `runner_action=wait_for_approval`: covered by test
- _Note: Audit events for approvals are NOT required at this gate. Audit is Phase 10.3. Approval decisions are persisted in approvals tables only at this stage._

**Gate for moving from policies → audit (10.2 → 10.3):**
- Policy with matching condition creates ApprovalRequest even when `requiresApproval=false` in schema: verified manually
- `requiresApproval=true` floor is honored: policy `AutoApprove` on a `requiresApproval=true` step still results in `ApprovalRequired`: covered by test
- Policy evaluation record created for every evaluated step: covered by test
- Policy evaluation failure does not auto-approve: covered by test
- Runner contract for policy-driven approval verified end-to-end: verified manually

**Gate for moving from audit → artifacts (10.3 → 10.4):**
- Audit event written in same DB transaction as triggering action: covered by test
- `AuditEvent` model has no update path in the service layer: verified by code review
- Execution audit trail shows all state transitions in correct order: verified manually

**Gate for moving from artifacts → integrations (10.4 → 10.5):**
- Artifact upload creates both the file and the DB record: covered by test
- Artifact download URL is time-limited: covered by test
- Artifact upload size limit enforced: covered by test

**Gate for moving from integrations → AI parsing (10.5 → 10.6):**
- Integration delivery failure does not affect execution: covered by test
- Outbound URL blocklist prevents SSRF: covered by test
- Credentials never returned in API response: verified by code review

**Gate for moving from AI parsing → auth (10.6 → 10.7):**
- AI-parsed workflow requires human review before execution: verified manually
- Parse result fails schema validation when AI returns malformed output: covered by test

**Gate for moving from auth → streaming (10.7 → 10.8):**
- Unauthenticated request to any non-health endpoint returns 401: covered by test
- User in org A cannot read org B's data: covered by test
- Runner token rejected on user-facing endpoints: covered by test

**Gate for moving from streaming → hardening (10.8 → 10.9):**
- SSE stream closes on execution terminal state: covered by test
- Polling fallback activates after 3 connection failures: covered by test

**Gate for moving from hardening → AWS (10.9 → 10.10):**
- P99 API latency < 200ms under 50 concurrent users: load test
- Graceful runner shutdown completes without stuck executions: verified manually
- All secrets read from environment, not hardcoded: verified by code review

---

## 7. Anti-Patterns

These are the ways this system most commonly gets ruined. Each one looks reasonable in the moment and is harmful at the system level.

**AP-1: Adding a message queue to solve polling overhead.**
"The runner polls too often — let's add Celery and Redis." This replaces a simple, debuggable polling loop with a distributed system that has its own failure modes (task loss, duplicate execution, stuck workers). Poll-based execution is correct until you have measured the polling overhead in production and determined it is genuinely a problem. At 10 executions per day, it never will be.

**AP-2: Moving business logic into the runner.**
"The runner is already there during execution — it's faster to just update the DB directly." This is the most common way to break INV-2. The moment the runner writes to the database, the runner becomes a second control plane. Now you have two systems that can mutate execution state, and their changes can conflict. Every runner action must be mediated by a Django API call.

**AP-3: Letting the frontend call the AI service directly.**
"The AI parse call is slow and we want to show progress to the user — let's stream directly from FastAPI to the browser." This violates INV-3 and INV-4. The frontend should call Django, which calls the AI service, which returns the result to Django, which returns it to the frontend. The latency overhead is small; the architectural clarity is large.

**AP-4: Building approvals for the general case on the first pass.**
"We should support delegation, escalation, multi-party approval, and time-zone-aware approval windows from the start." This produces a system so complex it cannot be built or debugged. Build the simplest thing that works: a single human approves or rejects. Add complexity when a real user asks for it with a specific use case.

**AP-5: Skipping the human review gate on AI-parsed workflows.**
"The AI is good enough — auto-execute the parsed workflow." AI models hallucinate. A hallucinated step in a runbook that deletes production data will execute. The human review gate is a hard requirement, not a UX nicety.

**AP-6: Adding auth too early.**
"We should start with auth so we don't have to retrofit it later." Adding auth before the domain model is stable means every feature you build requires RBAC wiring on unstable models. The correct tradeoff is: develop quickly on a stable domain, add auth as a layer after the domain is proven. This is only safe because the system is not publicly deployed until phase 10.10.

**AP-7: Treating the AI service as a source of truth.**
"Let's have the AI service call back to Django to store results directly." The AI service must remain stateless. It transforms inputs into outputs. Django decides what to do with those outputs. The moment the AI service writes to the database, you have two services with write authority over execution state.

**AP-8: Skipping phase gates to move faster.**
"We're confident in our implementation — let's skip the verification gates." Gates exist because integration bugs surface at the seam between phases, not within a single phase's implementation. Every skipped gate is a risk that the next phase will be built on a broken foundation and the bug will be expensive to diagnose.

**AP-9: Over-indexing on microservice autonomy.**
"Each domain app should have its own API service." There are four services in this system and there should remain four. Splitting Django's domain apps into separate API microservices multiplies deployment complexity, introduces network latency on every cross-domain query, and requires a service mesh. The monolith is the correct architecture for this scale.

**AP-10: Building observability last as an afterthought.**
Structured logging and request ID propagation must be added during phase 10.9 (hardening), not after AWS deployment when production incidents make them urgent. By that point, debugging a live issue without them is extremely painful.

---

## 8. Future Blueprint Recommendations

After phase 10.10, the system will be a production-deployed platform. Future blueprints should follow this naming convention:

```
docs/blueprints/phase-11-{focus-area}-blueprint.md
```

Recommended future blueprints and their sequencing rationale:

| Blueprint | Trigger condition |
|---|---|
| `phase-11-multi-runner-fleet-blueprint.md` | When execution queue depth regularly exceeds 10 and single-runner throughput is the bottleneck |
| `phase-12-approval-delegation-blueprint.md` | When a real organization asks for on-call escalation or delegated approval |
| `phase-13-scheduled-executions-blueprint.md` | When organizations need runbooks to run on a cron schedule rather than being manually triggered |
| `phase-14-workflow-versioning-blueprint.md` | When organizations need to pin executions to a specific workflow version and audit version changes |
| `phase-15-sso-saml-oidc-blueprint.md` | When a customer requires SSO as a procurement condition |
| `phase-16-compliance-export-blueprint.md` | When SOC 2 or ISO 27001 audit requires formal audit log export in a specific format |
| `phase-17-multi-region-blueprint.md` | When data residency requirements prevent single-region deployment |

Each future blueprint must begin with a "current state analysis" section that re-reads the relevant source files before proposing changes. Blueprints authored from memory without reading current code produce plans that conflict with reality.

---

## 9. Codex / Claude Execution Strategy for Future Phases

When using an AI assistant to implement future phases:

**9.1 Always start with context loading.**

Before any implementation message, load:
- The current blueprint for the phase being implemented
- The relevant existing source files for the area being changed
- The verification gates from the previous phase (to confirm they are passing)

Do not assume the assistant knows the current state of the codebase. Read the files first.

**9.2 One milestone at a time.**

Each blueprint milestone breakdown contains 6–8 discrete steps. Feed one step at a time to the assistant. Confirm it passes before proceeding to the next. Batching multiple steps into a single prompt produces implementations where the later steps assume things the earlier steps haven't built yet.

**9.3 Specify the diff, not the goal.**

"Add `waiting_for_approval` to the step status enum in `apps/api/apps/executions/models.py` and generate a migration" produces a better result than "implement the approval system." The narrower the scope, the less the assistant needs to infer.

**9.4 Run validation before marking complete.**

Every milestone ends with a verification gate. Do not mark a milestone complete until the verification command has been run and passed. The assistant can propose that a command will pass — only actually running it can confirm it.

**9.5 Preserve architecture invariants explicitly.**

When giving instructions that touch service boundaries, explicitly state the constraint: "The runner must not call the database. Implement this by adding an endpoint to Django that the runner calls." Without explicit constraints, an assistant under optimization pressure will take the path of least resistance, which is often the architecturally wrong one.

**9.6 Review generated migrations.**

Django auto-generated migrations are correct 90% of the time. The 10% where they are wrong involves: renaming fields (Django may generate a delete + add instead of a rename), altering columns with data (ordering matters), and adding constraints to existing tables with data (may require a two-step migration). Always review generated migration files before running them.

**9.7 Commit at verification gates, not at the end of a blueprint.**

Commit after each milestone's verification gate passes, not at the end of the full blueprint. Small commits are easier to revert, easier to review, and make it obvious exactly which change introduced a regression.

---

## 10. Definition of Done

Phase 10 is complete when:

- [ ] All 10 expansion areas have been implemented and passed their verification gates
- [ ] The system is deployed to AWS and accessible at a production domain over HTTPS
- [ ] A real organization has used the system to execute at least one real operational runbook
- [ ] The audit trail shows a complete, accurate history of that execution
- [ ] At least one approval gate was triggered and resolved during that execution
- [ ] At least one integration (Slack or similar) delivered a notification about that execution
- [ ] The AI service parsed a real runbook document into an executable workflow that a human reviewed and approved
- [ ] The P99 API latency under realistic load is under 200ms
- [ ] The system has survived one planned and one unplanned runner restart without losing execution state
- [ ] An operational runbook for common failure scenarios exists and has been tested
- [ ] All architecture invariants (section 3) are enforced by tests, not just by convention

---

*This blueprint is a living document. Update it when architectural decisions change, when new failure modes are discovered, or when the sequencing rationale is invalidated by new information. A blueprint that accurately reflects current thinking is more valuable than one that accurately reflects past thinking.*
