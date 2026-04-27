# Packages

Shared package scaffolding for contracts, workflow schema material, and future SDK helpers.

## Current Packages

| Package | Status | Purpose |
| --- | --- | --- |
| `contracts` | Scaffold | Shared contract placeholders, including a workflow schema copy. |
| `workflow-schema` | Scaffold | Candidate home for canonical workflow schema exports. |
| `sdk` | Scaffold | Future TypeScript client/helper package. |

## Ownership Rules

- Current application behavior does not depend on these packages as the only source of truth.
- Do not add runtime business logic here.
- Do not create direct browser clients for FastAPI AI or runner services.
- Resolve workflow schema ownership before expanding schema usage.

See [repository map](../docs/architecture/repository-map.md) for maintainability guidance.
