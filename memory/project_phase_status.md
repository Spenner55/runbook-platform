---
name: Project Phase Status
description: Current implementation phase and what was completed when
type: project
---

Phase 4 (Versioned REST APIs) completed on 2026-04-22.

Phase 3 was verified complete with one class of gaps: all service-layer state transition errors used `ValueError` instead of domain exceptions, causing views to return ad-hoc `{"detail": ...}` instead of the standard error envelope. Fixed before Phase 4.

**Why:** Blueprints in docs/blueprints/ define phases 01–08. Each must be completed in order.

**Phase 4 deliverables now in place:**
- `config/api_v1_urls.py` — central versioned router with namespace "v1"
- `config/urls.py` — updated to include api_v1_urls with namespace, /health/ stays outside
- NamespaceVersioning + ALLOWED_VERSIONS in REST_FRAMEWORK settings
- Organizations: create/list/detail serializer split
- Runbooks: `mark_ready` + `archive` actions, list excludes raw_content, detail includes it
- Workflows: `publish` (with sibling supersede), `archive` actions; list excludes definition, detail includes it
- Executions: list includes runner metadata, detail adds `claim_token_present`
- `executions/internal_views.py` — clean separation of runner endpoints from public
- `executions/internal_serializers.py` — runner serializers isolated from public
- `executions/runner_services.py` — NOT created; runner services stayed in services.py (all related functions together, still clean)
- claim-next returns `claim_token` at top level of response
- `InvalidStateTransitionError` (409) added to common/exceptions.py
- 98 tests pass across all apps

**How to apply:** When working in this repo, assume Phases 1-4 are complete. Phase 5 (Runner implementation) is next.
