# Manual End-to-End Testing Runbook

## 1. Purpose

Use this runbook to manually verify the current Runbook Platform through the browser UI before a release or demo. The runbook is grounded in the current repository implementation:

- React web UI routes in `apps/web/src/app/router.tsx`.
- Django public API routes in `apps/api/config/api_v1_urls.py`.
- Runner behavior in `apps/runner/runner/`.
- AI parsing behavior in `apps/ai/app/`.
- Local stack, migrations, and seed data in `docker-compose.yml`, `Makefile`, `.env.example`, and `apps/api/apps/common/management/commands/seed_dev.py`.
- Backend domain apps under `apps/api/apps/`.
- Existing docs under `docs/`, especially `docs/runbooks/local-development.md`, `docs/runbooks/manual-execution-plane-testing.md`, and architecture docs for frontend/execution flow.
- Existing support scripts, including `scripts/load-test.js`; no browser-oriented manual test script was found beyond the manual runbooks.

Architecture constraints to verify while testing:

- [ ] The browser calls only Django public `/api/v1/...` APIs.
- [ ] The browser never calls FastAPI AI, runner internal APIs, PostgreSQL, or `/api/v1/internal/...`.
- [ ] Django remains authoritative for execution state.
- [ ] Runner state changes appear through Django-backed UI updates.
- [ ] AI workflow parsing is advisory and persisted only by Django.
- [ ] UUID identifiers are used for persisted entities.

## 2. Assumptions and prerequisites

Required local tools:

- [ ] Docker and Docker Compose are installed and running.
- [ ] `make` is available.
- [ ] The repository root is the current working directory.
- [ ] Ports `5173`, `8000`, `8001`, and `5432` are available, or Compose has been adjusted.

Important local environment values:

- `RUNNER_REGISTRATION_TOKEN` is required by the `api` and `runner` services.
- `INTEGRATION_FERNET_KEY` is required to seed or create webhook integrations with encrypted credentials.
- `RUNNER_EXECUTION_MODE=sandboxed` is required for real command execution smoke tests. The default `simulated` mode does not prove real stdout/stderr, timeout, or subprocess failure behavior.
- `AI_USE_LLM_PARSER=false` is the safe local default. With this default, the AI service uses deterministic parsing, not an external LLM.

Copy-paste setup for a fresh `.env`:

```sh
cp .env.example .env
```

Then edit `.env` and set at least:

```sh
RUNNER_REGISTRATION_TOKEN=local-dev-runner-token-change-me
RUNNER_EXECUTION_MODE=sandboxed
RUNNER_SANDBOX_PROVIDER=local_process
RUNNER_SANDBOX_CLEANUP_POLICY=always
```

Optional, but needed for integration creation and seed integration coverage:

```sh
INTEGRATION_FERNET_KEY=<fernet key>
```

To generate a Fernet key where Python and `cryptography` are available:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## 3. Local environment startup

First-time startup:

```sh
make bootstrap
```

Routine startup:

```sh
make up-d
```

Check service status:

```sh
make ps
```

Expected services:

- [ ] Web: `http://localhost:5173`
- [ ] Django API: `http://localhost:8000`
- [ ] AI service: `http://localhost:8001`
- [ ] Runner: background Compose service
- [ ] PostgreSQL and PgBouncer healthy

Useful logs when a browser-visible issue needs confirmation:

```sh
make logs-api
make logs-web
make logs-runner
make logs-ai
```

## 4. Database migration and seed data setup

Apply migrations:

```sh
make migrate
```

Seed local dev data:

```sh
make seed-dev
```

Re-queue only the seeded execution smoke runs:

```sh
make seed-execution-smoke
```

Seeded data that should be visible through the UI:

- [ ] Organization: `Acme Platform Engineering` with slug `acme-platform-eng`.
- [ ] Users: owner, operator, and viewer.
- [ ] Runbooks: `Deploy to Production`, `Database Rollback`, `Incident Response`, `TLS Certificate Renewal`, and `Execution Plane Smoke Tests`.
- [ ] Workflows: published deploy and incident workflows, draft deploy v2 workflow, and six smoke workflows.
- [ ] Executions: succeeded, failed, queued, running, cancelled, timeout, cancellation-pending, approval-waiting, and smoke queued scenarios.
- [ ] Approval request for a running incident execution waiting on a high-risk step.
- [ ] Policy: `High-risk steps require approval`.
- [ ] Artifact: seeded `smoke_test.log` on a succeeded execution.
- [ ] Runner pool: `Default Runner Pool`.
- [ ] Integration: `Seed Generic Webhook`, only if `INTEGRATION_FERNET_KEY` is configured.

Current seed gap:

- [ ] `seed_dev` does not create operation profiles, target connectivity routes, change records, freeze rules, closed changes, evidence bundles, auditor grants, external references, or control coverage records. Those UI areas are implemented, but many flows need existing database state or setup outside the current browser UI.

## 5. Test user / organization setup

Seeded login credentials:

| Email | Password | Role |
| --- | --- | --- |
| `admin@acme.test` | `Admin1234!` | owner |
| `operator@acme.test` | `Operator1!` | operator |
| `viewer@acme.test` | `Viewer1234!` | viewer |

Baseline login check:

- [ ] Open `http://localhost:5173/login`.
- [ ] Sign in as `admin@acme.test`.
- [ ] Confirm the header shows signed-in email and active organization name.
- [ ] Open `/settings`.
- [ ] Confirm name, email, staff flag, active organization, slug, and role.
- [ ] Click `Log out`.
- [ ] Confirm you return to `/login`.

Authorization roles to test:

- [ ] Owner/admin can create organizations, runbooks, policies, freeze rules, integrations, and manage auditor grants where UI exposes controls.
- [ ] Operator can create runbooks/workflows/executions and make operational decisions where allowed.
- [ ] Viewer should be able to view scoped data but should receive UI/API errors for operator-only mutations.

## 6. Manual testing matrix

| Area | Feature / behavior | UI route or page | Preconditions | Manual steps | Expected result | Notes / gaps |
| --- | --- | --- | --- | --- | --- | --- |
| Authentication | Login, refresh session, logout | `/login`, app header | Seed users | Sign in, refresh page, log out | Protected pages load after login; logout clears session | Uses access token plus refresh cookie |
| Settings | Current session and organization display | `/settings` | Logged in | Open Settings | User, staff flag, active org, and role are shown | No UI to switch active organization |
| Organizations | List and create organizations | `/organizations` | Logged in | Create org with name/slug; try duplicate slug | New org appears or field error appears | Creating org does not switch active org in UI |
| Runbooks | Create, list, detail, empty/loading/error states | `/runbooks`, `/runbooks/:runbookId` | Active org | Create runbook; open detail; expand long content | Runbook appears with status and raw content | No UI buttons for mark-ready/archive |
| AI workflow generation | Generate draft workflow from runbook | `/workflows/new?runbookId=...` | Runbook exists; AI service running | Click `Generate workflow` | Draft workflow created, marked needs review | Browser calls Django; Django calls AI |
| AI review gates | Accept or reject AI-generated workflow | `/workflows/:workflowId/review` | Workflow `requires_review=true` | Accept, then publish; repeat with reject on another workflow | Accept clears review flag; reject archives | Review page only reachable for workflow ID |
| Workflows | List, detail, publish, execute, v2 migration | `/workflows`, `/workflows/:workflowId` | Seed workflows | Open draft/published workflows; publish draft; create execution; migrate v1 | Buttons enable/disable by status/review state | Archive/validate APIs exist but no direct UI |
| Executions | List filters | `/executions` | Seed executions | Use All/Queued/Running/Succeeded/Failed/Cancelled filters | Table filters by status | No claimed filter button |
| Execution detail | Steps, policy badges, live updates, audit, artifacts | `/executions/:executionId` | Seed executions | Open examples for each status; expand step details; download artifact | Status, runner, heartbeat, steps, artifacts, audit shown | Cancel API exists but no current UI button |
| SSE/live updates | Stream execution status | `/executions/:executionId` | Active execution; API single worker | Open active execution while runner processes | Banner says `Receiving live updates`; state changes without manual refresh | Falls back to polling after repeated stream failures |
| Runner execution | Runner claims queued work and reports status | `/executions`, `/runners` | Runner registered; smoke queued | Start runner, open smoke execution | UI shows claimed/running/terminal states and runner heartbeat | Real execution requires sandboxed mode |
| Approvals | Approval inbox and decisions | `/approvals` | Pending approval request | Filter pending/all; click `Decide`; approve/reject with name | Request status changes; execution step unblocks or rejects | Approval for change records shares backend model |
| Policies | Policy list and rules | `/policies`, `/policies/:policyId` | Seed policy | Create policy; add/edit/deactivate rules; run approval smoke | Evaluation badges show on execution detail | UI supports risk, step type, time window only; backend has more v2 conditions |
| Audit trail | Execution audit timeline | `/executions/:executionId` | Seed executions | Open execution detail | Audit trail lists events or empty state | General audit API has no standalone UI route |
| Artifacts | Execution artifacts and downloads | `/executions/:executionId` | Seed artifact or smoke stdout/stderr | Open succeeded execution; click Download | File downloads; missing artifacts show empty state | Runner uploads stdout/stderr; arbitrary workspace files not auto-uploaded |
| Integrations | Connections and delivery history | `/integrations`, `/integrations/:integrationId` | `INTEGRATION_FERNET_KEY` for create/seed | Create webhook, view history, deactivate | Credentials masked; active/inactive state updates | PagerDuty model value exists, but UI exposes Slack/generic only |
| Changes | Change dossier list/create/detail | `/changes`, `/changes/new`, `/changes/:changeId` | Operation profiles must exist | Create change from profile; submit; inspect dossier | Draft and lifecycle sections render | No current UI to create operation profiles |
| Emergency changes | Emergency request and retro-review trigger | `/changes/new/emergency` | Emergency-enabled operation profile | Create emergency change | Change marked `EMERGENCY`; retro-review required later | Needs pre-existing operation profile |
| Change windows | Set/edit execution window | `/changes/:changeId` | Draft/pending/approved/scheduled change | Click Set/Edit window | Window saved; may invalidate approval for approved/scheduled | Requires existing change |
| Dispatch/preflight | Preflight and dispatch | `/changes/:changeId` | Approved/scheduled change; routes/runners | Run preflight, inspect checks, dispatch | Eligible change can dispatch to execution | Needs operation profile and route data |
| Exceptions | Request exception | `/changes/:changeId` | Existing change | Request exception with type/scope/expiry | Exception appears pending | Approve/reject exception APIs exist but no visible buttons in current component |
| Breakglass | Activate and view breakglass session | `/changes/:changeId` | Existing dispatchable/running change | Activate with reason/scope/confirmation | Active session panel, countdown, review status shown | End/heartbeat APIs exist; no visible end button |
| Verification | Manual attestation and close | `/changes/:changeId` | Change in verification state | Attest pending manual check; close verified/failed change | Verification counts and closure status update | Requires change lifecycle setup |
| Evidence bundles | Compile, seal, export, legal hold | `/changes/:changeId` | Closed change | Create bundle, seal if complete, export, place hold | Bundle status, hashes, manifest, export download shown | Only appears for closed changes |
| Freeze rules | Create/list/deactivate | `/freeze-rules` | Owner/admin | Create active rule; filter; deactivate | Rule appears and affects preflight | No direct UI to approve freeze exceptions |
| Runners | Pools, runners, routes | `/runners`, `/runners/pools/:poolId`, `/runners/runners/:runnerId`, `/runners/routes` | Runner pool/runner/route data | Inspect status/capacity; drain/disable/reactivate; route deactivate/reactivate | State and capacity update | UI cannot create pools, runner tokens, runners, or routes |
| Auditor workspace | Audit search/detail/access grants | `/audit/changes`, `/audit/changes/:changeId`, `/audit/access` | Change/evidence/auditor data | Filter search; open detail; create/revoke grant | Read-only evidence and grants render | Service catalog/control mapping/external reference APIs have no standalone UI create forms |

## 7. Full happy-path E2E test

This is the strongest current browser-first path that is fully supported by seed data and the existing UI.

### Setup

- [ ] Ensure `.env` has `RUNNER_REGISTRATION_TOKEN` set.
- [ ] For real execution, ensure `.env` has `RUNNER_EXECUTION_MODE=sandboxed`.
- [ ] Start services:

```sh
make up-d
make migrate
make seed-dev
docker compose restart runner
```

### Browser flow

- [ ] Open `http://localhost:5173`.
- [ ] Log in as `admin@acme.test`.
- [ ] Open `/runbooks`.
- [ ] Confirm `Execution Plane Smoke Tests` exists.
- [ ] Open `Execution Plane Smoke Tests`.
- [ ] Open the workflow `sandbox-success-release-check`.
- [ ] Confirm workflow status is `published`.
- [ ] Click `Create execution`.
- [ ] Confirm browser navigates to `/executions/:executionId`.
- [ ] Confirm execution initially shows `queued` or `claimed`.
- [ ] Watch the detail page while the runner processes the execution.
- [ ] Confirm live update banner says `Receiving live updates` or fallback banner says `Polling for updates (streaming unavailable)`.
- [ ] Expand each step with `Details`.
- [ ] Confirm step statuses progress to `succeeded`.
- [ ] Confirm runner, claimed time, heartbeat, sandbox provider, and timestamps are shown.
- [ ] Confirm final execution status is `succeeded`.
- [ ] Confirm the `Artifacts` section contains stdout artifacts after real sandbox execution.
- [ ] Download at least one artifact.
- [ ] Confirm the `Audit trail` section includes execution creation/status events.
- [ ] Open `/runners`.
- [ ] Confirm runner pool capacity/active runner data reflects the runner.

### Expected final state

- [ ] Execution status is `succeeded`.
- [ ] All steps are `succeeded`.
- [ ] `started_at`, `finished_at`, `claimed_by_runner_id`, `claimed_at`, and `last_heartbeat_at` are populated.
- [ ] Artifacts are downloadable if the runner produced stdout/stderr.
- [ ] No browser requests are made to AI, runner internal APIs, or internal Django routes.

## 8. Feature-by-feature manual test procedures

### Authentication and session

Route: `/login`, protected app shell.

Steps:

- [ ] Open `/runbooks` while logged out.
- [ ] Confirm redirect to `/login`.
- [ ] Submit with empty fields and confirm browser required-field validation.
- [ ] Submit invalid credentials and confirm an error banner.
- [ ] Submit valid credentials for `admin@acme.test`.
- [ ] Refresh the browser.
- [ ] Confirm the session is restored.
- [ ] Click `Log out`.

Expected:

- [ ] Protected routes require authentication.
- [ ] Header shows signed-in email after login.
- [ ] Logout clears local auth state and returns to login.

Release evidence:

- [ ] Screenshot login form, logged-in header, and logout redirect.

### Organizations

Route: `/organizations`.

Steps:

- [ ] Confirm seeded org appears.
- [ ] Create an organization with a unique name and slug.
- [ ] Try creating another org with the same slug.
- [ ] Click `View runbooks` for an organization.

Expected:

- [ ] Unique org appears in list.
- [ ] Duplicate slug shows an API field or banner error.
- [ ] `View runbooks` navigates to `/runbooks`.

Gaps:

- [ ] No current web UI path to switch the active organization after creating a second organization. Verify indirectly through Settings and organization-scoped lists, or defer manual UI testing.

### Runbooks

Routes: `/runbooks`, `/runbooks/:runbookId`.

Steps:

- [ ] Create a runbook with title, slug, and numbered raw content.
- [ ] Confirm it appears in the list with status pill.
- [ ] Open detail page.
- [ ] Confirm status, created time, slug, and raw content.
- [ ] Use a long raw content value and verify `Show more` / `Show less`.
- [ ] Click `Generate workflow (AI)`.

Expected:

- [ ] New runbook is created as a draft.
- [ ] Detail page displays raw content and workflow list.
- [ ] Empty state reads `No workflows yet. Generate one from this runbook.` when applicable.

Failure cases:

- [ ] Empty title or slug triggers required-field validation.
- [ ] Duplicate slug shows a field error.

Gaps:

- [ ] No current web UI path for runbook `mark-ready` or `archive` API actions.

### AI workflow generation and review

Routes: `/workflows/new?runbookId=...`, `/workflows/:workflowId`, `/workflows/:workflowId/review`.

Steps:

- [ ] From a runbook detail page, click `Generate workflow (AI)`.
- [ ] Confirm the page shows runbook title, status, raw content, and `Generate workflow`.
- [ ] Click `Generate workflow`.
- [ ] Confirm navigation to workflow detail.
- [ ] Confirm warning: `AI-generated workflow requires review before it can be published or executed.`
- [ ] Confirm `Review now` is visible.
- [ ] Confirm `Publish workflow` and `Create execution` are disabled while review is required.
- [ ] Open `Review now`.
- [ ] Confirm generated steps are visible.
- [ ] Click `Accept workflow`.
- [ ] Confirm workflow detail no longer shows the review warning.
- [ ] Click `Publish workflow`.

Expected:

- [ ] Workflow is created as draft, `parse_source=ai_parse`, and `requires_review=true`.
- [ ] Accepting review clears the review gate.
- [ ] Publishing transitions draft to `published`.

Failure cases:

- [ ] Stop AI service with `make stop-ai`, then try generating a workflow.
- [ ] Expected result: Django returns an external dependency error shown as an error banner.
- [ ] Restart AI with `make start-ai`.

Notes:

- With `AI_USE_LLM_PARSER=false`, FastAPI uses deterministic parsing. Numbered lines become manual task steps. If no numbered steps are found, default steps are returned.
- Browser should still call only Django `/api/v1/workflows/`; Django calls FastAPI internally.

### Workflows

Routes: `/workflows`, `/workflows/:workflowId`.

Steps:

- [ ] Open `/workflows`.
- [ ] Confirm workflows sort by creation time and show version, status, created date, running pill, and needs-review pill where applicable.
- [ ] Open a published workflow.
- [ ] Confirm `Create execution` is enabled.
- [ ] Open a draft workflow.
- [ ] Confirm `Publish workflow` is visible.
- [ ] Open a v1 workflow and click `Migrate to v2`.
- [ ] Confirm navigation to a new draft v2 workflow detail.
- [ ] Confirm v2 detail can show catalog, validation status, declared secrets, retry, idempotency, dry-run, action type, and artifacts where present.

Expected:

- [ ] Published workflows can start executions.
- [ ] Draft workflows can be published unless they require review.
- [ ] V1 workflows expose `Migrate to v2`.

Failure cases:

- [ ] Try `Create execution` on draft or review-required workflows. Button should be disabled.
- [ ] Try publishing invalid v2 workflow if such data exists. Expected API error banner.

Gaps:

- [ ] No current web UI path for workflow archive.
- [ ] No current web UI path for standalone workflow definition validation.

### Executions and execution detail

Routes: `/executions`, `/executions/:executionId`.

Steps:

- [ ] Open `/executions`.
- [ ] Test filters: `All`, `Queued`, `Running`, `Succeeded`, `Failed`, `Cancelled`.
- [ ] Open one seeded execution for each visible status.
- [ ] Confirm detail grid shows status, workflow version, started, finished, runner, claimed, and last heartbeat.
- [ ] Expand step details.
- [ ] Confirm step key, link to workflow command, timestamps, result metadata, sandbox provider/run ID, exit code, and status.
- [ ] Open the seeded timeout failure and confirm `Step timed out.`
- [ ] Open the seeded cancelled mid-run execution and confirm `Step was cancelled.`
- [ ] Open the seeded policy-blocked or policy-evaluated execution if available and confirm policy badges.
- [ ] Confirm artifact empty state or artifacts list.
- [ ] Confirm audit trail empty state or event list.

Expected:

- [ ] Execution statuses shown: `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`.
- [ ] Step statuses shown: `pending`, `waiting_for_approval`, `running`, `succeeded`, `failed`, `skipped`, `cancelled`.
- [ ] Active executions attempt SSE and fall back to polling after repeated failures.

Failure cases:

- [ ] Stop runner with `make stop-runner`, create an execution from a published workflow, and confirm it remains queued.
- [ ] Restart runner with `make start-runner` and confirm execution progresses.

Gaps:

- [ ] Execution cancellation is implemented in Django and runner heartbeat behavior, and the UI displays cancellation-requested/cancelled states. No current web UI path exposes a `Cancel` button. Verify indirectly through seeded cancellation examples or defer manual UI testing.

### Approvals

Route: `/approvals`.

Steps:

- [ ] Open `/approvals`.
- [ ] Confirm default status filter is pending.
- [ ] Open a pending seeded approval.
- [ ] Click `Decide`.
- [ ] Choose `Approve`.
- [ ] Enter `Your name`.
- [ ] Optionally enter notes.
- [ ] Submit.
- [ ] Switch filter to `Approved` or `All`.
- [ ] Confirm decision details are shown.
- [ ] Repeat on a fresh pending approval and choose `Reject`.

Expected:

- [ ] Pending approval status changes to approved or rejected.
- [ ] Execution detail for waiting step reflects the decision once runner observes it.
- [ ] Actor display name and notes are visible on approval rows.

Failure cases:

- [ ] Submit without `Your name`; browser required-field validation blocks submission.
- [ ] Try deciding an already decided approval; expect API error or no pending `Decide` control.

### Policies

Routes: `/policies`, `/policies/:policyId`.

Steps:

- [ ] Open `/policies`.
- [ ] Filter all/active/inactive.
- [ ] Create a policy.
- [ ] Open `Manage rules`.
- [ ] Add rule with condition `Risk level`, operator `in`, values `high, critical`, outcome `Approval Required`.
- [ ] Add rule with condition `Step type`, value `manual_task`, outcome `Auto Approve`.
- [ ] Add a `Time window` rule with timezone, weekdays, start/end, match when inside/outside.
- [ ] Edit a rule.
- [ ] Deactivate a rule.
- [ ] Deactivate and reactivate the policy.
- [ ] Run a smoke approval workflow and inspect policy evaluation badges on execution detail.

Expected:

- [ ] Rule count updates.
- [ ] Policy active/inactive pill updates.
- [ ] Execution step detail shows policy decision, rule name, policy name, reason, and effective outcome when evaluations exist.

Failure cases:

- [ ] Duplicate priority or duplicate rule name should show API error.
- [ ] Empty required fields should be blocked by browser validation.

Gaps:

- [ ] Backend supports additional v2 policy condition types (`action_type`, `action_version`, `execution_mode`, `idempotency_mode`, `mutates_target`), but current policy detail UI exposes only risk level, step type, and time window.

### Integrations

Routes: `/integrations`, `/integrations/:integrationId`.

Steps:

- [ ] Ensure `INTEGRATION_FERNET_KEY` is configured and API restarted.
- [ ] Open `/integrations`.
- [ ] Click `Create integration`.
- [ ] Create a Slack webhook or generic webhook with a safe local/test URL.
- [ ] Leave event types blank and confirm UI treats that as all events.
- [ ] Create another integration with event types such as `execution.finished, artifact.uploaded`.
- [ ] Open `View history`.
- [ ] Confirm credentials are masked and delivery history empty state or attempts are shown.
- [ ] Deactivate an integration.

Expected:

- [ ] Created integration appears active.
- [ ] Credentials show as configured/masked.
- [ ] Deactivation disables the row action and changes status.

Failure cases:

- [ ] Invalid or empty webhook URL is blocked by browser or API validation.
- [ ] Missing `INTEGRATION_FERNET_KEY` should cause create/seed failures surfaced as errors.

Gaps:

- [ ] Backend model includes `pagerduty`, but current UI exposes only Slack webhook and generic webhook.

### Runners, pools, and target routes

Routes: `/runners`, `/runners/pools/:poolId`, `/runners/runners/:runnerId`, `/runners/routes`.

Steps:

- [ ] Open `/runners`.
- [ ] Confirm seeded `Default Runner Pool` appears.
- [ ] Confirm status, key, environment, network zone, max concurrent, active runners, active executions, and capacity.
- [ ] Open pool detail.
- [ ] Confirm pool metadata and runners table.
- [ ] Open runner detail when a runner is registered.
- [ ] Confirm heartbeat badge (`OFFLINE`, `STALE`, or recent time), version, hostname, last seen, active executions.
- [ ] Drain a pool, confirm warning/confirmation, then reactivate.
- [ ] Disable a pool, confirm state, then reactivate.
- [ ] Drain/disable/revoke a runner where appropriate.
- [ ] Open `/runners/routes`.
- [ ] Deactivate/reactivate a target connectivity route if route data exists.

Expected:

- [ ] Runner heartbeat changes are visible without direct runner API calls.
- [ ] Pool capacity reflects active executions.
- [ ] Drain/disable/reactivate actions show updated status.

Failure cases:

- [ ] Stop runner and confirm runner heartbeat eventually becomes stale/offline.
- [ ] Disable pool and confirm dispatch eligibility reports ineligible where change route data exists.

Gaps:

- [ ] No current web UI path to create runner pools, runner registration tokens, runners, or target connectivity routes. Verify existing route behavior indirectly through seeded/pregenerated data, runner registration, and change dispatch eligibility, or defer manual UI testing.

### Changes, dispatch, verification, and closure

Routes: `/changes`, `/changes/new`, `/changes/new/emergency`, `/changes/:changeId`.

Preconditions:

- Operation profiles must already exist.
- Operation profiles must allow workflows.
- For dispatch, target connectivity routes and an eligible runner must exist.

Steps:

- [ ] Open `/changes`.
- [ ] Confirm list or empty state.
- [ ] Click `New Change Request`.
- [ ] Select operation profile.
- [ ] Select allowed workflow.
- [ ] Enter title, summary, justification.
- [ ] Enter valid requested inputs JSON.
- [ ] Add one or more production targets.
- [ ] Submit `Create Change`.
- [ ] On detail page, confirm overview, targets, status, hashes, and timestamps.
- [ ] Click `Submit for Approval`.
- [ ] Use `/approvals` to approve or reject if an approval request is created.
- [ ] Set or edit execution window while status allows it.
- [ ] Run preflight for approved/scheduled change.
- [ ] Confirm checks for approved status, policy, window, freeze conflicts, target locks, and actor authorization.
- [ ] Confirm runner availability panel.
- [ ] Dispatch when preflight is fresh and passed.
- [ ] Confirm execution binding links to `/executions/:executionId`.
- [ ] If verification is pending, submit manual attestation for manual checks.
- [ ] Close verified or failed changes with outcome, summary, and optional reviewer.

Expected:

- [ ] Status progresses through implemented lifecycle states according to backend gates.
- [ ] Dossier sections appear only when relevant.
- [ ] Dispatch creates/binds an execution and runner updates are reflected.

Failure cases:

- [ ] Invalid requested inputs JSON shows `Invalid JSON in requested inputs.`
- [ ] Duplicate targets show a local duplicate target error.
- [ ] Missing required fields are blocked by browser validation.
- [ ] Preflight fails when window is closed, runner route is missing, freeze rule blocks, or target locks exist.

Gaps:

- [ ] No current web UI path to create operation profiles, which blocks this browser-only flow in a freshly seeded database.
- [ ] No current web UI path to create target connectivity routes.
- [ ] Change exception approve/reject/resolve APIs exist, but current change detail UI exposes request/list only.

### Emergency, exceptions, breakglass, and retro reviews

Routes: `/changes/new/emergency`, `/changes/:changeId`, `/retro-reviews`.

Steps:

- [ ] Open `/changes/new/emergency`.
- [ ] Confirm only emergency-enabled operation profiles are listed.
- [ ] Enter emergency reason, profile, workflow, title, justification, requested inputs, and production targets.
- [ ] Create emergency change.
- [ ] On change detail, confirm `EMERGENCY` pill and emergency reason.
- [ ] On a change detail page, request exceptions for each exposed type: freeze override, window overrun, late verification, policy override, missing artifact.
- [ ] Activate breakglass, entering reason, expiry, scope fields, and confirmation checkbox.
- [ ] Confirm active breakglass panel shows status, countdown, review due, review status, reason, and scope hash.
- [ ] Open `/retro-reviews`.
- [ ] Confirm pending/overdue review sections.
- [ ] Open a change with pending retro review and submit review disposition.

Expected:

- [ ] Emergency/breakglass actions create mandatory retro-review records.
- [ ] Self-review protection errors are surfaced as `Self-review blocked: ...`.
- [ ] Violation banner appears for overdue reviews, missing artifact exceptions, control failures, or overdue breakglass review status.

Failure cases:

- [ ] Try breakglass activation without confirmation checkbox; browser blocks or API rejects.
- [ ] Try retro review without disposition/summary; submit button disabled or browser validation applies.

Gaps:

- [ ] No current web UI path to end an active breakglass session.
- [ ] No current web UI path to approve/reject exception requests.

### Freeze rules

Route: `/freeze-rules`.

Steps:

- [ ] Log in as owner/admin.
- [ ] Open `/freeze-rules`.
- [ ] Create a blocking rule for all production with current time window.
- [ ] Create an allow-with-exception rule requiring exception reference.
- [ ] Filter active/inactive/all.
- [ ] Deactivate a rule.
- [ ] Run change preflight against a matching target where change data exists.

Expected:

- [ ] Rule appears with behavior, scope, time range, and active state.
- [ ] Blocking freeze causes preflight conflict.
- [ ] Allow-with-exception requires appropriate exception data before dispatch.

Failure cases:

- [ ] Create rule with missing name/start/end; browser validation blocks.
- [ ] Use end before start; API should reject and show error.

### Evidence bundles

Route: `/changes/:changeId`, Evidence Bundle section.

Precondition: change status is `closed`.

Steps:

- [ ] Open a closed change.
- [ ] Confirm Evidence Bundle section appears.
- [ ] Click `Create evidence bundle`.
- [ ] Review completeness status and checklist.
- [ ] If complete, click `Seal bundle`.
- [ ] Confirm sealed pill, manifest hash, content hash, and package size.
- [ ] Click `View manifest`.
- [ ] Click `Create export`.
- [ ] Create export with blank redaction policy.
- [ ] Download ZIP when ready.
- [ ] Place legal hold with required reason and optional external reference.

Expected:

- [ ] Compiling bundle shows completeness report.
- [ ] Seal is disabled until completeness is `complete`.
- [ ] Sealed bundles show immutable manifest metadata.
- [ ] Exports include hashes/receipt metadata.
- [ ] Legal hold shows `HOLD ACTIVE`.

Failure cases:

- [ ] Try to seal incomplete bundle; button disabled and tooltip explains why.
- [ ] Try legal hold without reason; browser validation blocks.

Gaps:

- [ ] No current web UI path to invalidate a bundle.
- [ ] No current web UI path to release a legal hold.

### Auditor workspace

Routes: `/audit/changes`, `/audit/changes/:changeId`, `/audit/access`.

Steps:

- [ ] Open `/audit/changes`.
- [ ] Apply filters for service, target, risk, status, change type, bundle status, control ID, coverage status, external system, approver, executor, exception, dates, ordering, and limit.
- [ ] Confirm no-results state or result table.
- [ ] Open an audit change detail.
- [ ] Confirm summary, targets/service context, control coverage summary, coverage details, external reference snapshots, and audit metadata.
- [ ] Open `/audit/access`.
- [ ] As owner/admin, create access grant with user ID, reason, optional dates, and valid scope JSON.
- [ ] Revoke an active grant.

Expected:

- [ ] Audit search is read-only.
- [ ] Detail page displays persisted evidence metadata and coverage when available.
- [ ] Access grants can be created/revoked by owner/admin.

Failure cases:

- [ ] Invalid scope JSON shows `Scope must be valid JSON.`
- [ ] Non-admin users see warning and no grant creation form.

Gaps:

- [ ] Backend APIs for service catalog, control mapping profiles, external reference creation/refresh, and coverage recompute exist, but there is no standalone web UI for managing those records. Verify indirectly through audit detail if records already exist, or defer manual UI testing.

## 9. Negative/error-path test procedures

Run these as a focused pass after the happy path:

- [ ] Empty required fields: login, organization, runbook, policy, integration, change, emergency change, freeze rule, approval decision, legal hold, retro review.
- [ ] Invalid JSON: requested inputs on standard/emergency change, auditor access scope.
- [ ] Duplicate entities: organization slug, runbook slug, policy rule priority/name, duplicate change target.
- [ ] AI unavailable: `make stop-ai`, then generate workflow; expect error banner; `make start-ai`.
- [ ] Runner unavailable: `make stop-runner`, create execution; expect queued state; restart runner and confirm progression.
- [ ] Execution failure: run `sandbox-failure-diagnostics`; expect failed execution, failed step, skipped later step, stderr artifact.
- [ ] Timeout: run `sandbox-timeout-check`; expect timed-out banner and `failure_kind=timeout`.
- [ ] Approval rejection: reject a pending approval; expect approval status rejected and execution/step failure or blocked progress.
- [ ] Policy block: create active block rule matching a step, execute matching workflow, expect blocked policy badge and failed/skipped behavior if runner evaluates it.
- [ ] Integration delivery failure: configure unreachable webhook and trigger an event; expect failed delivery history when delivery attempt is recorded.
- [ ] Unauthorized/wrong role: log in as viewer and attempt create/update/delete style actions; expect disabled controls or API error banners.
- [ ] Wrong organization access: no current active-organization switch UI. Defer browser-only testing or verify indirectly with a user whose active membership differs.
- [ ] SSE failure: stop/restart API while active execution detail is open; expect fallback to polling after repeated failures.

## 10. Runner/execution behavior verification through UI

Use the seeded smoke workflows from `Execution Plane Smoke Tests`.

Checklist:

- [ ] `sandbox-success-release-check`: all steps succeed, stdout artifacts downloadable.
- [ ] `sandbox-failure-diagnostics`: second step fails with exit code 1, later step skipped, execution failed.
- [ ] `sandbox-timeout-check`: timeout step fails with timed-out banner and `failure_kind=timeout`.
- [ ] `sandbox-generated-artifacts`: stdout shows generated file list and checks; note that generated workspace files are not separate artifacts.
- [ ] `sandbox-cancellation-long-running`: No current web UI path to cancel. Verify indirectly through seeded cancellation examples or defer manual UI testing.
- [ ] `sandbox-policy-approval-gate`: high-risk step waits for approval; approve in `/approvals`; runner continues.

Runner UI checks:

- [ ] `/runners` shows pool status and capacity.
- [ ] `/runners/pools/:poolId` shows active runners and active execution count.
- [ ] `/runners/runners/:runnerId` shows recent heartbeat while runner is online.
- [ ] Stop runner; heartbeat becomes stale/offline.
- [ ] Restart runner; heartbeat recovers.

## 11. AI parsing/workflow generation verification through UI

Primary UI path:

- [ ] Create runbook with numbered steps.
- [ ] Generate workflow from runbook detail.
- [ ] Confirm draft workflow with review required.
- [ ] Review generated steps.
- [ ] Accept review.
- [ ] Publish workflow.
- [ ] Create execution from published workflow.

Expected deterministic parser behavior when `AI_USE_LLM_PARSER=false`:

- [ ] Numbered lines become steps.
- [ ] Step names reflect numbered line content.
- [ ] No direct browser call to `http://localhost:8001`.
- [ ] AI failures are surfaced through Django workflow creation errors.

Optional LLM mode:

- [ ] Set `OPENAI_API_KEY`, `AI_PARSE_MODEL`, and `AI_USE_LLM_PARSER=true`.
- [ ] Restart AI and API.
- [ ] Generate workflow from safe test content only.
- [ ] Confirm review-required gate still applies before publish/execute.

## 12. Approvals/manual gates verification, if implemented

Implemented UI:

- [ ] `/approvals` inbox.
- [ ] Execution step approval requests.
- [ ] Change approval request display and link to approvals.
- [ ] Workflow AI review accept/reject.
- [ ] Manual verification attestation on change detail.

Manual checks:

- [ ] Approve and reject execution step approvals.
- [ ] Confirm waiting step banner on execution detail.
- [ ] Confirm policy high-risk approval floor is visible when applicable.
- [ ] Confirm change approval request appears in change detail when change is submitted and backend creates one.

## 13. Policies verification, if implemented

Implemented UI:

- [ ] Policy create/list/activate/deactivate.
- [ ] Rule create/edit/deactivate.
- [ ] Execution policy evaluation badges.
- [ ] Change policy decision display.

Manual checks:

- [ ] Create approval-required, auto-approve, and block rules.
- [ ] Run matching workflows.
- [ ] Confirm expected approval/block/auto behavior through execution detail.
- [ ] Confirm policy decisions appear on change detail if change policy evaluation exists.

## 14. Audit trail verification, if implemented

Implemented UI:

- [ ] Execution audit trail on `/executions/:executionId`.
- [ ] Auditor read-only change workspace on `/audit/changes`.

Manual checks:

- [ ] Create/publish workflow and create execution.
- [ ] Open execution detail and inspect audit events.
- [ ] Approve/reject approval and confirm audit event appears if emitted.
- [ ] Open audit search/detail for changes where data exists.

Gaps:

- [ ] No standalone general audit-event browser page. Verify execution audit through execution detail or defer manual UI testing.

## 15. Artifacts verification, if implemented

Implemented UI:

- [ ] Execution artifact list/download on execution detail.
- [ ] Evidence bundle export download on closed change detail.

Manual checks:

- [ ] Open seeded succeeded execution and download `smoke_test.log`.
- [ ] Run sandbox success/failure smoke workflows and download stdout/stderr artifacts.
- [ ] Confirm empty state on executions with no artifacts.
- [ ] For closed changes, create/seal/export evidence bundle and download ZIP.

Known limitation:

- [ ] Runner captures stdout/stderr artifacts. It does not currently auto-upload arbitrary generated workspace files as separate artifacts.

## 16. Integrations verification, if implemented

Implemented UI:

- [ ] Integration create/list/deactivate.
- [ ] Integration delivery history.

Manual checks:

- [ ] Create Slack/generic webhook integration.
- [ ] Trigger execution events.
- [ ] Open integration detail and inspect delivery attempts.
- [ ] Deactivate integration and confirm no new deliveries should be attempted for it.

Gaps:

- [ ] No UI to manually retry delivery attempts.
- [ ] No UI for PagerDuty integration type.

## 17. Authentication/authorization verification, if implemented

Implemented UI/API:

- [ ] Login, refresh, logout, current user.
- [ ] Protected routes.
- [ ] Organization membership roles.
- [ ] Owner/admin checks for freeze rules and auditor grants.
- [ ] Operator checks for runbook/workflow/execution style mutations.

Manual checks:

- [ ] Logged-out access redirects to `/login`.
- [ ] Viewer can view but cannot perform operator/admin mutations.
- [ ] Owner/admin sees create controls where role-gated controls exist.
- [ ] Non-admin sees warning on `/audit/access`.

Gaps:

- [ ] No signup UI.
- [ ] No password reset UI.
- [ ] No active organization switch UI.
- [ ] No membership management UI.

## 18. Change/evidence/auditor features verification, if implemented

Implemented UI areas:

- [ ] Change list/create/detail.
- [ ] Emergency change creation.
- [ ] Window edit.
- [ ] Preflight and dispatch.
- [ ] Runner eligibility panel.
- [ ] Exception request/list.
- [ ] Breakglass activation/status.
- [ ] Retro-review inbox and submission.
- [ ] Verification attestation and closure.
- [ ] Evidence bundle compile/seal/export/legal hold.
- [ ] Auditor search/detail/access grants.

Manual checks:

- [ ] Use a prepared database with operation profiles, routes, and changes.
- [ ] Walk a change from draft to approval to dispatch to execution to verification to closure.
- [ ] Create evidence bundle after closure.
- [ ] Search the closed change from auditor workspace.
- [ ] Confirm evidence hashes and bundle metadata match between change detail and auditor detail.

Important gap:

- [ ] Current seed data does not create the operation profile and route prerequisites needed to complete this entire flow from a fresh browser-only state.

## 19. Reset/retest procedure

Fast execution smoke reset:

```sh
make seed-execution-smoke
docker compose restart runner
```

Full local reseed:

```sh
make seed-dev
docker compose restart runner
```

Full destructive reset:

```sh
make reset
```

Post-reset smoke checks:

- [ ] Log in as `admin@acme.test`.
- [ ] Confirm seeded org appears in header.
- [ ] Confirm runbooks, workflows, executions, approvals, policies, runners exist.
- [ ] Confirm runner re-registers and heartbeats after restart.

## 20. Known gaps and features without UI coverage

Use this exact label for release signoff notes where applicable:

- No current web UI path — verify indirectly through runbook status pills on seeded data or defer manual UI testing for runbook mark-ready/archive APIs.
- No current web UI path — verify indirectly through draft/publish/migrate workflow states or defer manual UI testing for workflow archive and standalone workflow validation APIs.
- No current web UI path — verify indirectly through seeded cancellation states or defer manual UI testing for execution cancellation action.
- No current web UI path — verify indirectly through Settings and scoped data or defer manual UI testing for active organization switching.
- No current web UI path — verify indirectly through seeded users/roles or defer manual UI testing for membership management.
- No current web UI path — verify indirectly through the change create page when operation profiles already exist or defer manual UI testing for operation profile creation/management.
- No current web UI path — verify indirectly through seeded/registered runner data and route list behavior or defer manual UI testing for runner pool creation, registration token creation, runner creation, and target connectivity route creation.
- No current web UI path — verify indirectly through exception request/list on change detail or defer manual UI testing for exception approve/reject/resolve controls.
- No current web UI path — verify indirectly through active breakglass status panel and retro-review requirement or defer manual UI testing for breakglass end action.
- No current web UI path — verify indirectly through evidence create/seal/export/place hold or defer manual UI testing for evidence bundle invalidation or legal hold release.
- No current web UI path — verify indirectly through auditor detail when records exist or defer manual UI testing for service catalog, control mapping profile, external reference creation/refresh, and control coverage recompute.
- No current web UI path — verify indirectly through the execution audit panel or defer manual UI testing for a generic audit-event list outside execution detail.
- No current web UI path — verify indirectly through Slack/generic webhook UI or defer manual UI testing for PagerDuty integration creation.

Seed/setup gaps:

- [ ] `seed_dev` is strong for runbook/workflow/execution/approval/policy/artifact/runner smoke testing.
- [ ] `seed_dev` is incomplete for full change/evidence/auditor UAT because it does not seed operation profiles, target routes, changes, closed changes, evidence bundles, external references, coverage records, or auditor grants.

## 21. Final release-readiness checklist

Before signoff:

- [ ] Local stack starts with `make up-d`.
- [ ] Migrations apply with `make migrate`.
- [ ] Seed completes with `make seed-dev`.
- [ ] Web UI loads at `http://localhost:5173`.
- [ ] Login/logout/session refresh pass.
- [ ] Every route in `apps/web/src/app/router.tsx` has been opened at least once:
  - [ ] `/login`
  - [ ] `/organizations`
  - [ ] `/runbooks`
  - [ ] `/runbooks/:runbookId`
  - [ ] `/workflows`
  - [ ] `/workflows/new?runbookId=...`
  - [ ] `/workflows/:workflowId`
  - [ ] `/workflows/:workflowId/review`
  - [ ] `/executions`
  - [ ] `/executions/:executionId`
  - [ ] `/approvals`
  - [ ] `/policies`
  - [ ] `/policies/:policyId`
  - [ ] `/integrations`
  - [ ] `/integrations/:integrationId`
  - [ ] `/changes`
  - [ ] `/changes/new`
  - [ ] `/changes/new/emergency`
  - [ ] `/changes/:changeId`
  - [ ] `/audit/changes`
  - [ ] `/audit/changes/:changeId`
  - [ ] `/audit/access`
  - [ ] `/retro-reviews`
  - [ ] `/freeze-rules`
  - [ ] `/settings`
  - [ ] `/runners`
  - [ ] `/runners/pools/:poolId`
  - [ ] `/runners/runners/:runnerId`
  - [ ] `/runners/routes`
- [ ] Every major backend domain with UI exposure is represented: users, organizations, runbooks, workflows, executions, approvals, policies, audit, artifacts, integrations, changes, evidence, auditor, runners.
- [ ] Every discovered execution status has UI coverage: queued, claimed, running, succeeded, failed, cancelled.
- [ ] Every discovered step status has UI coverage: pending, waiting_for_approval, running, succeeded, failed, skipped, cancelled.
- [ ] AI unavailable and runner unavailable paths have been tested.
- [ ] Approval approve and reject paths have been tested.
- [ ] Policy approval/block/auto behavior has been tested where data allows.
- [ ] Artifact download has been tested.
- [ ] SSE/live update or polling fallback has been observed.
- [ ] Unsupported or unimplemented UI paths are recorded in release notes.
- [ ] Screenshots captured for release readiness:
  - [ ] Login and Settings.
  - [ ] Runbook detail.
  - [ ] AI review page.
  - [ ] Workflow detail with steps.
  - [ ] Execution detail terminal success.
  - [ ] Execution failure/timeout.
  - [ ] Approval decision.
  - [ ] Policy detail.
  - [ ] Runner pool and runner detail.
  - [ ] Integration detail.
  - [ ] Change dossier if prepared data exists.
  - [ ] Evidence bundle if closed change exists.
  - [ ] Auditor search/detail if audit data exists.
