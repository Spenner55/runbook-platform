# Infrastructure

Infrastructure assets are intentionally minimal. Local development is owned by the root `docker-compose.yml` and `Makefile`.

## Current Directories

| Directory | Status | Purpose |
| --- | --- | --- |
| `aws` | Placeholder | Future AWS infrastructure and deployment workflows. |
| `compose` | Placeholder | Future split Compose files, overrides, and profiles. |
| `docker` | Placeholder | Future shared Docker snippets or production image assets. |
| `scripts` | Placeholder | Future operator scripts. |

## Ownership Rules

- Do not add live AWS infrastructure before the AWS deployment blueprint is approved.
- Do not move local source of truth away from the root `docker-compose.yml` without updating local development docs.
- Do not store secrets here.

See [local development](../docs/runbooks/local-development.md) and [repository map](../docs/architecture/repository-map.md).
