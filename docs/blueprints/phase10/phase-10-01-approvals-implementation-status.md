# Phase 10.1 Approvals Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-27 |
| Scope | Read-only implementation audit of Phase 10.1 Approvals |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-01-approvals-blueprint.md`, and Phase 10 guardrails |
| Verdict | Ready with minor follow-ups |

## 1. Executive verdict

Phase 10.1 Approvals is functionally implemented and is close enough to support Phase 10.2 Policies after a small set of follow-ups.

The core control-plane path exists:

- Approval request and decision models are present with migrations.
- `ExecutionStep.Status` includes `waiting_for_approval`.
- Django owns approval creation, decisioning, timeout materialization, and runner state transitions.
- Public approval inbox/detail/decision APIs exist under `/api/v1/approvals/`.
- Internal runner start and approval-status APIs exist under `/api/v1/internal/...`.
- The runner calls Django's step-start endpoint for every step and obeys `runner_action`.
- React has an approvals inbox and execution detail renders `waiting_for_approval`.

This is not blocked, but Phase 10.2 should not start until the required fixes in section 7 are handled or explicitly accepted. The most important gap is that the service layer does not enforce the blueprint's cross-execution/cross-organization invariants when `request_step_approval()` is called directly, even though current internal views pass a correctly scoped step. Phase 10.2 will add more service-layer call sites, so this should be tightened first.

## 2. Implemented scope

- Approval app is registered in `INSTALLED_APPS`.
- `ApprovalRequest` exists with organization, execution, one-to-one step, status, runner identity, timeout snapshot, `expires_at`, and `resolved_at`.
- `ApprovalDecision` exists with one-to-one request, decision, source type, nullable user FK, pre-auth actor label source, notes, and timestamp.
- Approval migrations create the new tables and the expected indexes.
- `waiting_for_approval` is added to execution step status choices and the execution migration exists.
- Execution step transitions allow `waiting_for_approval -> running` and `waiting_for_approval -> failed`.
- `request_step_approval()` uses `transaction.atomic()` and row locks for execution and step, creates or reuses one request per step, snapshots `approvalTimeoutSeconds`, and sets `expires_at`.
- `decide_approval()` locks the request with `select_for_update()`, resolves expired requests before human decisions, rejects already-terminal requests with `409`, and creates one terminal decision.
- `get_approval_status()` materializes timeouts to `timed_out` and creates a system decision.
- Public list/detail/decide endpoints are implemented.
- Internal step-start endpoint returns `runner_action=run` for normal steps and `runner_action=wait_for_approval` for protected steps.
- Internal approval-status endpoint returns `wait`, `run`, or `fail` and transitions approved steps to `running`, rejected/timed-out steps to `failed`.
- Runner schemas and client include step-start and approval-status contracts.
- Runner executor never branches on local `requires_approval`; it calls `start_step()` for every step and waits for Django before executing commands.
- React approval feature area includes types, API client, query hooks, inbox route, decision form, polling, and query invalidation.
- Workflow schema supports `approvalTimeoutSeconds`.
- No new service, queue, event bus, WebSocket, SSE, delegation system, policy engine, integration notification, or audit dependency was introduced.

## 3. Missing scope

- No manual end-to-end verification evidence was found for approved, rejected, and timed-out paths across API, runner, and UI.
- The required Phase 10.1 policy-forward contract test is missing: a `requiresApproval=false` step must still be able to produce `runner_action=wait_for_approval` from Django once Phase 10.2 policy evaluation requires approval.
- Runner client tests do not directly cover `start_step()` or `get_step_approval_status()` URLs/payloads/parsing.
- Frontend tests cover approval submission but do not cover reject submission, `409` already-decided error handling, or execution-detail `waiting_for_approval` rendering.
- Service tests do not cover cross-execution or cross-organization mismatch rejection.
- Public approval detail/decide endpoints are not tenant-scoped beyond unguessable UUIDs. This is expected pre-auth residual risk, but it is still a real multi-tenancy gap until Phase 10.7.
- General runner restart recovery for claimed executions is still not implemented. Phase 10.1 stores approval state in Django, but a restarted runner does not reclaim already-claimed executions through the current `claim-next` path.

## 4. Blueprint drift

- The implementation follows the newer Phase 10.1 runner-action contract better than the roadmap's older wording. The runner calls `/start/` for every step rather than locally branching on `requires_approval`.
- The implementation uses one normalized start endpoint instead of a separate internal `approval-request/` endpoint. This aligns with the Phase 10.1 blueprint's Phase 10.2 compatibility requirement, even though some milestone text still names `approval-request/`.
- Internal start responses include `execution_id`, `execution_status`, `step`, `approval_request`, `runner_action`, and `poll_after_seconds`. The guardrails show a more compact illustrative shape with `step_id`, `step_name`, `command`, and `approval_request_id`. This is acceptable contract drift because the runner has the original claimed step command and the response still carries the authoritative action.
- The roadmap's early risk section says the runner must guard approval polling with a hard timeout. The detailed Phase 10.1 blueprint makes Django authoritative for timeout resolution and tells the runner to keep polling through transient HTTP errors. The implementation follows the detailed blueprint.
- The service-layer invariant `organization_id == execution.organization_id` and `step.execution_id == execution.id` is not enforced in `request_step_approval()` itself. Current HTTP views scope the step by execution, but the service does not protect future direct callers.
- `ExecutionDetailPage` displays waiting approvals, but terminal approval-driven failures are only shown through the generic `error_message` field.

## 5. Test coverage review

Covered:

- Approval request creation, idempotency, wrong-runner rejection, non-approval rejection, and timeout snapshot.
- Approval approve/reject decisions, second-decision conflict, timeout materialization, and repeated timeout resolution.
- Public approval list default pending behavior, organization-scoped list filtering, detail, approve, reject, missing actor, double decision, and not found.
- Internal start for non-approval and approval steps, idempotent start retry, wrong runner, approval polling pending/approved/rejected/timed-out, and invalid approval flow.
- Runner executor approval wait, approve resume, reject fail, timeout fail, multi-poll wait, and normal continuation.
- React approvals inbox render, pending approval display, decision submission, and generic API error banner.

Gaps:

- The double-decision test is transaction-marked but serial; it does not run two concurrent threads racing on the same request as required by the blueprint.
- No direct runner client tests for approval methods.
- No test proves Phase 10.2 can force `wait_for_approval` on a workflow step with `requiresApproval=false` without runner changes.
- No API/service test rejects mismatched execution/step/organization passed to approval services.
- No frontend reject-action test.
- No frontend `409` already-decided test.
- No execution-detail waiting-state render test.
- No recorded manual full-stack approved/rejected/timed-out verification.

## 6. Security/concurrency risks

- Pre-auth public APIs use `AllowAny`; `actor_display_name` is client supplied and correctly marked as `unverified_pre_auth`, but it is not authoritative identity.
- Public detail and decide endpoints are accessible by approval UUID without an organization filter or authenticated tenant check. This must be corrected in Phase 10.7; until then, treat this as local/dev only.
- Internal runner endpoints rely on runner ownership fields and claim tokens, not network isolation or runner auth. This is acceptable for current local phases but must be isolated before production.
- Direct service calls can create cross-execution/cross-organization approval records if passed mismatched objects. This is the highest-priority Phase 10.1 fix before policies add more decision points.
- Approval timeout resolution is read-driven. If the runner is dead and no UI/API read touches the request, `timed_out` is delayed. Guardrails correctly defer a recovery sweep to Phase 10.9.
- Concurrent duplicate approval-status polls after approval could race while moving a step from `waiting_for_approval` to `running`. The current runner is single-threaded per execution, so this is low risk, but the endpoint is not fully race-hardened for duplicate poll requests.
- Runner restart while waiting remains limited by the broader claimed-execution recovery gap. Approval state is durable, but work recovery is not.

## 7. Required fixes before Phase 10.2

1. Enforce approval service invariants before creating a request:
   - `step.execution_id == execution.id`
   - `execution.organization_id == step.execution.organization_id`
   - approval request organization matches execution organization

2. Add the Phase 10.2 compatibility contract test:
   - A step with `requiresApproval=false` can receive `runner_action=wait_for_approval` from Django when a policy hook/stub requires approval.
   - The runner executes no command until Django later returns `runner_action=run`.

3. Add or run a real transaction/concurrency test for double decisions:
   - Two concurrent writers race.
   - Exactly one succeeds.
   - Exactly one `ApprovalDecision` exists.
   - The loser receives the service/API equivalent of `409`.

4. Capture manual end-to-end verification evidence for approved, rejected, and timed-out approval paths before treating Phase 10.1 as signed off.

## 8. Recommended non-blocking follow-ups

- Add runner client tests for `start_step()` and `get_step_approval_status()`.
- Add frontend tests for reject decisions, `409` already-decided display, and execution-detail waiting-state rendering.
- Add a public API test for `status=all`, `execution_id` filtering, and timeout materialization during list/detail reads.
- Add a small operator note or seed path that makes the required organization ID discoverable for the approvals inbox until auth provides tenant context.
- Add a documented manual verification record under `docs/audits/` or `docs/verification/` for each Phase 10 gate.
- Consider idempotent handling for duplicate approval-status polls after the first poll transitions an approved step to `running`.
- Preserve the current `decided_by_label_source` behavior when Phase 10.7 auth replaces client-supplied actor labels.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-blueprint.md`
- `docs/blueprints/phase-10-expansion-architecture-guardrails.md`
- `docs/audits/phase-10-expansion-blueprints-audit.md`
- `docs/runbooks/local-development.md`
- `Makefile`
- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/common/api_errors.py`
- `apps/api/apps/common/exceptions.py`
- `apps/api/apps/approvals/apps.py`
- `apps/api/apps/approvals/models.py`
- `apps/api/apps/approvals/migrations/0001_initial.py`
- `apps/api/apps/approvals/admin.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/serializers.py`
- `apps/api/apps/approvals/views.py`
- `apps/api/apps/approvals/urls.py`
- `apps/api/apps/approvals/tests/conftest.py`
- `apps/api/apps/approvals/tests/test_services.py`
- `apps/api/apps/approvals/tests/test_api_contracts.py`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/migrations/0006_alter_executionstep_status.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/tests/test_services.py`
- `apps/api/apps/executions/tests/test_runner_api.py`
- `apps/api/apps/executions/tests/test_approval_runner_api.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/tests/test_client.py`
- `apps/runner/runner/tests/test_executor.py`
- `apps/runner/runner/tests/test_orchestration.py`
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/features/approvals/types.ts`
- `apps/web/src/features/approvals/api/approvalsApi.ts`
- `apps/web/src/features/approvals/hooks/useApprovalsInbox.ts`
- `apps/web/src/features/approvals/hooks/useDecideApproval.ts`
- `apps/web/src/routes/approvals/ApprovalsInboxPage.tsx`
- `apps/web/src/routes/approvals/ApprovalsInboxPage.test.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- `packages/workflow-schema/workflow.schema.json`
- `packages/workflow-schema/README.md`

## 10. Commands to run for verification

Run the focused suites first:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/approvals/tests -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/executions/tests/test_approval_runner_api.py -v
docker compose exec runner pytest apps/runner/runner/tests/test_executor.py -v
docker compose exec runner pytest apps/runner/runner/tests/test_client.py -v
docker compose exec web npm test -- --run apps/web/src/routes/approvals/ApprovalsInboxPage.test.tsx apps/web/src/routes/executions/ExecutionDetailPage.test.tsx
```

Then run the full regression gates:

```sh
make test-api
make test-runner
make test-web
make lint
```

Manual gate before Phase 10.2:

```sh
make up-d
make migrate
make seed-dev
make logs-api
make logs-runner
```

Manual verification must prove:

- A protected step enters `waiting_for_approval` before command execution.
- Approving from `/approvals` resumes the runner and the execution succeeds.
- Rejecting from `/approvals` fails the step without running the command.
- An expired `approvalTimeoutSeconds` request resolves to `timed_out` and fails the step without running the command.

## Short summary

Phase 10.1 is substantially implemented and the architecture is pointed in the right direction for Phase 10.2. Treat it as ready with minor follow-ups: strengthen approval service invariants, add the missing policy-forward and true concurrency tests, and record manual end-to-end verification before starting policy implementation.
