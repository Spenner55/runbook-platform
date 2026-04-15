# Phase 07 Blueprint: AI Service Boundary

## Phase Metadata

| Field | Value |
| --- | --- |
| Phase number | 07 |
| Objective | Add the AI service boundary correctly so workflow creation from a runbook remains a Django-owned flow, while FastAPI stays an internal parsing dependency only. |
| Status | Planned |
| In-scope AI use case | Create workflow from runbook. Exactly one AI use case in this phase. |
| Out of scope | Summary generation, enrichment pipelines, failure summarization, background AI job orchestration, direct frontend-to-FastAPI calls, direct runner-to-FastAPI calls, FastAPI persistence, generalized AI abstraction layers, and multi-use-case AI routing. |
| Documentation basis reviewed on | 2026-04-01 |
| Current repo anchors reviewed | `/home/dylan/code/runbook-platform/apps/api`, `/home/dylan/code/runbook-platform/apps/ai`, `/home/dylan/code/runbook-platform/apps/web`, `/home/dylan/code/runbook-platform/apps/runner`, `/home/dylan/code/runbook-platform/.env.example`, `/home/dylan/code/runbook-platform/docker-compose.yml`, `/home/dylan/code/runbook-platform/packages/contracts/workflow/workflow.schema.json`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-03-application-service-layer-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-04-versioned-rest-apis-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-05-runner-real-flow-blueprint.md`. |
| Current repo state relevant to this phase | `/home/dylan/code/runbook-platform/apps/ai/app/api/routes/parse.py` exposes a placeholder `POST /parse/runbook`; `/home/dylan/code/runbook-platform/apps/ai/app/main.py` also registers `enrich` and `summarize`; `/home/dylan/code/runbook-platform/apps/api/apps/runbooks` exists but has no AI client yet; `/home/dylan/code/runbook-platform/apps/api/requirements/base.txt` does not yet include `httpx`; `/home/dylan/code/runbook-platform/.env.example` already carries `AI_BASE_URL`, `API_BASE_URL`, and `VITE_API_BASE_URL`. |

## Official Docs Reviewed

FastAPI:

- [Bigger Applications - Multiple Files](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [Response Model](https://fastapi.tiangolo.com/tutorial/response-model/)
- [Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Testing](https://fastapi.tiangolo.com/tutorial/testing/)

HTTPX:

- [Clients](https://www.python-httpx.org/advanced/clients/)
- [Timeouts](https://www.python-httpx.org/advanced/timeouts/)
- [Exceptions](https://www.python-httpx.org/exceptions/)
- [Transports](https://www.python-httpx.org/advanced/transports/)

Django:

- [Settings](https://docs.djangoproject.com/en/5.2/topics/settings/)
- [Advanced Testing Topics](https://docs.djangoproject.com/en/5.2/topics/testing/advanced/)
- [Testing Tools](https://docs.djangoproject.com/en/5.2/topics/testing/tools/)

## Non-Negotiable Boundary Rules

- Frontend must call Django only.
- Frontend must not call FastAPI directly.
- FastAPI must not become the system of record.
- Django must keep orchestration, validation, and persistence.
- Optional runner traffic, if relevant later, must still call Django only.
- Phase 07 covers one AI use case only: create workflow from runbook.
- Do not wire summary generation, enrichment, or failure summarization in this phase.
- Do not build a generic AI platform or job framework in this phase.

## 1. Phase Objective

Phase 07 exists to make the AI dependency real without breaking the platform architecture.

The desired request path is:

```text
Frontend -> Django public API -> Django workflow service -> Django AI client -> FastAPI parse endpoint
         -> Django mapping + validation + persistence -> Django response -> Frontend
```

The optional non-browser path remains:

```text
Runner -> Django internal API
```

Not this:

```text
Frontend -> FastAPI
Runner -> FastAPI
FastAPI -> PostgreSQL
FastAPI -> Workflow persistence
```

The only feature delivered by this boundary in Phase 07 is:

- take one stored runbook
- ask the internal AI service to parse it into a workflow candidate
- map that candidate into the platform’s canonical workflow JSON
- persist the resulting workflow through Django

Nothing else belongs in scope.

## 2. Architecture Boundary Explanation

### 2.1 System Roles

The repository already points toward a clear split:

- `/home/dylan/code/runbook-platform/apps/web` is the presentation layer.
- `/home/dylan/code/runbook-platform/apps/api` is the control plane and persistence owner.
- `/home/dylan/code/runbook-platform/apps/ai` is an internal dependency service.
- `/home/dylan/code/runbook-platform/apps/runner` is an execution worker that should already depend on Django, not on the AI service.

That split must become stricter in Phase 07, not blurrier.

### 2.2 Allowed Network Boundaries

Allowed:

- browser -> Django under `/api/v1/...`
- Django -> FastAPI internal endpoint for workflow parsing
- runner -> Django under `/api/v1/internal/...`

Disallowed:

- browser -> FastAPI
- web build config that exposes `AI_BASE_URL`
- runner -> FastAPI
- FastAPI -> Django database tables as durable owner
- FastAPI -> public API contract for workflow creation

### 2.3 Durable Data Ownership

Durable ownership stays in Django:

- runbook prose stays on Django `Runbook.raw_content`
- workflow JSON stays on Django `Workflow.definition` or equivalent persisted JSON field
- workflow version allocation stays in Django
- workflow lifecycle state stays in Django
- execution snapshots stay in Django

FastAPI owns none of the above. It returns a candidate, not a record.

### 2.4 Boundary Diagram

```text
+----------------------+       +----------------------------+       +----------------------+
| Web frontend         |       | Django API                |       | FastAPI AI           |
| /apps/web            |       | /apps/api                 |       | /apps/ai             |
|                      |       |                            |       |                      |
| POST /api/v1/...     | ----> | validate request           | ----> | parse runbook into   |
| only                 |       | load runbook               |       | workflow candidate   |
|                      | <---- | map + validate candidate   | <---- | return structured    |
|                      |       | persist workflow           |       | placeholder payload  |
+----------------------+       +----------------------------+       +----------------------+
                                        |
                                        v
                            +----------------------------+
                            | PostgreSQL via Django      |
                            | system of record           |
                            +----------------------------+
```

### 2.5 Why Existing Placeholder Routes Do Not Expand Scope

The FastAPI app currently mounts:

- `/health`
- `/parse/runbook`
- `/enrich/...`
- `/summarize/...`

That does not mean Django should call all of them. In Phase 07:

- use `/parse/runbook`
- leave `enrich` and `summarize` unwired from Django
- do not expand the Django-side AI client into a multi-purpose gateway

### 2.6 Optional Runner Boundary

`/home/dylan/code/runbook-platform/.env.example` already shows:

- `API_BASE_URL=http://api:8000`
- `AI_BASE_URL=http://ai:8001`

That is a useful signal:

- runner should keep depending on `API_BASE_URL`
- runner should not start depending on `AI_BASE_URL`

If a future runner flow ever causes workflow creation, the runner still calls Django and Django decides whether to call FastAPI.

## 3. Why Django Must Remain the Control Plane

### 3.1 Django Already Owns the Platform Contract

Earlier blueprints establish Django as the place that owns:

- versioned public APIs
- internal runner APIs
- service-layer orchestration
- validation before persistence
- transaction boundaries
- durable records and lifecycle state

If workflow generation becomes a FastAPI-first flow, the phase sequence from 03 to 05 stops being coherent.

### 3.2 Workflow Creation Is Not a Pure Parse Operation

Even if AI produces good structure, real workflow creation still requires Django-owned work:

- load the `Runbook`
- verify the runbook exists
- verify organization scoping
- verify the runbook is eligible for workflow creation
- allocate the next workflow version
- validate the candidate against platform rules
- map to the canonical workflow JSON schema
- persist the `Workflow`
- return the public API resource shape

FastAPI should not decide or persist any of that.

### 3.3 Why FastAPI Must Not Be the System of Record

If FastAPI becomes the system of record, the following problems appear immediately:

- the frontend now has two backends to understand
- workflow persistence rules split across services
- version assignment becomes ambiguous
- auditability becomes harder because source-of-truth logic is split
- runner and web traffic stop converging through Django
- public error handling becomes inconsistent

That is architectural regression, not an implementation shortcut.

### 3.4 Public Contract Stability

The public create contract from Phase 04 should remain:

`POST /api/v1/workflows/`

with a minimal input like:

```json
{
  "runbook_id": "11111111-1111-1111-1111-111111111111"
}
```

The frontend should not need to know:

- that FastAPI exists
- where FastAPI is hosted
- which prompt strategy FastAPI uses
- which AI provider is behind FastAPI
- whether the FastAPI response is stubbed or real

That abstraction boundary is the point of the phase.

## 4. Internal Client Design in Django

### 4.1 Recommended Location

Put the Django-side transport boundary here:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_client.py`

Optional supporting local types:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_types.py`

Keep it local to the runbook/workflow boundary. Do not create a repo-wide AI SDK package.

### 4.2 Why This Client Belongs Near `runbooks`

This use case starts from a stored runbook and ends as a workflow candidate. Locating the transport boundary in `apps/runbooks` is reasonable because:

- the request payload is sourced directly from a `Runbook`
- the user explicitly requested this location pattern
- it keeps the boundary small and easy to reason about

Orchestration still belongs in workflow services, not in the client.

### 4.3 Responsibilities Split

`ai_client.py` should own:

- building the FastAPI URL from Django settings
- creating and using `httpx.Client`
- applying explicit timeout configuration
- sending the JSON request
- interpreting HTTPX exceptions
- parsing the JSON response into a narrow local structure

`workflows/services.py` should own:

- loading the `Runbook`
- deciding whether creation can proceed
- invoking the AI client
- validating the candidate
- mapping to canonical workflow JSON
- version allocation
- database writes
- public error behavior

### 4.4 Recommended Client Shape

Keep the client synchronous for this phase. The Django service is currently sync-oriented, the use case is one request per workflow create, and async complexity would be pure ceremony here.

Suggested shape:

```python
class RunbookAiClient:
    def __init__(self, *, base_url: str, timeout: httpx.Timeout, transport: httpx.BaseTransport | None = None):
        ...

    def parse_runbook_to_workflow_candidate(
        self,
        *,
        request_id: str,
        runbook_id: str,
        runbook_title: str,
        raw_content: str,
    ) -> "WorkflowParseCandidate":
        ...
```

Suggested boundary types:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class WorkflowParseStepCandidate:
    step_key: str
    name: str
    step_type: str
    risk_level: str
    command: str | None
    requires_approval: bool

@dataclass(frozen=True)
class WorkflowParseCandidate:
    request_id: str
    workflow_title: str
    steps: list[WorkflowParseStepCandidate]
    warnings: list[str]
```

Why dataclasses or light local types instead of more framework:

- the boundary is tiny
- Django does not need Pydantic just to receive one internal response
- a dataclass or `TypedDict` is enough
- it keeps transport structure explicit without overbuilding

### 4.5 HTTPX Recommendation for This Repo

The official HTTPX docs recommend using `Client` for anything beyond one-off experimentation because it gives connection pooling and consistent configuration.

For this repo, the practical rule should be:

- do not scatter `httpx.post(...)` calls through services or views
- centralize all AI HTTP traffic in `RunbookAiClient`
- use `httpx.Client(...)` with explicit `Timeout(...)`
- allow an optional injected transport for tests

### 4.6 Settings and Configuration

Current relevant settings already exist:

- `AI_BASE_URL` in `/home/dylan/code/runbook-platform/.env.example`

Add only the minimum additional settings needed for explicit behavior:

- `AI_BASE_URL`
- `AI_CONNECT_TIMEOUT_SECONDS`
- `AI_READ_TIMEOUT_SECONDS`
- `AI_WRITE_TIMEOUT_SECONDS`
- `AI_POOL_TIMEOUT_SECONDS`

Suggested defaults for the internal network:

| Setting | Suggested default | Why |
| --- | --- | --- |
| `AI_BASE_URL` | `http://ai:8001` | matches current Compose service naming |
| `AI_CONNECT_TIMEOUT_SECONDS` | `1.0` | internal service discovery should fail fast |
| `AI_READ_TIMEOUT_SECONDS` | `20.0` | parsing may include provider latency later |
| `AI_WRITE_TIMEOUT_SECONDS` | `5.0` | request payload is small |
| `AI_POOL_TIMEOUT_SECONDS` | `1.0` | do not stall on pool acquisition |

That should be enough. Do not introduce large retry, circuit-breaker, or service-mesh configuration in this phase.

### 4.7 Error Types to Keep Narrow

Recommended Django-local exceptions:

- `AiServiceUnavailableError`
- `AiServiceTimeoutError`
- `AiServiceBadResponseError`
- `AiServiceContractError`

These can live either in:

- `/home/dylan/code/runbook-platform/apps/api/apps/common/exceptions.py`

or, if staying smaller:

- `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_client.py`

Keep them internal. The frontend should receive stable Django error codes, not raw HTTPX or FastAPI exception names.

## 5. Suggested FastAPI Contract for Workflow Parsing

### 5.1 Contract Shape

Use one internal endpoint only:

- `POST /parse/runbook`

Implement it in:

- `/home/dylan/code/runbook-platform/apps/ai/app/api/routes/parse.py`

Supporting files:

- `/home/dylan/code/runbook-platform/apps/ai/app/schemas/workflow_parse.py`
- `/home/dylan/code/runbook-platform/apps/ai/app/services/workflow_parser.py`

### 5.2 What FastAPI Should Accept

The request should include only what the parser needs:

- request identifier for tracing
- runbook identifier
- runbook title
- runbook raw content

Do not send:

- organization write rules
- workflow version
- public response serializer state
- workflow database IDs
- execution information

### 5.3 What FastAPI Should Return

Return a structured workflow candidate, not a workflow record.

The response should include:

- `request_id`
- `workflow_title`
- `steps`
- `warnings`

It should not include:

- persisted workflow ID
- workflow version
- workflow status
- organization ID as source of truth
- execution records

### 5.4 Why Use Pydantic Request and Response Models

The FastAPI docs recommend Pydantic models for request parsing and `response_model` for output typing and filtering.

That is useful here because it gives:

- one explicit internal contract
- OpenAPI clarity for the service itself
- early validation of stub output
- better guarantees that Django receives a stable shape

### 5.5 Suggested Route Skeleton

```python
@router.post("/runbook", response_model=WorkflowParseResponse)
def parse_runbook(payload: WorkflowParseRequest) -> WorkflowParseResponse:
    candidate = workflow_parser.parse_runbook(
        request_id=payload.request_id,
        runbook_id=payload.runbook.id,
        runbook_title=payload.runbook.title,
        raw_content=payload.runbook.raw_content,
    )
    return candidate
```

### 5.6 FastAPI Responsibility Line

FastAPI may:

- validate request shape
- run deterministic placeholder parsing
- later call an AI provider
- return a structured candidate

FastAPI may not in this phase:

- create workflows
- assign versions
- persist to Django tables
- expose a public browser-facing API for workflow creation
- own orchestration around retries, business eligibility, or lifecycle state

## 6. Request/Response Schema Examples

### 6.1 Public Frontend -> Django Request

`POST /api/v1/workflows/`

```json
{
  "runbook_id": "11111111-1111-1111-1111-111111111111"
}
```

The frontend stays intentionally ignorant of the AI service.

### 6.2 Internal Django -> FastAPI Request

`POST http://ai:8001/parse/runbook`

```json
{
  "request_id": "req_20260401_0001",
  "runbook": {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "Rotate AWS Credentials",
    "raw_content": "1. Verify current IAM user context\n2. Create replacement access key\n3. Update automation secrets\n4. Validate production automation"
  }
}
```

Suggested FastAPI request schema:

```json
{
  "type": "object",
  "required": ["request_id", "runbook"],
  "properties": {
    "request_id": { "type": "string" },
    "runbook": {
      "type": "object",
      "required": ["id", "title", "raw_content"],
      "properties": {
        "id": { "type": "string" },
        "title": { "type": "string" },
        "raw_content": { "type": "string" }
      }
    }
  }
}
```

### 6.3 Placeholder Structured FastAPI Response

```json
{
  "request_id": "req_20260401_0001",
  "workflow_title": "Rotate AWS Credentials",
  "steps": [
    {
      "step_key": "step-001",
      "name": "Verify current IAM user context",
      "step_type": "manual_task",
      "risk_level": "medium",
      "command": null,
      "requires_approval": false
    },
    {
      "step_key": "step-002",
      "name": "Create replacement access key",
      "step_type": "manual_task",
      "risk_level": "medium",
      "command": null,
      "requires_approval": false
    },
    {
      "step_key": "step-003",
      "name": "Update automation secrets",
      "step_type": "manual_task",
      "risk_level": "high",
      "command": null,
      "requires_approval": true
    },
    {
      "step_key": "step-004",
      "name": "Validate production automation",
      "step_type": "manual_task",
      "risk_level": "medium",
      "command": null,
      "requires_approval": false
    }
  ],
  "warnings": []
}
```

This is deliberately a candidate shape, not the final persisted workflow representation.

### 6.4 Django Internal Mapping Object

After the HTTP call, Django should convert the response into a local internal structure similar to:

```python
WorkflowParseCandidate(
    request_id="req_20260401_0001",
    workflow_title="Rotate AWS Credentials",
    steps=[
        WorkflowParseStepCandidate(
            step_key="step-001",
            name="Verify current IAM user context",
            step_type="manual_task",
            risk_level="medium",
            command=None,
            requires_approval=False,
        ),
        ...
    ],
    warnings=[],
)
```

### 6.5 Django Public Success Response

The public response should still be Django-owned and workflow-centric. Example:

```json
{
  "id": "22222222-2222-2222-2222-222222222222",
  "organization_id": "33333333-3333-3333-3333-333333333333",
  "runbook_id": "11111111-1111-1111-1111-111111111111",
  "name": "Rotate AWS Credentials",
  "status": "draft",
  "version": 1,
  "definition": {
    "name": "Rotate AWS Credentials",
    "steps": [
      {
        "id": "step-001",
        "name": "Verify current IAM user context",
        "type": "manual_task",
        "risk": "medium",
        "requiresApproval": false
      },
      {
        "id": "step-002",
        "name": "Create replacement access key",
        "type": "manual_task",
        "risk": "medium",
        "requiresApproval": false
      },
      {
        "id": "step-003",
        "name": "Update automation secrets",
        "type": "manual_task",
        "risk": "high",
        "requiresApproval": true
      },
      {
        "id": "step-004",
        "name": "Validate production automation",
        "type": "manual_task",
        "risk": "medium",
        "requiresApproval": false
      }
    ]
  }
}
```

### 6.6 Public Failure Response Example

If the AI service is unavailable or times out, the public API should still respond with the standardized Django error envelope from the Phase 04 API approach. Example:

```json
{
  "error": {
    "code": "workflow_ai_unavailable",
    "message": "Workflow generation is temporarily unavailable."
  }
}
```

or:

```json
{
  "error": {
    "code": "workflow_ai_timeout",
    "message": "Workflow generation timed out."
  }
}
```

Do not leak:

- raw upstream body
- provider details
- internal URLs
- Python exception tracebacks

## 7. Timeout/Retry/Error-Handling Guidance

### 7.1 Timeout Guidance

HTTPX explicitly supports fine-grained timeouts. Use them instead of an implicit default.

Recommended initial timeout object:

```python
httpx.Timeout(
    connect=settings.AI_CONNECT_TIMEOUT_SECONDS,
    read=settings.AI_READ_TIMEOUT_SECONDS,
    write=settings.AI_WRITE_TIMEOUT_SECONDS,
    pool=settings.AI_POOL_TIMEOUT_SECONDS,
)
```

Why this split fits this repo:

- `connect` should be short because Django and FastAPI are adjacent internal services on the same Compose network
- `read` should be longer because the parse implementation may later call an AI provider
- `write` can stay short because the request body is small
- `pool` should be explicit so client starvation fails predictably

### 7.2 Retry Guidance

Do not add broad automatic retries for all failures.

Recommended policy for Phase 07:

- retry count defaults to `0`
- optionally allow `1` retry for connection-establishment failures only
- do not retry `4xx`
- do not retry schema/contract failures
- do not retry `read` timeouts by default
- do not retry arbitrary `5xx` blindly

Why this is the right narrow policy:

- the internal parse endpoint is a `POST`
- even if it has no persistence side effects, a future provider call may be expensive
- duplicate retries on slow AI calls can double work and complicate debugging
- the simplest safe starting point is no retry, with a single future extension only for connect-level flakes

### 7.3 Exception Mapping Guidance

Suggested mapping:

| Low-level failure | Django-local exception | Public status | Public code |
| --- | --- | --- | --- |
| `httpx.ConnectError`, `httpx.ConnectTimeout` | `AiServiceUnavailableError` | `503` or `502` | `workflow_ai_unavailable` |
| `httpx.ReadTimeout` | `AiServiceTimeoutError` | `504` | `workflow_ai_timeout` |
| upstream non-2xx with unexpected body | `AiServiceBadResponseError` | `502` | `workflow_ai_bad_response` |
| upstream 200 but invalid JSON shape | `AiServiceContractError` | `502` | `workflow_ai_contract_error` |

Pick one public policy and keep it stable. The important thing is consistent Django-owned error semantics.

### 7.4 Logging Guidance

Log:

- request id
- runbook id
- upstream path
- timeout class when applicable
- upstream status code

Do not log by default:

- full runbook raw content
- secrets embedded in prose
- full prompt text
- full upstream response bodies if they may contain sensitive content

### 7.5 Persistence Safety Rule

If the AI call fails, times out, or returns an invalid contract:

- Django must not persist a partial workflow
- Django must not allocate or expose a half-created durable record
- the create flow should fail atomically from the caller’s perspective

## 8. Mapping Strategy From AI Response to Workflow `definition_json`

### 8.1 Terminology Note

Phase 02 uses `Workflow.definition` as the likely JSON field name. This section uses `definition_json` because that is the requested blueprint wording and is the conceptual target: the canonical JSON persisted on the workflow record.

If the actual model field remains `definition`, map into that field.

### 8.2 Mapping Principle

FastAPI returns a candidate structure. Django converts that candidate into the canonical workflow JSON shape required by:

- `/home/dylan/code/runbook-platform/packages/contracts/workflow/workflow.schema.json`

That means Django owns:

- final field names
- canonical step identifiers
- last-mile validation
- normalization rules

FastAPI should not return the exact persisted record shape as the source of truth.

### 8.3 Canonical Target Shape

Current shared schema expects:

```json
{
  "name": "Rotate AWS Credentials",
  "steps": [
    {
      "id": "step-001",
      "name": "Verify current IAM user context",
      "type": "manual_task",
      "risk": "medium",
      "command": null,
      "requiresApproval": false
    }
  ]
}
```

### 8.4 Recommended Mapping Table

| FastAPI candidate field | Django internal meaning | Persisted workflow JSON field |
| --- | --- | --- |
| `workflow_title` | workflow display name candidate | `name` |
| `steps[].step_key` | upstream candidate step key | source for canonical `id`, subject to Django normalization |
| `steps[].name` | step name candidate | `steps[].name` |
| `steps[].step_type` | step type candidate | `steps[].type` |
| `steps[].risk_level` | risk candidate | `steps[].risk` |
| `steps[].command` | optional command | `steps[].command` |
| `steps[].requires_approval` | approval flag candidate | `steps[].requiresApproval` |

### 8.5 Canonicalization Rules

Django should normalize before persistence:

1. Trim workflow title and step names.
2. Reject empty workflow title after trimming.
3. Reject zero-step responses.
4. Reject steps with empty names.
5. Normalize or regenerate step IDs if upstream keys are missing or invalid.
6. Normalize booleans and nullable command values.
7. Validate the final JSON against shared workflow schema expectations.

### 8.6 Step ID Ownership

Django should own durable step IDs.

Recommended rule:

- use `step_key` from FastAPI only as an input signal
- persist a Django-approved stable `id`
- if `step_key` already matches the allowed pattern, reuse it
- otherwise generate deterministic ordered IDs such as `step-001`, `step-002`, `step-003`

Why Django should own this:

- these IDs become part of durable workflow state
- later execution snapshots may depend on them
- durable identifiers should not be provider-shaped

### 8.7 Validation Rules Before Persistence

Django-side validation should reject at minimum:

- empty `workflow_title`
- empty `steps`
- missing `name`
- missing `step_type`
- missing `risk_level`
- duplicate step IDs after canonicalization
- non-boolean `requires_approval`
- command values that are not `string` or `null`

### 8.8 Warnings Handling

FastAPI may return `warnings`, for example:

- ambiguous language
- missing explicit commands
- inferred manual task

In Phase 07:

- do not create a warning persistence subsystem
- do not add warning-based workflow states
- optionally log warnings with request id
- optionally expose warnings later in diagnostics, but keep them out of the core create contract for now

### 8.9 Example Mapping

Input candidate from FastAPI:

```json
{
  "request_id": "req_20260401_0001",
  "workflow_title": "Rotate AWS Credentials",
  "steps": [
    {
      "step_key": "step-001",
      "name": "Verify current IAM user context",
      "step_type": "manual_task",
      "risk_level": "medium",
      "command": null,
      "requires_approval": false
    },
    {
      "step_key": "step-002",
      "name": "run: aws iam create-access-key",
      "step_type": "shell_command",
      "risk_level": "high",
      "command": "aws iam create-access-key",
      "requires_approval": true
    }
  ]
}
```

Persisted `definition_json`:

```json
{
  "name": "Rotate AWS Credentials",
  "steps": [
    {
      "id": "step-001",
      "name": "Verify current IAM user context",
      "type": "manual_task",
      "risk": "medium",
      "command": null,
      "requiresApproval": false
    },
    {
      "id": "step-002",
      "name": "run: aws iam create-access-key",
      "type": "shell_command",
      "risk": "high",
      "command": "aws iam create-access-key",
      "requiresApproval": true
    }
  ]
}
```

## 9. Stub-First Implementation Approach

### 9.1 Why Stub First

The architecture should be proven before any real provider integration is introduced.

That means:

- make the Django -> FastAPI boundary real
- keep the FastAPI parser deterministic at first
- validate mapping and persistence end to end
- only later swap the stub parser for real provider-backed logic

This reduces risk because boundary mistakes are cheaper to correct before model prompting and provider variability enter the path.

### 9.2 Phase-07 Stub Behavior

Recommended deterministic stub behavior for `apps/ai`:

1. normalize runbook text
2. split into non-empty lines
3. remove simple numbering or bullet markers
4. create one step candidate per line
5. default `step_type` to `manual_task`
6. default `risk_level` to `medium`
7. set `requires_approval` to `false`
8. optionally detect `run:` prefix and emit `shell_command`
9. if no lines remain, create one fallback step from the runbook title

This mirrors the earlier deterministic transform idea from Phase 03 while putting the behavior behind the real service boundary.

### 9.3 Why This Is the Right Amount of Scope

It gives:

- real HTTP boundary
- real timeout/error path
- real Django mapping
- real persistence path
- real tests around boundary behavior

It does not add:

- provider prompt engineering
- queueing
- async workflow generation
- summarization
- enrichment
- failure explanation pipelines

## 10. File-by-File Implementation Plan

This section is the implementation blueprint only. It does not mean all files already exist.

### Django API Service

`/home/dylan/code/runbook-platform/apps/api/requirements/base.txt`

- add `httpx>=0.27,<1.0`

`/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`

- add AI service settings for base URL and explicit timeouts
- keep settings read-only at runtime

`/home/dylan/code/runbook-platform/.env.example`

- keep `AI_BASE_URL=http://ai:8001`
- optionally add the timeout env vars if the team prefers env-driven tuning
- do not add any web-facing AI URL variable

`/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_client.py`

- new narrow HTTP client
- own transport details and exception translation
- return local parsed candidate objects

`/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_types.py`

- optional dataclasses or typed dicts for the boundary
- skip this file if `ai_client.py` stays readable without it

`/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py`

- update create-workflow orchestration to call `RunbookAiClient`
- map candidate to canonical workflow JSON
- validate before persistence
- persist workflow only after successful mapping

`/home/dylan/code/runbook-platform/apps/api/apps/workflows/serializers.py`

- keep public create input minimal: `runbook_id`
- do not accept raw workflow JSON from frontend in this phase

`/home/dylan/code/runbook-platform/apps/api/apps/workflows/views.py`

- keep view thin
- call service layer only
- do not call HTTPX directly from a view

`/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_services.py`

- test service orchestration and mapping behavior

`/home/dylan/code/runbook-platform/apps/api/apps/workflows/tests/test_api.py`

- test the public create endpoint remains Django-owned

`/home/dylan/code/runbook-platform/apps/api/apps/runbooks/tests/test_ai_client.py`

- test AI client exception and response mapping behavior

### FastAPI AI Service

`/home/dylan/code/runbook-platform/apps/ai/app/api/routes/parse.py`

- replace placeholder route body with typed request/response contract
- keep only workflow-parse behavior in scope

`/home/dylan/code/runbook-platform/apps/ai/app/schemas/workflow_parse.py`

- add Pydantic request and response models

`/home/dylan/code/runbook-platform/apps/ai/app/services/workflow_parser.py`

- add deterministic stub parser logic

`/home/dylan/code/runbook-platform/apps/ai/app/main.py`

- keep health and existing placeholder routers if desired
- do not expand Django integration beyond `/parse/runbook`

`/home/dylan/code/runbook-platform/apps/ai/tests/test_parse_route.py`

- optional but appropriate route-level test coverage

`/home/dylan/code/runbook-platform/apps/ai/tests/test_workflow_parser.py`

- optional but appropriate deterministic parser tests

### Files Explicitly Not Needed in This Phase

Do not add:

- Django Celery tasks
- queue models for AI jobs
- frontend FastAPI client modules
- runner FastAPI client modules
- AI result history tables
- summarization service files
- enrichment orchestration in Django

## 11. Step-by-Step Execution Checklist

1. Add `httpx` to Django API requirements.
2. Add explicit AI settings in `/home/dylan/code/runbook-platform/apps/api/config/settings/base.py`.
3. Keep or lightly extend `/home/dylan/code/runbook-platform/.env.example` for timeout settings.
4. Create `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_client.py`.
5. Add optional local AI boundary types if they make the client clearer.
6. Define the FastAPI request/response Pydantic models in `/home/dylan/code/runbook-platform/apps/ai/app/schemas/workflow_parse.py`.
7. Replace the placeholder `parse_runbook` route with a typed contract.
8. Add deterministic stub parsing logic in `/home/dylan/code/runbook-platform/apps/ai/app/services/workflow_parser.py`.
9. Update `/home/dylan/code/runbook-platform/apps/api/apps/workflows/services.py` so workflow creation calls the AI client.
10. Map FastAPI candidate output into canonical workflow JSON.
11. Validate the mapped JSON before persistence.
12. Persist the workflow only after successful AI response mapping.
13. Keep the public endpoint as `POST /api/v1/workflows/`.
14. Add Django client tests, service tests, and API tests.
15. Add FastAPI route/parser tests if the team wants service-local coverage.
16. Verify health, request path, mapping, and failure behavior manually.

## 12. Verification Plan

### 12.1 Service Health

Verify:

- Django health endpoint responds at `/health/`
- FastAPI health endpoint responds at `/health`
- FastAPI parse route is mounted under `/parse/runbook`

Manual checks:

```bash
curl -sS http://localhost:8000/health/
curl -sS http://localhost:8001/health
```

Expected outcome:

- both services are reachable
- AI service is alive before Django tries to call it

### 12.2 Request Path

Verify the full path is:

```text
browser -> Django /api/v1/workflows/ -> Django service -> Django AI client -> FastAPI /parse/runbook
```

and not:

```text
browser -> FastAPI
```

Checks:

- frontend config uses `VITE_API_BASE_URL`, not `AI_BASE_URL`
- Django logs show outbound AI call from workflow creation
- FastAPI logs show caller request correlated by `request_id`

### 12.3 Mapping Validation

Verify:

- AI response with valid steps maps to canonical workflow JSON
- mapped JSON matches shared schema shape
- step IDs are canonicalized correctly
- `requires_approval` becomes `requiresApproval`
- `risk_level` becomes `risk`
- `step_type` becomes `type`

### 12.4 Failure Path

Verify at minimum:

- FastAPI unavailable -> Django returns stable failure envelope
- FastAPI timeout -> Django returns stable failure envelope
- FastAPI returns invalid JSON shape -> Django rejects and does not persist
- FastAPI returns zero steps -> Django rejects and does not persist

The critical invariant:

- no partial workflow row should survive a failed AI boundary call

## 13. Test Plan

### 13.1 Django-Side Tests

Recommended Django tests:

`apps.workflows.tests.test_services`

- successful workflow creation with stubbed AI response
- zero-step AI response rejected
- malformed AI response rejected
- AI unavailable maps to stable domain exception
- AI timeout maps to stable domain exception
- no workflow persists on failure
- workflow version allocation still happens in Django, not in FastAPI

`apps.workflows.tests.test_api`

- `POST /api/v1/workflows/` accepts `runbook_id`
- public endpoint does not require frontend knowledge of AI
- public endpoint returns persisted workflow shape on success
- public endpoint returns stable error envelope on upstream failure

`apps.runbooks.tests.test_ai_client`

- request payload shape is correct
- success response maps to local candidate object
- invalid upstream JSON raises contract error
- `httpx.ConnectError` maps to unavailable error
- `httpx.ReadTimeout` maps to timeout error

### 13.2 FastAPI-Side Tests If Appropriate

Appropriate but still small:

- `POST /parse/runbook` accepts valid request payload
- response model shape is stable
- deterministic input yields deterministic output
- empty content produces one fallback step
- `run:` prefix behavior works if included

Do not build an enormous AI-service test pyramid in this phase.

### 13.3 Contract Tests and Stubbing Strategy

Recommended contract strategy:

- use `httpx.MockTransport` for Django AI client tests
- keep fixture JSON examples for success and failure cases
- test the Django client against raw HTTP payloads, not only mocked methods
- separately test the FastAPI route with `TestClient`

This gives two useful seams:

1. Django can prove it handles the wire contract correctly.
2. FastAPI can prove it serves that contract correctly.

That is enough for Phase 07.

### 13.4 What Not to Test Yet

Do not spend time in Phase 07 on:

- real provider integration tests
- end-to-end browser tests for AI behavior
- load testing
- queue behavior
- runner integration with AI

## 14. Best Practices / Anti-Patterns

### Best Practices

- Keep the public workflow create API in Django.
- Keep the FastAPI contract narrow and typed.
- Use one Django-side AI client abstraction.
- Use explicit HTTPX timeouts.
- Keep mapping and persistence in Django services.
- Validate the final workflow JSON before save.
- Keep the FastAPI implementation deterministic first.
- Use request IDs for cross-service tracing.

### Anti-Patterns

- letting the frontend call FastAPI directly
- exposing `AI_BASE_URL` to the frontend
- making FastAPI the owner of workflow records
- persisting provider-shaped JSON directly without Django mapping
- placing raw HTTPX calls inside DRF views
- placing workflow persistence in the FastAPI service
- expanding to summary generation or enrichment “while we are here”
- making runner call FastAPI “for convenience”
- building a generic AI orchestration framework before one use case works
- silently swallowing malformed AI responses and creating partial workflows

## 15. Codex Batching Plan

Batch A: FastAPI parse contract only

- add `workflow_parse.py`
- upgrade `parse.py` from placeholder to typed route
- add deterministic `workflow_parser.py`
- add small FastAPI route/parser tests

Stop condition:

- `POST /parse/runbook` returns the agreed stub response shape

Batch B: Django AI client boundary

- add `httpx` dependency
- add settings
- add `/apps/api/apps/runbooks/ai_client.py`
- add AI client tests with `MockTransport`

Stop condition:

- Django client can call the stub FastAPI contract and map it into local candidate objects

Batch C: Workflow orchestration integration

- update workflow service to call AI client
- map candidate to canonical workflow JSON
- validate and persist in Django
- keep public workflow create endpoint unchanged

Stop condition:

- `POST /api/v1/workflows/` creates a workflow through Django using the FastAPI stub

Batch D: Failure behavior and verification

- add API and service failure tests
- verify no partial persistence
- verify public error envelope
- manually verify service health and end-to-end request path

Stop condition:

- both happy path and failure path are stable and boundary-correct

## 16. Definition of Done

Phase 07 is done only when all of the following are true:

- frontend still calls Django only
- Django remains the control plane and system of record
- Django has a narrow internal AI client at `/home/dylan/code/runbook-platform/apps/api/apps/runbooks/ai_client.py` or equivalent approved local path
- Django workflow creation calls FastAPI only through that internal client
- FastAPI exposes a typed internal parse contract for runbook-to-workflow parsing
- the only AI use case implemented is create workflow from runbook
- FastAPI response is mapped into canonical workflow JSON in Django
- final validation and persistence happen in Django
- `enrich` and `summarize` are not wired into Django for this phase
- frontend does not know `AI_BASE_URL`
- runner does not call FastAPI
- timeout and error handling are explicit
- malformed or failed AI responses do not create partial workflow records
- Django-side tests cover happy path, contract failure, timeout, and unavailable service cases
- FastAPI-side tests exist if the team chooses them, but remain narrow and contract-focused
- no generic AI platform, queueing system, or extra use cases were added

## Final Direction

The correct Phase 07 implementation is not “add FastAPI and let the frontend use it.” The correct implementation is “make FastAPI a narrow internal parser behind Django, for one use case, with Django still owning orchestration, validation, and persistence.”
