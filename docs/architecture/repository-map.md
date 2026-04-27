# Repository Map

This map explains where changes belong and where they do not belong.

## `apps/api`

Purpose: Django + DRF control plane.

Owner/responsibility:

- Domain models, migrations, service-layer orchestration, serializers, views, public APIs, internal runner APIs, and Django-side integration clients.

Important files:

- `config/urls.py` and `config/api_v1_urls.py`
- `config/settings/`
- `apps/common/api_errors.py`
- `apps/*/models.py`
- `apps/*/services.py`
- `apps/*/serializers.py`
- `apps/*/views.py`
- `apps/executions/internal_views.py`
- `apps/runbooks/ai_client.py`
- `apps/workflows/internal_clients.py`

Belongs here:

- Persistence-backed domain behavior.
- Business validation and state transitions in service modules.
- Public `/api/v1/` contracts.
- Runner-only `/api/v1/internal/` contracts.
- Django-to-AI advisory clients.

Does not belong here:

- React UI code.
- Runner execution loops.
- FastAPI route handlers.
- Product features from future blueprints unless explicitly approved.

Common change patterns:

- Add a model field with a migration and data-model doc update.
- Add a service function, then expose it through a thin view/serializer pair.
- Add public API tests and update API docs.
- Add internal runner behavior only through dedicated internal serializers/views/services.

## `apps/runner`

Purpose: Long-running Python worker for claimed execution processing.

Owner/responsibility:

- Polling, claim handling, heartbeats, step updates, completion calls, and local execution mechanics.

Important files:

- `runner/main.py`
- `runner/poller.py`
- `runner/executor.py`
- `runner/client.py`
- `runner/schemas.py`
- `runner/log_streamer.py`

Belongs here:

- Runner HTTP client changes for Django internal APIs.
- Runner orchestration tests.
- Execution mechanics that report results back to Django.

Does not belong here:

- Database access.
- AI-service calls.
- Workflow versioning or persistence decisions.
- Approval/policy decisions that Django must own.

Common change patterns:

- Update Pydantic schemas when internal API contracts change.
- Add tests with fake clients before changing poller/executor behavior.
- Keep network calls inside `ApiClient`.

## `apps/ai`

Purpose: FastAPI advisory AI service.

Owner/responsibility:

- Stateless parsing and future advisory transformations requested by Django.

Important files:

- `app/main.py`
- `app/api/routes/parse.py`
- `app/api/routes/enrich.py`
- `app/api/routes/summarize.py`
- `app/schemas/workflow_parse.py`
- `app/services/workflow_parser.py`

Belongs here:

- Pydantic request/response schemas.
- Parser/provider orchestration that returns candidates.
- Tests for advisory output shape.

Does not belong here:

- Database writes.
- Workflow persistence.
- Runner APIs.
- Browser-facing product endpoints.

Common change patterns:

- Add or change advisory schema, then update Django client validation and docs.
- Keep parser logic deterministic unless a provider-backed phase is explicitly approved.

## `apps/web`

Purpose: React + TypeScript frontend.

Owner/responsibility:

- Product UI, routing, feature API clients, hooks, page-level tests, and browser state.

Important files:

- `src/app/router.tsx`
- `src/app/AppLayout.tsx`
- `src/app/providers/queryClient.ts`
- `src/shared/api/client.ts`
- `src/shared/api/env.ts`
- `src/features/*`
- `src/routes/*`

Belongs here:

- Pages and route components.
- Feature-scoped API functions and hooks.
- UI tests.

Does not belong here:

- Direct AI calls.
- Runner/internal API calls.
- Business state transitions not represented by Django APIs.

Common change patterns:

- Add a feature API function under `src/features/<domain>/api`.
- Add a query/mutation hook under `hooks`.
- Add or update a route in `src/app/router.tsx`.
- Use `apiRequest` for all Django calls.

## `packages`

Purpose: Shared package scaffolding.

Owner/responsibility:

- Future contract/schema/SDK material shared across apps.

Important files:

- `packages/contracts/workflow/workflow.schema.json`
- `packages/workflow-schema/workflow.schema.json`
- `packages/sdk/src/index.ts`

Belongs here:

- Stable contracts once ownership is decided.
- Shared schema exports.
- Future typed SDK helpers.

Does not belong here:

- Runtime business logic for current app services.
- A second source of truth for API behavior before docs and code agree.

Common change patterns:

- Consolidate duplicated workflow schema placeholders before broad usage.
- Add consumers only after package ownership is explicit.

## `docs`

Purpose: Architecture, runbooks, blueprints, audits, decisions, and product notes.

Owner/responsibility:

- Long-term maintainability and implementation guidance.

Important files:

- `docs/README.md`
- `docs/architecture/`
- `docs/runbooks/`
- `docs/blueprints/`
- `docs/audits/`

Belongs here:

- Current architecture truth.
- Historical and future blueprints.
- Operational procedures.
- Audits and decisions.

Does not belong here:

- Undifferentiated generated filler.
- Claims that planned features are implemented.

Common change patterns:

- Update architecture docs when service boundaries or data ownership changes.
- Update blueprint alignment notes after phase implementation.
- Add audit reports before major changes.

## `infra`

Purpose: Infrastructure documentation and future operational assets.

Owner/responsibility:

- Future AWS, shared Docker, Compose override, and script assets.

Important files:

- `infra/aws/README.md`
- `infra/docker/README.md`
- `infra/compose/README.md`
- `infra/scripts/README.md`

Belongs here:

- Infrastructure-as-code when approved.
- Shared container snippets.
- Operator scripts with documented ownership.

Does not belong here:

- Active local orchestration that contradicts root `docker-compose.yml`.
- Live AWS resources before the AWS deployment blueprint is approved.

Common change patterns:

- Add docs first, then infrastructure scaffolding during an approved deployment phase.

## `.github`

Purpose: GitHub Actions workflows.

Owner/responsibility:

- CI validation and future deployment workflows.

Important files:

- `.github/workflows/ci.yml`

Belongs here:

- Build, lint, format, and test gates.
- Future AWS workflows after approval.

Does not belong here:

- Secrets in plain text.
- Deployment workflows that bypass documented release gates.

Common change patterns:

- Add CI checks with a corresponding local Makefile command where practical.
- Keep workflow changes documented in local development or deployment runbooks.
