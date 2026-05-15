# Phase 04 Blueprint: Versioned REST APIs

## 1. Phase Overview and Objectives

| Field | Value |
| --- | --- |
| Phase number | 04 |
| Objective | Build the first versioned REST API surface for the Runbook Platform under `/api/v1/`, keeping public CRUD separate from runner-only internal endpoints and preserving the existing service-layer architecture. |
| Status | Implemented; retained as planning blueprint |
| Primary outputs | Versioned route tree, public CRUD endpoints for organizations/runbooks/workflows/executions, internal runner endpoints for claim/heartbeat/step updates/completion, serializer split by use case, standardized error envelope, and an atomic concurrency-safe `claim-next` contract. |
| Dependencies | `/home/dylan/code/runbook-platform/docs/blueprints/phase-02-django-domain-foundation-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-03-application-service-layer-blueprint.md`, Django project scaffold in `/home/dylan/code/runbook-platform/apps/api`, PostgreSQL from `/home/dylan/code/runbook-platform/docker-compose.yml`, and workflow schema scaffold in `/home/dylan/code/runbook-platform/packages/contracts/workflow/workflow.schema.json`. |
| Local runtime source of truth | Docker Compose in `/home/dylan/code/runbook-platform/docker-compose.yml`. |
| Documentation basis reviewed on | 2026-03-31 |
| Official docs basis | Django 6.0 transactions and `select_for_update()` docs, DRF versioning, generic views, viewsets, routers, serializers, exceptions, and DRF 3.16 announcement. |

### Current repo alignment notes

As of 2026-04-27, the versioned public API and internal runner API are implemented under `/api/v1/` and `/api/v1/internal/`. Current endpoint and response details are maintained in `docs/architecture/api-contracts.md` and may differ slightly from early blueprint examples.

### Official Documentation Reviewed

- Django transactions: [https://docs.djangoproject.com/en/6.0/topics/db/transactions/](https://docs.djangoproject.com/en/6.0/topics/db/transactions/)
- Django `select_for_update()`: [https://docs.djangoproject.com/en/6.0/ref/models/querysets/#select-for-update](https://docs.djangoproject.com/en/6.0/ref/models/querysets/#select-for-update)
- DRF versioning: [https://www.django-rest-framework.org/api-guide/versioning/](https://www.django-rest-framework.org/api-guide/versioning/)
- DRF generic views: [https://www.django-rest-framework.org/api-guide/generic-views/](https://www.django-rest-framework.org/api-guide/generic-views/)
- DRF viewsets: [https://www.django-rest-framework.org/api-guide/viewsets/](https://www.django-rest-framework.org/api-guide/viewsets/)
- DRF routers: [https://www.django-rest-framework.org/api-guide/routers/](https://www.django-rest-framework.org/api-guide/routers/)
- DRF serializers: [https://www.django-rest-framework.org/api-guide/serializers/](https://www.django-rest-framework.org/api-guide/serializers/)
- DRF exceptions: [https://www.django-rest-framework.org/api-guide/exceptions/](https://www.django-rest-framework.org/api-guide/exceptions/)
- DRF 3.16 announcement: [https://www.django-rest-framework.org/community/3.16-announcement/](https://www.django-rest-framework.org/community/3.16-announcement/)

### Notes on Version Alignment

- The repo currently pins `Django>=5.0,<6.0` and `djangorestframework>=3.15,<4.0` in `/home/dylan/code/runbook-platform/apps/api/requirements/base.txt`.
- This blueprint intentionally uses the latest official documentation as the design basis.
- Recommended patterns are restricted to APIs that remain compatible with the repo’s current dependency range.
- No Django 6.0-only ORM or DRF 3.16-only public APIs are required to implement this phase.

### Locked Constraints for This Phase

- Health endpoints remain outside API versioning.
- Frontend talks only to Django.
- Runner talks only to Django API.
- Internal runner endpoints remain separate from public CRUD endpoints.
- Avoid generic unsafe `PATCH` semantics for runner state transitions.
- `claim-next` must be atomic and concurrency-safe.

### In Scope

- `/api/v1/` route tree
- public endpoints for `organizations`, `runbooks`, `workflows`, and `executions`
- internal runner endpoints under `/api/v1/internal/...`
- DRF serializer split for create/list/detail/action payloads
- explicit status transition actions
- standardized error responses
- request/response examples
- implementation-ready file layout, commands, and verification plan

### Out of Scope

- authentication and permission hardening beyond the minimum separation needed to keep internal endpoints isolated in structure
- pagination customization beyond light defaults
- schema generation or OpenAPI work
- websockets, SSE, or push updates
- background workers or queue-based execution dispatch
- direct frontend-to-runner or frontend-to-AI-service traffic
- direct runner-to-database access

### Phase Goal in One Sentence

Expose a stable `/api/v1/` Django API that supports public CRUD and runner orchestration while keeping business logic in services, state transitions explicit, and execution claiming safe under concurrent access.

## 2. API Design Principles for This Project

### 2.1 Versioning Strategy

- Keep the externally visible URL prefix as `/api/v1/`.
- Keep `/health/` outside versioning exactly as it exists today in `/home/dylan/code/runbook-platform/apps/api/config/urls.py`.
- Prefer DRF `NamespaceVersioning` instead of dynamic URL-path kwargs.
- Rationale:
  - clients still see `/api/v1/...`
  - the route tree stays explicit
  - DRF’s docs describe `NamespaceVersioning` as operationally easier to manage for larger projects than `URLPathVersioning`
  - `request.version` becomes available without making every URL pattern dynamic

### 2.2 Boundary Discipline

- React frontend calls only Django endpoints.
- Runner process calls only Django internal endpoints.
- AI service remains a dependency behind Django services, not a public client-facing API.
- Internal runner routes must never be added as extra actions on the same public viewset used for CRUD.

### 2.3 Explicit State Transitions

- Use explicit `POST` actions for state changes.
- Do not expose generic runner-facing `PATCH /executions/{id}/` or `PATCH /steps/{id}/`.
- Do not allow the runner to submit arbitrary field patches.
- Represent runner transitions as narrow actions with narrow serializers:
  - `claim-next`
  - `heartbeat`
  - `step-update`
  - `complete`

### 2.4 Thin Views, Rich Services

- Serializers validate and shape data.
- Views own HTTP transport only.
- Services own orchestration, transactions, and state transitions.
- Models continue to own row-local invariants and database constraints only.
- This matches the direction already established in `/home/dylan/code/runbook-platform/docs/blueprints/phase-03-application-service-layer-blueprint.md`.

### 2.5 Separate Serializers by Intent

- Create serializers validate write payloads.
- List serializers optimize summary views and avoid heavy blobs.
- Detail serializers expose richer read payloads.
- Action payload serializers validate narrow mutation actions.
- Do not reuse one giant serializer for all CRUD and action cases.

### 2.6 Concurrency Is a First-Class API Concern

- `claim-next` is not “just another POST”.
- It must be implemented with `transaction.atomic()` plus row locking.
- It must not depend on single-runner assumptions.
- It must remain safe if a second runner process is introduced later.

### 2.7 Stable Error Envelope

- Public and internal APIs must share one error contract.
- Conflicts and invalid transitions must be first-class API errors, not ad hoc JSON strings.
- Client code should be able to branch on `error.code`, not only on the human-readable message.

### 2.8 Payload Size Discipline

- List endpoints must not return large document bodies by default.
- `raw_content`, `definition`, `workflow_snapshot`, and `step_snapshot` belong in detail responses only.
- Nested detail responses should expose human-meaningful fields first and raw snapshots only when necessary.

### 2.9 URL and Action Naming

- Use plural nouns for resource collections:
  - `/organizations/`
  - `/runbooks/`
  - `/workflows/`
  - `/executions/`
- Use verb-like suffixes only for explicit actions:
  - `/mark-ready/`
  - `/archive/`
  - `/publish/`
  - `/cancel/`
  - `/claim-next/`
  - `/heartbeat/`
  - `/update/`
  - `/complete/`

## 3. Endpoint Inventory

### 3.1 Non-Versioned Endpoints

| Path | Method | Audience | Purpose |
| --- | --- | --- | --- |
| `/health/` | `GET` | ops, local dev, probes | Service health check. Must remain outside `/api/v1/`. |
| `/admin/` | `GET` | internal admin | Django admin. Not part of the public API contract. |

### 3.2 Public Versioned Endpoints

| Path | Method | Purpose |
| --- | --- | --- |
| `/api/v1/organizations/` | `GET` | List organizations. |
| `/api/v1/organizations/` | `POST` | Create organization. |
| `/api/v1/organizations/{organization_id}/` | `GET` | Retrieve organization detail. |
| `/api/v1/runbooks/` | `GET` | List runbooks. |
| `/api/v1/runbooks/` | `POST` | Create runbook. |
| `/api/v1/runbooks/{runbook_id}/` | `GET` | Retrieve runbook detail. |
| `/api/v1/runbooks/{runbook_id}/mark-ready/` | `POST` | Transition runbook from `draft` to `ready`. |
| `/api/v1/runbooks/{runbook_id}/archive/` | `POST` | Transition runbook from `draft` or `ready` to `archived`. |
| `/api/v1/workflows/` | `GET` | List workflows. |
| `/api/v1/workflows/` | `POST` | Create workflow from a runbook through the service layer. |
| `/api/v1/workflows/{workflow_id}/` | `GET` | Retrieve workflow detail. |
| `/api/v1/workflows/{workflow_id}/publish/` | `POST` | Publish a draft workflow. |
| `/api/v1/workflows/{workflow_id}/archive/` | `POST` | Archive a draft or superseded workflow. |
| `/api/v1/executions/` | `GET` | List executions. |
| `/api/v1/executions/` | `POST` | Create execution from a workflow. |
| `/api/v1/executions/{execution_id}/` | `GET` | Retrieve execution detail, including steps. |
| `/api/v1/executions/{execution_id}/cancel/` | `POST` | Cancel a queued execution. |

### 3.3 Internal Runner Endpoints

| Path | Method | Purpose |
| --- | --- | --- |
| `/api/v1/internal/executions/claim-next/` | `POST` | Atomically claim the next queued execution. |
| `/api/v1/internal/executions/{execution_id}/heartbeat/` | `POST` | Refresh runner lease metadata for the claimed execution. |
| `/api/v1/internal/executions/{execution_id}/steps/{step_id}/update/` | `POST` | Apply a narrow, validated execution-step state transition. |
| `/api/v1/internal/executions/{execution_id}/complete/` | `POST` | Mark the execution as terminal. |

### 3.4 Route Tree

```text
/health/
/admin/
/api/v1/
  organizations/
  organizations/{organization_id}/
  runbooks/
  runbooks/{runbook_id}/
  runbooks/{runbook_id}/mark-ready/
  runbooks/{runbook_id}/archive/
  workflows/
  workflows/{workflow_id}/
  workflows/{workflow_id}/publish/
  workflows/{workflow_id}/archive/
  executions/
  executions/{execution_id}/
  executions/{execution_id}/cancel/
  internal/
    executions/claim-next/
    executions/{execution_id}/heartbeat/
    executions/{execution_id}/steps/{step_id}/update/
    executions/{execution_id}/complete/
```

## 4. Public API Contract Details

### 4.1 Organizations

#### Supported Operations

- `GET /api/v1/organizations/`
- `POST /api/v1/organizations/`
- `GET /api/v1/organizations/{organization_id}/`

#### List Contract

Recommended response fields:

- `id`
- `name`
- `slug`
- `created_at`
- `updated_at`

Recommended query parameters:

- `slug`
- `search`

Do not add organization update/delete endpoints in this phase.

#### Create Contract

Request body:

```json
{
  "name": "Platform Ops",
  "slug": "platform-ops"
}
```

Validation rules:

- `name` required, trimmed, max length consistent with the model
- `slug` required, lowercase slug format
- `slug` unique across organizations

Create behavior:

- persist organization through `OrganizationCreateSerializer`
- return detail payload
- return `201 Created`

#### Detail Contract

Detail payload should match list payload for now. Keep it simple until organization-scoped metadata grows.

### 4.2 Runbooks

#### Supported Operations

- `GET /api/v1/runbooks/`
- `POST /api/v1/runbooks/`
- `GET /api/v1/runbooks/{runbook_id}/`
- `POST /api/v1/runbooks/{runbook_id}/mark-ready/`
- `POST /api/v1/runbooks/{runbook_id}/archive/`

#### List Contract

Recommended response fields:

- `id`
- `organization_id`
- `title`
- `slug`
- `status`
- `created_at`
- `updated_at`

Recommended query parameters:

- `organization_id`
- `status`
- `slug`
- `search`

List responses should not include `raw_content`.

#### Create Contract

Request body:

```json
{
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "title": "Rotate AWS Credentials",
  "slug": "rotate-aws-credentials",
  "raw_content": "1. Verify current IAM user context...\n2. Rotate access keys...\n3. Validate production automation..."
}
```

Validation rules:

- `organization_id` required and must exist
- `title` required
- `slug` required and unique within the organization if the model uses scoped uniqueness
- `raw_content` required and non-empty after trimming
- client may not set `status` directly on create

Create behavior:

- create runbook with `status = draft`
- use service-layer create flow if any orchestration already exists
- return detail serializer

#### Detail Contract

Recommended response fields:

- `id`
- `organization_id`
- `title`
- `slug`
- `status`
- `raw_content`
- `created_at`
- `updated_at`

#### Status Transition Rules

Allowed public transitions:

- `draft -> ready` via `POST /mark-ready/`
- `draft -> archived` via `POST /archive/`
- `ready -> archived` via `POST /archive/`

Disallowed transitions:

- `archived -> ready`
- `archived -> draft`
- direct client-set `status` in generic update payloads

Recommended status-action payloads:

- `mark-ready`: empty payload or `{}` in v1
- `archive`: empty payload or `{}` in v1

Even for empty payloads, use dedicated serializers so validation and future extensions stay explicit.

### 4.3 Workflows

#### Supported Operations

- `GET /api/v1/workflows/`
- `POST /api/v1/workflows/`
- `GET /api/v1/workflows/{workflow_id}/`
- `POST /api/v1/workflows/{workflow_id}/publish/`
- `POST /api/v1/workflows/{workflow_id}/archive/`

#### List Contract

Recommended response fields:

- `id`
- `organization_id`
- `runbook_id`
- `name`
- `version`
- `status`
- `definition_schema_version`
- `created_at`
- `updated_at`

Recommended query parameters:

- `organization_id`
- `runbook_id`
- `status`
- `version`

List responses should not include `definition`.

#### Create Contract

Request body:

```json
{
  "runbook_id": "22222222-2222-2222-2222-222222222222"
}
```

Validation rules:

- `runbook_id` required and must exist
- runbook must belong to the current accessible organization scope once auth is added
- create endpoint may not accept arbitrary workflow JSON from the client in v1

Create behavior:

- delegate to the workflow service
- derive workflow definition from the runbook through the service boundary
- assign next `version` atomically in the service layer
- create workflow with `status = draft`
- set `definition_schema_version`, expected default `workflow.schema.v1`

#### Detail Contract

Recommended response fields:

- `id`
- `organization_id`
- `runbook_id`
- `name`
- `version`
- `status`
- `definition_schema_version`
- `definition`
- `created_at`
- `updated_at`

The detail payload is the right place for the structured definition because the frontend will only talk to Django.

#### Status Transition Rules

Allowed public transitions:

- `draft -> published` via `POST /publish/`
- `draft -> archived` via `POST /archive/`
- `superseded -> archived` via `POST /archive/`

Recommended publish behavior:

- within one transaction, lock sibling workflows for the same runbook
- set any currently `published` workflow for that runbook to `superseded`
- set the target workflow to `published`

Disallowed transitions:

- `archived -> published`
- `published -> draft`
- direct `status` patching on generic update endpoints

This keeps workflow publication explicit and auditable without inventing unsafe partial update semantics.

### 4.4 Executions

#### Supported Operations

- `GET /api/v1/executions/`
- `POST /api/v1/executions/`
- `GET /api/v1/executions/{execution_id}/`
- `POST /api/v1/executions/{execution_id}/cancel/`

#### List Contract

Recommended response fields:

- `id`
- `organization_id`
- `workflow_id`
- `workflow_version`
- `status`
- `claimed_by_runner_id`
- `claimed_at`
- `last_heartbeat_at`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

Recommended query parameters:

- `organization_id`
- `workflow_id`
- `status`

List responses should not include:

- `workflow_snapshot`
- `step_snapshot`
- fully nested step objects

#### Create Contract

Request body:

```json
{
  "workflow_id": "33333333-3333-3333-3333-333333333333"
}
```

Validation rules:

- `workflow_id` required and must exist
- workflow must be structurally valid
- workflow definition must contain at least one step
- recommended: workflow must be `published` before execution creation is allowed

Create behavior:

- create one execution row with `status = queued`
- copy workflow version and workflow snapshot
- materialize step rows with `status = pending`
- perform all writes in one atomic transaction

#### Detail Contract

Recommended response fields:

- `id`
- `organization_id`
- `workflow_id`
- `workflow_version`
- `status`
- `claimed_by_runner_id`
- `claim_token_present`
- `claimed_at`
- `last_heartbeat_at`
- `started_at`
- `finished_at`
- `workflow_snapshot`
- `steps`
- `created_at`
- `updated_at`

Recommended nested step detail fields:

- `id`
- `position`
- `step_key`
- `name`
- `step_type`
- `risk_level`
- `command`
- `requires_approval`
- `status`
- `started_at`
- `finished_at`
- `exit_code`
- `error_message`

`claim_token_present` is a safer public read field than returning the raw claim token.

#### Status Transition Rules

Allowed public transition in Phase 04:

- `queued -> cancelled` via `POST /cancel/`

Disallowed public transitions:

- setting `claimed`, `running`, `succeeded`, or `failed` from public CRUD endpoints
- cancelling an already `running` execution
- generic `PATCH` to mutate execution state

Reasoning:

- runner owns operational transitions
- public API owns creation and safe user-triggered cancellation only
- anything broader would blur the boundary between the control plane and the execution engine

## 5. Internal Runner API Contract Details

### 5.1 Shared Rules for All Internal Endpoints

- All internal endpoints live under `/api/v1/internal/`.
- They are owned by Django, not by the runner process.
- They must not be registered on the public router for CRUD endpoints.
- They must use dedicated serializers and dedicated service functions.
- They must reject stale ownership:
  - wrong `runner_id`
  - wrong or missing `claim_token`
  - execution already terminal
- They should eventually use dedicated internal authentication, even if initial local development keeps auth permissive.

### 5.2 Required Execution Metadata for Internal APIs

The Phase 02 execution model intentionally deferred runner metadata. Phase 04 should add the minimum fields needed for safe internal orchestration:

- `claimed_by_runner_id`: `CharField(max_length=128, blank=True, default="")`
- `claim_token`: `UUIDField(blank=True, null=True, unique=True)`
- `claimed_at`: `DateTimeField(blank=True, null=True)`
- `last_heartbeat_at`: `DateTimeField(blank=True, null=True)`

Recommended additional index:

- composite index on `("status", "claimed_at", "created_at")`

These fields belong on `Execution`, not on a separate lease table, because the project is still in the first vertical slice and does not need a generalized leasing subsystem yet.

### 5.3 `claim-next`

#### Endpoint

- `POST /api/v1/internal/executions/claim-next/`

#### Purpose

- find the oldest queued execution
- atomically claim it
- return the execution plus its materialized steps to one runner only

#### Request Body

```json
{
  "runner_id": "runner-dev-01",
  "runner_version": "0.1.0",
  "requested_at": "2026-03-31T15:00:00Z"
}
```

#### Response When Work Is Claimed

```json
{
  "execution": {
    "id": "44444444-4444-4444-4444-444444444444",
    "organization_id": "11111111-1111-1111-1111-111111111111",
    "workflow_id": "33333333-3333-3333-3333-333333333333",
    "workflow_version": 2,
    "status": "claimed",
    "claimed_by_runner_id": "runner-dev-01",
    "claimed_at": "2026-03-31T15:00:01Z",
    "last_heartbeat_at": "2026-03-31T15:00:01Z",
    "workflow_snapshot": {
      "name": "Rotate AWS Credentials",
      "steps": [
        {
          "id": "verify-context",
          "name": "Verify caller identity",
          "type": "shell",
          "risk": "low",
          "command": "aws sts get-caller-identity"
        }
      ]
    },
    "steps": [
      {
        "id": "55555555-5555-5555-5555-555555555555",
        "position": 1,
        "step_key": "verify-context",
        "name": "Verify caller identity",
        "step_type": "shell",
        "risk_level": "low",
        "command": "aws sts get-caller-identity",
        "requires_approval": false,
        "status": "pending"
      }
    ]
  },
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "poll_after_seconds": 5
}
```

#### Response When No Work Is Available

```json
{
  "execution": null,
  "poll_after_seconds": 5
}
```

#### Validation Rules

- `runner_id` required
- runner cannot claim terminal executions
- only rows with `status = queued` are claimable
- claim must happen inside one transaction

#### State Transition

- `queued -> claimed`

#### Important Design Decision

Return `200 OK` with `execution: null` when no work exists.

Reasons:

- the request itself succeeded
- runner poll loops stay simple
- response shape remains stable
- `204 No Content` would remove the ability to return polling hints

### 5.4 `heartbeat`

#### Endpoint

- `POST /api/v1/internal/executions/{execution_id}/heartbeat/`

#### Purpose

- prove liveness for a claimed or running execution
- refresh `last_heartbeat_at`
- confirm the runner still owns the claim

#### Request Body

```json
{
  "runner_id": "runner-dev-01",
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "observed_status": "claimed",
  "sent_at": "2026-03-31T15:00:10Z"
}
```

#### Response Body

```json
{
  "execution_id": "44444444-4444-4444-4444-444444444444",
  "status": "claimed",
  "last_heartbeat_at": "2026-03-31T15:00:10Z"
}
```

#### Validation Rules

- execution must exist
- `runner_id` must match `claimed_by_runner_id`
- `claim_token` must match the stored token
- execution status must be `claimed` or `running`
- terminal executions reject heartbeats with `409 Conflict`

#### State Transition

- no lifecycle state change required
- metadata update only

### 5.5 `step-update`

#### Endpoint

- `POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/update/`

#### Purpose

- apply a narrow step transition
- optionally promote execution status to `running`
- update runtime fields safely

#### Request Body for Starting a Step

```json
{
  "runner_id": "runner-dev-01",
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "status": "running",
  "started_at": "2026-03-31T15:00:12Z"
}
```

#### Request Body for Completing a Step

```json
{
  "runner_id": "runner-dev-01",
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "status": "succeeded",
  "finished_at": "2026-03-31T15:00:20Z",
  "exit_code": 0,
  "error_message": ""
}
```

#### Request Body for Failing a Step

```json
{
  "runner_id": "runner-dev-01",
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "status": "failed",
  "finished_at": "2026-03-31T15:00:20Z",
  "exit_code": 1,
  "error_message": "aws sts get-caller-identity returned AccessDenied"
}
```

#### Response Body

```json
{
  "execution_id": "44444444-4444-4444-4444-444444444444",
  "step": {
    "id": "55555555-5555-5555-5555-555555555555",
    "status": "succeeded",
    "started_at": "2026-03-31T15:00:12Z",
    "finished_at": "2026-03-31T15:00:20Z",
    "exit_code": 0,
    "error_message": ""
  },
  "execution_status": "running"
}
```

#### Validation Rules

- runner ownership and `claim_token` must match
- `step_id` must belong to `execution_id`
- allowed step transitions:
  - `pending -> running`
  - `running -> succeeded`
  - `running -> failed`
  - `pending -> skipped` only if the runner explicitly skipped before execution of the step
- disallowed step transitions:
  - terminal back to non-terminal
  - `pending -> succeeded` in one jump
  - arbitrary field patching outside the narrow payload
- when a step becomes `running`, the execution should become `running` and set `started_at` if still null

#### Important Boundary Rule

`step-update` updates step state only. It must not silently mark the whole execution terminal. The runner must call `complete` explicitly when the overall execution is done.

### 5.6 `complete`

#### Endpoint

- `POST /api/v1/internal/executions/{execution_id}/complete/`

#### Purpose

- mark the execution terminal after the runner has finished orchestrating all step updates

#### Request Body

```json
{
  "runner_id": "runner-dev-01",
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "final_status": "succeeded",
  "finished_at": "2026-03-31T15:00:25Z",
  "error_message": ""
}
```

#### Failure Example

```json
{
  "runner_id": "runner-dev-01",
  "claim_token": "66666666-6666-6666-6666-666666666666",
  "final_status": "failed",
  "finished_at": "2026-03-31T15:00:25Z",
  "error_message": "Execution halted after step verify-context failed."
}
```

#### Response Body

```json
{
  "id": "44444444-4444-4444-4444-444444444444",
  "status": "succeeded",
  "finished_at": "2026-03-31T15:00:25Z"
}
```

#### Validation Rules

- `final_status` allowed values: `succeeded`, `failed`
- runner ownership and `claim_token` must match
- execution must currently be `claimed` or `running`
- `finished_at` required
- if `final_status = succeeded`, all steps must already be terminal and none may be `failed`
- if `final_status = failed`, at least one failed step or an execution-level failure reason should exist

#### State Transition

- `claimed -> failed` allowed if startup/setup failed before any step ran
- `running -> succeeded`
- `running -> failed`

## 6. Serializer Strategy

### 6.1 Core Rule

Each domain app should have separate serializers for:

- create inputs
- list outputs
- detail outputs
- action payloads

Do not use one serializer for all purposes.

### 6.2 Organizations Serializer Plan

Recommended classes in `/home/dylan/code/runbook-platform/apps/api/apps/organizations/serializers.py`:

- `OrganizationCreateSerializer`
- `OrganizationListSerializer`
- `OrganizationDetailSerializer`

Notes:

- create serializer validates `name` and `slug`
- list and detail serializers can be identical in Phase 04 if organization shape is still small
- keeping them separate now prevents later API drift

### 6.3 Runbooks Serializer Plan

Recommended classes in `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/serializers.py`:

- `RunbookCreateSerializer`
- `RunbookListSerializer`
- `RunbookDetailSerializer`
- `RunbookMarkReadySerializer`
- `RunbookArchiveSerializer`

Notes:

- list serializer excludes `raw_content`
- detail serializer includes `raw_content`
- action serializers stay narrow even if they are temporarily empty

### 6.4 Workflows Serializer Plan

Recommended classes in `/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py`:

- `WorkflowCreateSerializer`
- `WorkflowListSerializer`
- `WorkflowDetailSerializer`
- `WorkflowPublishSerializer`
- `WorkflowArchiveSerializer`

Notes:

- create serializer should accept `runbook_id`, not raw `definition`
- list serializer excludes `definition`
- detail serializer includes `definition`
- publish/archive serializers enforce transition intent explicitly

### 6.5 Executions Public Serializer Plan

Recommended classes in `/home/dylan/code/runbook-platform/apps/api/apps/executions/serializers.py`:

- `ExecutionCreateSerializer`
- `ExecutionListSerializer`
- `ExecutionDetailSerializer`
- `ExecutionStepDetailSerializer`
- `ExecutionCancelSerializer`

Notes:

- list serializer excludes `workflow_snapshot`
- detail serializer includes nested steps and may include `workflow_snapshot`
- cancel serializer exists even if empty in v1

### 6.6 Executions Internal Serializer Plan

Recommended classes in `/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_serializers.py`:

- `ClaimNextRequestSerializer`
- `ClaimNextResponseSerializer`
- `HeartbeatSerializer`
- `StepUpdateSerializer`
- `ExecutionCompleteSerializer`
- `InternalExecutionStepSerializer`

Notes:

- internal serializers must never be imported by public CRUD views
- `StepUpdateSerializer` should validate transition-specific required fields
- `ExecutionCompleteSerializer` should validate terminal state requirements

### 6.7 Serializer Validation Guidance

- Always call `serializer.is_valid(raise_exception=True)`.
- Prefer explicit validation methods over overly clever dynamic field mutation.
- Use `get_serializer_class()` on public viewsets for action-specific serializers.
- Keep service orchestration out of serializer `create()` and `update()` methods unless the operation is truly row-local.
- Do not hide claim logic inside serializer `save()`.

## 7. View / Viewset / Action Recommendations

### 7.1 Public API Views

Use `GenericViewSet` plus mixins for public resources:

- `ListModelMixin`
- `CreateModelMixin`
- `RetrieveModelMixin`

Recommended public viewsets:

- `OrganizationViewSet`
- `RunbookViewSet`
- `WorkflowViewSet`
- `ExecutionViewSet`

Recommended extra actions on public viewsets:

- `RunbookViewSet.mark_ready`
- `RunbookViewSet.archive`
- `WorkflowViewSet.publish`
- `WorkflowViewSet.archive`
- `ExecutionViewSet.cancel`

Reasons:

- DRF viewsets and routers are a good fit for grouped CRUD behavior
- `@action(detail=True, methods=["post"])` gives explicit state-change URLs
- `get_serializer_class()` cleanly selects create/list/detail/action serializers

### 7.2 Internal API Views

Use dedicated `APIView` classes for internal runner routes:

- `ClaimNextExecutionView`
- `ExecutionHeartbeatView`
- `ExecutionStepUpdateView`
- `ExecutionCompleteView`

Reasons:

- these are command-style endpoints, not CRUD resources
- using `APIView` keeps the separation from public `ExecutionViewSet` obvious
- the internal surface should remain intentionally narrow

### 7.3 Queryset Guidance

Public list/detail views should use:

- `select_related()` for direct foreign keys
- `prefetch_related()` for nested step collections when needed

This follows DRF generic-view guidance to avoid N+1 query patterns.

Suggested queryset approach:

- runbooks: `select_related("organization")`
- workflows: `select_related("organization", "runbook")`
- executions list: `select_related("organization", "workflow")`
- execution detail: `select_related("organization", "workflow").prefetch_related("steps")`

### 7.4 Route Registration Recommendation

Create one central versioned URL config at:

- `/home/dylan/code/runbook-platform/apps/api/config/api_v1_urls.py`

Recommended structure:

```python
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.organizations.views import OrganizationViewSet
from apps.runbooks.views import RunbookViewSet
from apps.workflows.views import WorkflowViewSet
from apps.executions.views import ExecutionViewSet
from apps.executions.internal_views import (
    ClaimNextExecutionView,
    ExecutionHeartbeatView,
    ExecutionStepUpdateView,
    ExecutionCompleteView,
)

router = SimpleRouter()
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("runbooks", RunbookViewSet, basename="runbook")
router.register("workflows", WorkflowViewSet, basename="workflow")
router.register("executions", ExecutionViewSet, basename="execution")

urlpatterns = [
    path("", include(router.urls)),
    path("internal/executions/claim-next/", ClaimNextExecutionView.as_view(), name="internal-execution-claim-next"),
    path("internal/executions/<uuid:execution_id>/heartbeat/", ExecutionHeartbeatView.as_view(), name="internal-execution-heartbeat"),
    path("internal/executions/<uuid:execution_id>/steps/<uuid:step_id>/update/", ExecutionStepUpdateView.as_view(), name="internal-execution-step-update"),
    path("internal/executions/<uuid:execution_id>/complete/", ExecutionCompleteView.as_view(), name="internal-execution-complete"),
]
```

### 7.5 Root URL Recommendation

Update `/home/dylan/code/runbook-platform/apps/api/config/urls.py` so the root URL config looks conceptually like:

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/v1/", include(("config.api_v1_urls", "api_v1"), namespace="v1")),
]
```

That keeps health outside versioning while giving versioned API routes a dedicated namespace.

### 7.6 Service Integration Pattern

View behavior should be:

1. validate request with the correct serializer
2. call the relevant service function
3. serialize the returned model or action result
4. return the HTTP response

Example service ownership:

- organizations: create and simple status-free CRUD can stay light
- runbooks: status transitions should delegate to explicit service functions
- workflows: create and publish should delegate to service functions
- executions: create, cancel, claim-next, heartbeat, step-update, and complete should all delegate to service functions

## 8. Claim-Next Concurrency Design

### 8.1 Why This Needs a Special Design

The race is straightforward:

1. runner A asks for the next queued execution
2. runner B asks at nearly the same time
3. both read the same queued row
4. both mark it claimed unless locking is correct

That failure mode is unacceptable because the platform would execute the same workflow twice.

### 8.2 Required Database Strategy

Use:

- PostgreSQL
- `transaction.atomic()`
- `select_for_update(skip_locked=True)`

The repo already uses PostgreSQL 17 in `/home/dylan/code/runbook-platform/docker-compose.yml`, so the recommended locking behavior matches the project’s actual runtime.

### 8.3 Required Query Shape

The candidate query should look conceptually like:

```python
Execution.objects.select_for_update(skip_locked=True).filter(
    status=ExecutionStatus.QUEUED,
).order_by("created_at", "id")
```

Important properties:

- only queued executions are eligible
- ordering is deterministic
- locked rows are skipped, not blocked on
- the lock and the status update occur in the same transaction

### 8.4 Required Atomic Flow

Recommended service pseudocode:

```python
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from apps.executions.models import Execution

def claim_next_execution(*, runner_id: str):
    now = timezone.now()

    with transaction.atomic():
        execution = (
            Execution.objects
            .select_for_update(skip_locked=True)
            .filter(status=Execution.Status.QUEUED)
            .order_by("created_at", "id")
            .first()
        )

        if execution is None:
            return None

        execution.status = Execution.Status.CLAIMED
        execution.claimed_by_runner_id = runner_id
        execution.claim_token = uuid4()
        execution.claimed_at = now
        execution.last_heartbeat_at = now
        execution.save(
            update_fields=[
                "status",
                "claimed_by_runner_id",
                "claim_token",
                "claimed_at",
                "last_heartbeat_at",
                "updated_at",
            ]
        )

    return execution
```

### 8.5 Row-Level Locking Notes

- `select_for_update()` only works correctly inside a transaction.
- Evaluating it in autocommit mode on supported backends is a transaction-management error.
- `skip_locked=True` is the right choice for poll-based claiming because it prevents runners from blocking on each other.
- Do not combine `nowait=True` with `skip_locked=True`.
- Keep the claim query narrow and avoid unnecessary joins.

### 8.6 Single-Runner Now, Multi-Runner Later

Even if the current deployment only runs one runner process:

- still implement row locking now
- still generate a `claim_token`
- still validate runner ownership on follow-up actions

Reasons:

- single-runner assumptions drift quickly
- the cost of getting this right now is low
- retrofitting claim safety after public usage begins is much riskier

### 8.7 What Not to Do

Do not:

- query the next queued execution outside a transaction and save it later
- read queued rows with `.first()` and then update in a separate ORM call
- rely on in-memory mutexes in the runner
- let the runner write directly to the database
- overload `PATCH /executions/{id}/` to mean “claim this row”

### 8.8 Multi-Runner Extension Later

This design is already compatible with multiple runners.

Future additions can build on it:

- lease expiry detection using `last_heartbeat_at`
- reclaiming stale claims
- runner capability filtering
- queue partitioning

None of those require changing the core atomic-claim contract if Phase 04 establishes it correctly.

## 9. Request/Response Examples

### 9.1 Create Organization

Request:

```http
POST /api/v1/organizations/
Content-Type: application/json

{
  "name": "Platform Ops",
  "slug": "platform-ops"
}
```

Response:

```json
{
  "id": "11111111-1111-1111-1111-111111111111",
  "name": "Platform Ops",
  "slug": "platform-ops",
  "created_at": "2026-03-31T14:00:00Z",
  "updated_at": "2026-03-31T14:00:00Z"
}
```

### 9.2 Create Runbook

Request:

```http
POST /api/v1/runbooks/
Content-Type: application/json

{
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "title": "Rotate AWS Credentials",
  "slug": "rotate-aws-credentials",
  "raw_content": "1. Verify current IAM user context...\n2. Rotate access keys...\n3. Validate production automation..."
}
```

Response:

```json
{
  "id": "22222222-2222-2222-2222-222222222222",
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "title": "Rotate AWS Credentials",
  "slug": "rotate-aws-credentials",
  "status": "draft",
  "raw_content": "1. Verify current IAM user context...\n2. Rotate access keys...\n3. Validate production automation...",
  "created_at": "2026-03-31T14:05:00Z",
  "updated_at": "2026-03-31T14:05:00Z"
}
```

### 9.3 Publish Workflow

Request:

```http
POST /api/v1/workflows/33333333-3333-3333-3333-333333333333/publish/
Content-Type: application/json

{}
```

Response:

```json
{
  "id": "33333333-3333-3333-3333-333333333333",
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "runbook_id": "22222222-2222-2222-2222-222222222222",
  "name": "Rotate AWS Credentials",
  "version": 2,
  "status": "published",
  "definition_schema_version": "workflow.schema.v1",
  "definition": {
    "name": "Rotate AWS Credentials",
    "steps": [
      {
        "id": "verify-context",
        "name": "Verify caller identity",
        "type": "shell",
        "risk": "low",
        "command": "aws sts get-caller-identity"
      }
    ]
  },
  "created_at": "2026-03-31T14:10:00Z",
  "updated_at": "2026-03-31T14:15:00Z"
}
```

### 9.4 Create Execution

Request:

```http
POST /api/v1/executions/
Content-Type: application/json

{
  "workflow_id": "33333333-3333-3333-3333-333333333333"
}
```

Response:

```json
{
  "id": "44444444-4444-4444-4444-444444444444",
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "workflow_id": "33333333-3333-3333-3333-333333333333",
  "workflow_version": 2,
  "status": "queued",
  "claimed_by_runner_id": "",
  "claimed_at": null,
  "last_heartbeat_at": null,
  "started_at": null,
  "finished_at": null,
  "created_at": "2026-03-31T14:20:00Z",
  "updated_at": "2026-03-31T14:20:00Z"
}
```

### 9.5 Retrieve Execution Detail

Response:

```json
{
  "id": "44444444-4444-4444-4444-444444444444",
  "organization_id": "11111111-1111-1111-1111-111111111111",
  "workflow_id": "33333333-3333-3333-3333-333333333333",
  "workflow_version": 2,
  "status": "running",
  "claimed_by_runner_id": "runner-dev-01",
  "claim_token_present": true,
  "claimed_at": "2026-03-31T15:00:01Z",
  "last_heartbeat_at": "2026-03-31T15:00:10Z",
  "started_at": "2026-03-31T15:00:12Z",
  "finished_at": null,
  "workflow_snapshot": {
    "name": "Rotate AWS Credentials",
    "steps": [
      {
        "id": "verify-context",
        "name": "Verify caller identity",
        "type": "shell",
        "risk": "low",
        "command": "aws sts get-caller-identity"
      }
    ]
  },
  "steps": [
    {
      "id": "55555555-5555-5555-5555-555555555555",
      "position": 1,
      "step_key": "verify-context",
      "name": "Verify caller identity",
      "step_type": "shell",
      "risk_level": "low",
      "command": "aws sts get-caller-identity",
      "requires_approval": false,
      "status": "running",
      "started_at": "2026-03-31T15:00:12Z",
      "finished_at": null,
      "exit_code": null,
      "error_message": ""
    }
  ],
  "created_at": "2026-03-31T14:20:00Z",
  "updated_at": "2026-03-31T15:00:12Z"
}
```

### 9.6 Claim Next With No Work

Request:

```http
POST /api/v1/internal/executions/claim-next/
Content-Type: application/json

{
  "runner_id": "runner-dev-01",
  "runner_version": "0.1.0",
  "requested_at": "2026-03-31T15:30:00Z"
}
```

Response:

```json
{
  "execution": null,
  "poll_after_seconds": 5
}
```

### 9.7 Invalid Runner Step Update

Response:

```json
{
  "error": {
    "code": "claim_token_mismatch",
    "message": "Execution is not owned by the supplied runner claim.",
    "details": {
      "execution_id": "44444444-4444-4444-4444-444444444444",
      "runner_id": "runner-dev-02"
    }
  },
  "status": 409
}
```

## 10. Error Model and Status Codes

### 10.1 Standard Error Envelope

All raised API errors should return:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Human readable summary.",
    "details": {}
  },
  "status": 400
}
```

Recommended conventions:

- `code` is stable and machine-readable
- `message` is concise and human-readable
- `details` is structured and safe to parse
- `status` mirrors the HTTP code for easier client logging

### 10.2 Validation Errors

Recommended response shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": {
      "slug": [
        "This field must be unique."
      ]
    }
  },
  "status": 400
}
```

### 10.3 Conflict Errors

Use `409 Conflict` for:

- invalid state transitions
- claim token mismatch
- attempting to claim or mutate a terminal execution
- publish or cancel operations rejected due to current state

Example codes:

- `invalid_state_transition`
- `execution_not_claimable`
- `claim_token_mismatch`
- `runner_ownership_mismatch`

### 10.4 Not Found Errors

Use `404 Not Found` for:

- missing organization
- missing runbook
- missing workflow
- missing execution
- step not found under the given execution

### 10.5 Server Errors

Use:

- `500 Internal Server Error` for unexpected failures
- `503 Service Unavailable` only for explicit dependency-unavailable cases

Do not leak stack traces or raw database exception strings in the response body.

### 10.6 DRF Implementation Recommendation

Create:

- custom `APIException` subclasses in `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`
- custom exception handler in `/home/dylan/code/runbook-platform/apps/api/apps/common/api_errors.py`

Configure in `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`:

```python
REST_FRAMEWORK = {
    ...,
    "EXCEPTION_HANDLER": "apps.common.api_errors.custom_exception_handler",
}
```

Important DRF note:

- the exception handler only standardizes raised exceptions
- therefore views should use `serializer.is_valid(raise_exception=True)` and raise typed exceptions instead of returning ad hoc `Response(..., status=...)` objects for error cases

### 10.7 Recommended Status Code Map

| HTTP status | When to use it |
| --- | --- |
| `200 OK` | successful reads, successful state actions, heartbeat, step update, completion, claim-next with or without work |
| `201 Created` | resource creation |
| `400 Bad Request` | serializer validation errors, malformed payloads |
| `401 Unauthorized` | future internal/public auth failures |
| `403 Forbidden` | authenticated caller lacks access |
| `404 Not Found` | resource does not exist in scope |
| `409 Conflict` | invalid transition or stale claim/ownership conflict |
| `500 Internal Server Error` | unexpected unhandled errors |
| `503 Service Unavailable` | explicit dependency or maintenance condition |

## 11. File-by-File Implementation Plan

### 11.1 Existing Files to Update

#### `/home/dylan/code/runbook-platform/apps/api/config/urls.py`

- keep `/health/` unchanged and outside versioning
- include `config.api_v1_urls` at `/api/v1/`
- keep admin path unchanged

#### `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`

- add DRF versioning config using `NamespaceVersioning`
- set allowed/default version to `v1`
- configure custom exception handler
- keep existing permissive defaults only if auth is still intentionally deferred

Recommended additions:

```python
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ("v1",),
    "EXCEPTION_HANDLER": "apps.common.api_errors.custom_exception_handler",
}
```

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/models.py`

- add runner-claim metadata fields:
  - `claimed_by_runner_id`
  - `claim_token`
  - `claimed_at`
  - `last_heartbeat_at`
- add any needed index for claim queries
- keep existing status model choices aligned with Phase 02

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py`

- add explicit status transition service functions if they do not exist yet:
  - `mark_runbook_ready`
  - `archive_runbook`

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`

- add explicit status transition service functions:
  - `publish_workflow`
  - `archive_workflow`

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py`

- keep `create_execution`
- add public `cancel_execution`

### 11.2 New Files to Create

#### `/home/dylan/code/runbook-platform/apps/api/config/api_v1_urls.py`

- central versioned router and internal route registration

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`

- typed API exceptions for:
  - not found
  - invalid transition
  - claim ownership mismatch
  - conflict

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/api_errors.py`

- custom DRF exception handler
- envelope-normalization helpers

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/serializers.py`

- organization create/list/detail serializers

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/views.py`

- `OrganizationViewSet`

#### `/home/dylan/code/runbook-platform/apps/api/apps/organizations/tests/test_api.py`

- organization API tests

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/serializers.py`

- runbook create/list/detail/action serializers

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/views.py`

- `RunbookViewSet`

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_api.py`

- runbook API tests

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py`

- workflow create/list/detail/action serializers

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/views.py`

- `WorkflowViewSet`

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api.py`

- workflow API tests

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/serializers.py`

- execution public serializers

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/views.py`

- `ExecutionViewSet`

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_serializers.py`

- runner-only serializers

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_views.py`

- internal runner API views

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/runner_services.py`

- `claim_next_execution`
- `heartbeat_execution`
- `update_execution_step`
- `complete_execution`

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_api.py`

- public execution API tests

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_runner_api.py`

- internal runner API tests

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_concurrency.py`

- `claim-next` concurrency tests using transaction-aware test classes

### 11.3 Migration Files

Create the next Django-generated migration under:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/migrations/`

Expected purpose:

- add execution claim metadata fields
- add indexes required for queue polling and ownership validation

Do not hand-author the migration filename until the actual sequence number is known.

## 12. Step-by-Step Implementation Checklist With Commands and Verification

### Step 1: Confirm Runtime Baseline

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose up -d
docker compose exec api python manage.py check
```

Verification:

- Django check passes
- `/health/` still responds

### Step 2: Add Versioned URL Entry Point

Files:

- `/home/dylan/code/runbook-platform/apps/api/config/urls.py`
- `/home/dylan/code/runbook-platform/apps/api/config/api_v1_urls.py`
- `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py check
```

Verification:

- `/health/` unchanged
- `/api/v1/` resolves without import errors
- `request.version` is available for versioned routes

### Step 3: Implement Common API Error Plumbing

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/common/api_errors.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py check
```

Verification:

- raised DRF/Django API errors return the standard envelope
- no ad hoc error payloads remain in new views

### Step 4: Implement Public Organizations API

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/organizations/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/organizations/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/organizations/tests/test_api.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.organizations.tests.test_api
```

Verification:

- create/list/detail work
- validation errors use the standard envelope

### Step 5: Implement Public Runbooks API

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_api.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.runbooks.tests.test_api
```

Verification:

- create/list/detail work
- `mark-ready` and `archive` transitions enforce rules
- list payload does not include `raw_content`

### Step 6: Implement Public Workflows API

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.workflows.tests.test_api
```

Verification:

- workflow creation delegates through services
- list payload excludes `definition`
- publish action supersedes the previous published version in one transaction if that behavior is implemented now

### Step 7: Extend Execution Model for Runner Claims

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/models.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/migrations/<next_migration>.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py makemigrations executions
docker compose exec api python manage.py migrate
```

Verification:

- execution table has claim metadata fields
- migrations apply cleanly

### Step 8: Implement Public Executions API

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_api.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.executions.tests.test_api
```

Verification:

- create/list/detail work
- detail returns nested steps
- cancel only works for valid states

### Step 9: Implement Internal Runner Endpoints

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/runner_services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_runner_api.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.executions.tests.test_runner_api
```

Verification:

- claim-next returns either one claimed execution or `execution: null`
- heartbeat requires runner ownership
- step-update enforces allowed transitions
- complete enforces terminal-state rules

### Step 10: Add Concurrency-Sensitive Tests

Files:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_concurrency.py`

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.executions.tests.test_concurrency
```

Verification:

- concurrent claim attempts never claim the same execution twice
- `skip_locked` behavior is proven against PostgreSQL
- tests use `TransactionTestCase` or equivalent transaction-aware strategy

### Step 11: Run Focused Full API Test Pass

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose exec api python manage.py test apps.organizations.tests apps.runbooks.tests apps.workflows.tests apps.executions.tests
docker compose exec api python manage.py check
```

Verification:

- no failing tests
- no import errors
- route tree is stable

## 13. API Testing Plan

### 13.1 Manual `curl` Smoke Tests

Create organization:

```bash
curl -sS http://localhost:8000/api/v1/organizations/ \
  -H 'Content-Type: application/json' \
  -d '{"name":"Platform Ops","slug":"platform-ops"}'
```

Create runbook:

```bash
curl -sS http://localhost:8000/api/v1/runbooks/ \
  -H 'Content-Type: application/json' \
  -d '{"organization_id":"11111111-1111-1111-1111-111111111111","title":"Rotate AWS Credentials","slug":"rotate-aws-credentials","raw_content":"1. Verify context"}'
```

Create workflow:

```bash
curl -sS http://localhost:8000/api/v1/workflows/ \
  -H 'Content-Type: application/json' \
  -d '{"runbook_id":"22222222-2222-2222-2222-222222222222"}'
```

Create execution:

```bash
curl -sS http://localhost:8000/api/v1/executions/ \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id":"33333333-3333-3333-3333-333333333333"}'
```

Claim next:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/claim-next/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","runner_version":"0.1.0","requested_at":"2026-03-31T15:00:00Z"}'
```

Heartbeat:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/44444444-4444-4444-4444-444444444444/heartbeat/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","claim_token":"66666666-6666-6666-6666-666666666666","observed_status":"claimed","sent_at":"2026-03-31T15:00:10Z"}'
```

Step update:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/44444444-4444-4444-4444-444444444444/steps/55555555-5555-5555-5555-555555555555/update/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","claim_token":"66666666-6666-6666-6666-666666666666","status":"running","started_at":"2026-03-31T15:00:12Z"}'
```

Complete execution:

```bash
curl -sS http://localhost:8000/api/v1/internal/executions/44444444-4444-4444-4444-444444444444/complete/ \
  -H 'Content-Type: application/json' \
  -d '{"runner_id":"runner-dev-01","claim_token":"66666666-6666-6666-6666-666666666666","final_status":"succeeded","finished_at":"2026-03-31T15:00:25Z","error_message":""}'
```

### 13.2 DRF/API Test Coverage

Public API tests should cover:

- create/list/detail for each public resource
- list serializer field shape versus detail serializer field shape
- explicit status actions only allow the intended transitions
- invalid action transitions return `409`
- create endpoints call services, not inline orchestration logic

Internal API tests should cover:

- claim-next returns `execution: null` when queue empty
- claim-next claims queued work exactly once
- heartbeat rejects wrong runner or wrong token
- step-update rejects invalid transitions
- complete rejects success when failed steps remain

### 13.3 Concurrency-Sensitive Checks

These checks are mandatory for `claim-next`:

- two concurrent claim requests against one queued execution should result in exactly one claim
- two concurrent claim requests against two queued executions should return two different execution IDs
- a locked queued row should be skipped, not block other claims
- claim query outside `atomic()` should be considered a test failure

### 13.4 Test Class Guidance

Use `TransactionTestCase` for locking tests.

Reason:

- Django’s docs explicitly warn that `TestCase` wraps tests in a transaction and can make `select_for_update()` behavior appear to work even when the code under test is not using explicit transaction boundaries correctly

### 13.5 Suggested Test Split

- `test_api.py`: normal public API behavior
- `test_runner_api.py`: runner endpoint behavior
- `test_concurrency.py`: locking and race tests only

Keep the concurrency tests separate so slow or transaction-heavy tests do not pollute ordinary API feedback loops.

## 14. Best Practices / Anti-Patterns

### Best Practices

- Keep `/health/` outside `/api/v1/`.
- Use namespaced versioned routes.
- Keep public CRUD and internal runner APIs in separate modules.
- Use explicit action endpoints for transitions.
- Use separate serializers for create/list/detail/action cases.
- Keep orchestration in services.
- Use `select_related()` and `prefetch_related()` intentionally.
- Use `transaction.atomic()` only where the business action actually needs it.
- Use `select_for_update(skip_locked=True)` for queue claiming.
- Return a stable error envelope everywhere.

### Anti-Patterns

- putting internal runner actions on `ExecutionViewSet`
- exposing generic `PATCH` for runner lifecycle changes
- implementing claim-next as “query then save later”
- catching database errors inside the same `atomic()` block and continuing as if nothing happened
- returning large blobs in list endpoints
- letting the runner call the database directly
- letting the frontend call the runner or AI service directly
- enabling `ATOMIC_REQUESTS` globally for every API request
- hiding business orchestration inside serializer `save()` methods

## 15. Codex Batching and Approval Gates

### Batch A: Routing and Error Foundation

Scope:

- versioned URL entry point
- DRF settings for versioning and exception handling
- common exception utilities

Approval gate:

- stop after `/api/v1/` routing loads cleanly and the error envelope exists

### Batch B: Public Organizations and Runbooks

Scope:

- organization CRUD
- runbook CRUD plus explicit runbook status actions

Approval gate:

- stop after public create/list/detail/status tests pass for these two resources

### Batch C: Public Workflows and Executions

Scope:

- workflow create/list/detail/publish/archive
- execution create/list/detail/cancel

Approval gate:

- stop after serializer split and service integration are verified

### Batch D: Execution Claim Metadata and Internal Runner Endpoints

Scope:

- execution model migration for claim metadata
- claim-next, heartbeat, step-update, complete

Approval gate:

- stop after all internal endpoint tests pass

### Batch E: Concurrency Verification and Final Hardening

Scope:

- transaction-aware concurrency tests
- focused route and serializer cleanup
- final API check

Approval gate:

- stop only after atomic-claim tests prove no double-claim behavior

### Batch Discipline Rules for Codex

- make one batch of code changes at a time
- run verification after each batch
- do not begin internal runner work before public execution contracts are stable
- do not merge public and internal views into one file “for convenience”
- do not sign off without concurrency checks

## 16. Definition of Done

Phase 04 is done only when all of the following are true:

- `/health/` still exists outside versioned API routing.
- `/api/v1/` exists and is the only public API namespace introduced in this phase.
- public endpoints for organizations, runbooks, workflows, and executions are implemented.
- internal runner endpoints exist only under `/api/v1/internal/...`.
- public CRUD endpoints and internal runner endpoints are implemented in separate modules.
- create/list/detail serializers are separate for each public resource.
- explicit action serializers exist for status transitions.
- public lifecycle transitions use explicit `POST` actions, not generic unsafe patching.
- runner state transitions do not use generic `PATCH`.
- `claim-next` is implemented with `transaction.atomic()` and row-level locking.
- concurrent claim attempts cannot claim the same execution twice.
- error responses use one standardized envelope.
- request/response examples in this blueprint match the implemented API shape.
- DRF/API tests pass for public endpoints.
- transaction-aware tests pass for `claim-next`.
- frontend still only needs Django.
- runner still only needs Django API.

## Recommended Final Route, View, and Serializer Summary

### Route Structure

```text
/home/dylan/code/runbook-platform/apps/api/config/urls.py
/home/dylan/code/runbook-platform/apps/api/config/api_v1_urls.py
```

### View Structure

```text
/home/dylan/code/runbook-platform/apps/api/apps/organizations/views.py
/home/dylan/code/runbook-platform/apps/api/apps/runbooks/views.py
/home/dylan/code/runbook-platform/apps/api/apps/workflows/views.py
/home/dylan/code/runbook-platform/apps/api/apps/executions/views.py
/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_views.py
```

### Serializer Structure

```text
/home/dylan/code/runbook-platform/apps/api/apps/organizations/serializers.py
/home/dylan/code/runbook-platform/apps/api/apps/runbooks/serializers.py
/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py
/home/dylan/code/runbook-platform/apps/api/apps/executions/serializers.py
/home/dylan/code/runbook-platform/apps/api/apps/executions/internal_serializers.py
```

### Service Integration Structure

```text
/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py
/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py
/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py
/home/dylan/code/runbook-platform/apps/api/apps/executions/runner_services.py
```

The most important operational rule in this entire phase is simple:

`claim-next` must select and mutate the queued execution inside the same database transaction while holding a row lock.
