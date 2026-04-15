# Phase 08 Blueprint: Targeted Testing Before More Feature Work

## 1. Phase overview

| Field | Value |
| --- | --- |
| Phase number | 08 |
| Objective | Add a narrow, high-value testing layer before continuing feature work, with the strongest emphasis on Django service behavior, critical API contracts, runner execution logic, and a minimal frontend smoke suite. |
| Status | Planned |
| Documentation basis reviewed on | 2026-04-01 |
| Current repo anchors reviewed | `/home/dylan/code/runbook-platform/apps/api`, `/home/dylan/code/runbook-platform/apps/runner`, `/home/dylan/code/runbook-platform/apps/web`, `/home/dylan/code/runbook-platform/docker-compose.yml`, `/home/dylan/code/runbook-platform/Makefile`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-03-application-service-layer-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-04-versioned-rest-apis-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-05-runner-real-flow-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-06-react-product-slice-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-07-ai-service-boundary-blueprint.md`. |
| Current repo state relevant to testing | `/home/dylan/code/runbook-platform/apps/api/requirements/dev.txt` already includes `pytest` and `pytest-django`; `/home/dylan/code/runbook-platform/apps/api/Dockerfile` currently installs only `requirements/base.txt`; `/home/dylan/code/runbook-platform/apps/runner` has no test dependency yet; `/home/dylan/code/runbook-platform/apps/web/package.json` has no test tooling yet; code in API, runner, and web is still scaffold-heavy. |
| In scope | Django tests for runbook creation, workflow creation service, execution creation service, claim-next atomic behavior, and execution status transition rules; runner tests for polling loop behavior, step status transitions, failure handling, and API client payload mapping; frontend tests for form submission smoke, execution detail rendering, and loading/error states. |
| Out of scope | Broad line coverage targets, browser E2E, visual regression, Playwright/Cypress suites, real container execution inside unit tests, overbuilt factory frameworks, testing library internals, or adding tests for placeholder code that has no business value yet. |

### Official docs reviewed first

- pytest good integration practices: [https://docs.pytest.org/en/stable/explanation/goodpractices.html](https://docs.pytest.org/en/stable/explanation/goodpractices.html)
- pytest fixtures: [https://docs.pytest.org/en/stable/how-to/fixtures.html](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- `pytest-django` configuring settings: [https://pytest-django.readthedocs.io/en/latest/configuring_django.html](https://pytest-django.readthedocs.io/en/latest/configuring_django.html)
- `pytest-django` database access: [https://pytest-django.readthedocs.io/en/latest/database.html](https://pytest-django.readthedocs.io/en/latest/database.html)
- `pytest-django` helpers: [https://pytest-django.readthedocs.io/en/latest/helpers.html](https://pytest-django.readthedocs.io/en/latest/helpers.html)
- Vitest getting started: [https://vitest.dev/guide/](https://vitest.dev/guide/)
- Vitest environment config: [https://main.vitest.dev/config/environment](https://main.vitest.dev/config/environment)
- Vitest mocking guide: [https://vitest.dev/guide/mocking.html](https://vitest.dev/guide/mocking.html)
- React Testing Library intro: [https://testing-library.com/docs/react-testing-library/intro/](https://testing-library.com/docs/react-testing-library/intro/)
- Testing Library `user-event` intro: [https://testing-library.com/docs/user-event/intro/](https://testing-library.com/docs/user-event/intro/)
- MSW quick start for Vitest: [https://mswjs.io/docs/quick-start](https://mswjs.io/docs/quick-start)

### Version-alignment notes

- Recommendations stay compatible with the repo’s current pinned runtime where possible:
  - Django `<6.0`
  - React `19.2.4`
  - Vite `8.0.1`
  - TanStack Query `5.95.2`
  - Python `3.12`
- Latest official docs were reviewed first because the phase is about locking in test patterns before the repo grows.
- Where the latest docs describe multiple options, this blueprint picks the smallest pattern that matches this repo’s stage.

### What this phase must accomplish

1. Prove the service layer and critical Django API contracts work before more features stack on top.
2. Prove the runner orchestration logic can be tested without containers or a real executor backend.
3. Add a very small frontend suite that catches broken forms, broken execution-detail rendering, and broken loading/error handling.
4. Avoid false confidence from large numbers of low-value tests.

## 2. Testing philosophy for this repo stage

This repo is still early enough that the biggest testing risk is not “too little line coverage.” The biggest risk is shipping structurally wrong behavior in the control plane and then layering more product code on top of it.

The correct testing philosophy for this phase is:

- Test the orchestration seams first.
- Test the critical contracts second.
- Test the thin UI paths last.
- Stop once the highest-risk behavior is covered.

That means:

- Django tests should focus on service-layer behavior and the APIs that matter to the runner and frontend.
- Runner tests should mostly be pure unit tests with fake dependencies.
- Frontend tests should verify only the page-level user paths that are expensive to break and cheap to keep deterministic.

This phase should not try to make the repo “fully tested.” It should make the repo safe enough that the next phases can move faster without constantly breaking create flows, claim flows, and status flows.

### Repo-stage rules

- Prefer one strong test over five superficial tests.
- Prefer service tests over model trivia tests.
- Prefer API contract tests over DRF plumbing duplication.
- Prefer runner unit tests over container-based execution tests.
- Prefer page-level frontend smoke tests over leaf-component tests.
- Prefer deterministic fixtures and builders over random data.
- Do not add coverage gates yet.
- Do not add tests just because a file exists.

## 3. Test pyramid / priority guidance for this project

### Recommended pyramid for this phase

| Priority | Layer | Why it matters now | Target size |
| --- | --- | --- | --- |
| P0 | Django service tests | This repo’s real business logic lives here or will live here imminently. | Largest part of the suite |
| P0 | Critical Django API contract tests | Frontend and runner both depend on these contracts being stable. | Small but explicit |
| P1 | Django transaction/concurrency tests | `claim-next` can create severe false confidence if not tested correctly. | Very small, very intentional |
| P1 | Runner unit tests | The runner should be testable as orchestration code, not as a container integration. | Medium |
| P2 | Frontend route/page smoke tests | Protects against obvious regressions without building a heavy UI suite. | Very small |
| P3 | Full Docker smoke runs | Useful for confidence, but not the main source of correctness. | A few commands, not a broad suite |

### What not to optimize for

- Do not optimize for percentages.
- Do not optimize for snapshot counts.
- Do not optimize for every serializer branch.
- Do not optimize for every CSS state.
- Do not optimize for real shell execution in runner tests.

### Highest-value test order

1. Django service tests for create flows.
2. Django runner-facing API tests.
3. PostgreSQL-backed claim-next concurrency tests.
4. Runner poller and executor unit tests.
5. Frontend smoke tests for creation and execution detail.

## 4. Django test plan in detail

### 4.1 Tooling and configuration recommendation

Use `pytest` plus `pytest-django` as the default Django test stack for this phase.

Why:

- The repo already includes `pytest` and `pytest-django` in `/home/dylan/code/runbook-platform/apps/api/requirements/dev.txt`.
- `pytest` fixtures are the right fit for shared setup across apps.
- `pytest-django` gives a clean path for `DJANGO_SETTINGS_MODULE`, DB access control, `client`, `rf`, and `settings` fixtures.
- Transaction-sensitive tests can use `@pytest.mark.django_db(transaction=True)` where needed.

Recommended config baseline:

- Add `pytest.ini` under `/home/dylan/code/runbook-platform/apps/api`.
- Set `DJANGO_SETTINGS_MODULE=config.settings.test`.
- Add `python_files = test_*.py *_tests.py`.
- Add `addopts = -ra --strict-markers --import-mode=importlib`.

The `--import-mode=importlib` recommendation comes directly from pytest good-practices guidance for new projects. `--strict-markers` matters because this phase will likely introduce one or two custom markers and should fail fast on typos.

### 4.2 Django test split

Use three Django test categories:

1. Service-layer tests.
2. API contract tests.
3. Transaction/concurrency tests.

Do not collapse all three into one file.

### 4.3 Runbook creation tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_services.py`

Secondary contract target:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_api_contracts.py`

Core service tests:

- `test_create_runbook_persists_row_and_returns_runbook`
- `test_create_runbook_sets_expected_fields_from_input`
- `test_create_runbook_rejects_duplicate_slug_within_same_organization`
- `test_create_runbook_allows_same_slug_in_different_organizations`
- `test_create_runbook_translates_integrity_error_to_domain_error`

Critical API contract tests:

- `test_post_runbooks_returns_201_with_expected_envelope`
- `test_post_runbooks_returns_validation_error_shape_for_bad_payload`
- `test_post_runbooks_delegates_to_service_instead_of_inline_save_logic`

What these tests should prove:

- the create flow writes the right durable row
- tenant-scoped uniqueness behaves correctly
- validation and domain errors map to a stable API shape
- the endpoint contract is safe for the frontend

### 4.4 Workflow creation service tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_services.py`

Secondary contract target:

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api_contracts.py`

Core service tests:

- `test_create_workflow_from_runbook_creates_version_1_for_first_workflow`
- `test_create_workflow_from_runbook_increments_version_for_subsequent_workflows`
- `test_create_workflow_from_runbook_persists_canonical_definition`
- `test_create_workflow_from_runbook_rejects_missing_runbook`
- `test_create_workflow_from_runbook_does_not_call_ai_inside_db_transaction`
- `test_create_workflow_from_runbook_maps_ai_payload_to_canonical_shape`

Critical API contract tests:

- `test_post_workflows_accepts_runbook_id_only`
- `test_post_workflows_returns_workflow_detail_shape_expected_by_frontend`
- `test_post_workflows_surfaces_ai_or_mapping_failure_as_stable_error_envelope`

High-value assertions:

- workflow version assignment is correct
- persisted definition shape is canonical, not raw AI output
- service owns orchestration
- AI client failures do not create partial workflow rows

### 4.5 Execution creation service tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_services.py`

Secondary contract target:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_api_contracts.py`

Core service tests:

- `test_create_execution_from_published_workflow_creates_execution_and_steps`
- `test_create_execution_copies_workflow_snapshot_into_execution_record`
- `test_create_execution_materializes_steps_in_position_order`
- `test_create_execution_rejects_non_published_workflow`
- `test_create_execution_is_atomic_when_step_materialization_fails`
- `test_create_execution_does_not_mutate_source_workflow_definition`

Critical API contract tests:

- `test_post_executions_accepts_workflow_id_only`
- `test_post_executions_returns_execution_detail_shape_with_nested_steps`
- `test_post_executions_returns_conflict_for_non_published_workflow`

High-value assertions:

- execution creation is aggregate creation, not a single-row write
- snapshot semantics are real
- invalid workflow state is blocked
- partial step creation cannot leak through

### 4.6 Claim-next atomic behavior tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_concurrency.py`

These tests are special. They are not ordinary ORM tests. They exist to prove queue claiming behavior under PostgreSQL semantics.

Mandatory tests:

- `test_claim_next_returns_null_execution_when_queue_is_empty`
- `test_claim_next_claims_oldest_queued_execution_once`
- `test_claim_next_two_concurrent_claims_on_one_execution_yield_one_claim_and_one_empty_result`
- `test_claim_next_two_concurrent_claims_on_two_executions_return_different_execution_ids`
- `test_claim_next_skips_locked_rows_instead_of_blocking`
- `test_claim_next_does_not_claim_non_queued_rows`

Implementation guidance:

- run these against PostgreSQL, not SQLite
- use `@pytest.mark.django_db(transaction=True)`
- keep them isolated from ordinary API tests
- use separate DB connections or threads/processes only where required to exercise locking truthfully

This is the highest-risk area for false confidence. A fake concurrency test that never exercises real transaction semantics is worse than no test.

### 4.7 Execution status transition rule tests

Primary targets:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_runner_api.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_services.py`

Tests to include:

- `test_heartbeat_rejects_wrong_runner_id`
- `test_heartbeat_rejects_wrong_claim_token`
- `test_step_update_allows_pending_to_running`
- `test_step_update_allows_running_to_succeeded`
- `test_step_update_allows_running_to_failed`
- `test_step_update_rejects_pending_to_succeeded_without_running`
- `test_step_update_rejects_terminal_step_transition_back_to_running`
- `test_complete_execution_allows_succeeded_when_all_steps_succeeded`
- `test_complete_execution_rejects_succeeded_when_any_step_failed`
- `test_complete_execution_rejects_failed_without_error_context_if_contract_requires_it`
- `test_complete_execution_rejects_runner_that_does_not_own_execution`

What these tests should prove:

- status transitions are explicit
- ownership rules are enforced
- invalid transitions fail consistently
- the runner-facing contract cannot silently corrupt execution state

### 4.8 Django test order inside the phase

Implement in this exact order:

1. runbook service tests
2. workflow service tests
3. execution service tests
4. execution API contract tests
5. runner-facing status transition tests
6. claim-next concurrency tests

That order ensures the deterministic create logic is locked before the harder transaction work.

## 5. Runner test plan in detail

### 5.1 Runner test stack recommendation

Use `pytest` for the runner as well.

Reason:

- consistent developer workflow with Django tests
- strong fixture support for fake clients, fake clocks, and stub executors
- easy `monkeypatch` use when needed
- good fit for `httpx.MockTransport` or fake client objects

Do not make runner tests container-dependent.

The runner should mostly be tested as pure Python orchestration code with:

- fake API client objects
- fake sleep/time functions
- fake logger/log streamer
- deterministic claimed-execution payloads

### 5.2 Polling loop behavior

Primary target:

- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_poller.py`

Core tests:

- `test_run_forever_sleeps_for_server_poll_after_seconds_when_no_work`
- `test_run_forever_uses_local_fallback_interval_when_server_does_not_send_poll_after_seconds`
- `test_run_forever_calls_executor_once_when_claim_returns_execution`
- `test_run_forever_does_not_poll_again_until_executor_returns`
- `test_run_forever_logs_and_backs_off_after_claim_next_network_error`
- `test_run_forever_does_not_retry_mutating_claim_request_inline`

Key design rule to preserve in tests:

- the poller should be a small loop around `claim_next`, `sleep`, and `executor.run_execution`
- it should not know step-level details

### 5.3 Step status transition tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_executor.py`

Core tests:

- `test_run_execution_marks_each_step_running_then_succeeded_in_order`
- `test_run_execution_stops_after_first_failed_step`
- `test_run_execution_does_not_start_later_steps_after_failure`
- `test_run_execution_sends_failed_step_update_before_execution_completion`
- `test_run_execution_sends_succeeded_completion_when_all_steps_succeed`
- `test_run_execution_sorts_steps_by_position_before_processing`

These tests should assert call order on the fake API client, not just final state.

### 5.4 Failure handling tests

Primary targets:

- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_executor.py`
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_orchestration.py`

Core tests:

- `test_run_execution_marks_execution_failed_when_step_simulation_returns_failure`
- `test_run_execution_includes_error_message_in_failed_completion_payload`
- `test_run_execution_surfaces_step_update_failure_without_claiming_success`
- `test_run_execution_attempts_terminal_failure_completion_when_mid_run_exception_occurs`
- `test_heartbeat_is_stopped_or_not_reused_after_execution_finishes`

Keep these unit-testable by stubbing:

- the step runner
- the heartbeat worker
- the API client
- sleep/timer behavior

Do not require:

- Docker
- subprocesses
- real shell commands
- real artifact upload

### 5.5 API client payload mapping tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_client.py`

Core tests:

- `test_claim_next_maps_success_json_into_claim_response_model`
- `test_claim_next_returns_empty_execution_when_api_returns_null_execution`
- `test_update_step_serializes_request_payload_fields_correctly`
- `test_complete_execution_serializes_terminal_status_and_error_message_correctly`
- `test_client_raises_domain_error_for_non_2xx_response`
- `test_client_wraps_httpx_timeout_as_runner_api_error`
- `test_client_uses_expected_internal_endpoint_paths`

Preferred technique:

- `httpx.MockTransport` for payload/HTTP contract tests
- plain fake `httpx.Client` wrapper only if `MockTransport` is too awkward

### 5.6 Runner tests to explicitly defer

- real container execution
- real filesystem artifact upload
- real streaming log integration
- network retry/backoff timing under actual wall-clock delays
- full `main.py` boot integration beyond one minimal smoke test

## 6. Frontend test plan in detail

### 6.1 Frontend test stack recommendation

Use:

- Vitest
- React Testing Library
- `@testing-library/user-event`
- MSW only where request/response wiring matters

Pattern choice:

- use `jsdom` test environment because Vitest defaults to `node`
- use `userEvent.setup()` per test
- restore/clear mocks after each test
- prefer page/route tests over individual widget tests

### 6.2 Frontend suite size target

Keep the initial frontend suite intentionally small:

- 5 to 8 total tests
- mostly route/page tests
- only one or two shared API/client tests if needed

That is enough for this phase.

### 6.3 Form submission smoke tests

Primary targets:

- `/home/dylan/code/runbook-platform/apps/web/src/routes/runbooks/RunbooksPage.test.tsx`
- `/home/dylan/code/runbook-platform/apps/web/src/routes/workflows/WorkflowCreatePage.test.tsx`
- `/home/dylan/code/runbook-platform/apps/web/src/routes/workflows/WorkflowDetailPage.test.tsx`

Recommended tests:

- `submits_runbook_create_form_and_shows_new_row_or_success_state`
- `shows_validation_error_from_runbook_create_response`
- `submits_generate_workflow_action_and_navigates_to_workflow_detail`
- `submits_create_execution_action_and_navigates_to_execution_detail`

These are smoke tests, not exhaustive form suites.

What to assert:

- the right visible controls exist
- a user can complete the minimum path
- the mutation result causes the expected UI change or navigation
- server validation errors surface to the page

### 6.4 Execution detail rendering tests

Primary target:

- `/home/dylan/code/runbook-platform/apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`

Recommended tests:

- `renders_execution_metadata_and_step_rows_from_api_payload`
- `renders_terminal_failed_state_with_error_message_when_present`
- `renders_runner_metadata_when_claimed_or_running`

High-value assertions:

- execution status is shown
- step rows render in order
- failure context is visible when returned by API
- polling-dependent UI text is not inverted

### 6.5 Loading and error state tests

Primary targets:

- `/home/dylan/code/runbook-platform/apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- optionally `/home/dylan/code/runbook-platform/apps/web/src/shared/ui/AsyncPageBoundary.test.tsx` if a shared boundary is created

Recommended tests:

- `shows_loading_state_while_execution_query_is_pending`
- `shows_error_state_when_execution_query_fails`
- `keeps_last_good_data_visible_when_background_refetch_fails` if that UX is implemented

### 6.6 Mocking strategy for frontend

Use two levels only:

1. MSW for route-level tests that should exercise `fetch`, query hooks, and response handling together.
2. `vi.mock` only for narrow unit-level cases where using MSW would add noise.

Do not:

- mock React Query itself
- assert on internal hook implementation details
- mock every feature API module in every route test

### 6.7 Frontend tests to defer

- snapshot tests
- pixel/layout assertions
- router-library behavior tests
- exhaustive query-cache tests
- end-to-end browser tests
- every possible form validation branch

## 7. Directory and file layout recommendations for tests

### 7.1 Django

```text
/home/dylan/code/runbook-platform/apps/api/
  pytest.ini
  conftest.py
  tests/
    factories.py
    helpers.py
  apps/
    runbooks/
      tests/
        __init__.py
        test_services.py
        test_api_contracts.py
    workflows/
      tests/
        __init__.py
        test_services.py
        test_api_contracts.py
    executions/
      tests/
        __init__.py
        test_services.py
        test_api_contracts.py
        test_runner_api.py
        test_concurrency.py
```

### 7.2 Runner

```text
/home/dylan/code/runbook-platform/apps/runner/
  pytest.ini
  runner/
    tests/
      __init__.py
      conftest.py
      builders.py
      test_client.py
      test_executor.py
      test_poller.py
      test_orchestration.py
```

### 7.3 Frontend

```text
/home/dylan/code/runbook-platform/apps/web/
  vitest.config.ts
  src/
    test/
      setup.ts
      server.ts
      handlers.ts
      render.tsx
      factories.ts
    routes/
      runbooks/
        RunbooksPage.test.tsx
      workflows/
        WorkflowCreatePage.test.tsx
        WorkflowDetailPage.test.tsx
      executions/
        ExecutionDetailPage.test.tsx
```

### 7.4 Layout rules

- Keep shared helpers close to the app root, not duplicated per feature.
- Keep transaction/concurrency tests in their own file.
- Keep runner tests grouped by module responsibility.
- Keep frontend tests alongside the route containers they protect.

## 8. Fixtures / factories / helpers strategy

### 8.1 General rule

Start small. Do not introduce a heavy factory framework in the first batch unless repetition becomes materially painful.

### 8.2 Django strategy

Recommended first choice:

- plain pytest fixtures in `/home/dylan/code/runbook-platform/apps/api/conftest.py`
- small builder functions in `/home/dylan/code/runbook-platform/apps/api/tests/factories.py`

Builder examples to add later:

- `organization_factory(**overrides)`
- `runbook_factory(**overrides)`
- `workflow_factory(**overrides)`
- `published_workflow_factory(**overrides)`
- `execution_factory(**overrides)`
- `execution_step_factory(**overrides)`

Helper examples:

- `workflow_definition_builder(step_count=3, failed_step_index=None)`
- `assert_error_envelope(response, *, status, code)`
- `iso8601(value)` for stable timestamp formatting assertions

Do not start with:

- a giant object graph factory layer
- randomness
- hidden autouse fixtures that create data for most tests

### 8.3 Runner strategy

Use:

- `runner/tests/conftest.py` for fake clients, fake logger, fake sleeper, and test settings
- `runner/tests/builders.py` for `claimed_execution_builder()` and `claimed_step_builder()`

Important helpers:

- `FakeRunnerApiClient`
- `FakeExecutor`
- `FakeLogStreamer`
- `sleep_spy`
- `clock_fixture`

### 8.4 Frontend strategy

Use:

- `src/test/render.tsx` for `renderWithProviders`
- `src/test/handlers.ts` for MSW handlers
- `src/test/factories.ts` for typed payload builders

Useful builders:

- `buildRunbook()`
- `buildWorkflow()`
- `buildExecutionDetail()`
- `buildExecutionStep()`
- `buildValidationErrorResponse()`

### 8.5 Fixture discipline

- default to function-scoped fixtures
- widen scope only when setup is expensive and safe to share
- keep fixtures explicit
- avoid magic implicit state

## 9. Commands to run tests locally and in Docker

### 9.1 Django local commands

Run from `/home/dylan/code/runbook-platform/apps/api` once pytest config exists:

```bash
pytest -q
pytest apps/runbooks/tests/test_services.py -q
pytest apps/workflows/tests/test_services.py -q
pytest apps/executions/tests/test_services.py -q
pytest apps/executions/tests/test_runner_api.py -q
pytest apps/executions/tests/test_concurrency.py -q
```

For transaction-sensitive claim tests:

```bash
pytest apps/executions/tests/test_concurrency.py -q -vv
```

### 9.2 Django Docker commands

After the API image is updated to include dev test dependencies:

```bash
docker compose run --rm api pytest -q
docker compose run --rm api pytest apps/runbooks/tests/test_services.py -q
docker compose run --rm api pytest apps/executions/tests/test_runner_api.py -q
docker compose run --rm api pytest apps/executions/tests/test_concurrency.py -q -vv
```

Important current-repo caveat:

- `/home/dylan/code/runbook-platform/apps/api/Dockerfile` currently installs only `requirements/base.txt`.
- `pytest` and `pytest-django` live in `requirements/dev.txt`.
- Docker-based API test commands will not work until the Dockerfile or test image path is adjusted.

### 9.3 Runner local commands

Run from `/home/dylan/code/runbook-platform/apps/runner` after adding runner pytest support:

```bash
pytest -q
pytest runner/tests/test_client.py -q
pytest runner/tests/test_executor.py -q
pytest runner/tests/test_poller.py -q
```

### 9.4 Runner Docker commands

After runner test dependencies are available in the image:

```bash
docker compose run --rm runner pytest -q
docker compose run --rm runner pytest runner/tests/test_poller.py -q
```

### 9.5 Frontend local commands

Run from `/home/dylan/code/runbook-platform/apps/web` after adding the frontend test stack:

```bash
npm run test
npm run test -- --run
npm run test -- src/routes/executions/ExecutionDetailPage.test.tsx --run
```

If a coverage script is added for local inspection only:

```bash
npm run test:coverage
```

### 9.6 Frontend Docker commands

After web test dependencies and scripts exist:

```bash
docker compose run --rm web npm run test -- --run
docker compose run --rm web npm run test -- src/routes/executions/ExecutionDetailPage.test.tsx --run
```

### 9.7 Useful repository-level verification commands

```bash
cd /home/dylan/code/runbook-platform
git status --short
docker compose ps
```

## 10. Step-by-step implementation checklist

1. Add Django `pytest` configuration and shared fixtures.
2. Add Django builder helpers for organizations, runbooks, workflows, executions, and steps.
3. Implement runbook service tests.
4. Implement workflow service tests.
5. Implement execution service tests.
6. Implement narrow API contract tests for create endpoints.
7. Implement runner-facing execution transition tests.
8. Implement PostgreSQL-backed `claim-next` concurrency tests.
9. Add runner pytest config and core test helpers.
10. Implement runner API client mapping tests.
11. Implement runner executor step-transition and failure-path tests.
12. Implement runner poller tests.
13. Add frontend Vitest configuration, setup file, and `renderWithProviders`.
14. Add MSW setup only if route-level tests need real request interception.
15. Implement form submission smoke tests.
16. Implement execution-detail rendering and loading/error tests.
17. Update Docker and CI paths so the new tests can actually run.
18. Run targeted suites before any full-suite pass.
19. Run the smallest Docker-backed smoke pass for Django concurrency and repo health.
20. Stop when the definition of done is satisfied. Do not pad the suite.

## 11. File-by-file blueprint

### Django config and shared support

- `/home/dylan/code/runbook-platform/apps/api/pytest.ini`
  - configure `DJANGO_SETTINGS_MODULE`
  - strict markers
  - import mode
- `/home/dylan/code/runbook-platform/apps/api/conftest.py`
  - shared fixtures for API client, settings overrides, and common objects
- `/home/dylan/code/runbook-platform/apps/api/tests/factories.py`
  - object builders for repeated domain data
- `/home/dylan/code/runbook-platform/apps/api/tests/helpers.py`
  - error-envelope assertions and workflow-definition helpers

### Runbooks

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_services.py`
  - service tests for runbook creation
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_api_contracts.py`
  - POST contract tests for `/api/v1/runbooks/`

### Workflows

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_services.py`
  - workflow creation orchestration tests
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api_contracts.py`
  - POST contract tests for `/api/v1/workflows/`

### Executions

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_services.py`
  - execution creation service tests
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_api_contracts.py`
  - POST contract tests for `/api/v1/executions/`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_runner_api.py`
  - heartbeat, step-update, and complete transition rule tests
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_concurrency.py`
  - PostgreSQL-backed `claim-next` atomic behavior tests

### Runner

- `/home/dylan/code/runbook-platform/apps/runner/pytest.ini`
  - basic pytest config
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/conftest.py`
  - fake client, fake sleeper, fake logger
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/builders.py`
  - claimed execution and step builders
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_client.py`
  - payload mapping and error handling
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_executor.py`
  - per-step sequencing and failure handling
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_poller.py`
  - polling loop and backoff behavior
- `/home/dylan/code/runbook-platform/apps/runner/runner/tests/test_orchestration.py`
  - a few top-level orchestration tests connecting poller, executor, and client fakes

### Frontend

- `/home/dylan/code/runbook-platform/apps/web/vitest.config.ts`
  - `jsdom` environment
  - setup file registration
- `/home/dylan/code/runbook-platform/apps/web/src/test/setup.ts`
  - Testing Library cleanup, mock reset, MSW lifecycle if used
- `/home/dylan/code/runbook-platform/apps/web/src/test/server.ts`
  - `setupServer(...handlers)` only if MSW is adopted
- `/home/dylan/code/runbook-platform/apps/web/src/test/handlers.ts`
  - API handlers for route tests
- `/home/dylan/code/runbook-platform/apps/web/src/test/render.tsx`
  - providers for router and query client
- `/home/dylan/code/runbook-platform/apps/web/src/test/factories.ts`
  - payload builders for frontend API responses
- `/home/dylan/code/runbook-platform/apps/web/src/routes/runbooks/RunbooksPage.test.tsx`
  - runbook creation smoke tests
- `/home/dylan/code/runbook-platform/apps/web/src/routes/workflows/WorkflowCreatePage.test.tsx`
  - workflow creation smoke tests
- `/home/dylan/code/runbook-platform/apps/web/src/routes/workflows/WorkflowDetailPage.test.tsx`
  - execution creation smoke tests
- `/home/dylan/code/runbook-platform/apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
  - rendering, loading, and error-state tests

## 12. Failure cases and edge cases to include

### Django

- duplicate runbook slug in same organization
- missing runbook on workflow creation
- AI/client mapping failure during workflow creation
- workflow not in `published` state during execution creation
- execution step materialization failure after execution row creation attempt
- empty queue on `claim-next`
- two runners racing for one queued execution
- two runners racing while one row is locked
- wrong runner ID on heartbeat
- wrong claim token on heartbeat or step update
- invalid step transition from pending directly to succeeded if that is disallowed
- execution completion reporting `succeeded` while a step is failed

### Runner

- API returns `execution: null`
- API omits `poll_after_seconds`
- `claim-next` times out
- `update_step` call fails during a run
- step simulation raises an exception
- failure on step 1 should prevent step 2 start
- steps arrive out of order and must be sorted
- terminal completion must be sent exactly once

### Frontend

- create form receives field-level validation errors
- execution detail query is still loading
- execution detail query fails with error envelope
- execution detail shows failed step error message
- create execution action should not appear when workflow is not publishable or not published

## 13. CI-readiness considerations

### 13.1 Minimum CI shape for this phase

Use separate jobs or steps:

1. Django targeted tests
2. Django concurrency tests against PostgreSQL
3. Runner unit tests
4. Frontend smoke tests

### 13.2 Important repository caveats

- API Docker image does not yet install test dependencies.
- Runner image does not yet install pytest.
- Web app does not yet have a test script or test dependencies.

CI work is not just “run tests.” Phase 08 must also make the test environment real.

### 13.3 CI recommendations

- run Django service/API tests first because they deliver the most value per minute
- run `claim-next` concurrency tests in a PostgreSQL-backed job
- keep frontend tests in `--run` mode, not watch mode
- keep runner tests container-free where possible
- fail on unknown pytest markers
- do not introduce a coverage threshold yet

### 13.4 Flake prevention rules

- avoid wall-clock sleeps in tests
- patch sleep/timers instead
- keep concurrency tests few and focused
- do not depend on test execution order
- prefer explicit payload builders to shared mutable fixtures

## 14. Best practices / anti-patterns

### Best practices

- keep service tests at the center of the Django suite
- write API contract tests against the smallest number of critical endpoints
- isolate PostgreSQL locking tests from regular tests
- test runner behavior with fake dependencies and call-order assertions
- keep frontend tests route-level and user-oriented
- reset mocks after each frontend test
- use `userEvent.setup()` per test
- use deterministic builders for payloads and models

### Anti-patterns

- chasing broad coverage for its own sake
- testing Django models for behavior already proven by service tests
- writing `claim-next` tests that never exercise real transaction semantics
- relying on SQLite to prove PostgreSQL locking behavior
- coupling runner tests to Docker or real shell execution
- snapshotting entire frontend pages
- mocking React Query internals
- asserting implementation details instead of visible outcomes or stable call contracts
- adding a large factory framework before the repeated setup justifies it

## 15. Codex batching plan with approval stops

### Batch A: Django pytest scaffolding

Files:

- `apps/api/pytest.ini`
- `apps/api/conftest.py`
- `apps/api/tests/factories.py`
- `apps/api/tests/helpers.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/api
pytest --collect-only -q
```

Approval stop:

- confirm the shared test scaffolding is acceptable before adding app-specific tests

### Batch B: Django high-value service tests

Files:

- `apps/runbooks/tests/test_services.py`
- `apps/workflows/tests/test_services.py`
- `apps/executions/tests/test_services.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/api
pytest apps/runbooks/tests/test_services.py apps/workflows/tests/test_services.py apps/executions/tests/test_services.py -q
```

Approval stop:

- confirm service-level naming, fixture style, and domain assertions before adding API contract tests

### Batch C: Django critical API contracts and transition rules

Files:

- `apps/runbooks/tests/test_api_contracts.py`
- `apps/workflows/tests/test_api_contracts.py`
- `apps/executions/tests/test_api_contracts.py`
- `apps/executions/tests/test_runner_api.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/api
pytest apps/runbooks/tests/test_api_contracts.py apps/workflows/tests/test_api_contracts.py apps/executions/tests/test_api_contracts.py apps/executions/tests/test_runner_api.py -q
```

Approval stop:

- confirm the public and runner-facing contract assertions before the harder concurrency batch

### Batch D: Claim-next PostgreSQL concurrency tests

Files:

- `apps/executions/tests/test_concurrency.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/api
pytest apps/executions/tests/test_concurrency.py -q -vv
```

Docker command:

```bash
cd /home/dylan/code/runbook-platform
docker compose run --rm api pytest apps/executions/tests/test_concurrency.py -q -vv
```

Approval stop:

- require explicit sign-off because this is the highest-risk area and may need Docker/test-image adjustments

### Batch E: Runner unit test scaffolding and tests

Files:

- `apps/runner/pytest.ini`
- `apps/runner/runner/tests/*`

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/runner
pytest runner/tests/test_client.py runner/tests/test_executor.py runner/tests/test_poller.py -q
```

Approval stop:

- confirm the repo wants pytest added to runner before modifying its dependency/install path

### Batch F: Frontend minimal smoke suite

Files:

- `apps/web/vitest.config.ts`
- `apps/web/src/test/*`
- route test files

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run test -- --run
```

Approval stop:

- confirm the team wants Vitest + Testing Library + optional MSW added before changing frontend dev dependencies

### Batch G: Docker and CI wiring

Files:

- Dockerfiles, compose/test scripts, CI workflow files if they exist

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose run --rm api pytest -q
docker compose run --rm runner pytest -q
docker compose run --rm web npm run test -- --run
```

Approval stop:

- require approval before expanding from local-targeted suites into container/CI changes

## 16. Definition of done

Phase 08 is done when all of the following are true:

- Django has a working `pytest` setup with shared fixtures and helper builders.
- Runbook creation, workflow creation, and execution creation each have focused service tests.
- Critical create-endpoint API contracts are covered with a small number of explicit tests.
- Runner-facing execution transition rules are covered.
- `claim-next` atomic behavior is proven with PostgreSQL-backed transaction tests.
- Runner has unit tests for poller behavior, step transitions, failure handling, and client payload mapping.
- Frontend has a minimal smoke suite covering form submission, execution-detail rendering, and loading/error states.
- Test commands are documented and actually runnable locally.
- Docker-backed test commands are either runnable or explicitly unblocked by the same phase work.
- No coverage target has been added just to look complete.
- The suite remains intentionally small, readable, and high-signal.

### Practical stop rule

If the phase has proven:

- service orchestration
- runner/API contracts
- claim-next concurrency truth
- minimal frontend safety

then stop. The goal is targeted confidence, not a test-count milestone.
