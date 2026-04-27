# Contracts

Shared contract scaffolding for frontend, API, AI service, and runner.

## Current Scope

- Contains a workflow schema placeholder under `workflow/workflow.schema.json`.
- Not yet the enforced canonical schema source for every service.

## Ownership Rules

- Do not duplicate runtime business logic here.
- Do not assume schema changes are active until consuming services are updated and documented.
- Coordinate with `packages/workflow-schema`, which currently contains a related placeholder.
