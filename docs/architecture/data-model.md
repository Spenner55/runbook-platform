# Data Model

Current persistence lives in Django models under `apps/api/apps`. Django is the only application service that talks to PostgreSQL.

## Shared Base

`apps.common.models.BaseModel`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID primary key | Generated with `uuid.uuid4`. |
| `created_at` | DateTime | Set on create. |
| `updated_at` | DateTime | Updated on save. |

All current domain models inherit this base.

## Current Django Apps And Models

| App | Model status |
| --- | --- |
| `common` | Implemented shared base and error helpers. |
| `organizations` | Implemented `Organization`. |
| `runbooks` | Implemented `Runbook`. |
| `workflows` | Implemented `Workflow`. |
| `executions` | Implemented `Execution` and `ExecutionStep`. |
| `approvals`, `audit`, `artifacts`, `integrations`, `policies`, `users` | Placeholder packages only; no implemented models. |

## Organization

`apps.organizations.models.Organization`

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | From `BaseModel`. |
| `name` | `CharField(255)` | Display name. |
| `slug` | `SlugField(64, unique=True)` | Globally unique today. |
| `created_at`, `updated_at` | DateTime | From `BaseModel`. |

Ordering: `name`.

## Runbook

`apps.runbooks.models.Runbook`

| Field | Type | Notes |
| --- | --- | --- |
| `organization` | FK to `Organization`, `PROTECT` | Tenant root. |
| `title` | `CharField(255)` | Human-authored runbook title. |
| `slug` | `SlugField(96)` | Unique per organization. |
| `raw_content` | `TextField` | Source runbook prose; preserved. |
| `status` | `CharField(24)` | `draft`, `ready`, `archived`; defaults to `draft`. |

Indexes:

- `organization`, `status`, `created_at`.

Constraints:

- Unique `organization`, `slug`.

## Workflow

`apps.workflows.models.Workflow`

| Field | Type | Notes |
| --- | --- | --- |
| `organization` | FK to `Organization`, `PROTECT` | Direct tenant scoping. |
| `runbook` | FK to `Runbook`, `PROTECT` | Source runbook. |
| `name` | `CharField(255)` | Derived workflow name. |
| `version` | `PositiveIntegerField` | Allocated per runbook. |
| `status` | `CharField(24)` | `draft`, `published`, `superseded`, `archived`; defaults to `draft`. |
| `definition_schema_version` | `CharField(32)` | Defaults to `workflow.schema.v1`. |
| `definition` | `JSONField` | Canonical structured workflow definition. |

Indexes:

- `organization`, `status`, `created_at`.

Constraints:

- Unique `runbook`, `version`.
- `version >= 1`.

## Execution

`apps.executions.models.Execution`

| Field | Type | Notes |
| --- | --- | --- |
| `organization` | FK to `Organization`, `PROTECT` | Direct tenant scoping. |
| `workflow` | FK to `Workflow`, `PROTECT` | Source workflow row. |
| `workflow_version` | `PositiveIntegerField` | Copied from workflow at execution creation. |
| `workflow_snapshot` | `JSONField` | Immutable execution-time copy of workflow definition. |
| `status` | `CharField(24)` | `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`; defaults to `queued`. |
| `started_at` | nullable DateTime | Set when first step starts or completion happens first. |
| `finished_at` | nullable DateTime | Set on completion. |
| `claimed_by_runner_id` | `CharField(255, blank=True)` | Runner that claimed the execution. |
| `claim_token` | nullable unique UUID | Django-generated ownership token; not exposed directly on public API. |
| `claimed_at` | nullable DateTime | Set on claim. |
| `last_heartbeat_at` | nullable DateTime | Set on claim and heartbeat. |

Indexes:

- `status`, `created_at`.
- `organization`, `created_at`.
- `workflow`, `created_at`.

## ExecutionStep

`apps.executions.models.ExecutionStep`

| Field | Type | Notes |
| --- | --- | --- |
| `execution` | FK to `Execution`, `CASCADE` | Aggregate child. |
| `position` | `PositiveIntegerField` | Order within execution. |
| `step_key` | `CharField(128)` | Copied from workflow step `id`. |
| `name` | `CharField(255)` | Copied step display name. |
| `step_type` | `CharField(64)` | Copied step type. |
| `risk_level` | `CharField(32)` | Copied risk value. |
| `command` | `TextField(blank=True)` | Copied command if present. |
| `requires_approval` | Boolean | Copied approval flag. No approval workflow is implemented yet. |
| `step_snapshot` | `JSONField` | Full copied step definition. |
| `status` | `CharField(24)` | `pending`, `running`, `succeeded`, `failed`, `skipped`; defaults to `pending`. |
| `started_at` | nullable DateTime | Set when step starts. |
| `finished_at` | nullable DateTime | Set when step succeeds or fails. |
| `exit_code` | nullable Integer | Set on terminal step update when supplied. |
| `error_message` | `TextField(blank=True)` | Set on failed step when supplied. |

Indexes:

- `execution`, `status`, `position`.

Constraints:

- Unique `execution`, `position`.
- Unique `execution`, `step_key`.

## Ownership Model

- `Organization` is the tenant root.
- `Runbook`, `Workflow`, and `Execution` carry direct `organization` FKs.
- `ExecutionStep` is scoped through `Execution`.
- Placeholder phase-10 apps must reuse this model unless an approved blueprint changes it.

## Tenant Scoping

Current implementation stores organization FKs but does not enforce authenticated tenant access because auth is deferred. Future auth work must add permission filtering without removing the direct organization ownership fields.

## Execution History And Snapshot Strategy

- `Workflow.definition` is mutable only through future workflow-version creation, not through execution records.
- `Execution.workflow_snapshot` stores the workflow definition at execution creation time.
- `ExecutionStep.step_snapshot` stores each step at materialization time.
- This lets old executions remain explainable after workflow versions change.

## Status Enums

| Model | Values |
| --- | --- |
| `Runbook` | `draft`, `ready`, `archived` |
| `Workflow` | `draft`, `published`, `superseded`, `archived` |
| `Execution` | `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled` |
| `ExecutionStep` | `pending`, `running`, `succeeded`, `failed`, `skipped` |

## Deletion Strategy

- Tenant and history-preserving relationships use `PROTECT`.
- `ExecutionStep.execution` uses `CASCADE` because steps are aggregate children of executions.
- No public delete API is implemented for core domain records.
- Future deletion behavior should prefer archival/status transitions unless a blueprint requires deletion.

## Migration Guidance

- Add model changes through Django migrations.
- Keep migrations narrow and review generated operations.
- Do not edit old migrations after they have been shared unless the repo is explicitly still before any shared database usage.
- Add data migrations only when necessary and document assumptions.
- Update this document when fields, relationships, indexes, constraints, or enum values change.

## Model Extension Rules

- Keep business rules in services unless the rule is row-local and model-intrinsic.
- Preserve UUID primary keys for domain entities.
- Preserve direct organization ownership for tenant-scoped root records.
- Do not add event queues or denormalized state unless the relevant phase is approved.
- Do not persist AI output before Django validates it.

## Planned Models From Blueprints

Planned and not currently implemented:

- `User` and `Membership`.
- Approval request models.
- Policy and policy evaluation models.
- Audit event models.
- Artifact models.
- Integration configuration and dispatch models.

Placeholder packages do not imply model implementation.
