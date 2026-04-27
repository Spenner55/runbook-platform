# Documentation Maintenance

Documentation must stay aligned with current code, blueprints, and architecture boundaries.

## When Docs Must Be Updated

Update docs when a change affects:

- Service boundaries.
- API paths, payloads, responses, status codes, or error envelopes.
- Django models, fields, relationships, indexes, constraints, or status enums.
- Runner lifecycle or internal API contracts.
- AI service schemas or allowed calls.
- Frontend routes, API clients, query conventions, or environment variables.
- Local development commands, Compose services, Makefile targets, or CI workflow.
- Blueprint implementation status.

## Marking Planned Vs Implemented

Use these labels consistently:

| Label | Meaning |
| --- | --- |
| Implemented | Current code supports it. |
| Partially implemented | Some code exists, but the full behavior or integration is incomplete. |
| Planned | Blueprint or roadmap describes it, but current code does not implement it. |
| Deferred | Intentionally out of current scope. |

Never claim implementation from a blueprint alone.

## Updating Blueprints After Implementation

Blueprints are historical planning docs. Keep the original plan intact unless it is harmful or factually wrong.

Preferred update:

```md
## Current repo alignment notes

- As of YYYY-MM-DD, this phase is implemented/partially implemented.
- Current implementation differs from the original plan in these ways:
  - ...
- Still planned/deferred:
  - ...
```

Do not delete important planning context just because the implementation changed.

## Keeping Architecture Docs Current

Architecture docs should describe current truth. Update:

- [Architecture overview](../architecture/architecture-overview.md) for component or flow changes.
- [Service boundaries](../architecture/service-boundaries.md) for dependency changes.
- [API contracts](../architecture/api-contracts.md) for endpoint or error shape changes.
- [Data model](../architecture/data-model.md) for model changes.
- [Runner](../architecture/runner.md) for runner lifecycle changes.
- [AI service boundary](../architecture/ai-service-boundary.md) for AI contract changes.
- [Frontend](../architecture/frontend.md) for route/query/API client changes.

## PR Documentation Review Checklist

- [ ] Does the change preserve Django as the control plane?
- [ ] Did any endpoint or payload change?
- [ ] Did any model field, enum, relationship, or migration change?
- [ ] Did runner behavior or internal API contracts change?
- [ ] Did frontend routes or environment variables change?
- [ ] Did AI schemas or Django-to-AI calls change?
- [ ] Are planned/deferred features still labeled accurately?
- [ ] Are blueprints updated only where needed?
- [ ] Are docs linked from `docs/README.md` if they are new?

## AI Agent Drift Reporting

When an AI agent finds doc drift, it should report:

- File with stale statement.
- Current code evidence.
- Whether the feature is implemented, partial, planned, or deferred.
- Recommended narrow doc update.
- Verification performed.

It should not implement planned functionality just to resolve doc drift.

## Future Phase Completion Checklist

At the end of each phase:

- [ ] Update implementation status in relevant blueprint.
- [ ] Update `README.md` if maturity, quick start, or service responsibilities changed.
- [ ] Update `docs/README.md` links if docs were added.
- [ ] Update architecture docs for boundary, API, data, runner, AI, or frontend changes.
- [ ] Update runbooks for local workflow, deployment, or operational changes.
- [ ] Update app-level READMEs if ownership or scope changed.
- [ ] Run relevant tests and doc checks.
- [ ] Record remaining planned/deferred work explicitly.
