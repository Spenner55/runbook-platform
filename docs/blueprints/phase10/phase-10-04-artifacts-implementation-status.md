# Phase 10.4 Artifacts Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-28 |
| Scope | Read-only implementation audit of Phase 10.4 Artifacts |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-04-artifacts-blueprint.md`, and Phase 10.1/10.2/10.3 implementation status docs |
| Verdict | **Ready for Phase 10.5 Integrations** after remediation on 2026-04-28. Artifact lint, download grants, audit reliability, tenant scoping, terminal upload rejection, settings drift, and required test gaps have been resolved. |

## 1. Executive verdict

Phase 10.4 Artifacts is ready to use as the baseline for Phase 10.5 Integrations.

The core artifact path exists and the blocking readiness gaps from the original audit have been remediated: Django owns artifact metadata and storage keys, runner uploads go through internal Django APIs, public listing and download request APIs are tenant-scoped, runner uploads stdout/stderr before terminal step updates, execution detail shows artifacts, and upload/download URL creation emits reliable audit events.

Resolved blockers:

1. `make lint` is clean.
2. `POST /api/v1/artifacts/{id}/download/` now returns a signed, expiring local content URL with `organization_id` and `token` query parameters.
3. Direct content access without a valid token is rejected, and expired tokens are rejected.
4. Artifact upload and download URL audit emission is fail-closed. Upload audit is inside the artifact DB transaction with storage cleanup on rollback.
5. Public artifact list, download, and content endpoints require `organization_id` and reject cross-tenant access.
6. Production storage and validation settings exist: `ARTIFACT_STORAGE_BACKEND`, `ARTIFACT_S3_BUCKET`, `ARTIFACT_S3_REGION`, `ARTIFACT_S3_PREFIX`, `ARTIFACT_ALLOWED_MIME_TYPES`, `ARTIFACT_REQUIRE_CHECKSUM`, and metadata/limit settings.
7. Runner uploads are rejected after execution reaches a terminal status.
8. Targeted backend, runner, and frontend tests cover the remediated behavior.

Phase 10.5 can start from this artifact baseline.

## 2. Implemented scope

- `apps.artifacts` is registered in `INSTALLED_APPS`.
- `Artifact` model exists with UUID primary key, organization, execution, optional step, kind, name, original name, MIME type, size, checksum, unique storage key, runner ID, upload status, uploaded timestamp, content disposition, and metadata.
- Artifact migration creates the model and indexes for organization/uploaded, execution/uploaded, step/uploaded, kind/uploaded, and checksum.
- Artifact admin is read-only and disables add/change/delete.
- Local filesystem `ArtifactStorage` wrapper writes, opens, checks, sizes, and deletes files under `ARTIFACT_MEDIA_ROOT`.
- Storage keys include organization ID, execution ID, step or execution scope, artifact UUID, and sanitized filename.
- Upload service validates runner ownership, step/execution match, artifact kind, file presence, per-artifact size, per-execution total quota, per-step artifact count, metadata object shape, and checksum mismatch.
- Upload service computes SHA-256 in Django and stores only metadata in Postgres.
- Upload service writes storage before creating the DB row and attempts best-effort storage cleanup if DB creation fails.
- Runner daily byte quota exists through Django cache counters.
- stdout/stderr MIME type is normalized to `text/plain; charset=utf-8`; report defaults to JSON.
- Internal step-scoped and execution-scoped runner upload endpoints exist under `/api/v1/internal/executions/.../artifacts/` using multipart parsing.
- Public execution artifact listing exists at `/api/v1/executions/{execution_id}/artifacts/`.
- Public download URL request exists at `POST /api/v1/artifacts/{artifact_id}/download/`.
- Local artifact content streaming exists at `GET /api/v1/artifacts/{artifact_id}/content/`.
- Public artifact serializers omit `storage_key` and claim token.
- `AuditEvent.ObjectType.ARTIFACT` exists.
- Normal-path upload emits `artifact.uploaded`.
- Normal-path download URL creation emits `artifact.download_url_created`.
- Artifact listing is not audited by default.
- Runner `ApiClient.upload_artifact(...)` posts multipart data to Django.
- Runner `ArtifactUploader` computes checksum, enforces local max size, truncates stdout/stderr, sends truncation metadata, retries 5xx/network failures once, and does not retry 4xx failures.
- Runner executor uploads stdout/stderr before reporting succeeded or failed terminal step status.
- Runner artifact upload failures do not change the command outcome.
- React artifact types, API client, query hook, download hook, query key, execution-detail artifact panel, empty state, truncated indicator, and download action are implemented.
- No direct runner-to-S3 upload, frontend internal API call, DB file blob, search, compression, deduplication, retention engine, queue, live streaming, or AI dependency was introduced.

## 3. Missing scope

No blocking Phase 10.4 scope remains before Phase 10.5.

Accepted deferred scope:

- Generated-file artifact directory collection remains deferred. The accepted Phase 10.4 scope is stdout/stderr plus the implemented execution/step upload APIs.
- S3 object I/O is not implemented in Phase 10.4. S3 bucket/region/prefix settings and incomplete-S3 validation exist, but local storage remains the only active backend until the later infrastructure phase implements S3 writes and presigned S3 URLs.
- Authenticated user/tenant context remains deferred to Phase 10.7. Until then, public artifact APIs require explicit `organization_id` as the tenant scope.

## 4. Blueprint drift

Blocking drift has been resolved:

- Download access is time-limited and enforced by a signed local content token.
- Direct content access without a grant is rejected.
- Upload and download URL audit failures are no longer suppressed.
- Public artifact APIs require tenant scope through `organization_id`.
- Artifact settings are present in Django settings and `.env.example`.
- MIME allowlist, checksum requirement, metadata-size cap, and incomplete S3 configuration validation exist.
- Terminal execution upload rejection exists.

Accepted non-blocking drift:

- The execution-level upload endpoint remains implemented even though the blueprint said to add it only if needed. It is still Django-internal, claim-token protected, tenant-bound through execution ownership, and covered by the same service validations.
- S3 backend settings exist, but S3 object I/O remains deferred to the infrastructure phase.

## 5. Test coverage review

Covered:

- Artifact model UUID behavior, kind choices, unique storage key, string representation, and absence of DB file-byte fields.
- Successful service upload writes storage and DB metadata.
- Runner ownership mismatch and claim-token mismatch rejection.
- Step/execution mismatch rejection.
- Invalid artifact kind rejection.
- Per-artifact size limit including exact-limit success and over-limit 413 path.
- Checksum mismatch and correct checksum paths.
- Storage key includes artifact UUID and omits claim token.
- Unsafe filename sanitization.
- Artifact listing and kind filtering.
- Download URL response and normal-path audit event emission.
- Per-execution total byte quota.
- Internal upload success, missing file, invalid claim token, wrong runner, oversize, checksum mismatch, invalid kind, and response redaction.
- Public list success, empty state, kind filter, storage key redaction, download response, download audit emission, and no audit on list.
- Runner checksum, stdout/stderr upload, truncation metadata, local oversize skip, retry behavior, no retry on 4xx, and uploader path arguments.
- Executor upload-before-terminal ordering for success and failure.
- Executor upload failure not changing successful command outcome.
- Execution detail artifact empty state, artifact rows, truncation indicator, and download action.

Current validation after remediation:

```sh
make lint
# passed

make test-api
# 342 passed

make test-runner
# 72 passed

make test-web
# 51 passed
```

New or expanded coverage includes signed download grants, missing/expired token rejection, cross-tenant rejection, invalid metadata JSON, `step_id` filtering, terminal execution upload rejection, runner daily quota, per-step count limit, metadata size cap, MIME allowlist, storage path containment, storage failure, audit rollback on upload, runner multipart upload shape, artifact list load errors, and download error display.

## 6. Storage/security risks

- Public artifact APIs still use the global pre-auth `AllowAny` posture until Phase 10.7. This is now mitigated for artifacts by requiring explicit `organization_id` tenant scope and signed download grants.
- `GET /api/v1/artifacts/{artifact_id}/content/` is Django-mediated and requires both matching `organization_id` and a signed, unexpired download token.
- `POST /api/v1/artifacts/{artifact_id}/download/` audits URL creation and returns the only valid local content grant.
- Artifact upload audit and download URL audit are fail-closed. Upload audit is inside the artifact DB transaction, with storage cleanup on failure.
- Runner claim tokens are not persisted in artifact rows, returned responses, storage keys, or audit metadata in the inspected implementation.
- `metadata` is persisted from runner input after JSON object validation and a size cap. Future generated-file metadata may still need value-level redaction if it can include user-controlled paths or messages.
- Audit metadata uses safe fields and omits raw content, storage key, download URL, and claim token.
- MIME type is treated mostly as metadata, which is appropriate. Optional MIME allowlist validation now exists through `ARTIFACT_ALLOWED_MIME_TYPES`.
- Content disposition defaults to attachment, reducing browser execution risk.
- Local storage validates path containment before opening, writing, sizing, or deleting objects.
- Daily runner quota uses a cache check then later increment, not an atomic projected increment. Concurrent uploads can still race past the daily limit; this is acceptable for Phase 10.4 local/dev storage and can be hardened with Redis or DB-backed counters later.
- Per-execution quota also uses an aggregate check before storage/DB creation without a lock. Concurrent uploads can race past the limit.
- Upload after terminal execution is rejected.
- No production storage encryption, private bucket, or signed S3 URL behavior is implemented yet; S3 object I/O remains deferred to the infrastructure phase.

## 7. Required fixes before Phase 10.5

All required fixes from the original audit are complete.

Evidence record: `docs/verification/phase-10-04-readiness-record.md`.

## 8. Recommended non-blocking follow-ups

- Document stdout/stderr-only artifact collection as the accepted Phase 10.4 initial scope, or add generated-file artifact directory support later.
- Add a small storage abstraction test suite separate from service tests.
- Consider grouping artifacts by step in the UI instead of one flat list.
- Add a UI display for checksum and uploaded-by runner if operators need evidence traceability.
- Add local artifact cleanup documentation for developers while retention remains out of scope.
- Make runner artifact limits configurable from environment rather than hard-coded constants, keeping defaults aligned with Django settings.
- Add value-level redaction for artifact metadata if future generated-file metadata can include user-controlled paths or messages.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-04-artifacts-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-implementation-status.md`
- `docs/blueprints/phase-10-02-policies-implementation-status.md`
- `docs/blueprints/phase-10-03-audit-trail-implementation-status.md`
- `docs/blueprints/phase-10-audit-remediation-summary.md`
- `docs/audits/phase-10-expansion-blueprints-audit.md`
- `docs/audits/phase-10-readiness-audit.md`
- `Makefile`
- `.env.example`
- `docker-compose.yml`
- `infra/aws/README.md`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/dev.py`
- `apps/api/config/settings/prod.py`
- `apps/api/config/settings/test.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/config/urls.py`
- `apps/api/apps/common/models.py`
- `apps/api/apps/common/exceptions.py`
- `apps/api/apps/common/api_errors.py`
- `apps/api/apps/artifacts/__init__.py`
- `apps/api/apps/artifacts/apps.py`
- `apps/api/apps/artifacts/models.py`
- `apps/api/apps/artifacts/migrations/0001_initial.py`
- `apps/api/apps/artifacts/admin.py`
- `apps/api/apps/artifacts/storage.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/artifacts/serializers.py`
- `apps/api/apps/artifacts/internal_views.py`
- `apps/api/apps/artifacts/views.py`
- `apps/api/apps/artifacts/urls.py`
- `apps/api/apps/artifacts/tests/conftest.py`
- `apps/api/apps/artifacts/tests/test_models.py`
- `apps/api/apps/artifacts/tests/test_services.py`
- `apps/api/apps/artifacts/tests/test_internal_api.py`
- `apps/api/apps/artifacts/tests/test_public_api.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/migrations/0001_initial.py`
- `apps/api/apps/audit/migrations/0002_add_artifact_object_type.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/audit/views.py`
- `apps/api/apps/audit/serializers.py`
- `apps/api/apps/audit/tests/test_models.py`
- `apps/api/apps/audit/tests/test_services.py`
- `apps/api/apps/audit/tests/test_api.py`
- `apps/api/apps/audit/tests/test_transaction_rollback.py`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/urls.py`
- `apps/api/apps/executions/tests/test_runner_api.py`
- `apps/api/apps/executions/tests/test_audit_integration.py`
- `apps/runner/runner/artifact_uploader.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/log_streamer.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/tests/test_artifact_uploader.py`
- `apps/runner/runner/tests/test_client.py`
- `apps/runner/runner/tests/test_executor.py`
- `apps/runner/runner/tests/test_orchestration.py`
- `apps/web/src/features/artifacts/types.ts`
- `apps/web/src/features/artifacts/api/artifactsApi.ts`
- `apps/web/src/features/artifacts/hooks/useExecutionArtifacts.ts`
- `apps/web/src/features/artifacts/hooks/useArtifactDownload.ts`
- `apps/web/src/features/executions/types.ts`
- `apps/web/src/features/executions/api/executionsApi.ts`
- `apps/web/src/features/executions/hooks/useExecutionDetail.ts`
- `apps/web/src/features/audit/types.ts`
- `apps/web/src/features/audit/api/auditApi.ts`
- `apps/web/src/features/audit/hooks/useExecutionAuditTrail.ts`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`

## 10. Commands to run for verification

Focused backend artifact suites:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/artifacts/tests -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/audit/tests/test_transaction_rollback.py -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/executions/tests/test_audit_integration.py -v
```

Focused runner and frontend suites:

```sh
docker compose exec runner pytest runner/tests/test_artifact_uploader.py runner/tests/test_client.py runner/tests/test_executor.py -v
docker compose exec web npm test -- --run src/routes/executions/ExecutionDetailPage.test.tsx
```

Full regression gates:

```sh
make test-api
make test-runner
make test-web
make lint
```

Manual verification before Phase 10.5:

```sh
make up-d
make migrate
make seed-dev
make logs-api
make logs-runner
```

Manual verification must prove:

- Runner uploads stdout/stderr through Django internal APIs.
- Upload creates both storage bytes and an `Artifact` DB row.
- Execution detail lists uploaded artifacts.
- Download request creates a fresh, time-limited grant.
- Expired or missing download grants cannot fetch bytes.
- Downloaded content matches captured output.
- Audit trail includes `artifact.uploaded` and `artifact.download_url_created`.
- Direct listing does not emit audit noise.
- Public responses do not expose `storage_key`, claim token, bucket name, credentials, or raw artifact content.
- Runner has no S3 credentials and no direct S3 upload path.

## Short summary

Phase 10.4 has the artifact plumbing and readiness remediation in place. Lint and the API, runner, and web test suites pass. The repo is ready to start Phase 10.5 Integrations from this artifact baseline.
