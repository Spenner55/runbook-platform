---
name: Project phases completed
description: Which implementation phases have been completed and verified
type: project
---

Phase 10.7 (Backend Identity Foundation) is complete and verified as of 2026-04-29.

**Why:** Phase 10.7 adds a custom UUID-based User model and JWT auth endpoints under `/api/v1/auth/`. This replaces Django's built-in `auth.User` as the `AUTH_USER_MODEL`.

**How to apply:** Next phase is org RBAC / membership. Do not touch runner auth or frontend auth yet. Use the `users.User` model for any new FK references — never `auth.User`. Auth endpoints: login (POST), refresh (POST, httpOnly cookie), logout (POST), me (GET), register (POST).

## Phase completion summary

- Phase 1-3: Service layer, models, migrations
- Phase 4: Versioned REST APIs
- Phase 5: Runner real flow (claim/execute/complete)
- Phase 6: React product slice
- Phase 7: AI service boundary (Django → FastAPI, workflow creation)
- Phase 8: Targeted testing
- Phase 9: Makefile, seed_dev, ruff, prettier, pre-commit
- Phase 10.1: Approvals (step approval flow)
- Phase 10.2: Policies (policy evaluation, risk floor)
- Phase 10.3: Audit trail (AuditEvent model, AuditService.emit)
- Phase 10.4: Artifacts — **complete**
- Phase 10.5: Integrations — **complete**
- Phase 10.6: (audit/workflow fixes) — **complete**
- Phase 10.7: Backend Identity Foundation (custom User, JWT auth endpoints) — **complete**

## Phase 10.4 final test counts (all passing)

| Suite | Tests | Notes |
|---|---|---|
| Django API | 342 | Includes artifact readiness remediation tests |
| Runner | 72 | Includes runner multipart artifact upload contract test |
| Frontend (Vitest) | 51 | Includes artifact list and download error tests |

## Phase 10.4 key implementation details

- Artifact model with UUID PK, organization/execution/step FKs, storage_key (unique), checksum_sha256
- ArtifactStorage wraps local filesystem (ARTIFACT_MEDIA_ROOT), S3-ready abstraction
- Internal upload: POST /api/v1/internal/executions/{id}/steps/{step_id}/artifacts/
- Public listing: GET /api/v1/executions/{id}/artifacts/
- Download URL: POST /api/v1/artifacts/{id}/download/ with `organization_id` → signed, expiring /api/v1/artifacts/{id}/content/?organization_id=...&token=...
- Audit events: artifact.uploaded, artifact.download_url_created
- Runner: ArtifactUploader uploads stdout/stderr before terminal step status
- Quotas: 50MB/artifact, 250MB/execution, 1GB/runner/day (cache-backed)
- Public artifact list/download/content APIs require `organization_id` until Phase 10.7 auth.
- Uploads after terminal execution are rejected.
