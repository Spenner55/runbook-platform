# Runbook Platform Documentation

This is the documentation landing page for the Runbook Platform repository.

## Architecture

| Document | Purpose |
| --- | --- |
| [Architecture overview](architecture/architecture-overview.md) | System overview, diagrams, request flows, ownership boundaries, and future expansion points. |
| [Service boundaries](architecture/service-boundaries.md) | Allowed and disallowed calls between Django, React, runner, AI, PostgreSQL, and API namespaces. |
| [Repository map](architecture/repository-map.md) | Maintainability map of major directories and common change patterns. |
| [API contracts](architecture/api-contracts.md) | Implemented, partial, planned, and deferred API surface. |
| [Data model](architecture/data-model.md) | Current Django models, fields, relationships, status enums, snapshots, and migration rules. |
| [Runner](architecture/runner.md) | Runner lifecycle, polling, claim, heartbeat, step update, completion, testing, and expansion rules. |
| [AI service boundary](architecture/ai-service-boundary.md) | FastAPI purpose, advisory role, current endpoints, and integration expectations. |
| [Frontend](architecture/frontend.md) | React role, routes, query strategy, feature folders, and API boundary rules. |
| [Per-file documentation guide](architecture/per-file-documentation-guide.md) | Standards for docstrings, comments, subdirectory READMEs, migrations, and code-adjacent documentation. |
| [Execution flow](architecture/execution-flow.md) | Existing detailed execution lifecycle reference. |

## API And Runner References

| Document | Purpose |
| --- | --- |
| [REST API v1](api/rest-api-v1.md) | Public API reference for `/api/v1/`. |
| [Internal runner API](api/internal-runner-api.md) | Runner-only internal API reference under `/api/v1/internal/`. |
| [Runner execution loop](runner/execution-loop.md) | Existing runner loop reference. |

## Runbooks

| Document | Purpose |
| --- | --- |
| [Local development](runbooks/local-development.md) | Docker Compose, Makefile, migrations, seed data, tests, linting, and troubleshooting. |
| [AI-agent working guide](runbooks/ai-agent-working-guide.md) | How Codex and Claude Code should work in this repo without drifting from architecture. |
| [Documentation maintenance](runbooks/documentation-maintenance.md) | When and how to update docs, blueprints, and implementation status. |

## Blueprints

[Blueprints](blueprints/) are planning documents. They preserve phase intent and future roadmap context, but they are not proof that a feature is implemented.

Use current code and [API contracts](architecture/api-contracts.md) for implementation truth. Use [Phase 10 guardrails](blueprints/phase-10-expansion-architecture-guardrails.md) when working on future expansion phases.

## Audits

| Document | Purpose |
| --- | --- |
| [Repository documentation audit](audits/repository-documentation-audit.md) | Current documentation inventory, drift findings, missing docs, and prioritized fixes. |
| [Phase 01 implementation audit](audits/phase-01-implementation-audit-report.md) | Historical phase audit. |
| [Phase 10 readiness/audit files](audits/) | Forward-looking expansion audit material. |

## Product And Decisions

| Area | Purpose |
| --- | --- |
| [Product docs](product/README.md) | Product notes and future product-facing documentation. |
| [Architecture decisions](decisions/README.md) | Decision records and cross-cutting rationale as they are added. |

## Maintenance Rule

When code, blueprints, and docs disagree:

1. Inspect current code.
2. Mark behavior as implemented, partially implemented, planned, or deferred.
3. Update the narrowest relevant docs.
4. Do not implement planned features just to make docs match a blueprint.
