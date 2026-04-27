# Repository Documentation Audit

Date: 2026-04-27

This audit compares the current working tree against the existing documentation and blueprints. It is documentation-only and does not authorize feature work.

## Current Repo Structure Summary

| Area | Current state |
| --- | --- |
| `apps/api` | Django + DRF control plane. Owns PostgreSQL persistence, public `/api/v1/` APIs, internal runner APIs under `/api/v1/internal/`, service-layer orchestration, error envelopes, and the Django-side AI client boundary. |
| `apps/runner` | Python worker. Polls Django internal APIs, claims queued executions, sends heartbeats, updates steps, and completes executions. It simulates step execution today; it does not access PostgreSQL or the AI service. |
| `apps/ai` | FastAPI advisory service. Exposes `GET /health`, implemented `POST /parse/runbook`, and placeholder `POST /enrich/workflow` and `POST /summarize/failure`. It has no persistence. |
| `apps/web` | React + TypeScript + Vite frontend. Uses React Router and TanStack Query. Calls only Django `/api/v1/` endpoints through `src/shared/api/client.ts`. |
| `packages` | Shared contract/package scaffolds. `packages/contracts` and `packages/workflow-schema` both contain workflow schema placeholders; `packages/sdk` is a minimal package scaffold. |
| `infra` | Documentation placeholders for future AWS, Docker, Compose, and script assets. The root `docker-compose.yml` is the current local orchestration source of truth. |
| `.github/workflows` | CI for web build/lint/format/tests, Python lint/format/compile, API tests, runner tests, and AI tests. |
| `docs` | Existing API docs, runner docs, phase blueprints, audits, product/decision placeholders, and runbook placeholders. It lacked a single documentation landing page and several maintainability docs. |

## Existing Documentation Inventory

| File or directory | Assessment |
| --- | --- |
| `README.md` | Too short for current repo maturity. It listed the stack and layout but omitted current API/runner/AI boundaries, commands, implemented-vs-planned status, and AI-agent rules. |
| `docs/api/rest-api-v1.md` | Useful but stale: missing runbook `mark-ready`, runbook `archive`, workflow `archive`, current error envelope, and current internal response details. |
| `docs/api/internal-runner-api.md` | Mostly accurate in spirit, but response examples differed from current code for heartbeat, step update, and complete. |
| `docs/architecture/execution-flow.md` | Useful and mostly aligned with runner flow. Needed links into a broader architecture system. |
| `docs/runner/execution-loop.md` | Useful runner reference. Some details overlap with the new architecture runner guide. |
| `docs/blueprints/phase-01` through `phase-09` | Planning history. Several earlier files still said `Status: Planned` even though their core outputs are implemented. Some "current state" sections were stale. |
| `docs/blueprints/phase-10-*` | Forward-looking blueprints. Generally should remain planning documents. They correctly mark many features as blueprint-only, but they need to be read with the current architecture guardrails. |
| `docs/blueprints/implemented/phase-01-implemented-architecture-blueprint.md` | Valuable implemented snapshot, but stale for frontend and test coverage because the React product slice and AI tests now exist. |
| `docs/runbooks/README.md` | Placeholder. Missing local development, AI-agent workflow, and documentation maintenance procedures. |
| `docs/decisions/README.md` and `docs/product/README.md` | Placeholders. Acceptable but should be linked from the docs index. |
| App-level READMEs | Present for `apps/api`, `apps/runner`, `apps/ai`, and `apps/web`, but several described old placeholder states. |
| `infra/*/README.md` and package READMEs | Present and short. Needed clearer ownership and "do not put here" guidance. |

## Missing Documentation

- Repository-level documentation index at `docs/README.md`.
- Architecture overview tying together Django, React, runner, AI, PostgreSQL, and Docker.
- Explicit service-boundary guide with allowed and disallowed calls.
- Maintainability-focused repository map.
- Current API contract reference in `docs/architecture` that distinguishes implemented, partially implemented, planned, and deferred endpoints.
- Current data model reference covering models, fields, relationships, tenant scoping, snapshots, status enums, and deletion strategy.
- Runner lifecycle guide aligned to the current code.
- AI service boundary guide aligned to the current FastAPI parse route.
- Frontend architecture guide aligned to React Router, TanStack Query, feature folders, and `VITE_API_BASE_URL`.
- Local development runbook with Makefile and Docker Compose workflows.
- AI-agent working guide for Codex/Claude to prevent architecture drift.
- Per-file documentation strategy.
- Documentation maintenance checklist.

## Stale or Inaccurate Documentation

| File | Drift |
| --- | --- |
| `apps/api/README.md` | Said app namespaces were placeholders. Current Django apps, models, APIs, services, and tests are implemented for core vertical-slice domains. |
| `apps/runner/README.md` | Said the runner was a basic entrypoint with placeholder API behavior. Current runner polls, claims, heartbeats, updates steps, and completes executions. |
| `apps/ai/README.md` | Said parse was a placeholder and schemas were future work. Current parse route, schemas, parser service, and tests exist. |
| `apps/web/README.md` | Said the frontend was a placeholder landing page. Current app has routes, feature API clients, TanStack Query hooks, and page tests. |
| `docs/api/rest-api-v1.md` | Claimed validation errors surfaced naturally via DRF with no custom envelope. Current code normalizes DRF and domain errors to `{"errors": [...]}`. |
| `docs/api/internal-runner-api.md` | Claimed complete returns full public execution detail. Current code returns compact `{id,status,finished_at}`. |
| `docs/blueprints/phase-05-runner-real-flow-blueprint.md` | Current-state row described placeholder runner modules. Those modules are now implemented for the simulated execution flow. |
| `docs/blueprints/phase-06-react-product-slice-blueprint.md` | Current-state row described placeholder `App.tsx`. The route/page slice is now present. |
| `docs/blueprints/phase-07-ai-service-boundary-blueprint.md` | Current-state row described parse as placeholder and missing API `httpx`; both have changed. |
| `docs/blueprints/implemented/phase-01-implemented-architecture-blueprint.md` | Described frontend as placeholder and said there were no AI service tests. Both are now stale. |

## Blueprint Drift Findings

- Phases 02 through 09 mostly read as implementation plans. Their core outputs are now represented in the repo: domain models, service layer, versioned APIs, runner flow, frontend slice, AI parse boundary, targeted tests, Makefile/local polish, seed command, lint/format tooling, and CI gates.
- The blueprints remain useful as planning history, so they should not be rewritten as implementation logs.
- Targeted "Current repo alignment notes" should be added where a stale current-state statement would mislead a maintainer or AI agent.
- Phase 10 blueprints remain planned/deferred. They should not be treated as implemented merely because placeholder packages exist for `approvals`, `policies`, `audit`, `artifacts`, `integrations`, or `users`.
- Phase 10.8 intentionally discusses SSE as a later phase. The current project should continue to avoid websockets, SSE, Kafka, RabbitMQ, Celery, and similar infrastructure unless that phase is explicitly implemented.

## Architecture Drift Findings

- The core architecture invariants are still intact:
  - Django is the control plane.
  - React calls only Django APIs.
  - Runner calls only Django internal APIs.
  - Runner never talks directly to PostgreSQL.
  - Runner never calls the AI service.
  - FastAPI AI is stateless and advisory only.
  - Django owns persistence, orchestration, validation, state transitions, and API contracts.
  - APIs are versioned under `/api/v1/`.
  - Runner-only endpoints live under `/api/v1/internal/`.
  - Business logic is concentrated in service modules.
  - UUIDs are used for domain entities.
  - Docker-first local development remains the source of truth.
- Documentation drift, not code drift, is the main problem. The actual code mostly preserves the intended boundaries.
- One contract nuance matters: public execution serializers expose runner metadata except the actual `claim_token`, which is represented only as `claim_token_present`. This is acceptable for local early-stage visibility but should be revisited when auth and production hardening are implemented.

## File and Folder Areas With Unclear Ownership

| Area | Ownership gap |
| --- | --- |
| `apps/api/apps/approvals`, `audit`, `artifacts`, `integrations`, `policies`, `users` | Placeholder packages exist but are not Django apps yet. Without documentation, agents may assume phase-10 features are partially implemented. |
| `packages/contracts` vs `packages/workflow-schema` | Both contain workflow schema scaffolding. The canonical source of truth is not yet decided. |
| `packages/sdk` | Future scaffold only. It should not become a parallel frontend API client until package ownership is defined. |
| `infra/aws` | Intentional placeholder. No live AWS infrastructure or deployment workflow exists. |
| `docs/api` vs `docs/architecture/api-contracts.md` | Older API docs remain useful as endpoint references, but architecture-level API rules need one maintainability-focused source of truth. |

## New Contributor Confusion Risks

- They may think auth, approvals, policies, artifacts, audit trail, integrations, AWS deployment, or live streaming exist because placeholders and blueprints exist.
- They may miss that workflow creation already calls the FastAPI parse service through Django.
- They may use old README commands or app READMEs that described placeholder states.
- They may not know that direct frontend-to-AI and runner-to-PostgreSQL calls are forbidden even if convenient.
- They may not know which Makefile targets rebuild containers versus only restart them.
- They may not know that tests are split across Docker Makefile targets and CI jobs.

## AI Coding Agent Drift Risks

- Implementing Phase 10 blueprint content without explicit human approval.
- Treating placeholder packages as implemented features.
- Adding business logic to DRF views or serializers instead of `services.py`.
- Adding a direct browser call to the FastAPI service to speed up workflow parsing.
- Adding runner database access to simplify claim or heartbeat logic.
- Introducing Celery, Kafka, RabbitMQ, websockets, or SSE before the relevant blueprint is approved.
- Treating planned endpoint examples as current API contracts.
- Editing tests or product code during a documentation-only task.

## Prioritized Documentation Fixes

1. Add a docs landing page and update the top-level README.
2. Add architecture overview, service boundaries, repository map, API contracts, data model, runner, AI service, and frontend docs.
3. Add local development, AI-agent working, and documentation maintenance runbooks.
4. Update stale app/package/infra READMEs.
5. Add targeted alignment notes to stale blueprints without rewriting historical planning content.
6. Add only small source-level boundary comments where they prevent future unsafe edits.

## Files Updated or Created

Created:

- `docs/README.md`
- `docs/architecture/ai-service-boundary.md`
- `docs/architecture/api-contracts.md`
- `docs/architecture/architecture-overview.md`
- `docs/architecture/data-model.md`
- `docs/architecture/frontend.md`
- `docs/architecture/per-file-documentation-guide.md`
- `docs/architecture/repository-map.md`
- `docs/architecture/runner.md`
- `docs/architecture/service-boundaries.md`
- `docs/audits/repository-documentation-audit.md`
- `docs/runbooks/ai-agent-working-guide.md`
- `docs/runbooks/documentation-maintenance.md`
- `docs/runbooks/local-development.md`
- `infra/README.md`
- `packages/README.md`

Updated:

- `README.md`
- `apps/ai/README.md`
- `apps/api/README.md`
- `apps/api/config/api_v1_urls.py`
- `apps/runner/README.md`
- `apps/web/README.md`
- `apps/web/src/shared/api/client.ts`
- `docs/api/README.md`
- `docs/api/internal-runner-api.md`
- `docs/api/rest-api-v1.md`
- `docs/architecture/README.md`
- `docs/blueprints/implemented/phase-01-implemented-architecture-blueprint.md`
- `docs/blueprints/phase-01-end-to-end-vertical-slice-blueprint.md`
- `docs/blueprints/phase-02-django-domain-foundation-blueprint.md`
- `docs/blueprints/phase-03-application-service-layer-blueprint.md`
- `docs/blueprints/phase-04-versioned-rest-apis-blueprint.md`
- `docs/blueprints/phase-05-runner-real-flow-blueprint.md`
- `docs/blueprints/phase-06-react-product-slice-blueprint.md`
- `docs/blueprints/phase-07-ai-service-boundary-blueprint.md`
- `docs/blueprints/phase-08-targeted-testing-blueprint.md`
- `docs/blueprints/phase-09-local-operational-polish-blueprint.md`
- `docs/runbooks/README.md`
- `infra/aws/README.md`
- `infra/compose/README.md`
- `infra/docker/README.md`
- `infra/scripts/README.md`
- `packages/contracts/README.md`
- `packages/sdk/README.md`
- `packages/workflow-schema/README.md`
