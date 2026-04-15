# Phase 03 Blueprint: Application Service Layer

## 1. Phase Overview

| Field | Value |
| --- | --- |
| Phase number | 03 |
| Objective | Introduce a clean Django application service layer for the first real vertical slice so create flows are orchestrated in services instead of views, while preserving the AI-service boundary and execution-history immutability. |
| Status | Planned |
| Primary outcomes | `create_runbook`, `create_workflow`, and `create_execution` service flows; deterministic stub workflow transformation behind an internal client boundary; explicit transaction boundaries; consistent error contract; tests focused on services and API-adjacent behavior. |
| Dependencies | `/home/dylan/code/runbook-platform/docs/blueprints/phase-02-django-domain-foundation-blueprint.md`, domain models in `organizations`, `runbooks`, `workflows`, `executions`, and the placeholder AI service in `/home/dylan/code/runbook-platform/apps/ai`. |
| In-scope apps | `/home/dylan/code/runbook-platform/apps/api/apps/runbooks`, `/home/dylan/code/runbook-platform/apps/api/apps/workflows`, `/home/dylan/code/runbook-platform/apps/api/apps/executions`, plus small shared support in `/home/dylan/code/runbook-platform/apps/api/apps/common`. |
| Out of scope | Real approvals, policies, audit, artifacts, background jobs, full auth, permissions hardening, real AI inference, runner claim/advance flows, and broad CRUD beyond the vertical-slice create paths. |
| Documentation basis reviewed on | 2026-03-31 |
| Official docs basis | Django 6.0 transactions docs, Django model/constraint docs, DRF 3.16 serializer docs, DRF generic-view docs, DRF exception docs, and the DRF 3.16 announcement. |

### Official Documentation Reviewed

- Django transactions: [https://docs.djangoproject.com/en/6.0/topics/db/transactions/](https://docs.djangoproject.com/en/6.0/topics/db/transactions/)
- Django constraints: [https://docs.djangoproject.com/en/5.0/ref/models/constraints/](https://docs.djangoproject.com/en/5.0/ref/models/constraints/)
- DRF serializers: [https://www.django-rest-framework.org/api-guide/serializers/](https://www.django-rest-framework.org/api-guide/serializers/)
- DRF generic views: [https://www.django-rest-framework.org/api-guide/generic-views/](https://www.django-rest-framework.org/api-guide/generic-views/)
- DRF exceptions: [https://www.django-rest-framework.org/api-guide/exceptions/](https://www.django-rest-framework.org/api-guide/exceptions/)
- DRF 3.16 announcement: [https://www.django-rest-framework.org/community/3.16-announcement/](https://www.django-rest-framework.org/community/3.16-announcement/)

### Notes on Version Alignment

- The repo currently pins `Django>=5.0,<6.0` and `djangorestframework>=3.15,<4.0` in `/home/dylan/code/runbook-platform/apps/api/requirements/base.txt`.
- This blueprint uses the latest official Django and DRF documentation as the architectural basis, per requirement.
- Recommended patterns are intentionally restricted to APIs that are compatible with the repo’s current dependency range. No 6.0-only features are required to implement this phase.

### Phase Goal in One Sentence

Move orchestration for runbook creation, workflow generation, and execution creation into explicit application services so views stay thin, serializers stay focused on validation, and models keep only row-local invariants.

## 2. Why the Service Layer Matters in This Architecture

This repository is explicitly split into a control plane and dependencies:

- React is UI only.
- Django is orchestration plus persistence.
- FastAPI AI is a dependency, not the source of truth.
- Runner executes steps, but should not invent workflow or execution records directly.

That architecture breaks down quickly if create flows are implemented ad hoc inside DRF views or serializers. The create paths in this project are not plain `serializer.save()` cases:

- creating a `Runbook` is simple persistence with tenant scoping and uniqueness handling
- creating a `Workflow` requires derived-data generation from a `Runbook`
- creating an `Execution` requires fan-out from one `Workflow` row into one `Execution` row plus many `ExecutionStep` rows

Those are orchestration concerns, not representation concerns.

Using a service layer here solves five concrete problems:

1. It gives Django a clear place to coordinate multiple model writes.
2. It preserves the AI-service boundary even when workflow transformation is stubbed locally.
3. It keeps DRF serializers in their strongest role: input validation and output representation.
4. It makes transaction scopes explicit instead of accidentally tying them to the entire request lifecycle.
5. It creates a test seam where business behavior can be unit-tested without invoking full request/response plumbing.

### Architectural Inference from Official Docs

The official docs do not prescribe a single “service layer” pattern. The recommendation here is an inference from how the official docs separate responsibilities:

- Django models are the data definition and row behavior layer.
- Django transactions are explicit and should be scoped deliberately with `transaction.atomic()`.
- DRF serializers validate and transform input/output data.
- DRF generic views provide hooks such as `perform_create()`, but those hooks are still view-layer entry points, not a substitute for domain orchestration.

For this codebase, the cleanest result is:

- models own small invariants and persistence structure
- serializers own validation and serialization
- services own orchestration and transactions
- views own HTTP concerns and delegation

## 3. Target Module Layout and Recommended Package Structure

### Recommended Layout

Keep the application layer shallow and explicit. Do not introduce a large “services framework”. A few focused modules are enough for this vertical slice.

```text
/home/dylan/code/runbook-platform/apps/api/apps/
  common/
    __init__.py
    api_errors.py
    exceptions.py
  runbooks/
    __init__.py
    models.py
    serializers.py
    services.py
    views.py
    urls.py
    tests/
      __init__.py
      test_services.py
      test_api.py
  workflows/
    __init__.py
    models.py
    serializers.py
    internal_clients.py
    services.py
    views.py
    urls.py
    tests/
      __init__.py
      test_services.py
      test_internal_clients.py
      test_api.py
  executions/
    __init__.py
    models.py
    serializers.py
    services.py
    views.py
    urls.py
    tests/
      __init__.py
      test_services.py
      test_api.py
```

### Minimum Required New Phase-03 Modules

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/internal_clients.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py`

### Why `internal_clients.py` Exists

Only the workflow flow needs an internal client in this phase. That file exists to preserve this boundary:

- Django application service requests a transformation
- internal client provides the transformation
- implementation is a deterministic stub today
- implementation can become HTTP to `/parse/runbook` or `/enrich/workflow` later

The workflow service must depend on an interface or thin client object, not on inline transformation logic buried inside the service function.

### Package-Structure Guidance

- Use one `services.py` per app for this phase. The scope is still small.
- Do not create `services/commands/handlers` subpackages yet.
- Use a `tests/` package rather than one monolithic `tests.py` because service and API-adjacent tests will diverge immediately.
- Keep common exceptions and error-envelope code in `common`, not duplicated per app.

## 4. Responsibilities Matrix

| Layer | Owns | Allowed to know | Must not do | Examples in this phase |
| --- | --- | --- | --- | --- |
| Models | schema, small invariants, DB constraints, enum choices, convenience properties | row-local state, FK structure, uniqueness/check constraints | multi-model orchestration, HTTP concerns, external service calls, request parsing | `Workflow.version >= 1`, `UniqueConstraint(runbook, version)`, execution/status enums |
| Serializers | request validation, output shape, field normalization | request payload shape, serializer context, model-backed validation | creating multiple records across aggregates, external calls, transaction coordination, business workflow branching | validate `title`, `slug`, `raw_content`; validate `workflow_id`; render response payload |
| Services | orchestration, transactions, aggregate creation, domain branching, mapping low-level exceptions to domain exceptions | models, internal clients, transaction boundaries, domain rules for the vertical slice | reading HTTP headers directly, constructing `Response`, coupling to DRF internals | `create_runbook`, `create_workflow`, `create_execution` |
| Views | HTTP transport, lookup of request-scoped objects, serializer invocation, permission hooks, response codes | requests, serializers, service calls | inline business logic, cross-model write orchestration, transformation logic | `POST /api/v1/runbooks/`, `POST /api/v1/workflows/`, `POST /api/v1/executions/` |
| Internal clients | boundary to other processes or swappable adapters | external endpoint contract or stub contract | DB writes, HTTP response creation, serializer validation | deterministic stub transformer in `workflows/internal_clients.py` |

### Layer Boundaries in Plain Language

- Views may decide which service to call, but not how the workflow is generated or how execution steps are materialized.
- Serializers may reject bad inputs, but they must not create an `Execution` and its `ExecutionStep` children.
- Models may reject invalid rows with constraints, but they must not “reach out” to the AI service or perform request-aware behavior.
- Services may compose model operations and internal client calls, but they should not import DRF `Response` objects or encode HTTP status codes.

## 5. Service Boundaries vs Serializers vs Models vs Views

### Recommended Rule Set

- Business logic must not live in views.
- Models should only hold small invariants.
- Serializers are for validation, not orchestration.
- Workflow creation must preserve the AI-service boundary even if stubbed.
- Execution creation must expand workflow steps into execution-step records.

### What Goes in Models

Allowed:

- status enums with `TextChoices`
- DB constraints
- row-level helper properties
- minimal `clean()` logic if truly row-local

Not allowed:

- “when a workflow is created also create execution steps”
- “when a runbook is saved auto-generate a workflow”
- HTTP calls to the AI service
- request-user-dependent behavior

### What Goes in Serializers

Allowed:

- required/optional field declarations
- field and object validation
- normalization of empty strings, trimmed text, slug validation
- read serializer composition for API output

Not allowed:

- opening transactions for aggregate creation
- calling AI clients directly
- assigning workflow versions
- copying workflow snapshots into execution rows

### What Goes in Views

Allowed:

- request parsing through serializers
- loading parent objects from URL parameters
- invoking services
- mapping service results to response serializers

Not allowed:

- building workflow JSON
- incrementing versions manually
- iterating through workflow steps to create execution rows
- catching `IntegrityError` and hand-authoring inconsistent response formats in each endpoint

### What Goes in Services

Allowed:

- transaction coordination
- sequencing model writes
- version assignment
- AI/stub transform orchestration
- immutable snapshot creation
- translation of `IntegrityError` and stale-state conditions into domain exceptions

Not allowed:

- direct dependency on DRF `Request`, `Response`, or serializer classes
- HTML/JSON rendering
- broad framework-level policy logic that is out of scope for the vertical slice

## 6. Detailed Design: `create_runbook`

### Purpose

Create a `Runbook` row as the durable authored source document for an organization.

### File

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py`

### Suggested Interface

```python
from apps.organizations.models import Organization
from apps.runbooks.models import Runbook

def create_runbook(
    *,
    organization: Organization,
    title: str,
    slug: str,
    raw_content: str,
) -> Runbook:
    ...
```

### Inputs

- `organization`
- `title`
- `slug`
- `raw_content`

### Outputs

- newly created `Runbook` instance

### Preconditions

- `organization` already exists and is already resolved by the caller
- serializer already validated request shape and basic field rules
- `raw_content` is non-empty after validation

### Service Responsibilities

- create the row
- normalize only what belongs to orchestration-level safety, if any
- translate uniqueness failures into a domain-specific conflict error
- return the created instance

### Explicit Non-Responsibilities

- generating a workflow automatically
- parsing runbook content
- calling the AI service
- writing audit records

### Flow

1. Receive already-validated inputs.
2. Open a small `transaction.atomic()` block.
3. Call `Runbook.objects.create(...)`.
4. Catch `IntegrityError` outside the atomic block and translate likely `(organization, slug)` collisions into a domain exception.
5. Return the created `Runbook`.

### Pseudocode

```python
from django.db import IntegrityError, transaction

from apps.common.exceptions import DomainConflictError
from apps.runbooks.models import Runbook

def create_runbook(*, organization, title, slug, raw_content):
    try:
        with transaction.atomic():
            runbook = Runbook.objects.create(
                organization=organization,
                title=title,
                slug=slug,
                raw_content=raw_content,
            )
    except IntegrityError as exc:
        raise DomainConflictError(
            code="runbook_slug_conflict",
            detail="A runbook with this slug already exists in the organization.",
            attr="slug",
        ) from exc

    return runbook
```

### Notes

- This service should stay small. Over-design here is a mistake.
- Uniqueness is enforced by the database, not by a preflight `.exists()` check.
- A preflight existence check can still race; the DB constraint is the real guardrail.

## 7. Detailed Design: `create_workflow`

### Purpose

Create a derived `Workflow` for a `Runbook` while preserving the AI-service boundary. In Phase 03, the transformer is deterministic and local, but the workflow service must still call through an internal client boundary.

### Files

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/internal_clients.py`

### Suggested Internal Client Interface

```python
from typing import Protocol

class WorkflowTransformClient(Protocol):
    def transform_runbook(
        self,
        *,
        runbook_title: str,
        runbook_slug: str,
        raw_content: str,
    ) -> dict:
        ...
```

### Suggested Service Interface

```python
from apps.runbooks.models import Runbook
from apps.workflows.models import Workflow

def create_workflow(
    *,
    runbook: Runbook,
    transform_client: WorkflowTransformClient,
) -> Workflow:
    ...
```

### Inputs

- `runbook`
- `transform_client`

### Outputs

- newly created `Workflow`

### Preconditions

- `runbook` exists
- `runbook.raw_content` is present
- `runbook.organization` is available
- serializer or caller has already validated user input such as the runbook reference

### Service Responsibilities

- request a workflow definition from the client boundary
- validate the returned structure at the service boundary before persisting
- assign the next workflow version safely
- persist the workflow row
- translate malformed transform output or version conflicts into domain exceptions

### Explicit Non-Responsibilities

- deciding HTTP response codes
- embedding stub transform rules inline in the service function
- performing real AI calls in this phase

### Required Orchestration Sequence

The order matters:

1. Resolve `runbook`.
2. Call the internal transform client outside the DB transaction.
3. Validate the returned definition shape.
4. Open `transaction.atomic()`.
5. Lock the parent `Runbook` row with `select_for_update()` to serialize version assignment for that runbook.
6. Compute `next_version`.
7. Create the `Workflow`.
8. Translate integrity/concurrency failures into domain exceptions.

### Why the Transform Call Must Be Outside the Transaction

Even with a deterministic stub, this call represents the future AI boundary. Keeping it outside the transaction preserves the correct architecture now:

- no long-lived transaction while waiting on an external dependency
- no accidental coupling between network latency and DB locks later
- easier replacement of the stub with a real HTTP client

### Suggested Workflow Row Shape

The persisted `Workflow` should at minimum include:

- `organization = runbook.organization`
- `runbook = runbook`
- `name = runbook.title`
- `version = next_version`
- `status = draft` or `published`, depending on the Phase 02 model decision
- `definition_schema_version = "workflow.schema.v1"`
- `definition = <validated transform result>`

### Pseudocode

```python
from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.common.exceptions import (
    ConcurrencyConflictError,
    InvalidWorkflowDefinitionError,
)
from apps.runbooks.models import Runbook
from apps.workflows.models import Workflow

def create_workflow(*, runbook, transform_client):
    definition = transform_client.transform_runbook(
        runbook_title=runbook.title,
        runbook_slug=runbook.slug,
        raw_content=runbook.raw_content,
    )
    validate_workflow_definition(definition)

    try:
        with transaction.atomic():
            locked_runbook = (
                Runbook.objects
                .select_for_update()
                .select_related("organization")
                .get(pk=runbook.pk)
            )

            latest_version = (
                Workflow.objects
                .filter(runbook=locked_runbook)
                .aggregate(max_version=Max("version"))
                ["max_version"]
                or 0
            )

            workflow = Workflow.objects.create(
                organization=locked_runbook.organization,
                runbook=locked_runbook,
                name=locked_runbook.title,
                version=latest_version + 1,
                definition_schema_version="workflow.schema.v1",
                definition=definition,
            )
    except IntegrityError as exc:
        raise ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ) from exc

    return workflow
```

### Service-Level Validation of Returned Definition

The service must validate the transform output before writing it:

- top-level object is a dict
- `schema_version` exists and equals `workflow.schema.v1`
- `steps` exists and is a non-empty list
- every step has `step_key`, `name`, `step_type`, `risk_level`, `requires_approval`
- `step_key` values are unique within the definition

This is not serializer validation because the definition is not direct user input. It is boundary validation for an internal dependency.

## 8. Detailed Design: `create_execution`

### Purpose

Create an immutable execution snapshot from a workflow and expand workflow steps into `ExecutionStep` rows in the same transaction.

### File

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py`

### Suggested Interface

```python
from apps.workflows.models import Workflow
from apps.executions.models import Execution

def create_execution(*, workflow: Workflow) -> Execution:
    ...
```

### Inputs

- `workflow`

### Outputs

- newly created `Execution`

### Preconditions

- `workflow` exists
- `workflow.definition` is structurally valid
- workflow contains at least one step

### Service Responsibilities

- validate that the workflow definition can be expanded
- create one `Execution` row
- copy the workflow definition into `Execution.workflow_snapshot`
- copy workflow metadata needed for history
- create one `ExecutionStep` per workflow step
- guarantee all-or-nothing creation for the aggregate

### Explicit Non-Responsibilities

- runner claim logic
- step execution
- real approval enforcement
- audit/artifact writes

### Required Aggregate Behavior

Execution creation is the first place immutability becomes operationally important. The service must copy, not reference live mutable workflow state.

Required copy behavior:

- `Execution.workflow_snapshot` receives the full workflow definition
- `Execution.workflow_version` receives `workflow.version` if that field exists on the model
- `ExecutionStep.step_snapshot` receives the full step payload
- `ExecutionStep.step_key`, `name`, `step_type`, `risk_level`, `command`, and `requires_approval` are copied from the step snapshot

### Suggested Expansion Logic

For each step in `workflow.definition["steps"]`:

- preserve source order
- assign `position` starting at 1
- create step rows with `status = pending`
- leave runtime fields null or empty

### Pseudocode

```python
from django.db import IntegrityError, transaction

from apps.common.exceptions import InvalidWorkflowDefinitionError
from apps.executions.models import Execution, ExecutionStep

def create_execution(*, workflow):
    definition = workflow.definition
    validate_workflow_definition(definition)

    steps = definition["steps"]
    if not steps:
        raise InvalidWorkflowDefinitionError(
            code="workflow_has_no_steps",
            detail="Workflow definition must contain at least one step.",
        )

    try:
        with transaction.atomic():
            execution = Execution.objects.create(
                organization=workflow.organization,
                workflow=workflow,
                workflow_snapshot=definition,
                workflow_version=workflow.version,
            )

            step_rows = []
            for position, step in enumerate(steps, start=1):
                step_rows.append(
                    ExecutionStep(
                        execution=execution,
                        position=position,
                        step_key=step["step_key"],
                        name=step["name"],
                        step_type=step["step_type"],
                        risk_level=step["risk_level"],
                        command=step.get("command"),
                        requires_approval=step.get("requires_approval", False),
                        step_snapshot=step,
                    )
                )

            ExecutionStep.objects.bulk_create(step_rows)
    except IntegrityError as exc:
        raise InvalidWorkflowDefinitionError(
            code="execution_step_materialization_failed",
            detail="Execution steps could not be materialized from the workflow definition.",
        ) from exc

    return execution
```

### Why This Must Be Atomic

An `Execution` without its steps is a broken aggregate. The service must never leave:

- an execution row without step rows
- partial step fan-out
- duplicated positions or duplicate `step_key` values within the same execution

## 9. Transaction Design

### Official Guidance Applied

Django’s transaction docs recommend explicit `transaction.atomic()` blocks and warn that per-request transactions via `ATOMIC_REQUESTS` add overhead and can become inefficient as traffic grows. That is the right fit for this architecture:

- keep default autocommit mode
- use explicit `transaction.atomic()` in application services
- do not rely on request-wide transactions in views

### Where `transaction.atomic()` Should Be Used

Use `transaction.atomic()` inside service functions:

- `create_runbook`
- `create_workflow`
- `create_execution`

### What Should Be Atomic

`create_runbook`

- one `Runbook` create
- any immediate same-aggregate row writes, if those are added later

`create_workflow`

- parent row lock for version assignment
- version calculation
- one `Workflow` create

`create_execution`

- one `Execution` create
- all `ExecutionStep` creates

### What Should Not Be Atomic

- serializer validation
- request parsing
- HTTP rendering
- the deterministic transform client call
- future real network calls to the AI service

### Avoid `ATOMIC_REQUESTS`

Do not enable request-wide transactions in settings for this phase.

Reasons:

- the docs explicitly warn about overhead for every request
- the create flows have different transaction needs
- the workflow transform boundary should remain outside the transaction
- request-wide transactions make it easier for business logic to drift back into views

### Savepoint Guidance

- Default nested savepoint behavior is fine if a helper function later needs an inner `atomic()` block.
- Do not add nested transactions prematurely in Phase 03.
- Prefer one top-level atomic block per service operation.

### Exception-Handling Guidance Around Transactions

Follow Django’s guidance and do not swallow database exceptions inside the `atomic()` block. Pattern:

```python
try:
    with transaction.atomic():
        ...
except IntegrityError as exc:
    ...
```

Do not do this:

```python
with transaction.atomic():
    try:
        ...
    except IntegrityError:
        ...
```

### `transaction.on_commit()` Guidance

This phase should not require `transaction.on_commit()` because out-of-scope features such as audit events, emails, and background jobs are deferred.

If a later phase needs post-commit work:

- use `transaction.on_commit()`
- keep that callback outside the critical write path
- do not pretend it is part of the database transaction

## 10. Error Handling Contract

### Design Goal

Expose predictable API errors while keeping service code independent of DRF response objects.

### Recommended Shared Modules

- `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/common/api_errors.py`

### Recommended Exception Families

In `common/exceptions.py`, define small domain exceptions such as:

- `DomainValidationError`
- `DomainConflictError`
- `ConcurrencyConflictError`
- `InvalidWorkflowDefinitionError`
- `ExternalDependencyError`

Each should carry:

- `code`
- `detail`
- optional `attr`

### Standard Error Response Shape

Recommend a single envelope for both DRF validation failures and service/domain exceptions:

```json
{
  "errors": [
    {
      "code": "runbook_slug_conflict",
      "detail": "A runbook with this slug already exists in the organization.",
      "attr": "slug"
    }
  ]
}
```

For field validation:

```json
{
  "errors": [
    {
      "code": "required",
      "detail": "This field is required.",
      "attr": "title"
    }
  ]
}
```

### DRF Integration Pattern

- Always call `serializer.is_valid(raise_exception=True)` in views.
- Use a custom DRF exception handler so raised validation errors and domain exceptions share one response envelope.
- Do not hand-build ad hoc JSON error bodies in every view.

### Error Categories and Status Mapping

| Category | Source | HTTP status | Example codes |
| --- | --- | --- | --- |
| Validation | serializer field/object validation | `400 Bad Request` | `required`, `blank`, `invalid`, `invalid_reference` |
| Domain | service-level business rules | `400 Bad Request` or `409 Conflict` depending on case | `workflow_has_no_steps`, `invalid_workflow_definition`, `runbook_slug_conflict` |
| Concurrency | DB conflicts or stale writes | `409 Conflict` | `workflow_version_conflict`, `concurrent_state_change` |
| Not found | view/object lookup | `404 Not Found` | `not_found` |
| External dependency | internal client or future AI HTTP failure | `503 Service Unavailable` | `workflow_transform_unavailable` |

### Recommended Initial Error Codes

- `runbook_slug_conflict`
- `workflow_version_conflict`
- `invalid_workflow_definition`
- `workflow_has_no_steps`
- `execution_step_materialization_failed`
- `workflow_transform_unavailable`
- `invalid_reference`

### Validation vs Domain vs Concurrency Failures

Validation failures:

- malformed request payload
- missing fields
- empty `raw_content`
- invalid UUID in request path/body

Domain failures:

- workflow definition missing required keys after transform
- workflow definition resolves to zero steps
- execution requested from a workflow in an unsupported status, if status gating is added in-scope

Concurrency failures:

- two requests attempt to create the next workflow version for the same runbook at the same time
- future execution state transitions conflict with a stale update

### Important Constraint

DRF’s default generic-view validation errors may bypass a custom exception handler if errors are returned directly instead of being raised. Use `raise_exception=True` consistently so the API stays standardized.

## 11. Deterministic Workflow Stub Logic

### Goal

Provide a local, deterministic stand-in for future AI workflow generation without collapsing the architecture and putting transformation logic directly into the service function.

### Required Location

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/internal_clients.py`

### Required Properties

The stub transform must be:

- deterministic
- pure for the same inputs
- free of randomness
- free of clock-based output differences
- free of network calls
- realistic enough that a future HTTP client can replace it without changing the service contract

### Acceptable Placeholder Logic

Recommended v1 stub algorithm:

1. Normalize line endings to `\n`.
2. Split `raw_content` into lines.
3. Strip whitespace.
4. Drop empty lines.
5. Drop Markdown headings only if they would create empty/noisy steps.
6. Treat each remaining line as one candidate step.
7. Normalize the candidate text by removing leading list markers such as `-`, `*`, or `1.`.
8. Build one workflow step per candidate line.
9. If no candidate steps remain, produce one fallback step using the runbook title.

### Suggested Deterministic Field Mapping

- `step_key`: `step-001`, `step-002`, `step-003`, zero-padded and ordered by source order
- `name`: normalized line text truncated safely if needed
- `step_type`: `"manual_task"` by default
- `command`: `null` by default
- `risk_level`: `"medium"` by default
- `requires_approval`: `false` always in this phase

Optional deterministic refinement:

- if a line starts with `run:` then set `step_type = "shell_command"` and `command = <text after run:>`

That refinement is acceptable because it stays deterministic and helps the schema feel realistic without implementing a full parser.

### Suggested Output Schema

```json
{
  "schema_version": "workflow.schema.v1",
  "source": {
    "kind": "stub_transform",
    "generator": "django_api_stub",
    "runbook_slug": "restart-web"
  },
  "steps": [
    {
      "step_key": "step-001",
      "name": "Drain traffic from the instance",
      "step_type": "manual_task",
      "command": null,
      "risk_level": "medium",
      "requires_approval": false
    },
    {
      "step_key": "step-002",
      "name": "Restart the web process",
      "step_type": "shell_command",
      "command": "systemctl restart web",
      "risk_level": "medium",
      "requires_approval": false
    }
  ]
}
```

### Schema Expectations

Required top-level keys:

- `schema_version`
- `source`
- `steps`

Required per-step keys:

- `step_key`
- `name`
- `step_type`
- `risk_level`
- `requires_approval`

Optional per-step keys:

- `command`
- `description`

### How to Keep the Path Realistic

The stub should model the future boundary, not replace it.

Do:

- call a client object from the service
- validate the returned dict in the service
- keep schema names stable
- keep the output aligned with the execution-expansion requirements

Do not:

- inline transformation code directly in `create_workflow`
- store a serializer-specific output shape as the canonical workflow schema
- include random UUIDs, timestamps, or generated prose in the definition
- pretend approvals are implemented by setting `requires_approval` dynamically from policy logic

### Future-Safe Swap Path

Phase-03 service code should be written so this:

```python
client = StubWorkflowTransformClient()
```

can later become this:

```python
client = HttpWorkflowTransformClient(base_url=settings.AI_SERVICE_URL)
```

without changing the public service interface.

### AI-Service Boundary in the Current Repo

The existing AI service already exposes placeholder FastAPI routes in:

- `/home/dylan/code/runbook-platform/apps/ai/app/api/routes/parse.py`
- `/home/dylan/code/runbook-platform/apps/ai/app/api/routes/enrich.py`

Those placeholders are enough to justify the boundary now. The Django app should preserve that seam even before those routes become real.

## 12. Orchestration Flow and Transaction Boundaries

### Runbook Create Flow

```text
request
  -> view
  -> input serializer validation
  -> create_runbook service
    -> transaction.atomic()
    -> Runbook insert
  -> output serializer
  -> 201 response
```

### Workflow Create Flow

```text
request
  -> view
  -> input serializer validation
  -> create_workflow service
    -> transform client call outside transaction
    -> validate returned workflow definition
    -> transaction.atomic()
      -> lock parent runbook
      -> allocate next version
      -> Workflow insert
  -> output serializer
  -> 201 response
```

### Execution Create Flow

```text
request
  -> view
  -> input serializer validation
  -> create_execution service
    -> validate workflow definition
    -> transaction.atomic()
      -> Execution insert
      -> ExecutionStep bulk_create
  -> output serializer
  -> 201 response
```

### Boundary Rule

The service is the unit of orchestration. The transaction boundary should be co-located with that orchestration, not split across the view and model layers.

## 13. Immutability Expectations for Execution History

### Core Principle

Execution history is an immutable snapshot of what was intended to run at creation time plus mutable runtime state that records what happened during execution.

### Immutable After Creation

On `Execution`:

- `organization`
- `workflow`
- `workflow_version`
- `workflow_snapshot`

On `ExecutionStep`:

- `execution`
- `position`
- `step_key`
- `name`
- `step_type`
- `risk_level`
- `command`
- `requires_approval`
- `step_snapshot`

### Mutable After Creation

On `Execution`:

- `status`
- `started_at`
- `finished_at`
- failure summary fields if they exist later

On `ExecutionStep`:

- `status`
- `started_at`
- `finished_at`
- `exit_code`
- `error_message`

### Why This Matters

If a workflow changes later:

- past executions must still explain what was actually queued
- past execution steps must still show the exact planned step payload used at execution time
- UI and operator debugging must not depend on reading the current workflow row and guessing what used to exist

### Practical Rule for Later Phases

Never “refresh” old executions from a newer workflow definition.

## 14. File-by-File Implementation Plan

### Shared Support

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`

- add small domain exception classes used by services
- keep them framework-light
- no DRF `Response` creation here

#### `/home/dylan/code/runbook-platform/apps/api/apps/common/api_errors.py`

- add helpers or a custom DRF exception handler
- convert DRF validation errors and domain exceptions into one envelope

### Runbooks

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py`

- implement `create_runbook`
- catch and translate uniqueness collisions
- keep transaction scope minimal

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/serializers.py`

- add `RunbookCreateSerializer`
- add `RunbookSerializer` for responses
- keep `.create()` empty or unimplemented if using explicit services

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/views.py`

- add create endpoint
- validate input
- call `create_runbook`
- serialize output

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/urls.py`

- register the create route for the vertical slice

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_services.py`

- test `create_runbook` success and conflict behavior

#### `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_api.py`

- test endpoint validation and success envelope

### Workflows

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/internal_clients.py`

- define transform-client protocol or class interface
- implement deterministic stub client

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`

- implement `create_workflow`
- call transform client outside transaction
- validate returned schema
- allocate version safely under lock

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py`

- add request serializer for runbook reference if needed
- add response serializer

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/views.py`

- add create endpoint
- load `Runbook`
- call service
- return serialized workflow

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/urls.py`

- register workflow create route

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_internal_clients.py`

- test deterministic transform behavior
- test output schema

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_services.py`

- test version allocation, schema validation, and conflict mapping

#### `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api.py`

- test endpoint behavior and standardized errors

### Executions

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py`

- implement `create_execution`
- validate workflow definition
- create execution plus steps atomically

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/serializers.py`

- add create serializer for workflow reference
- add response serializer including nested steps if desired

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/views.py`

- add create endpoint
- load `Workflow`
- call service
- serialize output

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/urls.py`

- register execution create route

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_services.py`

- test aggregate creation and rollback behavior

#### `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_api.py`

- test API shape and failure mapping

### Routing

#### `/home/dylan/code/runbook-platform/apps/api/config/urls.py`

- include app URLs under `/api/v1/`
- do not overbuild router complexity for only three create endpoints

## 15. Step-by-Step Checklist with Commands, Touched Files, Expected Outputs, and Verification

### Step 1. Confirm baseline and model layer availability

Commands:

```bash
cd /home/dylan/code/runbook-platform
docker compose up -d postgres api
docker compose exec api python manage.py check
```

Touched files:

- none

Expected outputs:

- Django check passes
- API container is healthy

Verification:

```bash
docker compose ps
docker compose logs api --tail=50
```

### Step 2. Add shared exception and error-envelope support

Commands:

```bash
docker compose exec api python manage.py check
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/common/api_errors.py`
- `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`

Expected outputs:

- imports resolve
- DRF exception handler is configurable

Verification:

```bash
docker compose exec api python manage.py shell -c "from apps.common.exceptions import DomainConflictError; print(DomainConflictError.__name__)"
```

### Step 3. Implement runbook service and tests

Commands:

```bash
docker compose exec api python manage.py test apps.runbooks.tests.test_services
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_services.py`

Expected outputs:

- service tests pass
- duplicate slug conflict maps cleanly

Verification:

```bash
docker compose exec api python manage.py test apps.runbooks.tests.test_services -v 2
```

### Step 4. Wire runbook create serializer and view

Commands:

```bash
docker compose exec api python manage.py test apps.runbooks.tests.test_api
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/urls.py`
- `/home/dylan/code/runbook-platform/apps/api/config/urls.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_api.py`

Expected outputs:

- `POST /api/v1/runbooks/` returns `201` on valid input
- validation errors use standard envelope

Verification:

```bash
docker compose exec api python manage.py test apps.runbooks.tests.test_api -v 2
```

### Step 5. Implement deterministic workflow transform client and tests

Commands:

```bash
docker compose exec api python manage.py test apps.workflows.tests.test_internal_clients
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/internal_clients.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_internal_clients.py`

Expected outputs:

- identical input yields identical output
- generated workflow definitions match schema expectations

Verification:

```bash
docker compose exec api python manage.py test apps.workflows.tests.test_internal_clients -v 2
```

### Step 6. Implement workflow service and tests

Commands:

```bash
docker compose exec api python manage.py test apps.workflows.tests.test_services
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_services.py`

Expected outputs:

- workflow version increments safely
- malformed client output is rejected
- transform call remains outside transaction

Verification:

```bash
docker compose exec api python manage.py test apps.workflows.tests.test_services -v 2
```

### Step 7. Wire workflow create serializer and view

Commands:

```bash
docker compose exec api python manage.py test apps.workflows.tests.test_api
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/urls.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api.py`
- `/home/dylan/code/runbook-platform/apps/api/config/urls.py`

Expected outputs:

- `POST /api/v1/workflows/` returns `201`
- persisted workflow contains deterministic definition

Verification:

```bash
docker compose exec api python manage.py test apps.workflows.tests.test_api -v 2
```

### Step 8. Implement execution service and tests

Commands:

```bash
docker compose exec api python manage.py test apps.executions.tests.test_services
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_services.py`

Expected outputs:

- one execution row plus one step row per workflow step
- rollback on step materialization failure

Verification:

```bash
docker compose exec api python manage.py test apps.executions.tests.test_services -v 2
```

### Step 9. Wire execution create serializer and view

Commands:

```bash
docker compose exec api python manage.py test apps.executions.tests.test_api
```

Touched files:

- `/home/dylan/code/runbook-platform/apps/api/apps/executions/serializers.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/views.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/urls.py`
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/tests/test_api.py`
- `/home/dylan/code/runbook-platform/apps/api/config/urls.py`

Expected outputs:

- `POST /api/v1/executions/` returns `201`
- execution response matches stored snapshot data

Verification:

```bash
docker compose exec api python manage.py test apps.executions.tests.test_api -v 2
```

### Step 10. Run the vertical-slice test suite

Commands:

```bash
docker compose exec api python manage.py test \
  apps.runbooks.tests.test_services \
  apps.runbooks.tests.test_api \
  apps.workflows.tests.test_internal_clients \
  apps.workflows.tests.test_services \
  apps.workflows.tests.test_api \
  apps.executions.tests.test_services \
  apps.executions.tests.test_api
```

Touched files:

- none

Expected outputs:

- all service and API-adjacent tests pass

Verification:

```bash
docker compose exec api python manage.py check
```

### Step 11. Manual smoke test

Commands:

```bash
curl -s http://localhost:8000/health/
```

Then manual create flow against the new endpoints once implemented.

Touched files:

- none

Expected outputs:

- health still returns OK
- create flow works end-to-end for the vertical slice

Verification:

- create organization
- create runbook
- create workflow from runbook
- create execution from workflow
- inspect DB or admin to confirm execution step expansion

## 16. Test Plan

## Service-Layer Unit Tests

### Runbooks

- creates a runbook successfully
- maps duplicate `(organization, slug)` to `runbook_slug_conflict`
- does not generate workflow records implicitly

### Workflows

- deterministic transform client returns the same output for the same input
- service rejects malformed definitions
- service allocates `version=1` for the first workflow on a runbook
- service allocates the next version for subsequent workflows
- concurrent version conflicts map to `workflow_version_conflict`

### Executions

- service creates one execution row and N execution-step rows
- step ordering matches workflow source ordering
- copied fields match workflow step payload
- rollback occurs if step creation fails
- service rejects empty workflow definitions

## API-Adjacent Tests

- create endpoints return `201`
- serializer validation errors use the standard envelope
- domain conflicts use the standard envelope
- object lookup failures return `404`
- output serializers return persisted values, not raw request echoes

## Edge Cases

- runbook with blank or whitespace-only content
- runbook with only Markdown headings and no real lines
- runbook with repeated lines producing distinct but ordered steps
- workflow definition with duplicate `step_key`
- workflow definition missing `steps`
- workflow with one step only
- workflow with a `run:` line mapping to a `shell_command`
- large runbook body that still creates a bounded, deterministic step list if a cap is introduced

### Concurrency Test Focus

At least one test should simulate competing workflow creates for the same runbook. The goal is to verify:

- the DB constraint remains the source of truth
- the service maps the failure cleanly
- no duplicate `(runbook, version)` rows are persisted

## 17. Best Practices / Anti-Patterns

### Best Practices

- Keep service interfaces keyword-only and explicit.
- Keep transactions in services, not views.
- Use database constraints as the hard guardrails.
- Validate internal dependency output before persistence.
- Copy immutable snapshots for execution history.
- Keep the stub AI boundary swappable.
- Use small domain exception classes rather than leaking raw `IntegrityError` to views.

### Anti-Patterns

- putting orchestration in `serializer.create()`
- putting workflow generation logic directly in a DRF view
- calling the AI client inside `transaction.atomic()`
- enabling `ATOMIC_REQUESTS` just to avoid thinking about transaction boundaries
- mutating `Execution.workflow_snapshot` after creation
- reconstructing execution steps from the current workflow instead of stored snapshots
- using preflight `.exists()` checks as the only conflict protection
- adding approvals, audit, artifacts, or policy branching into this phase

## 18. Codex Batching Plan with Approval Gates

This phase should be executed in small, reviewable batches. Each batch should end with a verification point before continuing.

### Batch 1: Shared error plumbing

Scope:

- common exceptions
- common error handler
- DRF settings wiring

Approval gate:

- confirm the error envelope shape

### Batch 2: Runbook service slice

Scope:

- runbook service
- runbook serializers/views/URL
- runbook tests

Approval gate:

- confirm service signature and create-endpoint shape

### Batch 3: Workflow transform boundary

Scope:

- transform client interface
- deterministic stub client
- transform client tests

Approval gate:

- confirm step schema and acceptable stub behavior

### Batch 4: Workflow creation service slice

Scope:

- workflow service
- workflow serializers/views/URL
- workflow service and API tests

Approval gate:

- confirm versioning and conflict behavior

### Batch 5: Execution creation slice

Scope:

- execution service
- execution serializers/views/URL
- execution service and API tests

Approval gate:

- confirm execution snapshot and step-expansion behavior

### Batch 6: Final verification

Scope:

- full test suite for the vertical slice
- manual smoke verification
- docs cleanup if needed

Approval gate:

- confirm definition of done

## 19. Definition of Done

Phase 03 is done when all of the following are true:

- create orchestration no longer lives in views
- models still contain only small invariants and DB constraints
- serializers validate payloads and render outputs but do not orchestrate aggregates
- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/services.py` exists and owns runbook creation
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py` exists and owns workflow creation
- `/home/dylan/code/runbook-platform/apps/api/apps/workflows/internal_clients.py` exists and preserves the AI boundary with deterministic stub behavior
- `/home/dylan/code/runbook-platform/apps/api/apps/executions/services.py` exists and expands workflow steps into execution-step rows
- workflow transform calls happen outside DB transactions
- execution creation is atomic across the execution row and all step rows
- execution history stores immutable snapshots
- error responses are standardized across validation and domain failures
- service-layer unit tests pass
- API-adjacent tests pass
- the implementation remains aligned to the vertical slice and does not pull in approvals, policy logic, audit, artifacts, or full auth

## 20. Final Implementation Notes

### Endpoint Shape Recommendation

This phase does not need a large router abstraction. Simple explicit routes are enough:

- `POST /api/v1/runbooks/`
- `POST /api/v1/workflows/`
- `POST /api/v1/executions/`

### Serializer Pattern Recommendation

Use separate write and read serializers where it keeps the service boundary clean:

- create serializer for input validation
- detail serializer for output rendering

That is usually clearer than trying to make one serializer serve both responsibilities.

### Service Return Pattern Recommendation

Return model instances from services in this phase.

Do not introduce a custom “result object” abstraction yet unless a concrete need appears. That would be unnecessary framework-building for a three-service vertical slice.

### Naming Recommendation

Use direct function names:

- `create_runbook`
- `create_workflow`
- `create_execution`

Do not wrap these in classes like `RunbookCreationManager` or `ExecutionFactoryService`. Those names add ceremony without clarity at this stage.

### Summary

Phase 03 should leave the codebase with one obvious place for orchestration, one obvious place for validation, and one obvious place for transport concerns. If implemented this way, later phases can safely add real AI calls, richer execution transitions, auth, and policy layers without needing to unwind business logic that leaked into views or serializers.
