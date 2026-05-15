# Phase 10.2 Policies Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-28 |
| Scope | Read-only implementation audit of Phase 10.2 Policies |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-02-policies-blueprint.md`, and Phase 10.1 approval status |
| Verdict | Blocker remediation implemented; automated gates green; manual end-to-end verification still pending before Phase 10.3 sign-off |

## 0. Remediation update — 2026-04-28

The automated blockers identified in this status blueprint have been remediated in the Phase 10.2 implementation:

- `time_window` evaluation now uses the supplied `evaluated_at` value for matching and stores only the ISO string in `context_snapshot`.
- Policy detail/update and rule mutation APIs now require `organization_id` and scope UUID lookups to that organization.
- Execution policy evaluation history now requires `organization_id` and scopes by execution organization.
- Unexpected policy evaluation failures now attempt to persist a fail-closed `PolicyEvaluation` record before the step is failed.
- `is_active` query validation now accepts only `true`, `false`, or `all`.
- Runner client and executor coverage now includes `start_step()`, approval-status polling, and `runner_action=blocked`.

Implemented non-blocking follow-ups from section 8:

- Execution detail loading now prefetches only the latest policy evaluation per step.
- Execution detail now distinguishes `policy_blocked` from generic step failure.
- Frontend tests now cover policy metadata update and rule deactivation submissions.
- `PolicyEvaluation` is read-only in Django admin.

Verification completed:

- `make test-api` — 252 passed.
- `make test-runner` — 55 passed.
- `make test-web` — 44 passed.
- `make lint` — passed.

Remaining before Phase 10.3 sign-off:

- Perform and record manual end-to-end verification for policy approval, auto-approve, block, time-window, execution-detail visibility, and cross-tenant rejection paths.

## 1. Executive verdict

Phase 10.2 Policies is substantially implemented, but it is not ready to become an Audit Trail event source yet.

The core shape is correct: policies are organization-scoped models, rules use structured condition params, evaluation happens in Django, policy outcomes are wired into the internal step-start transition, policy-driven approvals can create approval requests for `requiresApproval=false` steps, `block` maps to failed steps, public CRUD APIs exist, and React has a policy management UI.

The blockers are correctness and tenant-safety issues:

1. `time_window` evaluation is nondeterministic because `_build_evaluation_context()` stores `evaluated_at` as a string and `_evaluate_time_window_condition()` falls back to wall-clock `timezone.now()` when it receives that string. Time-based rules can therefore make the wrong decision for a supplied evaluation timestamp.
2. Policy detail, update, and rule mutation APIs are addressable by policy UUID only and do not require or verify an organization scope. Until auth exists, this leaves cross-tenant reads and writes possible for any known UUID.
3. Unexpected policy evaluation failures fail the step but do not persist a `PolicyEvaluation` error record. Phase 10.3 depends on stable policy evaluation records as audit event sources.

Do not start Phase 10.3 until the required fixes in section 7 are completed and verified.

## 2. Implemented scope

- `Policy`, `PolicyRule`, and `PolicyEvaluation` models exist and inherit UUID `BaseModel`.
- Policies are tied to `Organization`; active policies are evaluated by organization.
- Rules support `risk_level`, `step_type`, and `time_window` condition types.
- Rules support `approval_required`, `auto_approve`, and `block` outcomes.
- Rule uniqueness is enforced for `(policy, priority)` and `(policy, name)`.
- `PolicyEvaluation` records raw `outcome`, `effective_outcome`, source, matched rule, condition snapshot, context snapshot, reason, and error fields.
- Policy CRUD service functions exist for policy and rule create/update.
- Condition validation exists in serializers and services.
- Evaluation uses a deterministic global sort key: `(rule.priority, policy.created_at, policy.id, rule.id)`.
- First matching rule wins.
- Workflow default fallback is implemented when no active rule matches.
- `requiresApproval=true` floor is implemented: policy `auto_approve` cannot waive a workflow approval requirement.
- `request_step_approval()` supports `policy_driven=True`, preserving the default rejection of non-policy approval creation for unprotected steps.
- `ExecutionStepStartView` evaluates policies before allowing a step to run.
- `approval_required` creates or reuses an `ApprovalRequest` and returns `runner_action=wait_for_approval`.
- `auto_approve` transitions the step to `running` and returns `runner_action=run`.
- `block` transitions the step to `failed`, sets `error_message=policy_blocked`, and returns `runner_action=blocked`.
- Runner schemas and executor accept `runner_action=blocked` and do not execute the command.
- Public policy routes are registered under `/api/v1/policies/`.
- Execution detail serialization embeds the latest policy evaluation summary per step.
- A public execution `policy-evaluations` action exists for evaluation history.
- React includes policy list, policy create, policy activate/deactivate, policy detail, metadata edit, rule add/edit/deactivate, and execution policy evaluation display.
- No new queues, event buses, external services, runner-side policy engine, AI dependency, or workflow schema changes were introduced.

## 3. Missing scope

- Time-window policy evaluation does not reliably use the evaluation timestamp supplied to `evaluate_step_policy()`.
- Policy detail/update/rule endpoints do not enforce organization scope.
- Unexpected evaluation exceptions do not attempt to persist an error `PolicyEvaluation`.
- Runner client tests do not directly cover `start_step()` or `get_step_approval_status()` URL/payload/parsing, including `blocked`.
- Runner executor tests do not directly cover `runner_action=blocked`.
- Frontend tests do not cover rule create submission, rule update submission, rule deactivate submission, policy activate/deactivate failure handling, or metadata update success/refetch.
- No evidence was found that the focused or full backend/frontend/runner suites were run after the Phase 10.2 implementation.
- No manual end-to-end verification record was found for policy approval, auto-approve, block, and execution-detail visibility paths.

## 4. Blueprint drift

- The roadmap text says conflicting policies return the stricter outcome, but the dedicated Phase 10.2 blueprint locks first-match deterministic semantics. The implementation correctly follows the dedicated blueprint.
- `GET /api/v1/policies/?is_active=<value>` treats any value other than `true` or `false` as `all`; the blueprint only allows `true`, `false`, or `all`.
- `PolicyEvaluation` error rows exist for invalid persisted rule params and condition evaluation exceptions, but not for broader unexpected failures in loading policies or writing evaluation rows.
- Execution detail prefetch loads all policy evaluations for each step and then uses the first item. The behavior is correct for display, but the query is broader than the "latest evaluation" intent.
- The policy list UI defaults to `is_active=all`, which matches the frontend section of the blueprint but differs from the backend API default of active-only.
- Policy CRUD uses UUID-only detail URLs without an organization query param. The API contract examples allow this shape, but it weakens the phase goal that policies are organization-scoped under the current pre-auth model.

## 5. Test coverage review

Covered:

- Policy model creation, inactive policy visibility, org cascade, rule uniqueness, inactive rule visibility.
- Policy create/update duplicate active-name handling.
- Rule create/update duplicate priority and duplicate name handling.
- Risk-level, step-type, and time-window condition validation.
- Risk-level and step-type evaluation.
- Workflow-default fallback for `requires_approval=true` and `false`.
- `requiresApproval=true` floor for `auto_approve`.
- Single-policy and cross-policy deterministic priority ordering.
- Inactive policy and inactive rule exclusion.
- Invalid persisted condition params fail closed.
- Policy start integration for `run`, `wait_for_approval`, `blocked`, floor behavior, idempotent approval request reuse, priority ordering, and deactivation fallback.
- Approval service `policy_driven=True` bypass and idempotency.
- Public policy list/create/detail/update/rule create/update/delete basics.
- React policy list/detail rendering and basic create form display.
- Execution detail policy evaluation display and floor-applied warning.

Gaps:

- Time-window tests do not catch that supplied `evaluated_at` is ignored after context construction.
- No API tests prove policy detail/update/rule mutations are tenant-scoped.
- The API test named `test_cross_tenant_policy_access_returns_404_on_rules` explicitly accepts either `201` or `404`, so it does not enforce isolation.
- No tests cover invalid `is_active` query values.
- No tests cover unexpected evaluation exception persistence.
- No runner client contract tests cover step-start and approval-status methods.
- No runner executor test covers `blocked`.
- Frontend tests do not exercise actual rule create/edit/deactivate submissions or policy metadata update submissions.
- No full-suite or manual verification evidence was found.

## 6. Security/multi-tenancy risks

- All API endpoints still use `AllowAny`; this is expected before Phase 10.7 but remains a real risk outside local/dev use.
- `GET/PATCH /api/v1/policies/{policy_id}/` can read or update any policy by UUID with no organization check.
- `POST/PATCH/DELETE /api/v1/policies/{policy_id}/rules/...` can mutate rules on any known policy UUID with no organization check.
- `GET /api/v1/executions/{execution_id}/policy-evaluations/` exposes evaluation history by execution UUID only.
- Policy evaluation itself filters active policies by `execution.organization`, so runtime enforcement is tenant-scoped even though management APIs are not.
- Public policy APIs should not be treated as production-safe until auth or explicit organization scoping is enforced.

## 7. Required fixes before Phase 10.3

1. Fix `time_window` evaluation to use the actual `evaluated_at` datetime passed to `evaluate_step_policy()`.
   - Keep an aware datetime for condition evaluation.
   - Store an ISO string only in `context_snapshot`.
   - Add tests where supplied `evaluated_at` differs from current wall-clock time.

2. Enforce tenant scope on policy management and evaluation-history APIs.
   - Require and validate `organization_id` for policy detail/update/rule mutations until auth exists, or otherwise route through an authenticated tenant context.
   - Add API tests proving cross-org UUID reads/writes are rejected.

3. Persist error evaluations for unexpected evaluation failures where persistence is still possible.
   - If policy loading or condition evaluation fails unexpectedly, the execution hook should leave a `PolicyEvaluation` record with `error_code`/`error_message` before failing the step.
   - Add service/integration tests for this fail-closed path.

4. Tighten API validation for `is_active`.
   - Accept only `true`, `false`, or `all`.
   - Return `400` for invalid values.

5. Add missing runner coverage.
   - Test `ApiClient.start_step()`.
   - Test `ApiClient.get_step_approval_status()`.
   - Test executor behavior for `runner_action=blocked`.

6. Run and record focused plus full verification gates before declaring Phase 10.2 complete.

## 8. Recommended non-blocking follow-ups

- Optimize execution detail evaluation loading to fetch only the latest evaluation per step.
- Add frontend submission tests for add/edit/deactivate rule and edit policy details.
- Add UI access to the full execution policy evaluation history endpoint.
- Add operator-facing copy that distinguishes `policy_blocked` from generic step failure in execution detail.
- Add a manual verification note under `docs/audits/` or `docs/verification/` for Phase 10.2.
- Consider service-level validation for blank policy/rule names, not only serializer-level validation.
- Consider adding admin read-only protection for `PolicyEvaluation` to reinforce append-only expectations before Phase 10.3.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-02-policies-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-implementation-status.md`
- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/common/api_errors.py`
- `apps/api/apps/common/exceptions.py`
- `apps/api/apps/approvals/models.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_policy_integration.py`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/tests/test_approval_runner_api.py`
- `apps/api/apps/executions/tests/test_policy_integration.py`
- `apps/api/apps/policies/apps.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/policies/migrations/0001_initial.py`
- `apps/api/apps/policies/admin.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/policies/serializers.py`
- `apps/api/apps/policies/views.py`
- `apps/api/apps/policies/urls.py`
- `apps/api/apps/policies/tests/test_models.py`
- `apps/api/apps/policies/tests/test_services.py`
- `apps/api/apps/policies/tests/test_api.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/tests/test_client.py`
- `apps/runner/runner/tests/test_executor.py`
- `apps/runner/runner/tests/test_orchestration.py`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/app/router.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/features/executions/types.ts`
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
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- `packages/workflow-schema/workflow.schema.json`

## 10. Commands to run for verification

Focused backend policy suites:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/policies/tests -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/executions/tests/test_policy_integration.py -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/approvals/tests/test_policy_integration.py -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/api/apps/executions/tests/test_approval_runner_api.py -v
```

Runner and frontend focused suites:

```sh
docker compose exec runner pytest apps/runner/runner/tests/test_client.py apps/runner/runner/tests/test_executor.py -v
docker compose exec web npm test -- --run apps/web/src/routes/policies/PoliciesPage.test.tsx apps/web/src/routes/policies/PolicyDetailPage.test.tsx apps/web/src/routes/executions/ExecutionDetailPage.test.tsx
```

Full regression gates:

```sh
make test-api
make test-runner
make test-web
make lint
```

Manual verification before Phase 10.3:

```sh
make up-d
make migrate
make seed-dev
make logs-api
make logs-runner
```

Manual verification must prove:

- A matching `approval_required` policy pauses a `requiresApproval=false` step and creates one approval request.
- A matching `auto_approve` policy lets a `requiresApproval=false` step run without approval.
- A matching `auto_approve` policy does not waive a `requiresApproval=true` step.
- A matching `block` policy fails the step before command execution.
- A `time_window` policy decision matches a controlled evaluation timestamp.
- Execution detail shows the latest policy evaluation for each evaluated step.
- Cross-tenant policy detail and mutation attempts are rejected.

## Short summary

Phase 10.2 is close but not signed off. Fix the time-window timestamp bug, enforce tenant scope on policy management APIs, persist fail-closed evaluation records for unexpected errors, and add the missing runner/API verification before moving to Phase 10.3 Audit Trail.
