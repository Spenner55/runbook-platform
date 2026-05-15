Runbook Platform — Phase 1 Execution Blueprint
================================================

End-to-End Vertical Slice Implementation Plan
---------------------------------------------

## Current repo alignment notes

As of 2026-04-27, the core vertical slice described by this blueprint is substantially implemented across Django, runner, AI, and React. Treat this file as historical implementation guidance, not as the current API reference. Current architecture truth lives in `docs/architecture/`, and current API truth lives in `docs/architecture/api-contracts.md`.

## Purpose

This document defines a step-by-step execution plan to build the first real working slice of the Runbook Platform.

It is designed for:

- Human execution (you)
- Codex-assisted execution (controlled, step-by-step)

It prioritizes:

- correctness over speed
- incremental validation
- zero drift between plan and implementation
- production-grade architecture from day one

## Guiding Principles

- Build one vertical slice end-to-end before expanding horizontally
- Django is the control plane — all orchestration flows through it
- Runner interacts ONLY through API — never directly with DB
- Frontend talks ONLY to Django API
- AI service is a dependency — not a source of truth
- All changes must be small, testable, and reversible
- Every step includes a verification gate

## Phase 1 Objective

Deliver a working system where:

- User creates organization
- User creates runbook
- System generates workflow
- User starts execution
- Runner claims execution
- Runner executes steps
- Execution status updates in DB
- UI reflects real-time progress (polling)

## Locked Design Decisions

### IDs

Use UUID primary keys for all domain entities

### API Versioning

All endpoints under:

```text
/api/v1/...
```

### Execution Model

Poll-based runner (no queues yet)

### Status Enums

#### Execution

- queued
- claimed
- running
- succeeded
- failed
- cancelled

#### Step

- pending
- running
- succeeded
- failed
- skipped

### Architecture Boundaries

| Layer | Responsibility |
| --- | --- |
| React | UI only |
| Django | orchestration + persistence |
| Runner | execution engine |
| FastAPI | AI processing only |

## EXECUTION PLAN

## STEP 1 — Create Django Domain Apps

### Goal

Replace placeholder folders with real Django apps.

### Commands

```bash
cd apps/api

python manage.py startapp common
python manage.py startapp organizations
python manage.py startapp runbooks
python manage.py startapp workflows
python manage.py startapp executions
```

Move apps into apps/api/apps/ if needed.

### Update settings

Edit:

```text
apps/api/config/settings/base.py
```

Add:

```python
INSTALLED_APPS += [
    "apps.common",
    "apps.organizations",
    "apps.runbooks",
    "apps.workflows",
    "apps.executions",
]
```

### Verification

Run:

```bash
docker compose exec api python manage.py check
```

Expected:

- No errors

### Stop Condition

- ✔ Django recognizes all apps
- ✔ No import or config errors

## STEP 2 — Base Models (Common App)

### Goal

Establish shared model foundation.

### File

```text
apps/api/apps/common/models.py
```

### Implementation

```python
import uuid
from django.db import models

class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

### Verification

```bash
docker compose exec api python manage.py makemigrations
```

Expected:

- No errors

### Stop Condition

- ✔ Base model usable by other apps

## STEP 3 — Core Domain Models

### Organization Model

`organizations/models.py`

```python
from django.db import models
from apps.common.models import BaseModel

class Organization(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
```

### Runbook Model

```python
class Runbook(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    raw_content = models.TextField()
    status = models.CharField(max_length=50, default="draft")
```

### Workflow Model

```python
class Workflow(BaseModel):
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    runbook = models.ForeignKey("runbooks.Runbook", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    version = models.IntegerField(default=1)
    status = models.CharField(max_length=50, default="draft")
    definition_json = models.JSONField()
```

### Execution + Steps

```python
class Execution(BaseModel):
    workflow = models.ForeignKey("workflows.Workflow", on_delete=models.CASCADE)
    status = models.CharField(max_length=50, default="queued")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

class ExecutionStep(BaseModel):
    execution = models.ForeignKey(Execution, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    order_index = models.IntegerField()
    status = models.CharField(max_length=50, default="pending")
    logs_text = models.TextField(blank=True)
```

### Migrate

```bash
docker compose exec api python manage.py makemigrations
docker compose exec api python manage.py migrate
```

### Verification

```bash
docker compose exec api python manage.py showmigrations
```

### Stop Condition

- ✔ Tables exist
- ✔ No migration errors

## STEP 4 — Admin Registration

### Goal

Enable visibility + debugging.

### Register models

Example:

```python
from django.contrib import admin
from .models import Organization

admin.site.register(Organization)
```

Repeat for all models.

### Verification

Visit:

```text
http://localhost:8000/admin
```

### Stop Condition

- ✔ All models visible in admin

## STEP 5 — Service Layer

### Goal

Move business logic OUT of views.

### Create service files

- `apps/runbooks/services.py`
- `apps/workflows/services.py`
- `apps/executions/services.py`

### Example: Workflow Creation Service

```python
def create_workflow_from_runbook(runbook):
    steps = [
        {"id": "step1", "name": "Example Step", "type": "command"}
    ]

    workflow = Workflow.objects.create(
        organization=runbook.organization,
        runbook=runbook,
        name=runbook.title,
        status="ready",
        definition_json={"steps": steps}
    )

    return workflow
```

### Verification

Use Django shell:

```bash
docker compose exec api python manage.py shell
```

### Stop Condition

- ✔ Services execute without error

## STEP 6 — API Layer

### Goal

Expose real endpoints.

### Endpoints

#### Runbooks

- POST /api/v1/runbooks
- GET /api/v1/runbooks

#### Workflows

- POST /api/v1/workflows

#### Executions

- POST /api/v1/executions
- GET /api/v1/executions/:id

### Best Practice

Separate serializers:

- create
- list
- detail

### Verification

```bash
curl http://localhost:8000/api/v1/runbooks
```

### Stop Condition

- ✔ All endpoints respond correctly

## STEP 7 — Runner Integration

### Goal

Enable async execution.

### Flow

- Runner polls /claim-next
- API returns queued execution
- Runner executes steps
- Runner updates status

### Implementation

Add endpoint:

```text
POST /api/v1/internal/executions/claim-next
```

Runner loop

```python
while True:
    execution = client.claim_next()
    if not execution:
        sleep(5)
        continue

    for step in execution.steps:
        execute_step(step)
```

### Verification

Run runner container:

```bash
docker compose logs -f runner
```

### Stop Condition

- ✔ Runner claims and executes tasks

## STEP 8 — React Frontend

### Pages

- Organizations
- Runbooks
- Workflow Detail
- Execution Detail

### Key Behavior

Execution page:

- polls every 2–5 seconds
- displays step status

### Verification

Open:

```text
http://localhost:5173
```

### Stop Condition

- ✔ UI reflects execution state

## STEP 9 — AI Service Boundary

### Goal

Integrate FastAPI safely.

### Rule

Frontend NEVER calls AI service directly.

### Django → AI client

```python
def parse_runbook(text):
    response = httpx.post("http://ai:8001/parse/runbook", json={"text": text})
    return response.json()
```

### Verification

```bash
curl http://localhost:8001/health
```

### Stop Condition

- ✔ Django successfully calls AI service

## STEP 10 — Testing

### Django Tests

- workflow creation
- execution lifecycle
- claim-next logic

### Runner Tests

- polling loop
- step transitions

### Stop Condition

- ✔ Critical flows covered

## Codex Execution Pattern

Use this prompt structure:

```text
You are executing STEP X of the Phase 1 blueprint.

Rules:
- Do NOT skip steps
- Make minimal changes
- Show diff before writing
- Ask for approval before proceeding

Goal:
[describe step]

Files:
[list files]

Verification:
[commands]

Stop after completion
```

## Definition of Done

- ✔ End-to-end flow works
- ✔ Execution progresses automatically
- ✔ UI reflects state
- ✔ No manual DB intervention required
- ✔ Logs visible
- ✔ System restarts cleanly

## Final Notes

Do NOT:

- build approvals yet
- build policy engine yet
- over-design contracts
- add queues or Celery
- add websockets

Focus on:

- correctness
- clarity
- observability
