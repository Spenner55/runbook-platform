# Phase 02 Blueprint: Django Domain Foundation

## 1. Title and Phase Metadata

| Field | Value |
| --- | --- |
| Phase number | 02 |
| Objective | Build the Django domain foundation for the first real vertical slice by turning placeholder app packages into real Django apps and introducing production-shaped v1 domain models, admin registration, and migrations. |
| Status | Implemented; retained as planning blueprint |
| Dependencies | Existing Django project scaffold in `apps/api`, Docker Compose runtime in `/home/dylan/code/runbook-platform/docker-compose.yml`, PostgreSQL service, placeholder packages under `/home/dylan/code/runbook-platform/apps/api/apps`, and the Phase 1 execution plan at `/home/dylan/code/runbook-platform/docs/blueprints/phase-01-end-to-end-vertical-slice-blueprint.md`. |
| Outputs | Real Django apps for `common`, `organizations`, `runbooks`, `workflows`, and `executions`; shared abstract base models; initial domain models; Django admin registration; initial migrations; model smoke tests. |
| Local runtime source of truth | Docker Compose. All routine commands in this phase should run through `docker compose exec api ...` or existing `make` wrappers. |
| Documentation basis reviewed on | 2026-03-31 |
| Official docs basis | Django 6.0 model field/options/constraints/index/postgres-index docs, DRF 3.16 docs and announcement. |

### Current repo alignment notes

As of 2026-04-27, the core domain foundation is implemented in `apps/api/apps/common`, `organizations`, `runbooks`, `workflows`, and `executions`. Placeholder packages for `approvals`, `policies`, `audit`, `integrations`, `artifacts`, and `users` remain future-phase scaffolding only. Current field-level truth is documented in `docs/architecture/data-model.md`.

### Out of Scope

- `approvals` app implementation
- `policies` app implementation
- `audit` app implementation
- `integrations` app implementation
- `artifacts` app implementation
- API endpoints, serializers, viewsets, and permissions beyond what admin/checks need
- business orchestration services beyond what is required to define safe model shapes
- background jobs, queues, runner claim logic, or real execution engine behavior
- soft-delete framework, audit trail framework, artifact storage, or policy enforcement logic

## 2. Executive Summary

Phase 02 establishes the minimum durable Django domain layer needed for the first vertical slice to become real instead of remaining scaffold-only. At the end of this phase, the API service should recognize actual Django apps, the database should contain the core tables for organizations, runbooks, workflows, executions, and execution steps, and the admin should allow operators to inspect and manually verify those records.

This phase matters because every later vertical slice depends on the domain model being stable, migration-backed, and explicit about ownership and history. If the data model is vague here, later API work, runner behavior, and UI status views will drift. This phase deliberately keeps scope narrow: store raw runbooks, store derived workflow plans, snapshot workflow state into executions, copy step definitions into execution steps, and preserve history. Everything else stays deferred.

## 3. Architecture Decisions for This Phase

### UUID Strategy

- Use explicit `models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)` on every domain model.
- Do not rely on Django’s `DEFAULT_AUTO_FIELD` for domain tables.
- Keep the existing `DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"` in `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py` for any non-domain or third-party tables that still use integer PKs.
- Rationale: current official Django guidance continues to support UUID primary keys directly and PostgreSQL stores them as native `uuid` values.

### Model Ownership and Tenant Scoping

- `Organization` is the tenant root.
- `Runbook`, `Workflow`, and `Execution` each carry a direct `organization` foreign key.
- `ExecutionStep` is scoped indirectly through `execution` and should not duplicate `organization` in v1.
- Do not introduce an `OrganizationScopedModel` mixin in Phase 02.
- Rationale: only three concrete models need direct tenant ownership, and abstracting that foreign key now adds reverse-name and migration complexity without enough payoff.

### Base Model and Mixin Strategy

- Create one shared abstract base model in `common`: `TimeStampedUUIDModel`.
- Do not introduce `NamedModel` in Phase 02.
- Rationale: `Organization` and `Workflow` naturally use `name`, while `Runbook` should keep `title` to distinguish raw authored content from the derived workflow plan. A name mixin would force artificial uniformity.

### Delete Strategy

- Use `on_delete=models.PROTECT` for tenant and history-preserving relationships:
  - `Runbook.organization`
  - `Workflow.organization`
  - `Workflow.runbook`
  - `Execution.organization`
  - `Execution.workflow`
- Use `on_delete=models.CASCADE` only for `ExecutionStep.execution`.
- Operational rule: do not expose delete flows in application code during this phase.
- Rationale: deleting an organization, runbook, or workflow should not silently erase execution history. `ExecutionStep` is an aggregate child of `Execution`, so cascading inside that aggregate is acceptable.

### Status Enum Strategy

- Use `models.TextChoices` for all status fields.
- Keep statuses explicit on the models instead of hidden constants in views or serializers.
- Recommended v1 statuses:
  - `RunbookStatus`: `draft`, `ready`, `archived`
  - `WorkflowStatus`: `draft`, `published`, `superseded`, `archived`
  - `ExecutionStatus`: `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`
  - `ExecutionStepStatus`: `pending`, `running`, `succeeded`, `failed`, `skipped`
- Rationale: Django’s enum support is first-class, self-documenting, and works cleanly with admin, forms, and later DRF serializers.

### Raw Runbook Preservation

- Store raw human-authored runbook prose on `Runbook.raw_content` as `TextField`.
- Do not overwrite or normalize that field in place.
- Treat workflow generation as a derived artifact built from the runbook, not as a replacement for it.
- Rationale: preserving the authored source supports debugging, regeneration, and history review.

### Workflow Snapshot Strategy

- Store the canonical structured workflow definition on `Workflow.definition` as `JSONField`.
- The workflow definition is a structured derived plan, not raw prose.
- Add `Workflow.version` and a uniqueness constraint on `(runbook, version)`.
- Add `Workflow.definition_schema_version` as a short string field so snapshot interpretation is explicit even before a formal schema registry exists.
- Do not add a PostgreSQL `GinIndex` to `definition` in v1.
- Rationale: Django’s `JSONField` is appropriate for structured documents, but Django’s PostgreSQL guidance only justifies specialized JSON indexes when real JSON-path query needs exist. Phase 02 does not have those needs.

### Execution-Time Step Copy Strategy

- When an execution is created in a later phase, copy the full workflow definition into `Execution.workflow_snapshot`.
- Materialize each step from that snapshot into `ExecutionStep`.
- Each `ExecutionStep` should carry:
  - immutable copied plan fields such as `step_key`, `name`, `step_type`, `risk_level`, `command`, `requires_approval`
  - a full `step_snapshot` JSON copy
  - mutable runtime fields such as `status`, `started_at`, `finished_at`, `exit_code`, `error_message`
- Rationale: preserving both the whole-workflow snapshot and per-step copies protects history when a workflow changes later.

### Execution-Step Observability Strategy

- Store enough execution-step metadata to explain what happened without implementing artifacts or audit logging yet.
- Include `status`, timestamps, `exit_code`, and `error_message`.
- Do not add log blobs, artifact references, or audit event models in this phase.
- Rationale: v1 needs operational visibility, not a full observability subsystem.

## 4. File-by-File Implementation Plan

### Recommended Module Layout Under `apps/api/apps/*`

Keep each app shallow in Phase 02. Use single-file model modules because the domain surface is still small.

```text
/home/dylan/code/runbook-platform/apps/api/apps/
  common/
    __init__.py
    apps.py
    admin.py
    models.py
    tests.py
    migrations/
      __init__.py
  organizations/
    __init__.py
    apps.py
    admin.py
    models.py
    tests.py
    migrations/
      __init__.py
  runbooks/
    __init__.py
    apps.py
    admin.py
    models.py
    tests.py
    migrations/
      __init__.py
  workflows/
    __init__.py
    apps.py
    admin.py
    models.py
    tests.py
    migrations/
      __init__.py
  executions/
    __init__.py
    apps.py
    admin.py
    models.py
    tests.py
    migrations/
      __init__.py
```

### Files to Create or Update

#### `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`

- Add AppConfig entries for the five real apps:
  - `apps.common.apps.CommonConfig`
  - `apps.organizations.apps.OrganizationsConfig`
  - `apps.runbooks.apps.RunbooksConfig`
  - `apps.workflows.apps.WorkflowsConfig`
  - `apps.executions.apps.ExecutionsConfig`
- Do not register deferred apps here as real implementations if they remain empty placeholders.

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/apps.py`

- Define `CommonConfig` with `name = "apps.common"`.
- Keep config simple; no startup logic.

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/models.py`

- Define `TimeStampedUUIDModel` only.
- No concrete tables in `common`.
- Keep `Meta.abstract = True`.

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/admin.py`

- Leave empty or add a short comment explaining there are no concrete admin models in this app.

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/tests.py`

- Add a minimal smoke test that imports `TimeStampedUUIDModel` or asserts that common abstractions can be imported.

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/apps.py`

- Define `OrganizationsConfig` with `name = "apps.organizations"`.

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/models.py`

- Define `Organization(TimeStampedUUIDModel)`.
- Keep fields minimal and stable.

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/admin.py`

- Register `Organization`.
- Include searchable admin fields.

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/tests.py`

- Add model constraint smoke tests:
  - slug uniqueness
  - UUID pk generation

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/apps.py`

- Define `RunbooksConfig`.

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/models.py`

- Define `Runbook(TimeStampedUUIDModel)`.
- Import `Organization` via string reference in FK.
- Add status enum inside the model or module.

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/admin.py`

- Register `Runbook`.
- Make `organization`, `status`, and timestamps filterable.

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests.py`

- Add tests for:
  - `(organization, slug)` uniqueness
  - status default
  - raw content preservation

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/apps.py`

- Define `WorkflowsConfig`.

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/models.py`

- Define `Workflow(TimeStampedUUIDModel)`.
- Include `version`, `definition`, `definition_schema_version`, `status`.
- Use model constraints instead of custom serializer-only validation.

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/admin.py`

- Register `Workflow`.
- Keep JSON fields read-only in admin if they become large.

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests.py`

- Add tests for:
  - `(runbook, version)` uniqueness
  - `version >= 1`
  - JSON definition persistence

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/apps.py`

- Define `ExecutionsConfig`.

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/models.py`

- Define both `Execution` and `ExecutionStep`.
- Keep execution/runtime data together in one module for v1 clarity.

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/admin.py`

- Register both `Execution` and `ExecutionStep`.
- Add inline display for steps under `Execution` if helpful, but keep admin simple.
- Prefer a read-oriented admin over editing nested JSON heavily in the browser.

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests.py`

- Add tests for:
  - execution status default
  - workflow snapshot persistence
  - `(execution, position)` uniqueness
  - `(execution, step_key)` uniqueness

#### `/home/dylan/code/runbook-platform/apps/api/apps/*/migrations/__init__.py`

- Ensure `migrations` packages exist for all five apps.
- Expect no concrete migration for `common` if it only contains abstract models.

## 5. Detailed Step-by-Step Implementation Checklist

### Step 1. Confirm the API container is the working runtime

- Purpose: prevent local Python drift and ensure migration commands run against the same environment the repo documents.
- Commands:

```bash
docker compose up -d postgres api
docker compose exec api python manage.py check
```

- Files touched: none
- Expected result:
  - `postgres` is healthy
  - Django `check` passes with the current scaffold
- Verification steps:
  - `docker compose ps`
  - `docker compose logs api --tail=50`
- Rollback notes:
  - `docker compose down` if the local stack was started only for this work

### Step 2. Convert placeholder packages into real Django apps

- Purpose: make the existing directories under `apps/api/apps` behave like actual Django apps without rearranging the repo.
- Commands:

```bash
mkdir -p apps/api/apps/common/migrations
mkdir -p apps/api/apps/organizations/migrations
mkdir -p apps/api/apps/runbooks/migrations
mkdir -p apps/api/apps/workflows/migrations
mkdir -p apps/api/apps/executions/migrations
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/apps.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/admin.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/models.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/tests.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/migrations/__init__.py`
  - equivalent files in `organizations`, `runbooks`, `workflows`, and `executions`
- Expected result:
  - every in-scope app has a standard Django app skeleton
- Verification steps:
  - `find apps/api/apps -maxdepth 2 -type f | sort`
- Rollback notes:
  - safe to remove newly created files before any migrations are generated

### Step 3. Register only the in-scope apps in Django settings

- Purpose: let Django discover the real apps while keeping deferred apps deferred.
- Commands:

```bash
docker compose exec api python manage.py check
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`
- Expected result:
  - `manage.py check` recognizes the new AppConfig entries
- Verification steps:
  - confirm no `ImproperlyConfigured`, import, or label-collision errors
- Rollback notes:
  - revert the `INSTALLED_APPS` additions if app import paths are wrong

### Step 4. Add the shared abstract base model

- Purpose: define the common UUID and timestamp behavior once.
- Commands:

```bash
docker compose exec api python manage.py shell -c "from apps.common.models import TimeStampedUUIDModel; print(TimeStampedUUIDModel.__name__)"
docker compose exec api python manage.py makemigrations common
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/models.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/common/tests.py`
- Expected result:
  - imports work
  - `makemigrations common` reports no changes if only abstract models exist
- Verification steps:
  - confirm that “No changes detected in app 'common'” is treated as success, not failure
- Rollback notes:
  - revert the abstract model file; there is no DB rollback because no table should be created

### Step 5. Implement `Organization`

- Purpose: create the tenant root used by every later domain object.
- Commands:

```bash
docker compose exec api python manage.py makemigrations organizations
docker compose exec api python manage.py sqlmigrate organizations 0001
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/apps/organizations/models.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/organizations/admin.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/organizations/tests.py`
- Expected result:
  - one initial migration for `organizations`
  - `slug` uniqueness is reflected in generated SQL
- Verification steps:
  - inspect `sqlmigrate` output for a unique constraint or unique index on `slug`
- Rollback notes:
  - safe to delete the migration file before `migrate` if the model shape changes

### Step 6. Implement `Runbook`

- Purpose: preserve raw authored content and connect it to a tenant.
- Commands:

```bash
docker compose exec api python manage.py makemigrations runbooks
docker compose exec api python manage.py sqlmigrate runbooks 0001
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/models.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/admin.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests.py`
- Expected result:
  - migration depends on `organizations`
  - `(organization, slug)` uniqueness is generated
- Verification steps:
  - inspect migration dependency list
  - confirm `on_delete=PROTECT` in code
- Rollback notes:
  - if the migration is not applied yet, delete and regenerate it after corrections

### Step 7. Implement `Workflow`

- Purpose: store the structured derived plan generated from a runbook.
- Commands:

```bash
docker compose exec api python manage.py makemigrations workflows
docker compose exec api python manage.py sqlmigrate workflows 0001
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/apps/workflows/models.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/workflows/admin.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests.py`
- Expected result:
  - migration depends on `organizations` and `runbooks`
  - unique constraint exists on `(runbook, version)`
  - no GIN index is added to `definition`
- Verification steps:
  - inspect generated SQL and migration operations
  - confirm `definition` is `JSONField`
- Rollback notes:
  - if the schema version field name or constraints change before migrate, regenerate the migration cleanly

### Step 8. Implement `Execution` and `ExecutionStep`

- Purpose: preserve execution snapshots and per-step runtime state.
- Commands:

```bash
docker compose exec api python manage.py makemigrations executions
docker compose exec api python manage.py sqlmigrate executions 0001
```

- Files touched:
  - `/home/dylan/code/runbook-platform/apps/api/apps/executions/models.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/executions/admin.py`
  - `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests.py`
- Expected result:
  - execution tables exist with history-preserving foreign keys
  - indexes support listing executions by status and time
  - step uniqueness constraints exist inside each execution
- Verification steps:
  - inspect migration SQL for:
    - `workflow_snapshot` and `step_snapshot`
    - `on_delete=PROTECT` on `Execution.workflow`
    - `on_delete=CASCADE` on `ExecutionStep.execution`
- Rollback notes:
  - do not apply partial execution-schema migrations to shared environments; keep rollback local until verified

### Step 9. Apply all migrations in dependency order

- Purpose: materialize the new schema in PostgreSQL.
- Commands:

```bash
docker compose exec api python manage.py migrate
docker compose exec api python manage.py showmigrations organizations runbooks workflows executions
```

- Files touched:
  - generated migration files only
- Expected result:
  - all initial migrations apply cleanly
- Verification steps:
  - confirm all target apps show `[X]`
  - inspect the database using `make db-shell` and `\dt`
- Rollback notes:
  - local-only rollback order if absolutely needed:

```bash
docker compose exec api python manage.py migrate executions zero
docker compose exec api python manage.py migrate workflows zero
docker compose exec api python manage.py migrate runbooks zero
docker compose exec api python manage.py migrate organizations zero
```

- Rollback caution:
  - only do this before any meaningful local data exists

### Step 10. Register and verify Django admin

- Purpose: give operators and reviewers a direct read path into the domain objects.
- Commands:

```bash
docker compose exec api python manage.py createsuperuser
docker compose exec api python manage.py shell -c "from django.contrib import admin; print(sorted(admin.site._registry.keys(), key=lambda m: m.__name__))"
```

- Files touched:
  - each in-scope app’s `admin.py`
- Expected result:
  - all five models are registered in admin
- Verification steps:
  - browse to `http://localhost:8000/admin/`
  - confirm filters/search fields behave as expected
- Rollback notes:
  - admin registration changes are code-only and easy to revert

### Step 11. Run model and ORM smoke tests

- Purpose: prove the schema, constraints, and snapshots behave correctly before later API work begins.
- Commands:

```bash
docker compose exec api pytest
docker compose exec api python manage.py shell -c "from apps.organizations.models import Organization; from apps.runbooks.models import Runbook; from apps.workflows.models import Workflow; from apps.executions.models import Execution, ExecutionStep; print('imports-ok')"
```

- Files touched:
  - each in-scope app’s `tests.py`
- Expected result:
  - tests pass
  - imports and model creation work
- Verification steps:
  - if pytest output is noisy, rerun targeted tests per app
- Rollback notes:
  - fix tests before proceeding; do not paper over failures with relaxed assertions

## 6. Model Specifications

### `Organization`

**Purpose**

Tenant root for all user-owned runbook, workflow, and execution data.

**Fields**

| Field | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `UUIDField` | no | primary key |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | from base model |
| `updated_at` | `DateTimeField(auto_now=True)` | no | from base model |
| `name` | `CharField(max_length=255)` | no | human label |
| `slug` | `SlugField(max_length=64)` | no | URL-safe stable identifier |

**Indexes**

- implicit index from unique `slug`

**Uniqueness Constraints**

- `slug` unique globally in v1

**Foreign Keys**

- none

**Status Values**

- none in v1

**Admin Visibility Notes**

- show `name`, `slug`, `created_at`, `updated_at`
- search by `name` and `slug`

**Future-Proofing Notes**

- if enterprise tenancy later requires human-friendly duplicate names, keep uniqueness on `slug`, not `name`
- do not add owner/user membership fields in this phase

### `Runbook`

**Purpose**

Stores the raw human-authored runbook content that later produces a structured workflow.

**Fields**

| Field | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `UUIDField` | no | primary key |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | from base model |
| `updated_at` | `DateTimeField(auto_now=True)` | no | from base model |
| `organization` | `ForeignKey("organizations.Organization", on_delete=PROTECT, related_name="runbooks")` | no | direct tenant scoping |
| `title` | `CharField(max_length=255)` | no | operator-facing label |
| `slug` | `SlugField(max_length=96)` | no | unique within organization |
| `raw_content` | `TextField()` | no | original authored prose |
| `status` | `CharField(max_length=24, choices=RunbookStatus.choices, default=RunbookStatus.DRAFT)` | no | lifecycle state |

**Indexes**

- composite index on `("organization", "status", "created_at")`
- implicit index from unique constraint on `("organization", "slug")`

**Uniqueness Constraints**

- unique `("organization", "slug")`

**Foreign Keys**

- `organization -> Organization` with `PROTECT`

**Status Values**

- `draft`
- `ready`
- `archived`

**Admin Visibility Notes**

- list display: `title`, `organization`, `status`, `updated_at`
- filters: `organization`, `status`
- search: `title`, `slug`
- optionally mark `raw_content` read-only after create if admin editing is not desired

**Future-Proofing Notes**

- defer source metadata such as parser version, author, checksum, or AI parsing status
- do not split raw content into sections yet

### `Workflow`

**Purpose**

Stores the canonical structured plan derived from a runbook. This is the database record the system should execute against, not the raw prose.

**Fields**

| Field | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `UUIDField` | no | primary key |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | from base model |
| `updated_at` | `DateTimeField(auto_now=True)` | no | from base model |
| `organization` | `ForeignKey("organizations.Organization", on_delete=PROTECT, related_name="workflows")` | no | direct tenant scoping |
| `runbook` | `ForeignKey("runbooks.Runbook", on_delete=PROTECT, related_name="workflows")` | no | source runbook |
| `name` | `CharField(max_length=255)` | no | workflow display name |
| `version` | `PositiveIntegerField()` | no | version starts at 1 |
| `status` | `CharField(max_length=24, choices=WorkflowStatus.choices, default=WorkflowStatus.DRAFT)` | no | lifecycle state |
| `definition_schema_version` | `CharField(max_length=32, default="workflow.schema.v1")` | no | schema identifier for parsing/snapshot logic |
| `definition` | `JSONField()` | no | structured derived plan |

**Indexes**

- composite index on `("organization", "status", "created_at")`
- implicit index from unique constraint on `("runbook", "version")`

**Uniqueness Constraints**

- unique `("runbook", "version")`

**Foreign Keys**

- `organization -> Organization` with `PROTECT`
- `runbook -> Runbook` with `PROTECT`

**Status Values**

- `draft`
- `published`
- `superseded`
- `archived`

**Admin Visibility Notes**

- list display: `name`, `runbook`, `version`, `status`, `updated_at`
- filters: `organization`, `status`
- search: `name`
- include `definition_schema_version`
- use a compact admin form; large JSON is mainly for inspection

**Future-Proofing Notes**

- later phases may add generation metadata, provenance, publish timestamps, or “current version” helpers
- do not add conditional uniqueness for “one published workflow per runbook” until publishing behavior actually exists
- do not add PostgreSQL JSON indexes until a real query requires them

### `Execution`

**Purpose**

Represents one immutable attempt to run a particular workflow snapshot.

**Fields**

| Field | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `UUIDField` | no | primary key |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | from base model |
| `updated_at` | `DateTimeField(auto_now=True)` | no | from base model |
| `organization` | `ForeignKey("organizations.Organization", on_delete=PROTECT, related_name="executions")` | no | direct tenant scoping |
| `workflow` | `ForeignKey("workflows.Workflow", on_delete=PROTECT, related_name="executions")` | no | source workflow record |
| `status` | `CharField(max_length=24, choices=ExecutionStatus.choices, default=ExecutionStatus.QUEUED)` | no | execution lifecycle |
| `workflow_version` | `PositiveIntegerField()` | no | copied from workflow at launch time |
| `workflow_snapshot` | `JSONField()` | no | full execution-time workflow definition copy |
| `started_at` | `DateTimeField(blank=True, null=True)` | yes | set when work actually begins |
| `finished_at` | `DateTimeField(blank=True, null=True)` | yes | set on terminal state |

**Indexes**

- composite index on `("status", "created_at")`
- composite index on `("organization", "created_at")`
- composite index on `("workflow", "created_at")`

**Uniqueness Constraints**

- none beyond the primary key in v1

**Foreign Keys**

- `organization -> Organization` with `PROTECT`
- `workflow -> Workflow` with `PROTECT`

**Status Values**

- `queued`
- `claimed`
- `running`
- `succeeded`
- `failed`
- `cancelled`

**Admin Visibility Notes**

- list display: `id`, `organization`, `workflow`, `workflow_version`, `status`, `created_at`, `started_at`, `finished_at`
- filters: `organization`, `status`
- search: execution UUID
- treat `workflow_snapshot` as mostly read-only

**Future-Proofing Notes**

- later phases may add actor, runner claim metadata, cancellation reason, or summary fields
- do not add approval state here yet
- do not denormalize runbook data onto execution unless a concrete query proves it is needed

### `ExecutionStep`

**Purpose**

Stores the execution-time copy of each workflow step plus mutable runtime state for that step.

**Fields**

| Field | Type | Null | Notes |
| --- | --- | --- | --- |
| `id` | `UUIDField` | no | primary key |
| `created_at` | `DateTimeField(auto_now_add=True)` | no | from base model |
| `updated_at` | `DateTimeField(auto_now=True)` | no | from base model |
| `execution` | `ForeignKey("executions.Execution", on_delete=CASCADE, related_name="steps")` | no | aggregate parent |
| `position` | `PositiveIntegerField()` | no | 0-based or 1-based, choose one and document it; recommend 1-based |
| `step_key` | `CharField(max_length=128)` | no | copied from workflow step `id` |
| `name` | `CharField(max_length=255)` | no | copied from workflow step |
| `step_type` | `CharField(max_length=64)` | no | copied from workflow step `type` |
| `risk_level` | `CharField(max_length=32)` | no | copied from workflow step `risk` |
| `command` | `TextField(blank=True, default="")` | no | copied if present |
| `requires_approval` | `BooleanField(default=False)` | no | copied if present |
| `status` | `CharField(max_length=24, choices=ExecutionStepStatus.choices, default=ExecutionStepStatus.PENDING)` | no | runtime state |
| `step_snapshot` | `JSONField()` | no | full copied step payload |
| `started_at` | `DateTimeField(blank=True, null=True)` | yes | runtime field |
| `finished_at` | `DateTimeField(blank=True, null=True)` | yes | runtime field |
| `exit_code` | `IntegerField(blank=True, null=True)` | yes | runtime result |
| `error_message` | `TextField(blank=True, default="")` | no | operator-readable failure summary |

**Indexes**

- composite index on `("execution", "position")`
- composite index on `("execution", "status", "position")`

**Uniqueness Constraints**

- unique `("execution", "position")`
- unique `("execution", "step_key")`

**Foreign Keys**

- `execution -> Execution` with `CASCADE`

**Status Values**

- `pending`
- `running`
- `succeeded`
- `failed`
- `skipped`

**Admin Visibility Notes**

- list display: `execution`, `position`, `step_key`, `name`, `status`, `started_at`, `finished_at`, `exit_code`
- filters: `status`
- search: `step_key`, `name`, execution UUID

**Future-Proofing Notes**

- later phases may add stdout/stderr references, artifact pointers, retry counters, or approval metadata
- do not add artifact URLs or full logs here in Phase 02

## 7. Recommended Commands

### Docker Compose First

```bash
make up-d
docker compose ps
docker compose exec api python manage.py check
```

### Repo-Safe App Setup

Use the existing placeholder directories. Do not run `startapp` into a new top-level location and move files around afterward.

```bash
mkdir -p apps/api/apps/common/migrations
mkdir -p apps/api/apps/organizations/migrations
mkdir -p apps/api/apps/runbooks/migrations
mkdir -p apps/api/apps/workflows/migrations
mkdir -p apps/api/apps/executions/migrations
```

### If a Scaffold Reference Is Needed

Only use this pattern in a throwaway location for comparison, not as the primary repo workflow:

```bash
docker compose exec api django-admin startapp sample_app /tmp/sample_app
```

### Migrations

```bash
docker compose exec api python manage.py makemigrations
docker compose exec api python manage.py makemigrations organizations runbooks workflows executions
docker compose exec api python manage.py migrate
docker compose exec api python manage.py showmigrations organizations runbooks workflows executions
docker compose exec api python manage.py sqlmigrate organizations 0001
docker compose exec api python manage.py sqlmigrate runbooks 0001
docker compose exec api python manage.py sqlmigrate workflows 0001
docker compose exec api python manage.py sqlmigrate executions 0001
```

### Admin Validation

```bash
docker compose exec api python manage.py createsuperuser
docker compose exec api python manage.py shell -c "from django.contrib import admin; print([model.__name__ for model in admin.site._registry])"
```

### Shell Checks

```bash
docker compose exec api python manage.py shell -c "from apps.organizations.models import Organization; print(Organization._meta.app_label)"
docker compose exec api python manage.py shell -c "from apps.workflows.models import Workflow; print(Workflow._meta.get_field('definition').get_internal_type())"
docker compose exec api python manage.py shell -c "from apps.executions.models import ExecutionStep; print([c.name for c in ExecutionStep._meta.constraints])"
```

### Database Inspection

```bash
make db-shell
\dt
\d organizations_organization
\d runbooks_runbook
\d workflows_workflow
\d executions_execution
\d executions_executionstep
```

## 8. Testing and Verification Plan

### Migration Verification

- Run `docker compose exec api python manage.py makemigrations --check` after the migration files are committed.
- Run `docker compose exec api python manage.py migrate`.
- Run `docker compose exec api python manage.py showmigrations organizations runbooks workflows executions`.
- Inspect SQL for every initial migration with `sqlmigrate`.
- Confirm `common` produces no concrete table migration if it only contains abstract models.

### Admin Validation

- Create a superuser.
- Open `http://localhost:8000/admin/`.
- Confirm all models are visible.
- Create a sample `Organization`, `Runbook`, `Workflow`, `Execution`, and `ExecutionStep`.
- Verify that large JSON fields are inspectable and that list filters/search fields work.

### ORM Smoke Tests

- Create one `Organization`.
- Create one `Runbook` with `raw_content`.
- Create one `Workflow` with a minimal JSON definition aligned to `/home/dylan/code/runbook-platform/packages/workflow-schema/workflow.schema.json`.
- Create one `Execution` whose `workflow_snapshot` equals the workflow definition and whose `workflow_version` matches the workflow.
- Create at least two `ExecutionStep` rows copied from the workflow snapshot.
- Retrieve the execution and assert `execution.steps.order_by("position")` returns the expected sequence.

### DB Constraint Checks

- Attempt duplicate `Organization.slug` and confirm failure.
- Attempt duplicate `Runbook.slug` inside the same organization and confirm failure.
- Attempt duplicate `Workflow.version` for the same runbook and confirm failure.
- Attempt duplicate `ExecutionStep.position` inside the same execution and confirm failure.
- Attempt duplicate `ExecutionStep.step_key` inside the same execution and confirm failure.
- Attempt deleting an `Organization` with dependent runbooks and confirm `ProtectedError`.
- Attempt deleting a `Workflow` with executions and confirm `ProtectedError`.

### Execution-Step Snapshot Checks

- Mutate a `Workflow.definition` after creating an `Execution`.
- Confirm `Execution.workflow_snapshot` remains unchanged.
- Confirm existing `ExecutionStep.step_snapshot` rows remain unchanged.
- This is the critical history-preservation proof for this phase.

### Docker-Based Verification Steps

```bash
docker compose up -d postgres api
docker compose exec api python manage.py check
docker compose exec api python manage.py migrate
docker compose exec api pytest
docker compose exec api python manage.py shell -c "print('domain-foundation-ok')"
```

## 9. Best Practices and Anti-Patterns

### What to Do

- keep the implementation order: app scaffolding, settings registration, base model, organization, runbook, workflow, execution
- keep models simple and close to the data
- put hard constraints in the database and model `Meta`, not only in future serializers
- use direct `organization` foreign keys on tenant-owned root models
- preserve source and execution snapshots immutably
- use Docker Compose as the primary runtime for checks and migrations
- keep admin read-friendly and operationally useful

### What Not to Do

- do not implement approvals, policies, audit, integrations, or artifacts in this phase
- do not move business orchestration into views
- do not add service layers or selector layers before concrete usage exists
- do not introduce JSON indexes “just in case”
- do not replace raw runbook prose with structured workflow JSON
- do not make deletions cascade across historical records
- do not split these small models into many submodules yet

### Common Drift Risks

- creating Django apps outside `/home/dylan/code/runbook-platform/apps/api/apps` and later moving them by hand
- using `CASCADE` on history-critical foreign keys because it is Django’s default habit
- storing workflow prose directly in the workflow model instead of a structured definition
- storing only the workflow FK on executions without a full snapshot
- letting step runtime state depend on the current workflow definition instead of copied execution-step rows
- adding unapproved scope from deferred apps because the app directories already exist

## 10. Codex Execution Guidance

Codex should implement this phase later in small, controlled batches with human review between batches. The key is to preserve a clean migration history and keep each batch trivially reviewable.

### Suggested Batching Sequence

1. Batch 1: app scaffolding and settings
   - create `apps.py`, `admin.py`, `models.py`, `tests.py`, and `migrations/__init__.py` for the five in-scope apps
   - update `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`
   - verify with `docker compose exec api python manage.py check`

2. Batch 2: common and organizations
   - add `TimeStampedUUIDModel`
   - implement `Organization`
   - add organization admin and tests
   - generate `organizations` migration
   - verify import and `sqlmigrate`

3. Batch 3: runbooks
   - implement `Runbook`
   - add admin and tests
   - generate `runbooks` migration
   - verify uniqueness and delete protection behavior

4. Batch 4: workflows
   - implement `Workflow`
   - add admin and tests
   - generate `workflows` migration
   - verify definition JSON persistence and version constraints

5. Batch 5: executions
   - implement `Execution` and `ExecutionStep`
   - add admin and tests
   - generate `executions` migration
   - verify snapshot and step uniqueness behavior

6. Batch 6: final verification
   - run `migrate`
   - run targeted tests or full `pytest`
   - run ORM smoke checks and admin registration checks

### Stop Points for Human Approval

- after Batch 1, because import path mistakes can infect every later step
- after Batch 2, because the base model and tenant root shape are foundational
- after Batch 4, because the workflow snapshot design is the most important schema choice
- after Batch 5, because execution history preservation must be reviewed before migration apply
- before any migration is applied to a shared or long-lived database

### What Codex Should Verify After Each Batch

- the targeted files only changed
- `docker compose exec api python manage.py check` passes
- migration files contain the intended dependencies and constraints
- no deferred-scope apps gained real implementation accidentally
- model imports work from `manage.py shell`

## 11. Definition of Done

This phase is done only when all of the following are true:

- `common`, `organizations`, `runbooks`, `workflows`, and `executions` are real Django apps under `/home/dylan/code/runbook-platform/apps/api/apps`
- Django settings register those apps successfully
- every domain model uses UUID primary keys and timestamps
- `Organization`, `Runbook`, `Workflow`, `Execution`, and `ExecutionStep` exist as real models
- runbook raw prose is stored separately from workflow structured definitions
- workflow versions are constrained per runbook
- executions store immutable workflow snapshots
- execution steps store immutable copied step definitions plus mutable runtime fields
- history-preserving delete behavior is in place
- admin registration exists for the concrete models
- initial migrations are generated and apply cleanly
- model and constraint smoke tests pass in Docker
- no approvals, policies, audit, integrations, or artifacts implementation was added

## 12. Open Questions / Decisions to Confirm

1. This blueprint assumes `Runbook` should use `title` while `Workflow` uses `name`. Confirm that distinction is preferred over normalizing both to `name`.
2. This blueprint assumes `ExecutionStep.position` should be 1-based for operator readability. Confirm if the team prefers 0-based indexing for runner alignment.
3. This blueprint assumes global uniqueness for `Organization.slug`. Confirm whether future multi-region or account-bound tenancy might require scoped organization slugs instead.

## Appendix: Official Guidance Reflected Here

- The repo currently pins `Django>=5.0,<6.0` and `djangorestframework>=3.15,<4.0`; the recommendations in this blueprint were checked against the latest official docs and kept compatible with the repo’s current version range.
- Django 6.0 model field guidance supports explicit `UUIDField` primary keys and `TextChoices` enums.
- Django model `Meta.constraints` and `Meta.indexes` guidance favors explicit database constraints over ad hoc application validation.
- Django PostgreSQL index guidance supports `GinIndex` for JSON use cases when justified, but this phase intentionally avoids JSON-path indexing because the v1 query plan does not require it.
- DRF 3.16 improves `UniqueConstraint` support, which reinforces putting uniqueness in model constraints now so later serializers inherit correct validation behavior.
