# Phase 10.6: Richer AI Parsing Blueprint

| Field | Value |
|---|---|
| Phase number | 10.6 |
| Phase name | Richer AI Parsing |
| Objective | Replace the deterministic stub parser with real LLM-backed parsing, implement a parse→enrich pipeline, persist AI-generated workflows as human-reviewable drafts, and enforce the review gate before execution. |
| Status | Blueprint only |
| Depends on | Phases 01–09 complete and verified; Phase 10.1 approvals complete and verified; Phase 10.2 policies complete and verified; Phase 10.3 audit trail complete and verified; Phase 10.4 artifacts complete and verified; Phase 10.5 integrations complete and verified |
| Authored | 2026-04-24 |

---

## 1. Purpose and sequencing rationale

The runbook platform's primary value proposition is that an operator can paste a real runbook document — a Confluence page, a Markdown file, a Google Doc export, a shell script with comments — and the platform produces a structured, executable workflow. Without real AI parsing, users must author every workflow step by hand. That defeats the differentiator.

Phase 10.6 delivers this: real LLM-backed parsing of operator-supplied runbook text into reviewable workflow candidates, a human review gate before those candidates become executable, and an enrich route that adds risk classification and approval suggestions. The summarize route is also activated for post-execution summaries.

**Why Phase 10.6 comes after Phase 10.5 (integrations) and before Phase 10.7 (auth):**

The workflow schema and control plane must be fully stable before improving AI capability. After Phases 10.1–10.5 the following are all implemented and stable:

- `requiresApproval` on workflow steps is fully enforced by the runner and approval service.
- `risk` levels on steps drive policy evaluation.
- The audit trail captures every state transition.
- Artifact storage captures step outputs.
- Integrations notify external systems about execution events, including approval requests.

If AI parsing had been implemented earlier — say, in Phase 10.1 — every subsequent schema change (adding approval types, risk levels, step types) would have required simultaneous updates to the LLM prompts, the Pydantic response models, the Django mapper, and the schema validator. Building on an unstable schema produces compounding debt.

Auth (Phase 10.7) comes after AI parsing rather than before it for the same reason documented in the roadmap: auth is a cross-cutting concern that touches every model and endpoint. Adding it before the AI parsing model (specifically the `requires_review` flag and the review endpoints) is stable means wiring RBAC to models that will immediately change. The correct order is: prove the domain model with AI parsing, then add auth as a layer.

**What Phase 10.6 does not do:**

- It does not add streaming LLM output. Full responses only.
- It does not add multi-model routing or fallback chains. One model (OpenAI), one prompt set.
- It does not add background AI job orchestration. Parse is synchronous from the user's perspective — it may be slow but the user waits for the result.
- It does not automatically execute AI-parsed workflows. The human review gate is a hard requirement.
- It does not allow AI output to bypass schema validation. All LLM output is validated against `workflow.schema.json` before Django persists it.
- It does not add AI-driven re-enrich on demand as a user-facing feature (though the `/enrich` route is implemented; see section 6.2).

At blueprint authoring time, the checked-out source tree shows:

- `apps/ai/app/api/routes/parse.py` — typed endpoint delegating to `parse_runbook_to_candidate()`. The service is a deterministic regex parser, not an LLM.
- `apps/ai/app/schemas/workflow_parse.py` — Pydantic models: `ParseRunbookRequest`, `ParseRunbookResponse`, `WorkflowCandidateStep`. Missing the `command` field on `WorkflowCandidateStep`.
- `apps/ai/app/services/workflow_parser.py` — deterministic line-extraction stub. Must be replaced.
- `apps/ai/app/api/routes/enrich.py` — placeholder returning `{"status": "ok"}`. Must be replaced.
- `apps/ai/app/api/routes/summarize.py` — placeholder returning `{"status": "ok"}`. Must be replaced.
- `apps/ai/app/prompts/__init__.py` — empty. Must be populated.
- `apps/ai/app/services/__init__.py` — empty. Must be extended with `llm_client.py`.
- `apps/ai/requirements/base.txt` — has `fastapi`, `uvicorn`, `pydantic-settings`, `httpx`. Missing `openai`.
- `apps/api/apps/runbooks/ai_client.py` — `RunbookAiClient` with real `httpx` client, response validation, typed errors. Calls `/parse/runbook`.
- `apps/api/apps/workflows/internal_clients.py` — `HttpWorkflowTransformClient` wrapping `RunbookAiClient`. Used by `services.py`.
- `apps/api/apps/workflows/services.py` — `create_workflow_from_runbook()` → `create_workflow()` → validate → map → persist. No `requires_review` concept exists yet.
- `apps/api/apps/workflows/models.py` — `Workflow` model has `status`, `definition`, `definition_schema_version`. No `requires_review` or `parse_source` field.
- `packages/workflow-schema/workflow.schema.json` — canonical schema with required `name`, `steps`, each step requires `id`, `name`, `type`, `risk`; optional `command`, `requiresApproval`.
- `apps/api/config/settings/base.py` — AI service settings (`AI_BASE_URL`, timeouts). No AI input limit or caching settings yet.
- `.env.example` — has `OPENAI_API_KEY=` (empty), `AI_BASE_URL`. No parse-specific settings.

This blueprint assumes the requested baseline: Phases 01–09, approvals, policies, audit, artifacts, and integrations are complete and verified. All references to those systems assume they have been fully implemented.

---

## 2. Current-state inspection checklist

Before implementation begins, re-read the source files in this order. Do not implement from memory.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` section 4.6 to confirm richer AI parsing sequencing and key design decisions are still current.
- [ ] Read `docs/blueprints/phase-07-ai-service-boundary-blueprint.md` sections 4 and 8 to confirm the Django AI client pattern and mapping strategy are still in place.
- [ ] Read `docs/blueprints/phase-10-05-integrations-blueprint.md` section 14 (definition of done) and confirm Phase 10.5 is complete.
- [ ] Inspect `apps/ai/app/schemas/workflow_parse.py` — confirm `WorkflowCandidateStep` fields and verify `command` is absent.
- [ ] Inspect `apps/ai/app/services/workflow_parser.py` — confirm the deterministic stub is still the implementation.
- [ ] Inspect `apps/ai/app/api/routes/enrich.py` — confirm it is a placeholder.
- [ ] Inspect `apps/ai/app/api/routes/summarize.py` — confirm it is a placeholder.
- [ ] Inspect `apps/ai/app/prompts/` — confirm it contains only `__init__.py`.
- [ ] Inspect `apps/ai/requirements/base.txt` — confirm `openai` is absent; note exact version pins of other packages.
- [ ] Inspect `apps/api/apps/workflows/models.py` — confirm `requires_review` and `parse_source` fields are absent.
- [ ] Inspect `apps/api/apps/workflows/services.py` — note the exact signature of `create_workflow_from_runbook()` and `_validate_candidate()`.
- [ ] Inspect `apps/api/apps/workflows/internal_clients.py` — understand the `HttpWorkflowTransformClient` and `WorkflowCandidate` types that bridge the AI client to the workflow service.
- [ ] Inspect `apps/api/apps/runbooks/ai_client.py` — confirm `RunbookAiClient` only calls `/parse/runbook`. Note the exception hierarchy.
- [ ] Inspect `apps/api/apps/executions/services.py` — confirm the exact function that creates executions and identify where the `requires_review` guard must be added.
- [ ] Inspect `packages/workflow-schema/workflow.schema.json` — confirm the exact schema used for validation.
- [ ] Inspect `apps/api/config/settings/base.py` — note which AI settings exist; confirm `OPENAI_API_KEY` is not yet read here.
- [ ] Inspect `.env.example` — confirm `OPENAI_API_KEY=` is present and empty.
- [ ] Inspect `apps/web/src/features/workflows/` and `apps/web/src/routes/workflows/` — understand the existing workflow UI structure before adding review pages.
- [ ] Run current tests before starting: `docker compose exec api pytest`, `cd apps/web && npm test -- --run`.
- [ ] Confirm `OPENAI_API_KEY` is set in local `.env` before testing LLM-backed routes.

---

## 3. Architecture invariants and boundaries

These invariants apply to every decision in Phase 10.6. Any approach that requires violating one of them is wrong.

| Invariant | Phase 10.6 consequence |
|---|---|
| Django is the control plane. | Django decides whether AI output is valid, stores the validated workflow, enforces the review gate, and controls state transitions. The AI service is an advisory dependency. |
| Runner talks only to Django internal APIs. | The runner does not call the AI service. It does not know that AI parsing exists. |
| Frontend talks only to Django public APIs. | The React app calls `/api/v1/workflows/` and related endpoints. It never calls FastAPI directly. It does not know the AI service URL. |
| AI service is stateless and advisory. | FastAPI processes text and returns structured candidates. It does not persist anything. Django decides whether to use, modify, or discard the output. |
| All APIs remain under `/api/v1/`. | Parse-trigger, review, accept, and reject endpoints all live under `/api/v1/`. |
| Internal runner APIs remain under `/api/v1/internal/`. | No AI parsing API is on the internal router. |
| UUID primary keys remain standard. | No new model may use sequential integer PKs. |
| Business logic belongs in `services.py`. | LLM output mapping, schema validation, `requires_review` enforcement, review acceptance, and rejection logic all live in `apps/api/apps/workflows/services.py`. Views call services. |
| AI output must never become trusted state until Django validates it. | LLM output is first mapped by the Django AI client into typed Python objects. Then schema-validated by Django against `workflow.schema.json`. Only after both passes does Django persist the workflow record. |

Additional boundaries specific to Phase 10.6:

- The AI service reads `OPENAI_API_KEY` from its environment. It does not call Django to retrieve secrets.
- The AI service does not call any other service — not Django, not the runner, not external systems.
- Input character limits are enforced by Django before calling the AI service, not inside the AI service. The AI service can trust its input has already been bounded.
- Prompt templates are Python string constants in `apps/ai/app/prompts/`. They are not stored in the database, not editable at runtime, and not configurable via the API.
- AI-generated workflows are created with `requires_review=True` and `status=DRAFT`. They cannot be executed in this state. The execution service must reject attempts to execute a `requires_review=True` workflow.
- The `/enrich` route takes a parsed candidate and adds risk and approval metadata. Django is responsible for the two-step call sequence (`parse` → `enrich`). The AI service routes are independent and have no shared state.
- Schema validation against `workflow.schema.json` happens in Django, not in the AI service. The AI service validates its own Pydantic models; Django validates the final mapped definition against the canonical schema.

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.6 |
|---|---|
| `apps/ai/app/services/llm_client.py` | New file. Thin wrapper around `openai.OpenAI` SDK with structured output, token budget enforcement, and explicit timeout. |
| `apps/ai/app/prompts/` | New files: `parse.py`, `enrich.py`, `summarize.py`. System prompts and user prompt templates as Python string constants. |
| `apps/ai/app/schemas/workflow_parse.py` | Add `command: str \| None = None` to `WorkflowCandidateStep`. Add new schemas for enrich and summarize routes. |
| `apps/ai/app/services/workflow_parser.py` | Replace deterministic stub with LLM-backed implementation using `LLMClient`. Keep the deterministic fallback for test environments. |
| `apps/ai/app/api/routes/enrich.py` | Replace placeholder with typed endpoint: accepts `WorkflowEnrichRequest`, returns `WorkflowEnrichResponse`. |
| `apps/ai/app/api/routes/summarize.py` | Replace placeholder with typed endpoint: accepts `ExecutionSummarizeRequest`, returns `ExecutionSummarizeResponse`. |
| `apps/ai/requirements/base.txt` | Add `openai>=1.40,<2.0`. |
| `apps/api/apps/workflows/models.py` | Add `requires_review: BooleanField(default=False)` and `parse_source: CharField` with enum `manual` / `ai_parse`. |
| `apps/api/apps/workflows/migrations/` | New migration for model field additions. |
| `apps/api/apps/workflows/services.py` | Update `create_workflow_from_runbook()` to call `/enrich` after `/parse`; set `requires_review=True` and `parse_source="ai_parse"`; add `accept_review()` and `reject_review()` service functions; add jsonschema validation in `_validate_candidate()`; add `requires_review` guard in execution creation path; add input hash cache. |
| `apps/api/apps/workflows/internal_clients.py` | Extend to support the enrich call. Add `HttpWorkflowEnrichClient` or extend `HttpWorkflowTransformClient` to call `/enrich/workflow`. |
| `apps/api/apps/runbooks/ai_client.py` | Add `enrich_workflow_candidate()` method calling `/enrich/workflow`. Add `summarize_execution()` method calling `/summarize/execution`. |
| `apps/api/apps/workflows/serializers.py` | Add `requires_review` and `parse_source` to workflow serializer output. |
| `apps/api/apps/workflows/views.py` | Add `accept_review` and `reject_review` actions on the workflow detail endpoint. |
| `apps/api/apps/workflows/urls.py` | Register `accept-review/` and `reject-review/` URL patterns. |
| `apps/api/apps/executions/services.py` | Add guard: raise error if workflow has `requires_review=True` when creating execution. |
| `apps/api/config/settings/base.py` | Add `AI_MAX_INPUT_CHARS`, `AI_PARSE_MODEL`, and `AI_READ_TIMEOUT_SECONDS` increase recommendation for LLM latency. |
| `apps/api/requirements/base.txt` | Add `jsonschema>=4.0,<5.0` for schema validation. |
| `.env.example` | Add `AI_MAX_INPUT_CHARS=100000` and `AI_PARSE_MODEL=gpt-4o`. |
| `apps/web/src/features/workflows/` | Add types for `requires_review`, `parse_source`. Add review hooks. |
| `apps/web/src/routes/workflows/` | Add `WorkflowReviewPage.tsx` with step review table, edit affordance, accept and reject actions. |
| `apps/web/src/app/router.tsx` | Register review route. |

**Likely backend files touched:**

- `apps/ai/requirements/base.txt`
- `apps/ai/app/services/llm_client.py` (new)
- `apps/ai/app/prompts/parse.py` (new)
- `apps/ai/app/prompts/enrich.py` (new)
- `apps/ai/app/prompts/summarize.py` (new)
- `apps/ai/app/schemas/workflow_parse.py`
- `apps/ai/app/schemas/workflow_enrich.py` (new)
- `apps/ai/app/schemas/workflow_summarize.py` (new)
- `apps/ai/app/services/workflow_parser.py`
- `apps/ai/app/api/routes/enrich.py`
- `apps/ai/app/api/routes/summarize.py`
- `apps/ai/tests/test_parse_route.py` (extend)
- `apps/ai/tests/test_enrich_route.py` (new)
- `apps/ai/tests/test_summarize_route.py` (new)
- `apps/ai/tests/test_llm_client.py` (new)
- `apps/api/requirements/base.txt`
- `apps/api/apps/workflows/models.py`
- `apps/api/apps/workflows/migrations/0003_workflow_review_fields.py` (new)
- `apps/api/apps/workflows/services.py`
- `apps/api/apps/workflows/internal_clients.py`
- `apps/api/apps/workflows/serializers.py`
- `apps/api/apps/workflows/views.py`
- `apps/api/apps/workflows/urls.py`
- `apps/api/apps/workflows/tests/test_services.py` (extend)
- `apps/api/apps/workflows/tests/test_api_contracts.py` (extend)
- `apps/api/apps/runbooks/ai_client.py`
- `apps/api/apps/runbooks/tests/test_ai_client.py` (extend)
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/tests/test_services.py` (extend)
- `apps/api/config/settings/base.py`
- `.env.example`

**Likely frontend files touched:**

- `apps/web/src/features/workflows/types.ts`
- `apps/web/src/features/workflows/api/workflowsApi.ts`
- `apps/web/src/features/workflows/hooks/useAcceptWorkflowReview.ts` (new)
- `apps/web/src/features/workflows/hooks/useRejectWorkflowReview.ts` (new)
- `apps/web/src/routes/workflows/WorkflowReviewPage.tsx` (new)
- `apps/web/src/routes/workflows/WorkflowReviewPage.test.tsx` (new)
- `apps/web/src/app/router.tsx`

**Out of scope unless explicitly approved:**

- Streaming LLM output.
- Multi-model routing or provider fallback chains.
- Background AI job queue (Celery, SQS, etc.).
- AI-powered step command generation (the LLM may suggest commands for `shell_command` steps, but generating and auto-executing commands without human review is prohibited).
- Re-enrich user action (the `/enrich` route is implemented but no "re-classify this workflow" button is added to the UI in Phase 10.6).
- AI-powered runbook summarization triggered from the UI. The `/summarize` route is implemented; wiring it to the execution completion hook is in scope, but a dedicated summary UI panel is deferred.
- Auth changes (`AllowAny` remains until Phase 10.7).

---

## 5. Data model and contracts: candidate persistence, workflow schema changes, validation rules

### 5.1 `Workflow` model additions

Two new fields are required on `apps/api/apps/workflows/models.py`:

**`requires_review: BooleanField`**

```python
requires_review = models.BooleanField(
    default=False,
    help_text="True when the workflow was AI-generated and has not yet been reviewed by a human.",
)
```

Default is `False` so that manually-created workflows (any future hand-authored path) do not require review. AI-generated workflows set this to `True` in `create_workflow_from_runbook()`. `accept_review()` sets it to `False`. This field is the enforcement point: the execution service checks it before creating an execution.

**`parse_source: CharField`**

```python
class ParseSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    AI_PARSE = "ai_parse", "AI Parse"

parse_source = models.CharField(
    max_length=16,
    choices=ParseSource.choices,
    default=ParseSource.MANUAL,
)
```

Allows audit queries such as "show me all workflows parsed by AI in the last 30 days" and supports future reporting without querying execution history.

**Migration name:** `0003_workflow_review_fields`

Both fields have defaults and are nullable-compatible, so the migration is non-destructive on existing rows.

### 5.2 `WorkflowCandidateStep` schema additions

The current `WorkflowCandidateStep` in `apps/ai/app/schemas/workflow_parse.py` is missing `command`. The workflow schema in `packages/workflow-schema/workflow.schema.json` defines `command` as an optional string on steps. The AI service must be able to output it for `shell_command` type steps:

```python
class WorkflowCandidateStep(BaseModel):
    step_key: str
    name: str
    step_type: str        # e.g. "manual_task", "shell_command"
    risk_level: str       # e.g. "low", "medium", "high", "critical"
    command: str | None = None
    requires_approval: bool = False
```

The matching update in `apps/api/apps/runbooks/ai_client.py`:

```python
@dataclass
class WorkflowCandidateStep:
    step_key: str
    name: str
    step_type: str
    risk_level: str
    requires_approval: bool
    command: str | None = None
```

And in `_map_candidate_to_definition()` in `apps/api/apps/workflows/services.py`:

```python
step_dict = {
    "id": step.step_key,
    "name": step.name,
    "type": step.step_type,
    "risk": step.risk_level,
    "requiresApproval": step.requires_approval,
}
if step.command is not None:
    step_dict["command"] = step.command
```

### 5.3 Workflow schema changes (`workflow.schema.json`)

The canonical schema does not require changes for Phase 10.6. All AI output fields (`name`, `steps`, `id`, `name`, `type`, `risk`, `command`, `requiresApproval`) are already defined. The schema remains at `workflow.schema.v1`.

**Optional addition:** The roadmap mentions a `parsedFrom` provenance field. This is better expressed as the `parse_source` model field rather than embedding it in the definition JSON. Adding schema fields requires a schema version bump; a model field does not. Do not add `parsedFrom` to the schema in Phase 10.6.

### 5.4 Django-side schema validation

Add `jsonschema` to `apps/api/requirements/base.txt`. Extend `_validate_candidate()` in `apps/api/apps/workflows/services.py` to run jsonschema validation on the mapped definition before persisting:

```python
import json
import jsonschema
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parents[5] / "packages" / "workflow-schema" / "workflow.schema.json"

def _load_workflow_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())

def _validate_candidate(candidate: WorkflowCandidate) -> None:
    # Existing structural validation (empty steps, duplicate keys, etc.) first
    ...
    # Then schema validation on the mapped definition
    definition = _map_candidate_to_definition(candidate)
    try:
        jsonschema.validate(definition, _load_workflow_schema())
    except jsonschema.ValidationError as exc:
        raise InvalidWorkflowDefinitionError(
            code="invalid_workflow_definition",
            detail=f"Parsed workflow failed schema validation: {exc.message}",
        ) from exc
```

Load the schema file once at module import or at first call (the file is small). Do not cache it indefinitely in a module-level variable if the schema might change between test runs; use `functools.lru_cache` with the path as key so it loads once per process.

### 5.5 Input hash caching

To avoid re-parsing the same document twice, maintain a simple in-memory parse cache in `apps/api/apps/runbooks/services.py` (or in the workflow creation flow):

```python
import hashlib
from functools import lru_cache

_PARSE_CACHE: dict[str, dict] = {}  # sha256 hex → mapped definition dict

def _content_hash(raw_content: str) -> str:
    return hashlib.sha256(raw_content.encode()).hexdigest()
```

Before calling the AI service, check if the composite cache key is in `_PARSE_CACHE`. If it is, skip the LLM call and use the cached definition directly. The cache is per-process and cleared on server restart — this is sufficient for Phase 10.6. Do not add Redis or Postgres-backed caching until measured need.

> **ARCHITECTURE DECISION (C-M02): The cache key must include model version, prompt version, schema version, and organization ID — not raw content hash alone.**
>
> A content-hash-only key means:
> - If `AI_PARSE_MODEL` is upgraded, stale cached output from the old model is served.
> - If the prompt template is revised (fixing a hallucination), stale cached outputs bypass the fix.
> - If the workflow schema changes, cached definitions based on the old schema may fail validation.
> - If org-specific behaviors are introduced (e.g., org-level risk overrides), cross-org cache pollution occurs.

**Composite cache key:**
```python
from functools import lru_cache

CURRENT_PROMPT_VERSION = "v1"  # Increment when parse/enrich prompts change

def _cache_key(raw_content: str, org_id: str) -> str:
    content_hash = hashlib.sha256(raw_content.encode()).hexdigest()
    schema_hash = _get_schema_hash()  # hash of workflow.schema.json, cached at startup
    return f"{settings.AI_PARSE_MODEL}:{CURRENT_PROMPT_VERSION}:{schema_hash}:{org_id}:{content_hash}"
```

The `_PARSE_CACHE` dict is bounded using `functools.lru_cache` or a `collections.OrderedDict` with a max size (e.g., 256 entries). An unbounded dict is a memory leak: long-running workers accumulate entries indefinitely.

```python
from collections import OrderedDict
_PARSE_CACHE: OrderedDict[str, dict] = OrderedDict()
_CACHE_MAX_SIZE = 256

def _cache_put(key: str, value: dict) -> None:
    _PARSE_CACHE[key] = value
    if len(_PARSE_CACHE) > _CACHE_MAX_SIZE:
        _PARSE_CACHE.popitem(last=False)  # evict oldest
```

**Cache invalidation:** The composite key changes whenever model, prompt version, schema, or org changes. No manual invalidation required.

**Cache scope:** The in-memory cache only prevents re-parsing within a single Django process lifetime. This is acceptable for Phase 10.6. Cross-process caching (multiple Gunicorn workers) is a Phase 10.9 concern.

### 5.6 `requires_review` enforcement in execution service

In `apps/api/apps/executions/services.py`, the function that creates an execution must check:

```python
def create_execution(*, workflow: Workflow, ...) -> Execution:
    if workflow.requires_review:
        raise InvalidStateTransitionError(
            code="workflow_requires_review",
            detail="This workflow was AI-generated and must be reviewed before it can be executed.",
        )
    ...
```

This is the hard gate. No amount of frontend validation replaces this server-side check.

---

## 6. FastAPI AI contracts and Django AI client contracts

### 6.1 Parse route (`POST /parse/runbook`)

**Current state:** Typed endpoint exists; delegates to deterministic stub parser.

**Phase 10.6 target:** Same endpoint signature, but the service implementation calls the LLM.

**FastAPI request (unchanged from Phase 07):**

```python
class RunbookInput(BaseModel):
    id: str
    title: str
    raw_content: str

class ParseRunbookRequest(BaseModel):
    request_id: str
    runbook: RunbookInput
```

**FastAPI response (add `command` field to step):**

```python
class WorkflowCandidateStep(BaseModel):
    step_key: str
    name: str
    step_type: str         # "manual_task" | "shell_command"
    risk_level: str        # "low" | "medium" | "high" | "critical"
    command: str | None = None
    requires_approval: bool = False

class ParseRunbookResponse(BaseModel):
    request_id: str
    workflow_title: str
    steps: list[WorkflowCandidateStep]
    warnings: list[str]
```

**Upstream LLM structured output schema for `/parse`:**

The parse call asks the LLM to extract steps only — names and types. Risk and approval classification is handled by `/enrich`. The structured output schema passed to the LLM as `response_format`:

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "RunbookParseResult",
    "strict": true,
    "schema": {
      "type": "object",
      "required": ["workflow_title", "steps", "warnings"],
      "properties": {
        "workflow_title": { "type": "string" },
        "steps": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["step_key", "name", "step_type"],
            "properties": {
              "step_key": { "type": "string" },
              "name": { "type": "string" },
              "step_type": { "type": "string", "enum": ["manual_task", "shell_command"] },
              "command": { "type": ["string", "null"] }
            },
            "additionalProperties": false
          }
        },
        "warnings": { "type": "array", "items": { "type": "string" } }
      },
      "additionalProperties": false
    }
  }
}
```

**After parse returns:** `risk_level` and `requires_approval` are not set by the parse call. They are filled by the enrich call. The parse response sets `risk_level` to `"medium"` and `requires_approval` to `False` as default placeholders until the enrich call runs.

**Error handling at the FastAPI level:** If the LLM returns a malformed response (Pydantic validation fails, or the model returns a refusal), the route returns HTTP 422 with:

```json
{
  "error": "parse_failed",
  "detail": "<reason>",
  "raw_output": "<truncated LLM output, max 500 chars>"
}
```

Django receives this as a non-200 status and raises `AiServiceBadResponseError`. The truncated raw output is logged at the Django level for debugging, but is never returned to the frontend.

### 6.2 Enrich route (`POST /enrich/workflow`)

**Current state:** Placeholder returning `{"status": "ok"}`. Must be replaced.

**Phase 10.6 target:** Typed endpoint that takes a parsed candidate (steps with names and types) and returns enriched steps with risk levels and approval suggestions.

**New FastAPI schemas (`apps/ai/app/schemas/workflow_enrich.py`):**

```python
class EnrichStepInput(BaseModel):
    step_key: str
    name: str
    step_type: str
    command: str | None = None

class WorkflowEnrichRequest(BaseModel):
    request_id: str
    workflow_title: str
    steps: list[EnrichStepInput]

class EnrichedStep(BaseModel):
    step_key: str
    risk_level: str      # "low" | "medium" | "high" | "critical"
    requires_approval: bool

class WorkflowEnrichResponse(BaseModel):
    request_id: str
    enriched_steps: list[EnrichedStep]
    warnings: list[str]
```

**Upstream LLM structured output schema for `/enrich`:**

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "WorkflowEnrichResult",
    "strict": true,
    "schema": {
      "type": "object",
      "required": ["enriched_steps", "warnings"],
      "properties": {
        "enriched_steps": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["step_key", "risk_level", "requires_approval"],
            "properties": {
              "step_key": { "type": "string" },
              "risk_level": { "type": "string", "enum": ["low", "medium", "high", "critical"] },
              "requires_approval": { "type": "boolean" }
            },
            "additionalProperties": false
          }
        },
        "warnings": { "type": "array", "items": { "type": "string" } }
      },
      "additionalProperties": false
    }
  }
}
```

**FastAPI route (`apps/ai/app/api/routes/enrich.py`):**

```python
@router.post("/workflow", response_model=WorkflowEnrichResponse)
def enrich_workflow(payload: WorkflowEnrichRequest) -> WorkflowEnrichResponse:
    return workflow_enricher.enrich_workflow_candidate(payload)
```

**Django reconciliation of parse + enrich:** Django calls `/parse/runbook` and receives steps with names and types. It then calls `/enrich/workflow` with those steps and receives `enriched_steps` keyed by `step_key`. Django merges the two responses: for each step from the parse response, look up the corresponding `step_key` in `enriched_steps` and apply `risk_level` and `requires_approval`. If the LLM returns an `enriched_steps` list that does not contain all `step_key` values from the parse response, Django raises `AiServiceContractError`.

### 6.3 Summarize route (`POST /summarize/execution`)

**Current state:** Placeholder. Must be replaced.

**Phase 10.6 target:** Accepts execution context and returns a plain-text or markdown summary.

**New FastAPI schemas (`apps/ai/app/schemas/workflow_summarize.py`):**

```python
class ExecutionStepSummary(BaseModel):
    name: str
    status: str       # "succeeded" | "failed" | "skipped"
    had_approval: bool

class ExecutionSummarizeRequest(BaseModel):
    request_id: str
    workflow_name: str
    execution_status: str      # "succeeded" | "failed" | "cancelled"
    steps: list[ExecutionStepSummary]
    failed_step_name: str | None = None
    artifact_count: int = 0

class ExecutionSummarizeResponse(BaseModel):
    request_id: str
    summary: str          # plain text or Markdown, max 500 chars
    warnings: list[str]
```

The summarize call uses a simple chat completion (no structured output required — the response is a free-form string) with a max token budget. Django calls this after an execution reaches a terminal state (`succeeded`, `failed`, `cancelled`) and stores the summary on the `Execution` model if that field exists (or logs it; see note below).

**Note on Execution model:** If the `Execution` model does not yet have a `summary` field, the Phase 10.6 implementation stores the summary as a text artifact (type `text/plain`, name `execution_summary.md`) using the existing artifact upload mechanism. This avoids a migration dependency and respects the artifact system built in Phase 10.4. Add `Execution.summary` as a separate migration in Phase 10.6 only if the Execution model is confirmed stable and the team explicitly requests it. Default: use the artifact mechanism.

### 6.4 Django AI client additions (`apps/api/apps/runbooks/ai_client.py`)

Extend `RunbookAiClient` with two new methods:

```python
def enrich_workflow_candidate(
    self,
    *,
    request_id: str,
    workflow_title: str,
    steps: list[WorkflowCandidateStep],
) -> "WorkflowEnrichResult":
    """
    Call the AI service to add risk classification and approval suggestions
    to a parsed workflow candidate.
    """
    ...

def summarize_execution(
    self,
    *,
    request_id: str,
    workflow_name: str,
    execution_status: str,
    steps: list[dict],
    failed_step_name: str | None = None,
    artifact_count: int = 0,
) -> str:
    """
    Call the AI service to generate a plain-text execution summary.
    Returns the summary string.
    """
    ...
```

Add `WorkflowEnrichResult` as a local dataclass:

```python
@dataclass
class EnrichedStepResult:
    step_key: str
    risk_level: str
    requires_approval: bool

@dataclass
class WorkflowEnrichResult:
    request_id: str
    enriched_steps: list[EnrichedStepResult]
    warnings: list[str]
```

### 6.5 Timeout posture for LLM-backed routes

The current `AI_READ_TIMEOUT_SECONDS = 20.0` was set for the stub parser (which responds in milliseconds). For real LLM calls, 20 seconds is marginal for long runbook documents. Update the recommended default:

| Setting | Phase 07 default | Phase 10.6 recommended default | Reason |
|---|---|---|---|
| `AI_CONNECT_TIMEOUT_SECONDS` | 1.0 | 1.0 | Internal service; unchanged |
| `AI_READ_TIMEOUT_SECONDS` | 20.0 | 60.0 | LLM response for long documents can take 20–40 seconds |
| `AI_WRITE_TIMEOUT_SECONDS` | 5.0 | 10.0 | Large runbook documents take longer to transmit |
| `AI_POOL_TIMEOUT_SECONDS` | 1.0 | 1.0 | Unchanged |

Update `AI_READ_TIMEOUT_SECONDS=60.0` in `.env.example` with a comment explaining the reason.

### 6.6 LLM client design (`apps/ai/app/services/llm_client.py`)

```python
class LLMClient:
    """
    Thin synchronous wrapper around the OpenAI SDK.

    Responsibilities:
    - Read OPENAI_API_KEY from environment.
    - Enforce max_tokens budget on all calls.
    - Use structured output (json_schema response_format) for parse and enrich.
    - Return raw content strings or raise LLMCallError on failure.
    - Never persist anything.
    """

    def __init__(self, *, model: str, max_completion_tokens: int):
        ...

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_message: str,
        response_schema: dict,
    ) -> dict:
        """Returns parsed JSON dict. Raises LLMCallError on refusal or validation failure."""
        ...

    def complete_text(
        self,
        *,
        system_prompt: str,
        user_message: str,
        max_tokens: int,
    ) -> str:
        """Returns a free-form text string. Raises LLMCallError on failure."""
        ...
```

`LLMCallError` is a FastAPI-local exception. It is never exposed to Django — the FastAPI route handler catches it and returns an appropriate HTTP error.

**Environment variables read by the AI service:**

| Variable | Source | Notes |
|---|---|---|
| `OPENAI_API_KEY` | `.env` / container env | Required. Startup fails if absent. |
| `AI_PARSE_MODEL` | `.env` | Default `gpt-4o`. Controls which model is used for parse and enrich calls. |
| `AI_MAX_COMPLETION_TOKENS` | `.env` | Default `4096`. Budget per LLM call. |

These are read in `apps/ai/app/core/` or in a `pydantic-settings` config class, not from Django settings.

---

## 7. API contracts for parse trigger, candidate review, acceptance, and rejection

### 7.1 Trigger AI parsing: `POST /api/v1/workflows/`

The existing endpoint signature does not change. The frontend sends:

```json
{
  "runbook_id": "uuid"
}
```

Django internally calls `/parse/runbook` then `/enrich/workflow`, creates the `Workflow` record with `requires_review=True` and `parse_source="ai_parse"`, and returns the standard workflow response shape with new fields:

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "runbook_id": "uuid",
  "name": "Deploy API to Production",
  "version": 1,
  "status": "draft",
  "requires_review": true,
  "parse_source": "ai_parse",
  "definition": {
    "name": "Deploy API to Production",
    "steps": [
      {
        "id": "step-001",
        "name": "Verify canary deployment health",
        "type": "manual_task",
        "risk": "medium",
        "requiresApproval": false
      },
      {
        "id": "step-002",
        "name": "Run database migration",
        "type": "shell_command",
        "risk": "high",
        "command": "python manage.py migrate --run-syncdb",
        "requiresApproval": true
      }
    ]
  },
  "created_at": "...",
  "updated_at": "..."
}
```

**Error responses when AI parsing fails:**

| Code | HTTP Status | Condition |
|---|---|---|
| `workflow_ai_unavailable` | 502 | AI service unreachable |
| `workflow_ai_timeout` | 504 | AI service timed out |
| `workflow_ai_bad_response` | 502 | AI service returned non-2xx or non-JSON |
| `workflow_ai_contract_error` | 502 | AI service returned JSON that fails schema alignment |
| `invalid_workflow_definition` | 422 | Mapped definition fails jsonschema validation |
| `ai_input_too_large` | 400 | Runbook `raw_content` exceeds `AI_MAX_INPUT_CHARS` |

**Input size guard (enforced by Django before calling AI service):**

```python
def create_workflow_from_runbook(*, runbook: Runbook) -> Workflow:
    max_chars = settings.AI_MAX_INPUT_CHARS  # default 100,000
    if len(runbook.raw_content) > max_chars:
        raise DomainValidationError(
            code="ai_input_too_large",
            detail=f"Runbook content exceeds the maximum of {max_chars} characters for AI parsing.",
        )
    ...
```

### 7.2 Edit workflow definition before review: `PATCH /api/v1/workflows/{id}/`

The frontend may want to edit steps before accepting. This is handled by the existing (or extended) PATCH endpoint. The implementation allows partial update of `definition` when `requires_review=True`. After accepting review, the definition is frozen (PATCH is rejected on `status=published` workflows per existing rules).

**Validation rule:** When `PATCH`ing a workflow with `requires_review=True`, run `_validate_candidate` (including jsonschema validation) on the updated definition before saving. Reject invalid definitions.

### 7.3 Accept review: `POST /api/v1/workflows/{id}/accept-review/`

Sets `requires_review=False`. The workflow remains in `DRAFT` status and can then be published separately.

**Request:** No body required.

**Response (200):** Updated workflow with `requires_review: false`.

**Error conditions:**

| Code | HTTP Status | Condition |
|---|---|---|
| `workflow_not_pending_review` | 400 | `requires_review` is already `False` |
| `workflow_not_draft` | 400 | Workflow is not in `DRAFT` status (cannot review a published workflow) |

**Service function:**

```python
def accept_workflow_review(*, workflow: Workflow) -> Workflow:
    if not workflow.requires_review:
        raise DomainValidationError(
            code="workflow_not_pending_review",
            detail="This workflow is not pending review.",
        )
    if workflow.status != Workflow.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="workflow_not_draft",
            detail="Only draft workflows can be reviewed.",
        )
    workflow.requires_review = False
    workflow.save(update_fields=["requires_review", "updated_at"])
    return workflow
```

### 7.4 Reject review: `POST /api/v1/workflows/{id}/reject-review/`

Archives the AI-parsed workflow without executing it. The runbook remains available for re-parsing.

**Request:** No body required (optionally accepts `{"reason": "string"}` for audit metadata).

**Response (200):** Updated workflow with `status: "archived"`.

**Error conditions:**

| Code | HTTP Status | Condition |
|---|---|---|
| `workflow_not_pending_review` | 400 | `requires_review` is `False` — nothing to reject |
| `workflow_not_draft` | 400 | Only draft workflows can be rejected |

**Service function:**

```python
def reject_workflow_review(*, workflow: Workflow) -> Workflow:
    if not workflow.requires_review:
        raise DomainValidationError(
            code="workflow_not_pending_review",
            detail="This workflow is not pending review.",
        )
    if workflow.status != Workflow.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="workflow_not_draft",
            detail="Only draft workflows can be rejected.",
        )
    workflow.status = Workflow.Status.ARCHIVED
    workflow.save(update_fields=["status", "updated_at"])
    return workflow
```

### 7.5 Updated workflow serializer fields

The workflow serializer must include `requires_review` and `parse_source` in all responses. These are read-only from the API perspective; they are managed by the service layer only.

```python
class WorkflowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = [
            "id", "organization_id", "runbook_id", "name", "version",
            "status", "requires_review", "parse_source",
            "definition_schema_version", "definition",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "organization_id", "version", "requires_review",
            "parse_source", "definition_schema_version",
            "created_at", "updated_at",
        ]
```

### 7.6 Execution creation guard

When `POST /api/v1/executions/` is called (or the internal runner call), the execution service checks:

```python
if workflow.requires_review:
    raise InvalidStateTransitionError(
        code="workflow_requires_review",
        detail="This workflow was AI-generated and must be reviewed and accepted before execution.",
    )
```

The public API returns HTTP 400 with this error code. The frontend must check `requires_review` on the workflow before showing the "Run" button and disable it accordingly.

---

## 8. Frontend data contracts and review UI flow

### 8.1 TypeScript type additions

Extend `apps/web/src/features/workflows/types.ts`:

```typescript
export type ParseSource = 'manual' | 'ai_parse'

export interface Workflow {
  id: string
  organization_id: string
  runbook_id: string
  name: string
  version: number
  status: 'draft' | 'published' | 'superseded' | 'archived'
  requires_review: boolean     // new
  parse_source: ParseSource    // new
  definition_schema_version: string
  definition: WorkflowDefinition
  created_at: string
  updated_at: string
}

export interface WorkflowStep {
  id: string
  name: string
  type: 'manual_task' | 'shell_command'
  risk: 'low' | 'medium' | 'high' | 'critical'
  command?: string
  requiresApproval: boolean
}

export interface WorkflowDefinition {
  name: string
  steps: WorkflowStep[]
}
```

### 8.2 API functions

Add to `apps/web/src/features/workflows/api/workflowsApi.ts`:

```typescript
export async function acceptWorkflowReview(id: string): Promise<Workflow>
export async function rejectWorkflowReview(id: string): Promise<Workflow>
```

### 8.3 Hooks

```typescript
// apps/web/src/features/workflows/hooks/useAcceptWorkflowReview.ts
export function useAcceptWorkflowReview(): UseMutationResult<Workflow, Error, string>

// apps/web/src/features/workflows/hooks/useRejectWorkflowReview.ts
export function useRejectWorkflowReview(): UseMutationResult<Workflow, Error, string>
```

### 8.4 Workflow review page

`apps/web/src/routes/workflows/WorkflowReviewPage.tsx`:

Route: `/workflows/{id}/review`

Only accessible when `workflow.requires_review === true`. Redirect to the workflow detail page if `requires_review` is already false.

**Page sections:**

1. **Header:** "Review AI-Parsed Workflow" badge. Workflow name. Warning message: "This workflow was generated by AI. Review all steps carefully before accepting. Step commands will execute in the runner environment."

2. **Step table:** One row per step with columns: Position, Step Name, Type badge, Risk badge (colored by severity), Command (code block if present), Requires Approval (checkbox, read-only display).

3. **Edit affordance:** "Edit step" inline or modal. Allows changing: `name`, `risk`, `requiresApproval`. Does not allow changing `type` or `command` (those require full re-parse). Calls `PATCH /api/v1/workflows/{id}/` with the updated definition.

4. **AI parse warnings panel:** If the parse response contained warnings (stored in the workflow definition's metadata or surfaced through a separate field), display them above the step table.

5. **Action bar:**
   - **Accept** button: calls `POST /api/v1/workflows/{id}/accept-review/`. On success, redirects to the workflow detail page. The workflow is now reviewable and can be published.
   - **Reject** button: with confirmation dialog ("Are you sure you want to discard this AI-parsed workflow?"). Calls `POST /api/v1/workflows/{id}/reject-review/`. On success, redirects to the runbook page.

### 8.5 Workflow list and detail page additions

On the workflow list page and detail page:

- Show a "Pending Review" badge when `requires_review: true`.
- Disable the "Run" button with tooltip: "Review and accept this workflow before running it." when `requires_review: true`.
- Add a "Review" link on AI-parsed workflows pointing to `/workflows/{id}/review`.
- On the workflow detail page, show `parse_source` as an icon or label ("AI-generated" vs "Manual").

### 8.6 UI states

Required states for the review page:

- Loading workflow.
- Load error (workflow not found or not authorized).
- Already reviewed (redirect guard).
- Editing a step (inline form open).
- Step edit saving (mutation in progress).
- Accepting (accept button loading).
- Accept error (API returned error).
- Rejecting (reject button loading with confirmation dialog).
- Reject error.

### 8.7 What NOT to show in the UI

- Do not show the raw LLM output or prompt used to generate the workflow.
- Do not show the AI provider (OpenAI) or model name (gpt-4o) in the UI. This is an internal implementation detail.
- Do not show the input hash.
- Do not show a "re-parse" button in Phase 10.6. If the result is unacceptable, the user rejects and creates a new workflow. Re-parse is a future feature.

---

## 9. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### Milestone 0: Preflight and approval gate

**Purpose:** Confirm Phase 10.5 is complete and the test baseline is green before any changes.

**Files touched:** None.

**Commands:**

```bash
git status --short
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec runner pytest
cd apps/web && npm test -- --run
```

**Verify:**
- Phase 10.5 integration tests pass (delivery attempt creation, SSRF protection, redaction).
- `apps/api/apps/integrations/` is fully implemented.
- `AuditService.emit(...)` is confirmed working.
- `OPENAI_API_KEY` is set in local `.env`.
- Human confirms Phase 10.5 gate is passed before implementation starts.

**Rollback:** None; no files changed.

**Human approval gate: required.**

---

### Milestone 1: Add `openai` SDK to AI service and schema additions

**Purpose:** Install the OpenAI SDK in the AI service container and update the `WorkflowCandidateStep` to include `command`.

**Files touched:**

- `apps/ai/requirements/base.txt`
- `apps/ai/app/schemas/workflow_parse.py`
- `apps/ai/app/schemas/workflow_enrich.py` (new)
- `apps/ai/app/schemas/workflow_summarize.py` (new)
- `apps/ai/tests/test_parse_route.py` (update existing test for new `command` field)

**Small steps:**

1. Add `openai>=1.40,<2.0` to `apps/ai/requirements/base.txt`.
2. Add `command: str | None = None` to `WorkflowCandidateStep` in `workflow_parse.py`.
3. Create `apps/ai/app/schemas/workflow_enrich.py` with `EnrichStepInput`, `WorkflowEnrichRequest`, `EnrichedStep`, `WorkflowEnrichResponse`.
4. Create `apps/ai/app/schemas/workflow_summarize.py` with `ExecutionStepSummary`, `ExecutionSummarizeRequest`, `ExecutionSummarizeResponse`.
5. Update existing parse route tests to include `command: null` in expected response shapes.

**Commands:**

```bash
docker compose build ai
docker compose exec ai python -c "import openai; print(openai.__version__)"
docker compose exec ai pytest apps/ai/tests/test_parse_route.py
```

**Verify:** AI service container builds with `openai` installed. Parse route tests pass. Enrich and summarize schema imports succeed.

**Rollback:** Remove `openai` from requirements; revert schema files.

**Human approval gate: not required.**

---

### Milestone 2: LLM client wrapper

**Purpose:** Implement the `LLMClient` wrapper in the AI service. This is the only place in the AI service that calls the OpenAI API.

**Files touched:**

- `apps/ai/app/services/llm_client.py` (new)
- `apps/ai/app/core/config.py` (new or extend if already exists) — reads `OPENAI_API_KEY`, `AI_PARSE_MODEL`, `AI_MAX_COMPLETION_TOKENS` from environment
- `apps/ai/tests/test_llm_client.py` (new)

**Small steps:**

1. Create `apps/ai/app/core/config.py` with a Pydantic `Settings` class reading `OPENAI_API_KEY` (required), `AI_PARSE_MODEL` (default `gpt-4o`), `AI_MAX_COMPLETION_TOKENS` (default `4096`).
2. Implement `LLMClient` with `complete_structured(system_prompt, user_message, response_schema) -> dict` and `complete_text(system_prompt, user_message, max_tokens) -> str`.
3. Define `LLMCallError` as a local exception in `llm_client.py`.
4. In `complete_structured`, use `client.chat.completions.create(...)` with `response_format={"type": "json_schema", ...}`. Check `response.choices[0].message.refusal` and raise `LLMCallError` if set.
5. In `complete_text`, use `client.chat.completions.create(...)` without structured output, return `response.choices[0].message.content`.
6. Add unit tests using `unittest.mock.patch("openai.OpenAI")` to simulate success, refusal, and API error cases.

**Commands:**

```bash
docker compose exec ai pytest apps/ai/tests/test_llm_client.py
```

**Verify:** All unit tests pass with mocked OpenAI client. No real API calls made.

**Rollback:** Delete `llm_client.py`. Milestone 1 schema files are unaffected.

**Human approval gate: not required.**

---

### Milestone 3: Prompt templates

**Purpose:** Define prompt content as code-versioned Python constants. These are the only prompts used in Phase 10.6.

**Files touched:**

- `apps/ai/app/prompts/parse.py` (new)
- `apps/ai/app/prompts/enrich.py` (new)
- `apps/ai/app/prompts/summarize.py` (new)

**Small steps:**

1. Create `apps/ai/app/prompts/parse.py`:

```python
PARSE_SYSTEM_PROMPT = """
You are a technical workflow parser. Extract structured executable steps from runbook documents.

Rules:
- Extract each distinct action as a separate step. Do not merge steps.
- Use step_type "shell_command" only when the step involves running a specific shell command or script.
- Use step_type "manual_task" for all human actions, verifications, and decisions.
- If a shell command is identifiable in the step text, include it in the "command" field verbatim.
- Generate step_key values as "step-001", "step-002", etc.
- workflow_title should be a concise descriptive name for the overall process.
- Return exactly the steps you extract. Do not add preamble steps unless they are explicit in the document.
- Do not hallucinate commands that are not present in the document.
"""

PARSE_USER_TEMPLATE = """
Runbook title: {title}

Runbook content:
{content}
"""
```

2. Create `apps/ai/app/prompts/enrich.py`:

```python
ENRICH_SYSTEM_PROMPT = """
You are a security and operational risk classifier for runbook workflows.

For each step, assign:
- risk_level: "low" for read-only checks; "medium" for non-destructive writes; "high" for production-impacting changes; "critical" for irreversible or broadly-impacting actions.
- requires_approval: true only for high or critical risk steps that modify production infrastructure, delete data, or require sign-off.

Return exactly one enriched_step per input step, matching the same step_key values.
"""

ENRICH_USER_TEMPLATE = """
Workflow: {workflow_title}

Steps to classify:
{steps_text}
"""
```

3. Create `apps/ai/app/prompts/summarize.py`:

```python
SUMMARIZE_SYSTEM_PROMPT = """
You are a technical writer generating concise post-execution summaries for runbook workflows.
Write in plain text. Maximum 3 sentences. Be specific about what succeeded, what failed, and what required approval.
"""

SUMMARIZE_USER_TEMPLATE = """
Workflow: {workflow_name}
Execution result: {execution_status}
Steps:
{steps_text}
{failure_note}
{artifact_note}
"""
```

4. No tests required for prompt constants themselves (they are strings). The tests in Milestones 4 and 5 will exercise them.

**Rollback:** Delete prompt files. Later milestones depend on them but are not yet implemented.

**Human approval gate: review prompt content for accuracy and safety before Milestone 4 uses them with real LLM calls.**

---

### Milestone 4: Replace stub parser with LLM-backed implementation

**Purpose:** Replace `workflow_parser.py` deterministic logic with real LLM calls. Keep a test-environment fallback.

**Files touched:**

- `apps/ai/app/services/workflow_parser.py`
- `apps/ai/app/services/workflow_enricher.py` (new)
- `apps/ai/tests/test_workflow_parser.py` (update)
- `apps/ai/tests/test_enrich_route.py` (new)

**Small steps:**

1. Refactor `workflow_parser.py` so the public function `parse_runbook_to_candidate(request)` calls `LLMClient.complete_structured()` with the parse prompt and schema, then maps the result to `ParseRunbookResponse`. Extract the existing deterministic logic into `_deterministic_parse()` as a named fallback.

2. Use an environment variable `AI_USE_LLM_PARSER` (default `true`, set to `false` in test settings) to switch between real and deterministic. This prevents LLM calls in unit tests without mocking the entire OpenAI SDK.

3. Create `apps/ai/app/services/workflow_enricher.py` implementing `enrich_workflow_candidate(request: WorkflowEnrichRequest) -> WorkflowEnrichResponse` using `LLMClient.complete_structured()` with the enrich prompt.

4. Update `apps/ai/app/api/routes/enrich.py` to call `workflow_enricher.enrich_workflow_candidate(payload)`.

5. Update tests: `test_workflow_parser.py` tests the deterministic path (with `AI_USE_LLM_PARSER=false`). Add `test_enrich_route.py` testing the enrich route with mocked enricher service.

6. Add a golden test fixture: one sample runbook text file in `apps/ai/tests/fixtures/sample_runbook.txt` and an expected output file `apps/ai/tests/fixtures/sample_parse_expected.json`. The golden test runs against the real LLM only in a designated integration test run (not the default `pytest` invocation).

**Commands:**

```bash
docker compose exec ai pytest apps/ai/tests/  # deterministic path only; no real LLM calls
```

**Verify:** All AI service tests pass without real LLM calls. Parse route returns correct schema with `command` field populated for `shell_command` steps in deterministic mode.

**Rollback:** Restore previous `workflow_parser.py` (deterministic only). Delete `workflow_enricher.py`.

**Human approval gate: required before wiring Django to call the new enrich route (Milestone 5), to confirm the enricher contract is correct.**

---

### Milestone 5: Implement summarize route

**Purpose:** Activate the `/summarize/execution` route with real LLM calls.

**Files touched:**

- `apps/ai/app/services/workflow_summarizer.py` (new)
- `apps/ai/app/api/routes/summarize.py`
- `apps/ai/tests/test_summarize_route.py` (new)

**Small steps:**

1. Create `workflow_summarizer.py` implementing `summarize_execution(request: ExecutionSummarizeRequest) -> ExecutionSummarizeResponse`. Uses `LLMClient.complete_text()` with the summarize prompt. Caps at `max_tokens=256`.

2. Update `apps/ai/app/api/routes/summarize.py` to call the summarizer. Change the route path to `/execution` (from `/failure`) to match the new schema:

```python
@router.post("/execution", response_model=ExecutionSummarizeResponse)
def summarize_execution(payload: ExecutionSummarizeRequest) -> ExecutionSummarizeResponse:
    return workflow_summarizer.summarize_execution(payload)
```

3. Keep the old `/failure` route as an alias returning 301 or just remove it — confirm current Django code does not call `/summarize/failure` first (it doesn't; the route was unwired).

4. Add test: mock `LLMClient.complete_text` to return a sample string; assert response shape is correct.

**Commands:**

```bash
docker compose exec ai pytest apps/ai/tests/test_summarize_route.py
```

**Rollback:** Revert `summarize.py` to placeholder. Delete `workflow_summarizer.py`.

**Human approval gate: not required.**

---

### Milestone 6: Django model migration

**Purpose:** Add `requires_review` and `parse_source` to the `Workflow` model.

**Files touched:**

- `apps/api/apps/workflows/models.py`
- `apps/api/apps/workflows/migrations/0003_workflow_review_fields.py` (auto-generated)
- `apps/api/apps/workflows/admin.py` (add fields to display)

**Small steps:**

1. Add `ParseSource` inner class and `parse_source` field to `Workflow`.
2. Add `requires_review` field to `Workflow`.
3. Run `docker compose exec api python manage.py makemigrations workflows`.
4. Review the generated migration file. Confirm: both fields have defaults; migration is non-destructive.
5. Run migration.
6. Add `requires_review` and `parse_source` to admin list display for debugging.

**Commands:**

```bash
docker compose exec api python manage.py makemigrations workflows
docker compose exec api python manage.py migrate
docker compose exec api python manage.py check
docker compose exec api pytest apps/workflows/tests/
```

**Verify:** Migration applies cleanly. Existing workflow tests still pass. No default value error.

**Rollback:** Reverse migration: `docker compose exec api python manage.py migrate workflows 0002`. Remove model fields.

**Human approval gate: required if migration is not backward-compatible.**

---

### Milestone 7: Django AI client extension and input size guard

**Purpose:** Extend `RunbookAiClient` to call `/enrich/workflow` and `/summarize/execution`. Add input size guard to the workflow service.

**Files touched:**

- `apps/api/apps/runbooks/ai_client.py`
- `apps/api/apps/runbooks/tests/test_ai_client.py`
- `apps/api/config/settings/base.py`
- `.env.example`

**Small steps:**

1. Add `enrich_workflow_candidate(...)` and `summarize_execution(...)` methods to `RunbookAiClient` using the same `httpx.Client`, timeout configuration, and exception hierarchy already in place.

2. Add `AI_MAX_INPUT_CHARS = env.int("AI_MAX_INPUT_CHARS", default=100_000)` to `settings/base.py`.

3. Update `AI_READ_TIMEOUT_SECONDS` default in `settings/base.py` to `60.0` and document the reason.

4. Add the new settings to `.env.example`.

5. Add `WorkflowEnrichResult` and `EnrichedStepResult` dataclasses to `ai_client.py`.

6. Add `_validate_and_map_enrich_result()` function following the same pattern as `_validate_and_map_candidate()`.

7. Extend `test_ai_client.py`:
   - `enrich_workflow_candidate()` with valid mock response maps to `WorkflowEnrichResult`.
   - `enrich_workflow_candidate()` where response has missing step keys raises `AiServiceContractError`.
   - `summarize_execution()` with valid mock response returns a string.
   - `summarize_execution()` timeout raises `AiServiceTimeoutError`.

**Commands:**

```bash
docker compose exec api pytest apps/runbooks/tests/test_ai_client.py
```

**Rollback:** Remove new methods from `ai_client.py`. Revert settings additions.

**Human approval gate: not required.**

---

### Milestone 8: Django workflow service wiring

**Purpose:** Update `create_workflow_from_runbook()` to use the parse→enrich pipeline, set `requires_review=True`, add jsonschema validation, and add input hash caching.

**Files touched:**

- `apps/api/apps/workflows/services.py`
- `apps/api/apps/workflows/internal_clients.py`
- `apps/api/requirements/base.txt`
- `apps/api/apps/workflows/tests/test_services.py`

**Small steps:**

1. Add `jsonschema>=4.0,<5.0` to `apps/api/requirements/base.txt`.

2. In `services.py`, add `_load_workflow_schema()` using `functools.lru_cache` and `jsonschema.validate()` in `_validate_candidate()`.

3. Update `create_workflow_from_runbook()` (or the `create_workflow()` function it calls) to:
   - Check input size against `settings.AI_MAX_INPUT_CHARS` and raise `DomainValidationError(code="ai_input_too_large", ...)`.
   - Check the content hash cache before calling the AI service.
   - Call `/parse` → validate parsed steps → call `/enrich` → merge enriched metadata onto parsed steps → call `_validate_candidate()` with jsonschema → persist with `requires_review=True`, `parse_source="ai_parse"`.
   - Store the result in the content hash cache.

4. Update `internal_clients.py` (the `HttpWorkflowTransformClient`) to call both parse and enrich, or refactor to call `RunbookAiClient` directly from `services.py` and retire the intermediate client abstraction if it adds no value. Either approach is acceptable; maintain consistency with the existing pattern.

5. Add `accept_workflow_review()` and `reject_workflow_review()` service functions.

6. Add `requires_review` guard to the execution creation path (note: this may live in `apps/api/apps/executions/services.py`; add it there if so).

7. Extend `test_services.py`:
   - `create_workflow_from_runbook()` with mocked AI client returns workflow with `requires_review=True`, `parse_source="ai_parse"`.
   - `create_workflow_from_runbook()` where runbook content exceeds `AI_MAX_INPUT_CHARS` raises `DomainValidationError(code="ai_input_too_large")`.
   - `create_workflow_from_runbook()` where parse succeeds but enrich returns mismatched step keys raises `AiServiceContractError`.
   - `create_workflow_from_runbook()` where mapped definition fails jsonschema raises `InvalidWorkflowDefinitionError`.
   - Second call with same content hash returns cached result without calling AI client.
   - `accept_workflow_review()` sets `requires_review=False` on a draft workflow.
   - `accept_workflow_review()` on non-review workflow raises `DomainValidationError`.
   - `reject_workflow_review()` archives the workflow.

**Commands:**

```bash
docker compose exec api pip install jsonschema  # or rebuild container
docker compose build api
docker compose exec api python manage.py check
docker compose exec api pytest apps/workflows/tests/test_services.py
```

**Rollback:** Revert `services.py` to the previous implementation. Reverse `jsonschema` dependency if needed.

**Human approval gate: required before adding API endpoints (Milestone 9), to confirm the parse→enrich merge logic is correct.**

---

### Milestone 9: Django API endpoints for review

**Purpose:** Expose `accept-review/` and `reject-review/` endpoints and update the workflow serializer.

**Files touched:**

- `apps/api/apps/workflows/serializers.py`
- `apps/api/apps/workflows/views.py`
- `apps/api/apps/workflows/urls.py`
- `apps/api/apps/workflows/tests/test_api_contracts.py`

**Small steps:**

1. Update `WorkflowSerializer` to include `requires_review` and `parse_source` as read-only fields.

2. Add `AcceptWorkflowReviewView` and `RejectWorkflowReviewView` (or use `@action` on a ViewSet). Both call their respective service functions.

3. Register URLs:
   - `POST /api/v1/workflows/{id}/accept-review/`
   - `POST /api/v1/workflows/{id}/reject-review/`

4. Add API tests:
   - Workflow created via `create_workflow_from_runbook` returns `requires_review: true` and `parse_source: "ai_parse"`.
   - `POST /api/v1/workflows/{id}/accept-review/` on a `requires_review=true` workflow returns 200 with `requires_review: false`.
   - `POST /api/v1/workflows/{id}/accept-review/` on a `requires_review=false` workflow returns 400 with `workflow_not_pending_review`.
   - `POST /api/v1/workflows/{id}/reject-review/` archives the workflow and returns 200 with `status: "archived"`.
   - `POST /api/v1/executions/` (or the trigger endpoint) with a `requires_review=true` workflow returns 400 with `workflow_requires_review`.

**Commands:**

```bash
docker compose exec api python manage.py check
docker compose exec api pytest apps/workflows/tests/test_api_contracts.py
docker compose exec api pytest apps/executions/tests/
```

**Rollback:** Remove URL registrations and view functions. Serializer additions are non-breaking.

**Human approval gate: not required if tests pass.**

---

### Milestone 10: Summarize execution hook

**Purpose:** Wire the `/summarize/execution` call into the execution completion path and store the result as a text artifact.

**Files touched:**

- `apps/api/apps/executions/services.py`
- `apps/api/apps/runbooks/ai_client.py` (ensure `summarize_execution()` method is complete from Milestone 7)
- `apps/api/apps/executions/tests/test_services.py`

**Small steps:**

> **ARCHITECTURE DECISION (K-H07): `summarize_execution` must be dispatched via `transaction.on_commit()`, not called inline.**
>
> `complete_execution()` runs inside a database transaction. Calling `summarize_execution()` synchronously inside or immediately after that transaction means the runner's `complete_execution` HTTP call blocks for up to `AI_READ_TIMEOUT_SECONDS` (currently 60 seconds) waiting for OpenAI to return a summary. This holds a DB connection and causes the runner to time out. The summary is a non-critical enhancement — it must not extend the critical path.

1. Add a feature flag to `base.py`:
   ```python
   AI_SUMMARIZE_ENABLED = env.bool("AI_SUMMARIZE_ENABLED", default=False)
   ```
   Default is `False` — summarize is off until measured. Enable explicitly in dev/staging when evaluating the feature.

2. In `complete_execution(...)`, dispatch the summarize call via `transaction.on_commit()` so it runs after the transaction commits and does not block the runner's response:

```python
if settings.AI_SUMMARIZE_ENABLED:
    execution_id = str(execution.id)
    def _dispatch_summarize():
        try:
            client = RunbookAiClient.from_settings()
            summary = client.summarize_execution(
                request_id=execution_id,
                workflow_name=execution.workflow.name,
                execution_status=execution.status,
                steps=[...],
                failed_step_name=failed_step.name if failed_step else None,
                artifact_count=execution.artifacts.count(),
            )
            ArtifactService.create_from_text(
                execution=execution,
                name="execution_summary.md",
                content=summary,
                mime_type="text/plain",
            )
        except Exception:
            logger.warning("Execution summary generation failed", execution_id=execution_id, exc_info=True)
    transaction.on_commit(_dispatch_summarize)
```

3. Add service test: `complete_execution()` with mocked AI client dispatches `summarize_execution()` after commit when `AI_SUMMARIZE_ENABLED=True`; AI client failure does not propagate; when `AI_SUMMARIZE_ENABLED=False`, no AI client call is made.

**Commands:**

```bash
docker compose exec api pytest apps/executions/tests/test_services.py
```

**Rollback:** Remove the `summarize_execution` call from `complete_execution`. No model changes.

**Human approval gate: not required.**

---

### Milestone 11: Frontend review UI

**Purpose:** Add the workflow review page, update the workflow list/detail to show `requires_review`, and disable the Run button for unreviewed workflows.

**Files touched:**

- `apps/web/src/features/workflows/types.ts`
- `apps/web/src/features/workflows/api/workflowsApi.ts`
- `apps/web/src/features/workflows/hooks/useAcceptWorkflowReview.ts` (new)
- `apps/web/src/features/workflows/hooks/useRejectWorkflowReview.ts` (new)
- `apps/web/src/routes/workflows/WorkflowReviewPage.tsx` (new)
- `apps/web/src/routes/workflows/WorkflowReviewPage.test.tsx` (new)
- `apps/web/src/app/router.tsx`
- Existing workflow list/detail components to add badge and disable Run button

**Small steps:**

1. Add `requires_review` and `parse_source` to `Workflow` TypeScript interface.
2. Add `acceptWorkflowReview()` and `rejectWorkflowReview()` API functions.
3. Add `useAcceptWorkflowReview` and `useRejectWorkflowReview` mutation hooks.
4. Build `WorkflowReviewPage` per section 8.4.
5. Register route `/workflows/:id/review` in `router.tsx`.
6. On workflow list and detail pages: show "Pending Review" badge, add "Review" link, disable Run button with tooltip when `requires_review: true`.
7. Add tests per section 8.6.

**Commands:**

```bash
cd apps/web && npm run lint
cd apps/web && npm test -- --run
cd apps/web && npm run build
```

**Verify:** Lint passes, tests pass, build completes without type errors. Review page renders step table, accept and reject buttons work.

**Rollback:** Remove route registration and new component files. Existing workflow pages unaffected.

**Human approval gate: product review of the review page UI before merge.**

---

### Milestone 12: Local end-to-end manual gate

**Purpose:** Verify the full Phase 10.6 workflow with a real LLM and a real runbook document.

**Files touched:** None unless defects are found.

**Setup required:** `OPENAI_API_KEY` must be set in local `.env` with a working key.

**Commands:**

```bash
docker compose up --build
docker compose exec api python manage.py check
docker compose exec api pytest
docker compose exec ai pytest
docker compose exec runner pytest
cd apps/web && npm test -- --run
cd apps/web && npm run build
```

**Manual verification steps:**

1. Create a runbook using the API or UI with a realistic 5–10 step runbook document. Include at least one step with an explicit shell command (`aws`, `kubectl`, or `python manage.py` etc.) and one high-risk step like "Delete the staging database" or "Deploy to production."

2. Trigger workflow creation from the runbook (`POST /api/v1/workflows/` with `runbook_id`). Observe that the response includes `requires_review: true` and `parse_source: "ai_parse"`. Confirm the parsed steps reflect the actual runbook content — not generic placeholders.

3. Navigate to `/workflows/{id}/review`. Verify:
   - All steps appear with correct names and types.
   - High-risk steps show `high` or `critical` risk badges.
   - Steps with `requiresApproval: true` are correctly identified.
   - The "Run" button on the workflow detail page is disabled.

4. Edit one step name inline. Save. Confirm the definition is updated.

5. Attempt to create an execution directly via API: `POST /api/v1/executions/` with the workflow ID. Confirm it returns 400 with `workflow_requires_review`.

6. Accept the review from the UI. Confirm `requires_review` transitions to `false`.

7. Publish the workflow. Start an execution. Confirm the execution proceeds normally and the runner picks it up.

8. Complete the execution. Confirm an `execution_summary.md` artifact appears in the execution's artifact list.

9. Submit a runbook whose content exceeds `AI_MAX_INPUT_CHARS`. Confirm the API returns 400 with `ai_input_too_large`.

10. Submit the same runbook content a second time. Confirm (via Django logs) that the AI service is not called again (cache hit).

11. Submit a runbook that the LLM is likely to produce a malformed structure for (e.g., all whitespace). Confirm that Django handles the error gracefully and returns a clear error to the frontend, without persisting a partial workflow.

**Rollback plan:**

- If AI service errors affect Django stability: remove the AI client calls from `complete_execution` first (safest).
- If the review gate blocks legitimate executions: add a management command to clear `requires_review` on specific workflows for emergency unblocking.
- If the LLM cost is too high during testing: set `AI_USE_LLM_PARSER=false` in `.env` to revert to the deterministic stub without any code changes.

**Human approval gate: required before declaring Phase 10.6 complete.**

---

## 10. Testing strategy

### 10.1 AI service unit tests (no real LLM calls)

Use `AI_USE_LLM_PARSER=false` for all CI runs. With the deterministic fallback:

- `POST /parse/runbook` with a numbered list returns steps with correct names and types.
- `POST /parse/runbook` with empty content returns one default step.
- `POST /enrich/workflow` with mocked enricher returns enriched steps with matching step keys.
- `POST /enrich/workflow` where enricher raises `LLMCallError` returns HTTP 422.
- `POST /summarize/execution` with mocked summarizer returns a string summary.

### 10.2 AI service golden tests (real LLM — run manually, not in CI)

Located in `apps/ai/tests/golden/`. Marked with `@pytest.mark.integration` and excluded from the default test run.

- Fixture: `tests/fixtures/rotate_credentials_runbook.txt` (a realistic 8-step AWS credential rotation runbook).
- Expected: `tests/fixtures/rotate_credentials_expected.json` — at minimum, assert the correct number of steps, that the AWS IAM steps are `shell_command` type, and that the key rotation step is classified as `high` risk.
- Fixture: `tests/fixtures/kubernetes_restart_runbook.txt`.
- Expected: assert the `kubectl rollout restart` step is `shell_command` with the correct command text extracted.

The golden tests run with `pytest -m integration` and require `OPENAI_API_KEY`. They are not part of the CI pipeline gate. They are the manual gate for confirming the LLM prompts produce acceptable output before merge.

### 10.3 Django AI client tests

Cover:

- `parse_runbook_to_workflow_candidate()` with mocked `httpx.MockTransport`: success maps to `WorkflowCandidate` with `command` field populated.
- `enrich_workflow_candidate()` with mocked transport: success maps to `WorkflowEnrichResult`.
- `enrich_workflow_candidate()` where response has fewer step keys than parse response raises `AiServiceContractError`.
- `summarize_execution()` with mocked transport returns string.
- All three methods: `httpx.ReadTimeout` raises `AiServiceTimeoutError`.
- All three methods: non-200 response raises `AiServiceBadResponseError`.

### 10.4 Django schema validation tests

- `_validate_candidate()` on a well-formed candidate passes.
- `_validate_candidate()` on a candidate whose mapped definition fails `workflow.schema.json` raises `InvalidWorkflowDefinitionError`.
- `_validate_candidate()` on a candidate with duplicate step keys raises `InvalidWorkflowDefinitionError`.
- `_validate_candidate()` on a candidate with an empty `name` on one step raises `InvalidWorkflowDefinitionError`.

### 10.5 Django service tests

- `create_workflow_from_runbook()` with mocked AI client returns workflow with `requires_review=True`, `parse_source="ai_parse"`.
- `create_workflow_from_runbook()` where content exceeds limit raises `DomainValidationError(code="ai_input_too_large")`.
- `create_workflow_from_runbook()` where parse fails raises AI error without persisting a workflow.
- `create_workflow_from_runbook()` where enrich returns mismatched step keys raises `AiServiceContractError` without persisting a workflow.
- `create_workflow_from_runbook()` called twice with same content: second call returns cached definition without invoking AI client mock.
- `accept_workflow_review()` on draft + requires_review workflow sets `requires_review=False` and saves.
- `accept_workflow_review()` on non-review workflow raises `DomainValidationError`.
- `reject_workflow_review()` archives the workflow.
- `reject_workflow_review()` on already-archived workflow raises appropriate error.
- Execution creation with `requires_review=True` workflow raises `InvalidStateTransitionError(code="workflow_requires_review")`.

### 10.6 Django API contract tests

- `POST /api/v1/workflows/` returns `requires_review: true` and `parse_source: "ai_parse"` on success.
- `POST /api/v1/workflows/` with oversized content returns 400 with `ai_input_too_large`.
- `POST /api/v1/workflows/` when AI service is unavailable returns 502 with `workflow_ai_unavailable`.
- `POST /api/v1/workflows/{id}/accept-review/` returns 200 with `requires_review: false`.
- `POST /api/v1/workflows/{id}/accept-review/` when already accepted returns 400 with `workflow_not_pending_review`.
- `POST /api/v1/workflows/{id}/reject-review/` returns 200 with `status: "archived"`.
- `POST /api/v1/executions/` with `requires_review=true` workflow returns 400 with `workflow_requires_review`.

### 10.7 Malformed AI output tests

- Parse response with zero steps: Django raises `InvalidWorkflowDefinitionError`; no workflow persisted.
- Parse response with missing `workflow_title`: Django raises `AiServiceContractError`; no workflow persisted.
- Parse response with invalid JSON: Django raises `AiServiceBadResponseError`; no workflow persisted.
- Enrich response with missing step keys: Django raises `AiServiceContractError`; no workflow persisted.
- Mapped definition that passes parse validation but fails `workflow.schema.json`: Django raises `InvalidWorkflowDefinitionError`; no workflow persisted.

### 10.8 Frontend tests

Cover:

- `WorkflowReviewPage` renders step table with correct columns.
- Steps with `requiresApproval: true` show approval indicator.
- "Pending Review" badge appears when `requires_review: true`.
- Accept button triggers `acceptWorkflowReview()` mutation and navigates on success.
- Reject button shows confirmation dialog before calling `rejectWorkflowReview()`.
- Run button is disabled when `requires_review: true`.
- Workflow detail page shows "AI-generated" label when `parse_source: "ai_parse"`.

### 10.9 Manual real-runbook gate

The Milestone 12 manual gate is required. It is the only test that proves the full path from real operator input through real LLM to a reviewable, executable workflow.

---

## 11. Failure modes and risks

### Hallucinated step commands

**Risk:** The LLM produces a plausible-sounding but operationally incorrect shell command for a step. For example, it invents `--force-delete` flags that do not exist, or targets the wrong environment.

**Mitigation:** The human review gate is the primary defense. The review page displays step commands in a code block. A human must review and accept before the workflow is executable. If a hallucinated command reaches execution, the runner executes it and the step likely fails — which is safer than silently succeeding with wrong behavior. Add a visual warning on the review page: "Commands extracted by AI. Verify each command before accepting."

### Malformed JSON output from LLM

**Risk:** Despite structured output mode, the LLM occasionally returns JSON that fails Pydantic validation (rare but possible with complex schemas).

**Mitigation:**
- The AI service uses OpenAI's structured output enforcement (`strict: true`), which reduces but does not eliminate failures.
- The AI service catches Pydantic validation failures and returns HTTP 422 with a structured error.
- Django catches the 422 and raises `AiServiceBadResponseError`.
- No partial workflow is persisted.
- The user sees a clear error: "AI parsing failed. Please try again or simplify the runbook content."

### Unsafe step commands in the review UI

**Risk:** The review UI displays a command string that contains HTML or script injection in the step name or command field.

**Mitigation:** React escapes all string content by default in JSX. Use `<code>` or `<pre>` elements for command display, not `dangerouslySetInnerHTML`. This is the standard React XSS prevention.

### LLM provider timeout

**Risk:** The OpenAI API is slow or unavailable, causing the `POST /api/v1/workflows/` call to hang for up to `AI_READ_TIMEOUT_SECONDS`.

**Mitigation:**
- 60-second read timeout is enforced by `httpx`.
- After timeout, Django returns 504 with `workflow_ai_timeout`.
- No partial workflow is persisted.
- The user can retry. The content hash cache prevents re-parsing identical content that previously succeeded.

### Retry duplication

**Risk:** The user or a browser retry sends the same `POST /api/v1/workflows/` request twice (e.g., due to a network timeout on the response, not the request). Two workflow records are created for the same runbook.

**Mitigation:**
- The content hash cache prevents two LLM calls for the same content within a single process lifetime.
- The `unique_workflow_version_per_runbook` constraint prevents two workflows with the same version from being created (using `select_for_update` in `create_workflow()`).
- Duplicate draft workflows (same runbook, different versions) are harmless — only one can be published at a time.
- This is the same behavior as manual workflow creation. No special handling needed.

### Prompt drift

**Risk:** Over time, as the LLM provider updates the underlying model, the same prompt produces different output. Existing workflows remain correct (they are already parsed and saved), but new parse requests may produce different step classifications.

**Mitigation:**
> **ARCHITECTURE DECISION (K-L03): `AI_PARSE_MODEL` default must be a pinned dated alias, not a floating alias.**
>
> Setting `AI_PARSE_MODEL=gpt-4o` (floating) means that when OpenAI silently upgrades what `gpt-4o` points to, existing prompt templates and golden tests are tested against a different model than production uses. Output changes silently break workflows without a deployment event to blame.

- The default in `config.py` must be `AI_PARSE_MODEL = "gpt-4o-2024-11-20"` (or whatever dated alias is current at implementation time — check OpenAI docs). Never default to a floating alias like `gpt-4o`.
- When upgrading the model, change the pinned alias explicitly in code, increment `CURRENT_PROMPT_VERSION`, and re-run golden tests against the new alias before merging.
- Update `.env.example` default to the pinned alias as well.
- Golden tests (`@pytest.mark.integration`) must be run against the exact model in `AI_PARSE_MODEL` to evaluate output quality before changing the pinned version.
- Prompts are versioned with the code. Any prompt change requires a PR, a golden test run, and team review.

### Sensitive data in runbook content sent to the LLM

**Risk:** A runbook document contains environment-specific secrets (AWS keys, passwords, database connection strings). These are sent to the OpenAI API and potentially logged by the provider.

**Mitigation:**
- Document this risk clearly in the Phase 10.6 release notes and operator guide.
- Add a UI warning on the runbook parse input: "Content will be sent to an external AI provider. Do not include secrets, passwords, or credentials in runbook documents."
- Do not log `raw_content` in Django or in the AI service (this is already the policy from Phase 07).
- The input size limit (`AI_MAX_INPUT_CHARS`) bounds the exposure.
- In Phase 10.7 (auth), add organization-level opt-in for AI parsing so organizations can disable it if their runbooks contain sensitive content.

### Token cost blowup

**Risk:** Without input limits, a user submits a 200-page document and triggers a $30+ LLM call.

**Mitigation:**
- `AI_MAX_INPUT_CHARS = 100,000` (roughly 25,000 tokens) is enforced by Django before calling the AI service.
- `AI_MAX_COMPLETION_TOKENS = 4096` caps the output token budget per call.
- Two calls are made per workflow creation (parse + enrich), so total token budget is bounded at approximately `25,000 input + 2 × 4,096 output = ~33,000 tokens per workflow`. At typical OpenAI pricing, this is under $0.50 per parse.

### Pre-auth cost and data-governance controls (H-05)

> **ARCHITECTURE DECISION (H-05): Phase 10.6 introduces real LLM calls before auth (Phase 10.7). Without explicit controls, any user can trigger unbounded OpenAI spend and submit sensitive content to OpenAI without per-org consent.**

**Risk:** Phase 10.6 ships AI parsing before Phase 10.7 adds per-organization opt-in, consent gates, and RBAC. In this window, the following risks are live:
1. Any authenticated user can parse unlimited runbooks, running up OpenAI costs.
2. Sensitive runbook content (passwords, API keys, infrastructure topology) is sent to OpenAI without a documented org consent flow.
3. Production deployments can be publicly exposed before per-org controls exist.

**Mitigations required in Phase 10.6:**

**1. Private-environment guard (`AI_PARSE_REQUIRES_PRIVATE_ENV`)**

Add to `base.py`:
```python
AI_PARSE_REQUIRES_PRIVATE_ENV = env.bool("AI_PARSE_REQUIRES_PRIVATE_ENV", default=True)
```
In `prod.py` startup validation:
```python
if settings.AI_PARSE_REQUIRES_PRIVATE_ENV and not settings.DEBUG:
    # If private_env is required and DEBUG is off, verify this is a known private deployment.
    # Use the presence of a DEPLOY_ENV var (e.g., "staging" or "dev") vs absence to gate.
    deploy_env = env("DEPLOY_ENV", default="")
    if deploy_env not in {"dev", "staging", "test"}:
        raise ImproperlyConfigured(
            "AI_PARSE_REQUIRES_PRIVATE_ENV=True is set but DEPLOY_ENV is not 'dev', 'staging', or 'test'. "
            "Phase 10.6 must not be enabled in production until Phase 10.7 per-org opt-in is complete. "
            "Set AI_PARSE_REQUIRES_PRIVATE_ENV=False explicitly to override after Phase 10.7."
        )
```
This prevents accidental production deployment of AI parsing before per-org consent exists.

**2. Per-day cost ceiling (`AI_PARSE_DAILY_BUDGET_USD`)**

Add to `base.py`:
```python
AI_PARSE_DAILY_BUDGET_USD = env.float("AI_PARSE_DAILY_BUDGET_USD", default=10.0)
```
Before each parse call in `create_workflow_from_runbook()`, check a Django cache key `ai_parse_daily_cost_{date}` against the budget:
```python
from django.core.cache import cache
from django.utils import timezone

today = timezone.now().date().isoformat()
daily_cost = cache.get(f"ai_parse_daily_cost_{today}", 0.0)
if settings.AI_PARSE_DAILY_BUDGET_USD > 0 and daily_cost >= settings.AI_PARSE_DAILY_BUDGET_USD:
    raise AiDailyBudgetExceededError(
        code="ai_daily_budget_exceeded",
        message="Daily AI parse budget has been reached. Try again tomorrow.",
    )
```
After a successful parse, increment the cost estimate:
```python
estimated_cost = (input_chars / 4) * 0.000005  # rough GPT-4o input token cost
cache.incr_float(f"ai_parse_daily_cost_{today}", estimated_cost)
```
This is a best-effort guard using an in-process cache (Django default cache). Phase 10.7/10.10 may replace with a Redis counter for accuracy across multiple workers.

Surface this as HTTP 429 with `{"error": {"code": "ai_daily_budget_exceeded"}}`.

**3. Phase 10.6 → 10.7 release gate**

The phase-10.6→10.7 handoff checklist must include:
- [ ] `AI_PARSE_REQUIRES_PRIVATE_ENV` is lifted only after Phase 10.7 per-org opt-in is verified.
- [ ] A documented decision on data processing agreements with OpenAI for production data.
- [ ] `AI_PARSE_DAILY_BUDGET_USD` is tuned to a production-appropriate value once real usage data is known.

### AI service unavailable during execution

**Risk:** The AI service (FastAPI) is down when a user creates a workflow. The Django API call fails.

**Mitigation:**
- Django returns 502 with `workflow_ai_unavailable`. No execution is affected.
- The AI service being down does not affect runner operation, existing execution management, approvals, policies, or audit trail.
- The runner has no dependency on the AI service.

---

## 12. What NOT to do

- **Do not let the AI service call Django.** The AI service is stateless and receives only what Django sends it. It does not look up runbooks, workflows, or organizations in the database.

- **Do not let the frontend call FastAPI directly.** The parse trigger goes through `POST /api/v1/workflows/`. The frontend does not know FastAPI's URL.

- **Do not let the runner call the AI service.** The runner executes steps against the Django internal API. It is not aware that AI parsing exists.

- **Do not auto-execute AI-parsed workflows.** The `requires_review=True` flag is mandatory for all AI-generated workflows. It cannot be set to `False` at creation time. The only path to `requires_review=False` is the explicit `accept-review` action by a human.

- **Do not store unvalidated AI output.** The Django service validates the mapped definition against `workflow.schema.json` before the `Workflow.objects.create()` call. There is no code path that persists a workflow without passing schema validation.

- **Do not add multi-model routing in Phase 10.6.** One model (`AI_PARSE_MODEL`), one provider (OpenAI), one prompt set. If the model fails, return an error. Provider fallback is a future concern.

- **Do not add streaming LLM responses.** Full response first. Streaming is a UX optimization that adds complexity to the AI service and the Django client. Defer until user latency data justifies it.

- **Do not build a generic AI agent framework.** The AI service has three routes with specific contracts. No general-purpose "AI job" abstraction, no configurable agent chains, no dynamic prompt injection.

- **Do not build a re-enrich user action in Phase 10.6.** The `/enrich` route is implemented, but there is no "re-classify this workflow" button in the UI. Re-enrich is a natural future feature; implement it when a real user requests it.

- **Do not add AI-generated step commands to auto-execute without review.** Even if the LLM produces a `shell_command` step with a correct command, the workflow must be reviewed and accepted before the runner can execute it.

- **Do not put the `OPENAI_API_KEY` in Django's settings or in the Django container's environment.** The key is read only by the AI service (FastAPI container). Django calls the AI service; Django does not call OpenAI.

- **Do not add AI parsing for all runbook saves.** AI parsing is triggered only when the user explicitly requests `POST /api/v1/workflows/`. It is not a save hook on the `Runbook` model.

- **Do not add retry infrastructure for LLM calls in Phase 10.6.** If a call fails, return an error. The user retries manually. Automatic retries on LLM calls risk duplication and cost multiplication.

---

## 13. Definition of done

Phase 10.6 is done when:

- [ ] `openai>=1.40,<2.0` is in `apps/ai/requirements/base.txt` and the AI service container builds successfully.
- [ ] `LLMClient` wrapper exists in `apps/ai/app/services/llm_client.py` with `complete_structured()` and `complete_text()` methods.
- [ ] Prompt templates exist in `apps/ai/app/prompts/parse.py`, `enrich.py`, and `summarize.py` as versioned Python constants.
- [ ] `apps/ai/app/services/workflow_parser.py` uses the LLM for parsing (with deterministic fallback controlled by `AI_USE_LLM_PARSER`).
- [ ] `apps/ai/app/services/workflow_enricher.py` implements risk classification via LLM.
- [ ] `apps/ai/app/services/workflow_summarizer.py` implements post-execution summary generation.
- [ ] `/enrich/workflow` and `/summarize/execution` routes are implemented with typed Pydantic contracts. Placeholders are removed.
- [ ] `WorkflowCandidateStep` includes `command: str | None = None`.
- [ ] `Workflow.requires_review` and `Workflow.parse_source` fields exist with migration applied.
- [ ] `create_workflow_from_runbook()` calls parse → enrich → jsonschema validate → persist with `requires_review=True`, `parse_source="ai_parse"`.
- [ ] Input size guard (`AI_MAX_INPUT_CHARS`) raises `DomainValidationError(code="ai_input_too_large")` before calling the AI service.
- [ ] Content hash cache prevents re-parsing identical runbook content within a server process lifetime.
- [ ] `jsonschema` validates the mapped definition against `packages/workflow-schema/workflow.schema.json` before persistence.
- [ ] `accept_workflow_review()` and `reject_workflow_review()` service functions exist and are covered by tests.
- [ ] `POST /api/v1/workflows/{id}/accept-review/` and `POST /api/v1/workflows/{id}/reject-review/` endpoints exist and are registered.
- [ ] Execution creation raises `InvalidStateTransitionError(code="workflow_requires_review")` when the workflow has `requires_review=True`. Covered by test.
- [ ] `summarize_execution()` is dispatched via `transaction.on_commit()` when `AI_SUMMARIZE_ENABLED=True`. Default is `AI_SUMMARIZE_ENABLED=False`. The summarize call does NOT block the runner's `complete_execution` HTTP call. Failure does not affect execution state.
- [ ] `AI_PARSE_REQUIRES_PRIVATE_ENV=True` is the default. Production startup raises `ImproperlyConfigured` when `DEPLOY_ENV` is not a known private/staging value, blocking accidental production deployment before Phase 10.7 per-org opt-in.
- [ ] `AI_PARSE_DAILY_BUDGET_USD=10.0` is the default. Parse calls return HTTP 429 with `{"error": {"code": "ai_daily_budget_exceeded"}}` when the daily cost estimate is exceeded.
- [ ] All AI service unit tests pass without real LLM calls (deterministic fallback).
- [ ] All Django AI client tests pass with `httpx.MockTransport`.
- [ ] All Django service tests (parse→enrich pipeline, review acceptance, rejection, execution guard) pass.
- [ ] All Django API contract tests pass (review endpoints, execution guard, error codes).
- [ ] Malformed AI output tests pass: zero steps, missing title, invalid JSON, mismatched enrich keys, jsonschema failure — none create a persisted workflow.
- [ ] Frontend review page exists with step table, edit affordance, accept and reject actions.
- [ ] Frontend tests pass: review page renders, accept and reject mutations work, Run button disabled when `requires_review: true`.
- [ ] `npm run lint` and `npm run build` pass.
- [ ] Manual gate (Milestone 12) verified with a real runbook document against the real LLM.
- [ ] No code implements deferred features: streaming output, multi-model routing, re-enrich action, AI-to-Django callbacks, frontend-to-FastAPI calls, runner-to-AI calls, auto-execution of parsed workflows.

---

## Summary

**File created:** `docs/blueprints/phase-10-06-richer-ai-parsing-blueprint.md`

**Major sections included:**

1. Purpose and sequencing rationale — why Phase 10.6 comes after integrations (schema stable, control plane handles approvals/risk/steps/audit) and before auth (AI parsing model must be stable before RBAC wiring)
2. Current-state inspection checklist — exact files to read before writing code, including AI service stubs, missing `command` field on `WorkflowCandidateStep`, absent `requires_review` on `Workflow`
3. Architecture invariants — all nine platform invariants plus Phase 10.6-specific boundaries (no OPENAI_API_KEY in Django, no auto-execution, no frontend-to-FastAPI)
4. Implementation scope — per-area breakdown for AI service, Django backend, and frontend; 20+ backend files, 5+ frontend files
5. Data model and contracts — `Workflow.requires_review` and `parse_source` fields; `WorkflowCandidateStep.command` addition; jsonschema validation; content hash caching strategy
6. FastAPI AI contracts — updated parse contract; new typed enrich and summarize contracts with JSON schema schemas for structured LLM output; `LLMClient` design; updated timeout posture
7. API contracts — parse trigger (existing endpoint), edit before review (PATCH), accept-review, reject-review, execution guard; all error codes
8. Frontend data contracts and review UI — TypeScript types, review page with step table, edit affordance, accept/reject flow, disabled Run button
9. Ordered milestones — 12 milestones from preflight through manual gate, each with files, commands, verification steps, rollback notes, and approval gates
10. Testing strategy — AI service unit tests, golden tests, Django client tests, schema validation tests, service tests, API tests, malformed output tests, frontend tests, manual gate
11. Failure modes and risks — hallucinated commands, malformed JSON, unsafe UI content, provider timeout, retry duplication, prompt drift, sensitive data exposure, token cost blowup, AI service unavailability
12. What NOT to do — 13 explicit prohibitions covering auto-execution, runner-to-AI calls, frontend-to-FastAPI calls, unvalidated output, streaming, agent frameworks, re-enrich action, OPENAI_API_KEY in Django
13. Definition of done — 30 verifiable checklist items

**Key assumptions:**

- Phases 10.1–10.5 (approvals, policies, audit, artifacts, integrations) are complete and verified before Phase 10.6 begins.
- `OPENAI_API_KEY` is already in `.env.example` (confirmed from source inspection) and operators have a valid key.
- The workflow schema (`packages/workflow-schema/workflow.schema.json`) does not require version bumping in Phase 10.6. All AI output fields are already defined in the current schema.
- Django views remain synchronous; `httpx.Client` (not `AsyncClient`) is appropriate for AI service calls.
- The `RunbookAiClient` pattern from Phase 07 is preserved and extended, not replaced.
- The `HttpWorkflowTransformClient` / `WorkflowCandidate` types in `apps/api/apps/workflows/internal_clients.py` are the stable internal boundary for the workflow service, and are extended to support the enrich call without architectural change.
- The AI service reads `OPENAI_API_KEY` from its own container environment, not from Django.
- The execution summary is stored as a text artifact rather than as a new `Execution.summary` model field, avoiding a migration dependency on the execution model in this phase.
- `AI_USE_LLM_PARSER=false` is sufficient to make all CI tests deterministic without mocking the OpenAI SDK globally.
