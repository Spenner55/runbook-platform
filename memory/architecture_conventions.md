---
name: Architecture Conventions
description: Key architectural decisions and conventions established in this codebase
type: project
---

**Service layer pattern:**
- services.py per app owns orchestration + transactions
- Views are thin: validate input → call service → serialize output
- Serializers validate only, never orchestrate
- Models hold only row-local invariants

**Error handling:**
- All domain errors are subclasses of _BaseDomainError in common/exceptions.py
- custom_exception_handler in common/api_errors.py normalizes all errors to `{"errors": [...]}`
- InvalidStateTransitionError (409) for lifecycle violations
- DomainConflictError (409) for uniqueness violations
- InvalidWorkflowDefinitionError (400) for bad workflow structure
- ExternalDependencyError (503) for AI service failures
- Services must NEVER raise ValueError — always raise a typed domain exception

**URL structure:**
- /health/ is outside versioning
- /api/v1/ is the only public namespace (NamespaceVersioning, namespace="v1")
- Public CRUD under /api/v1/{resource}/
- Internal runner under /api/v1/internal/executions/...
- Central routing in config/api_v1_urls.py

**Execution/workflow flow:**
- workflow definition uses {"name": ..., "steps": [{"id": ..., "name": ..., "type": ..., "risk": ..., "requiresApproval": ...}]}
- Steps reference "id" (not "step_key") in the definition JSON, but ExecutionStep.step_key copies from step["id"]
- Workflows must be published before execution can be created
- Publishing a workflow supersedes the previous published sibling in one transaction

**Why:** Established by Phase 3 & 4 blueprints in docs/blueprints/
**How to apply:** Follow these conventions in all new code; do not add business logic to views or serializers
