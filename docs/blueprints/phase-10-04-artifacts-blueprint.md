# Phase 10.4: Artifacts Expansion Blueprint

| Field | Value |
|---|---|
| Phase number | 10.4 |
| Phase name | Artifacts |
| Objective | Add Django-controlled artifact storage and retrieval for execution outputs such as stdout, stderr, generated files, reports, and diagnostics. |
| Status | Blueprint only |
| Depends on | Phases 01-09 complete and verified; Phase 10.1 approvals complete and verified; Phase 10.2 policies complete and verified; Phase 10.3 audit trail complete and verified |
| Authored | 2026-04-24 |

---

## 1. Purpose and sequencing rationale

Artifacts are execution evidence. They are the durable outputs produced by a runner while executing a workflow: stdout, stderr, generated files, machine-readable reports, diagnostics, captured command results, and future screenshots or structured run summaries. Without artifacts, the platform can show that a step succeeded or failed, but it cannot show the evidence operators need to debug failures, prove what happened, or attach useful context to later integrations.

Phase 10.4 comes after audit because artifact creation and artifact access are themselves operationally meaningful events. Uploading an artifact changes the evidentiary record for an execution. Generating a download URL gives a user time-limited access to that evidence. Those actions should be emitted into the audit trail using the event vocabulary established in Phase 10.3. Building artifacts before audit would either lose access history or force retroactive reconstruction that is not trustworthy.

Phase 10.4 comes before integrations because integrations become more useful once execution evidence exists. A Slack, PagerDuty, Jira, or webhook notification can link to a failed execution and mention that stdout, stderr, or diagnostics are available. Integrations should not invent their own file handling or evidence semantics. They should consume the stable Django artifact API created here.

This phase introduces file storage, but Django remains the control plane. The runner does not upload directly to S3, does not receive S3 credentials, and does not bypass Django. The frontend does not talk to S3 directly except through a time-limited URL that Django created after checking domain rules. The AI service is not involved.

At blueprint authoring time, the checked-out source tree shows:

- `apps/api/apps/artifacts/`, `apps/api/apps/audit/`, `apps/api/apps/approvals/`, and `apps/api/apps/policies/` contain only `__init__.py` stubs.
- `apps/runner/runner/artifact_uploader.py` is a stub.
- Execution state and internal runner APIs are implemented in `apps/api/apps/executions/`.
- Public execution detail UI is implemented in `apps/web/src/routes/executions/ExecutionDetailPage.tsx`.
- `infra/aws/README.md` is intentionally a placeholder and no live AWS artifact infrastructure exists yet.

This blueprint assumes the requested implementation baseline, not the current stub state: Phases 01-09, approvals, policies, and audit trail are complete and verified before anyone starts Phase 10.4 implementation.

Official documentation reviewed where relevant:

- Django 5.2 file storage API: `https://docs.djangoproject.com/en/5.2/ref/files/storage/`
- Django file upload handling: `https://docs.djangoproject.com/en/5.0/topics/http/file-uploads/`
- Django REST Framework parser behavior for multipart uploads: `https://www.django-rest-framework.org/api-guide/parsers/`
- AWS S3 presigned URL behavior: `https://docs.aws.amazon.com/AmazonS3/latest/userguide/ShareObjectPreSignedURL.html`
- Boto3 S3 presigned URL guide: `https://docs.aws.amazon.com/boto3/latest/guide/s3-presigned-urls.html`

---

## 2. Current-state inspection checklist

Before implementation begins, inspect the repository in this order. Do not implement from this blueprint without re-reading the current source files first.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` and confirm Phase 10.4 still follows audit and precedes integrations.
- [ ] Read `docs/blueprints/phase-10-03-audit-trail-blueprint.md` and confirm audit events exist for state-changing service operations.
- [ ] Inspect the implemented `apps/api/apps/audit/` source, especially `models.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, and tests.
- [ ] Confirm `AuditService.emit(...)` or equivalent supports artifact event types without views or serializers deciding audit semantics.
- [ ] Inspect `apps/api/apps/artifacts/` and confirm whether it is still a stub or already partially implemented.
- [ ] Confirm `apps/api/apps/common/models.py` still provides UUID primary keys through `BaseModel`.
- [ ] Confirm `apps/api/apps/common/api_errors.py` and domain exceptions still define the API error envelope and status mapping.
- [ ] Inspect `apps/api/apps/executions/models.py` for `Execution` and `ExecutionStep` fields, statuses, relationships, indexes, and deletion behavior.
- [ ] Inspect `apps/api/apps/executions/services.py` and confirm runner ownership validation, step transitions, and execution completion are service-owned.
- [ ] Inspect `apps/api/apps/executions/internal_views.py` and `internal_serializers.py` to match the established internal runner API style.
- [ ] Confirm public APIs are registered in `apps/api/config/api_v1_urls.py` under `/api/v1/`.
- [ ] Confirm internal runner APIs remain under `/api/v1/internal/`.
- [ ] Inspect `apps/api/config/settings/base.py`, `dev.py`, `prod.py`, and `docker-compose.yml` for media/storage settings and container volume behavior.
- [ ] Inspect `apps/runner/runner/artifact_uploader.py`, `executor.py`, `client.py`, `schemas.py`, and `log_streamer.py`.
- [ ] Confirm runner schemas use Pydantic and internal API calls go through `ApiClient`.
- [ ] Confirm runner tests in `apps/runner/runner/tests/` before changing runner behavior.
- [ ] Inspect `apps/web/src/features/executions/types.ts`, `api/executionsApi.ts`, `hooks/useExecutionDetail.ts`, and `apps/web/src/routes/executions/ExecutionDetailPage.tsx`.
- [ ] Inspect `apps/web/src/shared/lib/queryKeys.ts` and current frontend test patterns.
- [ ] Inspect `infra/aws/README.md` and any new AWS files if they exist.
- [ ] Review latest official Django, DRF, django-storages, boto3, and AWS S3 docs only where they affect implementation details.
- [ ] Run the current backend, runner, and frontend tests before starting this phase.

---

## 3. Architecture invariants and boundaries

These invariants are non-negotiable for Phase 10.4:

| Invariant | Phase 10.4 consequence |
|---|---|
| Django is the control plane. | Artifact metadata, storage keys, upload validation, download authorization, URL generation, and audit emission live in Django services. |
| Runner talks only to Django internal APIs. | The runner uploads artifacts only to `/api/v1/internal/...`; it never calls S3, never receives object storage credentials, and never writes database rows directly. |
| Frontend talks only to Django public APIs. | The React app lists artifacts and requests downloads from `/api/v1/...`; it never constructs storage keys or calls internal APIs. |
| AI service is stateless and advisory. | AI does not store, read, upload, summarize, index, or mutate artifacts in this phase. |
| All APIs remain under `/api/v1/`. | Public artifact APIs live under `/api/v1/artifacts/` and execution-scoped artifact routes under `/api/v1/executions/...`. |
| Internal runner APIs remain under `/api/v1/internal/`. | Runner upload APIs live under `/api/v1/internal/executions/...`. |
| UUID primary keys remain standard. | `Artifact` inherits from `BaseModel`. |
| Business logic belongs in `services.py`. | Views parse requests and call artifact services. Serializers validate/serialize. Artifact storage, audit, ownership checks, and URL generation live in services. |
| No premature queues or event infrastructure. | Uploads and audit writes are synchronous Django work. No Celery, Kafka, RabbitMQ, SQS, EventBridge, outbox, or background pipeline. |
| Runner must not upload directly to S3 or bypass Django. | Production S3 is behind Django's storage abstraction and Django-generated download URLs only. |

Additional boundaries:

- Store file bytes in object/file storage, not in Postgres.
- Store metadata in Postgres through the `Artifact` model.
- Do not add retention deletion logic yet. Store indefinitely in Phase 10.4.
- Do not add artifact search, indexing, preview generation, compression, deduplication, or virus scanning in this phase.
- Do not stream logs line-by-line to Django. Upload completed stdout/stderr artifacts after each step result is known, with failure-path ordering described below.
- Do not expose storage keys to the UI as download URLs. `storage_key` is internal metadata.
- Do not include claim tokens in artifact records, audit metadata, logs, or frontend responses.

---

## 4. Implementation scope by repo area

| Repo area | Scope in Phase 10.4 |
|---|---|
| `apps/api/apps/artifacts/` | Implement app config, model, migration, storage abstraction, services, serializers, public views, internal runner views, URLs, admin, and tests. |
| `apps/api/apps/executions/` | Attach artifact visibility to execution detail flows; optionally expose an execution-scoped artifact listing endpoint; enforce execution/step relationships during upload. |
| `apps/api/apps/audit/` | Add artifact audit event taxonomy and emit events from artifact services. |
| `apps/api/apps/common/` | Reuse common domain exceptions and API error envelope; add artifact-specific exceptions only if existing exceptions are insufficient. |
| `apps/api/config/` | Register `apps.artifacts`, add artifact URLs under `/api/v1/`, configure local artifact storage, upload limits, and future production storage settings. |
| `apps/runner/runner/artifact_uploader.py` | Implement a narrow uploader that sends multipart artifacts to Django internal APIs through runner-owned credentials and claim token. |
| `apps/runner/runner/client.py` | Add `upload_artifact(...)` method that posts multipart data to Django. Keep all HTTP calls centralized. |
| `apps/runner/runner/schemas.py` | Add request/response models for artifact upload responses where useful. |
| `apps/runner/runner/executor.py` | Collect stdout/stderr/generated files and upload them at deterministic points without making execution correctness depend on S3. |
| `apps/runner/runner/log_streamer.py` | Reuse or extend buffering utilities if execution output capture is centralized there; do not convert it into live log streaming. |
| `apps/web/src/features/artifacts/` | Add artifact TypeScript types, API client calls, hooks, and tests. |
| `apps/web/src/features/executions/` | Include artifact counts or artifact lists where execution detail contracts need them. |
| `apps/web/src/routes/executions/` | Add execution-detail artifact panel with list and download action. |
| `docker-compose.yml` | Add a local artifact media volume only if required for persistence across API container restarts. |
| `infra/aws/` | Document S3 production requirements only. Do not provision live AWS resources in Phase 10.4 unless explicitly approved as part of a later infrastructure phase. |

Likely backend files touched:

- `apps/api/apps/artifacts/apps.py`
- `apps/api/apps/artifacts/models.py`
- `apps/api/apps/artifacts/admin.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/artifacts/storage.py`
- `apps/api/apps/artifacts/serializers.py`
- `apps/api/apps/artifacts/views.py`
- `apps/api/apps/artifacts/internal_views.py`
- `apps/api/apps/artifacts/urls.py`
- `apps/api/apps/artifacts/tests/test_models.py`
- `apps/api/apps/artifacts/tests/test_services.py`
- `apps/api/apps/artifacts/tests/test_internal_api.py`
- `apps/api/apps/artifacts/tests/test_public_api.py`
- `apps/api/apps/artifacts/tests/test_storage.py`
- `apps/api/apps/artifacts/migrations/0001_initial.py`
- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/tests/test_artifact_integration.py`
- `apps/api/apps/audit/services.py` or audit taxonomy module, depending on Phase 10.3 implementation
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/dev.py`
- `apps/api/config/settings/prod.py`
- `apps/api/config/api_v1_urls.py`

Likely runner files touched:

- `apps/runner/runner/artifact_uploader.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/log_streamer.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/tests/test_artifact_uploader.py`
- `apps/runner/runner/tests/test_executor.py`
- `apps/runner/runner/tests/test_client.py`

Likely frontend files touched:

- `apps/web/src/features/artifacts/types.ts`
- `apps/web/src/features/artifacts/api/artifactsApi.ts`
- `apps/web/src/features/artifacts/hooks/useExecutionArtifacts.ts`
- `apps/web/src/features/artifacts/hooks/useArtifactDownload.ts`
- `apps/web/src/features/executions/types.ts`
- `apps/web/src/features/executions/api/executionsApi.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`

Out of scope unless explicitly approved:

- AI service changes.
- Integration dispatch changes.
- Auth/RBAC beyond using whatever Phase 10.3 baseline provides.
- Live streaming, SSE, or WebSockets.
- Production AWS provisioning.
- Queue-backed upload processing.
- Retention engine or scheduled deletion.

---

## 5. Data model: fields, relationships, indexes, constraints

### 5.1 `Artifact`

`Artifact` stores metadata and a pointer to storage. It never stores file bytes in the database.

Required fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Inherits `BaseModel`. Also used in storage key to prevent collisions. |
| `organization` | FK to `organizations.Organization`, `PROTECT` | Required tenant boundary copied from execution for efficient filtering and authorization. |
| `execution` | FK to `executions.Execution`, `CASCADE` or `PROTECT` | Required. Prefer `PROTECT` if execution deletion is restricted; use `CASCADE` only if execution deletion is already accepted as deleting execution evidence. |
| `step` | FK to `executions.ExecutionStep`, nullable, `SET_NULL` or `PROTECT` | Nullable for execution-level artifacts. Prefer `PROTECT` if step rows are never deleted independently. |
| `kind` | enum string | Required. Recommended values: `stdout`, `stderr`, `file`, `report`, `diagnostic`. |
| `name` | `CharField(255)` | Display filename supplied by runner after sanitization. No path separators. |
| `original_name` | `CharField(255, blank=True)` | Optional raw filename after safe truncation; useful if `name` is normalized. |
| `mime_type` | `CharField(128)` | Runner-declared or Django-detected MIME type. Treat as metadata, not security boundary. |
| `size_bytes` | `PositiveBigIntegerField` | Required exact stored size. |
| `checksum_sha256` | `CharField(64)` | Required if feasible. Justified because it supports integrity checks, retry idempotency, and debugging storage corruption without storing bytes in DB. |
| `storage_key` | `CharField(1024, unique=True)` | Required internal key/path in the configured storage backend. Never generated from filename alone. |
| `uploaded_by_runner_id` | `CharField(255)` | Required for runner uploads; may be blank only for future system-created artifacts. |
| `upload_status` | enum string | Recommended values: `available`, `failed`. If service writes storage before DB row, failed rows should be rare. |
| `uploaded_at` | `DateTimeField` | Required timestamp set by service. |
| `content_disposition` | enum string | Optional but useful. Recommended values: `attachment`, `inline`. Default `attachment`. |
| `metadata` | `JSONField(default=dict)` | Small safe metadata only: command exit code, truncation flag, byte limit applied, report subtype. No raw output. |

`created_at` and `updated_at` come from `BaseModel`. Use `uploaded_at` for product-facing sort order.

### 5.2 Relationships

Rules:

- Every artifact belongs to exactly one organization.
- Every artifact belongs to exactly one execution.
- An artifact may belong to one step.
- If `step` is not null, `step.execution_id` must equal `execution_id`.
- `organization_id` must equal `execution.organization_id`.
- The service must enforce both relationship checks before storage write.

Why duplicate `organization` on `Artifact`:

- It makes tenant filtering and future auth efficient.
- It makes artifact list queries independent of deep joins.
- It mirrors the audit blueprint's tenant boundary approach.

### 5.3 Indexes

Recommended indexes:

| Index | Purpose |
|---|---|
| `(organization, uploaded_at)` | Tenant-scoped artifact browsing and future admin support. |
| `(execution, uploaded_at)` | Execution detail artifact listing. |
| `(step, uploaded_at)` | Step-specific artifact grouping. |
| `(kind, uploaded_at)` | Filtering stdout/stderr/report artifacts. |
| `(checksum_sha256)` | Optional lookup for retry diagnostics and duplicate detection, without deduplication behavior. |
| `storage_key unique` | Prevent accidental key reuse. |

If the database backend does not support descending index syntax consistently across dev/test/prod, use ascending indexes and order by `-uploaded_at` in queries.

### 5.4 Constraints

Recommended constraints:

- `kind` must be one of the declared enum values.
- `name` must be non-empty after sanitization.
- `mime_type` must be non-empty and max 128 characters.
- `size_bytes` must be greater than or equal to zero and less than or equal to the configured maximum upload size.
- `checksum_sha256` must be exactly 64 lowercase hex characters when present.
- `storage_key` must be unique and non-empty.
- `uploaded_by_runner_id` must be non-empty for internal runner uploads.
- `metadata` must be a JSON object and should stay below a small practical limit such as 16 KB.

Cross-row relationship constraints are best enforced in `ArtifactService.create_from_upload(...)` because Django check constraints cannot easily compare through foreign keys.

### 5.5 Deletion semantics

Phase 10.4 should not expose artifact deletion.

- No public delete endpoint.
- No internal runner delete endpoint.
- Admin deletion should be disabled unless support explicitly needs it.
- Retention and purge are future work.

If later phases allow deletion, deletion must be audited and must remove or tombstone storage bytes consistently. Do not design that engine now.

---

## 6. Storage contracts: local dev, production-ready abstraction, storage key format

### 6.1 Storage abstraction

Use a Django-owned storage abstraction instead of coupling services directly to S3 or local filesystem paths.

Recommended shape:

- `apps/api/apps/artifacts/storage.py` defines an `ArtifactStorage` wrapper around Django's configured storage backend.
- The wrapper exposes `save(storage_key, uploaded_file)`, `open(storage_key)`, `exists(storage_key)`, `size(storage_key)`, and `url(storage_key, expires_in_seconds)`.
- Services depend on the wrapper, not on `boto3` or direct filesystem operations.
- Tests can inject a temporary filesystem or in-memory storage backend.

Django 5 uses the `STORAGES` setting and `django.core.files.storage.storages` for named storage backends. Use that pattern rather than deprecated storage APIs.

### 6.2 Local dev storage

Local development should use a filesystem-backed artifact store:

- `ARTIFACT_STORAGE_BACKEND=local` or equivalent setting.
- `ARTIFACT_MEDIA_ROOT` defaults to a path inside the API container such as `/app/media/artifacts` or a repo-local ignored directory such as `apps/api/media/artifacts`.
- `ARTIFACT_MEDIA_URL` is a Django-served URL only in `DEBUG` or through a controlled Django download view.
- `docker-compose.yml` may add a named volume or bind mount for artifact media if artifacts need to survive API container restarts.

Recommended local download behavior:

- Public download endpoint calls artifact service.
- Service emits audit access event where appropriate.
- Service returns a short-lived Django URL or streams the file through Django using `FileResponse`.
- If returning a local URL, it must not be a permanent unaudited media URL that bypasses Django access checks.

For Phase 10.4, streaming through Django for local dev is acceptable because artifact size is capped.

### 6.3 Production-ready S3 abstraction

Production storage should be S3-ready but not require Phase 10.4 to provision AWS resources.

Settings to design for:

- `ARTIFACT_STORAGE_BACKEND=s3`
- `ARTIFACT_S3_BUCKET`
- `ARTIFACT_S3_REGION`
- `ARTIFACT_S3_PREFIX`, default `artifacts/`
- `ARTIFACT_DOWNLOAD_URL_TTL_SECONDS`, default 300 seconds
- `ARTIFACT_MAX_UPLOAD_BYTES`, default 50 MB
- `ARTIFACT_ALLOWED_MIME_TYPES`, optional allowlist
- `ARTIFACT_REQUIRE_CHECKSUM`, default true for runner uploads

Production S3 requirements:

- Bucket is private.
- Objects are encrypted at rest with SSE-S3 initially; SSE-KMS can be added when compliance requires it.
- Django API task role has permission to `PutObject`, `GetObject`, `HeadObject`, and later lifecycle/delete permissions if retention is added.
- Runner task role does not need S3 permissions for artifacts.
- Frontend has no AWS credentials.
- Download uses Django-generated time-limited GET URLs for S3.

Phase 10.4 should not create Terraform/CDK resources unless the implementation task explicitly expands into infrastructure. Add documentation or TODO notes in `infra/aws/` only if needed.

### 6.4 Storage key format

Storage keys must prevent collisions and avoid trusting filenames.

Recommended format:

```text
artifacts/org/{organization_id}/execution/{execution_id}/step/{step_id_or_execution}/artifact/{artifact_id}/{safe_filename}
```

Examples:

```text
artifacts/org/0db2.../execution/4c1a.../step/7ad9.../artifact/8f20.../stdout.txt
artifacts/org/0db2.../execution/4c1a.../step/execution/artifact/9a44.../summary.json
```

Rules:

- Include `artifact_id` in every key.
- Include organization ID and execution ID.
- Include step ID when the artifact is step-scoped.
- Sanitize `safe_filename` to remove path separators, control characters, leading dots, and confusing whitespace.
- Truncate `safe_filename` to fit the DB field and object store limits.
- Do not allow runner-supplied paths to influence directories.
- Do not rely on Django storage's alternative-name collision behavior for correctness. Generate a unique key before save.

### 6.5 File size limits

Start with a hard upload limit of 50 MB per artifact.

Recommended constants:

- `ARTIFACT_MAX_UPLOAD_BYTES=52428800`
- `ARTIFACT_MAX_ARTIFACTS_PER_STEP=10`
- `ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION=250 MB`, enforced only if simple to implement without expensive aggregation
- stdout/stderr capture limit per stream: 5 MB by default, with truncation metadata

Why hard limits matter:

- Django workers are blocked during uploads.
- Local dev storage can fill quickly.
- S3 cost and transfer time scale with artifact size.
- Large logs often indicate a workflow should produce a summarized report instead.

When a runner output exceeds the stdout/stderr capture limit, upload a truncated artifact and set metadata:

```json
{
  "truncated": true,
  "original_size_bytes": 73400320,
  "captured_size_bytes": 5242880,
  "truncation_reason": "stream_limit"
}
```

Do not add compression in Phase 10.4.

### 6.6 MIME type and checksum

MIME type:

- Runner may send `mime_type`.
- Django should normalize and store it.
- For known artifact kinds, Django can override obvious defaults: stdout/stderr use `text/plain; charset=utf-8`, JSON reports use `application/json`.
- Treat MIME type as display/download metadata, not as proof that content is safe.
- Use `Content-Disposition: attachment` by default for downloads to reduce browser execution risk.

Checksum:

- Compute SHA-256 in Django while reading the upload stream.
- Store `checksum_sha256`.
- Optionally accept runner-provided `checksum_sha256` and compare it.
- Reject upload with `400 checksum_mismatch` if runner-provided checksum does not match.

Checksum is justified in Phase 10.4 because it verifies upload integrity, supports runner retry diagnostics, and gives operators a stable fingerprint without adding deduplication.

---

## 7. Internal runner upload API contract

### 7.1 Endpoint

Use an execution-scoped internal endpoint:

```http
POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/
Content-Type: multipart/form-data
```

For execution-level artifacts that are not tied to a step, add a separate endpoint only if needed:

```http
POST /api/v1/internal/executions/{execution_id}/artifacts/
Content-Type: multipart/form-data
```

Prefer the step-scoped endpoint first because the initial use cases are stdout, stderr, and step-generated files.

### 7.2 Request fields

Multipart form fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `runner_id` | string | yes | Must match execution ownership. |
| `claim_token` | UUID | yes | Must match execution claim token. Never persist or audit. |
| `kind` | string | yes | `stdout`, `stderr`, `file`, `report`, or `diagnostic`. |
| `name` | string | yes | Display filename. Django sanitizes. |
| `mime_type` | string | optional | Django normalizes or defaults if omitted. |
| `checksum_sha256` | string | optional | If present, Django verifies it. |
| `metadata` | JSON string | optional | Small safe metadata. |
| `file` | file | yes | Uploaded bytes. |

DRF implementation note:

- Use `MultiPartParser` and `FormParser` for this view.
- Do not use `FileUploadParser` unless the API is intentionally raw-file-only. The runner needs metadata and file in the same request, so multipart is the correct first contract.

### 7.3 Validation behavior

The internal view should:

1. Validate request shape in serializer.
2. Load execution and step by UUID.
3. Call artifact service with the validated payload.
4. Let service validate runner ownership through the existing execution ownership helper or a shared equivalent.
5. Reject if step does not belong to execution.
6. Reject if execution is not owned by the runner/claim token.
7. Reject if execution is terminal unless the service intentionally allows a short post-terminal upload window. Prefer uploading before terminal step/execution updates instead.
8. Enforce file size limit before or during storage.
9. Compute checksum while saving.
10. Create `Artifact` record after successful storage save.
11. Emit audit event in the same service flow.

Recommended error codes:

- `artifact_file_required` -> 400
- `artifact_too_large` -> 413
- `artifact_invalid_kind` -> 400
- `artifact_invalid_metadata` -> 400
- `artifact_step_mismatch` -> 400
- `runner_ownership_mismatch` -> 409 or existing status from execution services
- `claim_token_mismatch` -> 409 or existing status from execution services
- `checksum_mismatch` -> 400
- `artifact_storage_failed` -> 503

Use the existing API error envelope.

### 7.4 Response

Response status: `201 Created`

```json
{
  "id": "uuid",
  "execution_id": "uuid",
  "step_id": "uuid",
  "kind": "stdout",
  "name": "stdout.txt",
  "mime_type": "text/plain; charset=utf-8",
  "size_bytes": 1283,
  "checksum_sha256": "64_lowercase_hex_chars",
  "uploaded_by_runner_id": "runner-dev",
  "uploaded_at": "2026-04-24T18:00:00Z"
}
```

Do not return:

- `storage_key`
- `claim_token`
- Permanent media URL
- S3 bucket name
- Any storage credentials

### 7.5 Audit events

Emit `artifact.uploaded` after the artifact record is available.

Recommended event:

- `actor_type`: `runner`
- `actor_id`: runner ID
- `actor_label`: runner ID
- `event_type`: `artifact.uploaded`
- `object_type`: `artifact`
- `object_id`: artifact ID
- `organization_id`: artifact organization ID

Metadata:

```json
{
  "execution_id": "uuid",
  "step_id": "uuid",
  "kind": "stdout",
  "name": "stdout.txt",
  "mime_type": "text/plain; charset=utf-8",
  "size_bytes": 1283,
  "checksum_sha256": "64_lowercase_hex_chars"
}
```

Do not include raw artifact content, storage keys, claim tokens, or command text.

---

## 8. Public artifact listing/download API contract

### 8.1 Execution artifact listing

Recommended endpoint:

```http
GET /api/v1/executions/{execution_id}/artifacts/
```

Purpose: list artifacts visible on an execution detail page.

Query params:

| Param | Required | Notes |
|---|---|---|
| `step_id` | optional | Filter to one step. |
| `kind` | optional | Filter `stdout`, `stderr`, `file`, `report`, `diagnostic`. |
| `limit` | optional | Default 50, max 200. |
| `offset` | optional | Default 0. |

Response:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "execution_id": "uuid",
      "step_id": "uuid",
      "kind": "stdout",
      "name": "stdout.txt",
      "mime_type": "text/plain; charset=utf-8",
      "size_bytes": 1283,
      "checksum_sha256": "64_lowercase_hex_chars",
      "uploaded_by_runner_id": "runner-dev",
      "uploaded_at": "2026-04-24T18:00:00Z",
      "metadata": {
        "truncated": false
      }
    }
  ]
}
```

Do not include `storage_key` in public responses.

Alternative:

- `GET /api/v1/artifacts/?execution_id={execution_id}` is acceptable if it better matches router structure.
- Still provide an execution-scoped convenience endpoint if it makes frontend data flow simpler.

### 8.2 Artifact detail

Optional endpoint:

```http
GET /api/v1/artifacts/{artifact_id}/
```

This is useful for future direct linking. It should return the same metadata fields as list responses and should not return `storage_key`.

### 8.3 Download URL request

Endpoint:

```http
POST /api/v1/artifacts/{artifact_id}/download/
```

Use `POST`, not `GET`, because requesting a download URL is an access-granting action that should be auditable and should not be accidentally prefetched by crawlers or browser link previews.

Response:

```json
{
  "artifact_id": "uuid",
  "download_url": "https://time-limited-url",
  "expires_at": "2026-04-24T18:05:00Z",
  "method": "GET",
  "content_disposition": "attachment",
  "filename": "stdout.txt"
}
```

Rules:

- Default TTL: 300 seconds.
- Maximum TTL: 900 seconds unless product and security approve otherwise.
- URL is generated by Django after authorization/tenant checks.
- Local dev may return a Django-controlled URL instead of an S3 presigned URL.
- Production S3 may return a presigned GET URL.
- Download URL generation emits audit event where appropriate.

### 8.4 Audit for listing and download access

Do not audit normal artifact list polling by default. Listing artifacts is a read operation and would create excessive low-value audit events, especially while execution detail polls.

Audit these access events:

- `artifact.download_url_created` when a public API grants a time-limited URL.
- Future `artifact.downloaded` only if downloads stream through Django and completion can be observed. With S3 presigned URLs, Django can audit URL creation but cannot reliably audit actual object retrieval without S3 access logs or CloudTrail integration, which is out of scope for Phase 10.4.

Recommended `artifact.download_url_created` metadata:

```json
{
  "execution_id": "uuid",
  "step_id": "uuid",
  "artifact_id": "uuid",
  "kind": "stderr",
  "name": "stderr.txt",
  "expires_at": "2026-04-24T18:05:00Z"
}
```

Do not store the generated URL in audit metadata.

---

## 9. Runner artifact collection/upload contract

### 9.1 Collection responsibilities

The runner should collect:

- `stdout.txt` for each step.
- `stderr.txt` for each step.
- Optional generated files from an explicit artifact directory if the executor/sandbox supports one.
- Optional diagnostic JSON when a step fails due to runner-side exception.

Initial implementation can start with stdout/stderr only if command execution still uses placeholder behavior. When real shell execution exists, capture subprocess stdout/stderr buffers or bounded temporary files.

### 9.2 Upload timing

For each step:

1. Mark step `running`.
2. Execute the step and capture outputs.
3. Determine step outcome.
4. Upload stdout/stderr artifacts before reporting terminal step status.
5. If artifact upload fails, log runner error and include a safe warning in the step error message only if the step itself failed or if product wants upload failure to affect execution outcome.
6. Report step terminal status.

The key failure-path rule is: upload artifacts before marking a failed step as failed. If the runner marks the step failed first and then crashes, the evidence can be lost. Uploading before terminal status improves the chance that failure evidence exists.

### 9.3 Does artifact upload failure fail the execution?

Recommended Phase 10.4 behavior:

- If the step command succeeded but artifact upload failed, do not fail the step by default. Record a runner log error and proceed. The execution result should reflect command behavior.
- If the step command failed and artifact upload failed, still mark the step failed with the command failure. Include a short safe suffix such as `Artifact upload failed; runner logs contain details.` if the error model supports it.
- If stdout/stderr upload is a strict compliance requirement later, add a policy setting. Do not hard-code that in Phase 10.4.

Reasoning:

- Artifact storage improves observability, but it should not turn transient storage issues into false execution failures unless product explicitly requires evidence capture as a hard gate.
- Audit and runner logs should reveal upload failure.

### 9.4 Retry behavior

Runner should retry artifact upload with bounded backoff:

- 2 attempts total for 5xx/network failures.
- No retry for 4xx validation errors.
- Per-upload timeout: 30 seconds by default.
- Respect max size locally before attempting upload.

Do not add persistent local retry queues. If runner crashes after command execution but before upload, local temporary outputs may be lost. That is an accepted Phase 10.4 risk documented below.

### 9.5 Artifact directory contract

If generated files are supported, define a per-step artifact directory:

```text
{runner_work_dir}/executions/{execution_id}/steps/{step_id}/artifacts/
```

Rules:

- Runner uploads regular files only.
- Ignore symlinks, device files, sockets, and directories.
- Enforce per-file and per-step count limits before upload.
- Preserve only basename in `name`; never upload relative paths as storage paths.
- If multiple files share the same basename, Django's storage key still remains unique because artifact ID is included.
- Clean up local temporary files after upload attempts.

### 9.6 Runner API client contract

Add `ApiClient.upload_artifact(...)` with arguments:

- `execution_id`
- `step_id`
- `claim_token`
- `kind`
- `name`
- `file_obj` or bytes/path
- `mime_type`
- `checksum_sha256`
- `metadata`

The client constructs multipart data and posts to:

```text
/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/
```

The client must include `runner_id` from its existing configuration.

`ArtifactUploader` should own file discovery, local limit checks, checksum calculation if done runner-side, and calls into `ApiClient`.

---

## 10. Frontend data contracts and execution detail UI

### 10.1 TypeScript contracts

Add artifact types:

```ts
export interface Artifact {
  id: string
  execution_id: string
  step_id: string | null
  kind: 'stdout' | 'stderr' | 'file' | 'report' | 'diagnostic'
  name: string
  mime_type: string
  size_bytes: number
  checksum_sha256: string
  uploaded_by_runner_id: string
  uploaded_at: string
  metadata: Record<string, unknown>
}

export interface ArtifactDownload {
  artifact_id: string
  download_url: string
  expires_at: string
  method: 'GET'
  content_disposition: 'attachment' | 'inline'
  filename: string
}
```

If list endpoints use pagination, add a shared or feature-local paginated response type.

### 10.2 API client and hooks

Recommended functions:

- `listExecutionArtifacts(executionId, filters?)`
- `createArtifactDownloadUrl(artifactId)`

Recommended hooks:

- `useExecutionArtifacts(executionId)`
- `useArtifactDownload()`

Query keys:

- `queryKeys.executionArtifacts(executionId)`
- `queryKeys.artifact(artifactId)` if detail endpoint exists

### 10.3 Execution detail UI

Add an artifact panel to `ExecutionDetailPage`:

- Show artifacts grouped by step where possible.
- Show execution-level artifacts separately if supported.
- Display kind, filename, size, upload time, and truncation status.
- Provide a download button that calls `POST /api/v1/artifacts/{id}/download/`, then opens the returned URL.
- Avoid showing raw stdout/stderr inline in Phase 10.4 unless the artifact is small and product explicitly wants previews.
- Keep polling behavior aligned with execution status. While execution is active, artifact list can refetch on the same cadence or after step status changes.

Do not expose:

- Storage key.
- Claim token.
- Internal runner URL.
- S3 bucket name.
- Permanent media path.

### 10.4 UI states

Required states:

- No artifacts yet.
- Loading artifacts.
- Artifact list load error.
- Download URL creation error.
- Download URL expires quickly; user can request a fresh URL by clicking download again.
- Truncated stdout/stderr indicator.

### 10.5 Frontend tests

Add tests for:

- Execution detail renders artifact panel.
- Empty artifact list displays a quiet empty state.
- Artifact rows display name, kind, size, and upload time.
- Download button calls the download endpoint and opens/uses returned URL.
- Download endpoint errors surface in the UI.
- Active execution polling does not create duplicate UI rows.

---

## 11. Ordered milestones with small steps, files touched, commands, verification, rollback notes, and human approval gates

### Milestone 0: Preflight and approval gate

Purpose: confirm the baseline and prevent accidental implementation against stale assumptions.

Files touched: none.

Commands:

```bash
git status --short
sed -n '1,260p' docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md
sed -n '1,360p' docs/blueprints/phase-10-03-audit-trail-blueprint.md
rg --files apps/api/apps apps/api/config apps/runner/runner apps/web/src infra/aws | sort
```

Verification:

- Current tests pass before the phase starts.
- Audit implementation is present and verified.
- Human confirms implementation should begin.

Rollback:

- None; no files changed.

Human approval gate:

- Required before writing code.

### Milestone 1: Artifact app scaffold and settings

Purpose: register the artifact app and configure storage limits without endpoint behavior.

Likely files touched:

- `apps/api/apps/artifacts/apps.py`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/dev.py`
- `apps/api/config/settings/prod.py`
- `docker-compose.yml` if local media persistence is required

Small steps:

1. Add `ArtifactsConfig`.
2. Add app to `INSTALLED_APPS`.
3. Add artifact settings with conservative defaults.
4. Configure local filesystem storage for dev/test.
5. Document production S3 settings placeholders without requiring AWS.

Commands:

```bash
docker compose run --rm api python manage.py check
docker compose run --rm api pytest apps/artifacts apps/executions
```

Verification:

- Django starts with artifact settings.
- No model migration exists yet unless model is included in this milestone.

Rollback:

- Remove app registration and settings.
- Remove compose volume if added.

Human approval gate:

- Not required if Milestone 0 approved implementation.

### Milestone 2: Artifact model and migration

Purpose: create metadata persistence.

Likely files touched:

- `apps/api/apps/artifacts/models.py`
- `apps/api/apps/artifacts/admin.py`
- `apps/api/apps/artifacts/migrations/0001_initial.py`
- `apps/api/apps/artifacts/tests/test_models.py`

Small steps:

1. Add `Artifact` model with fields listed above.
2. Add indexes and constraints.
3. Add read-only admin registration.
4. Generate migration.
5. Add model tests for defaults, string representation, constraints, and no DB file blobs.

Commands:

```bash
docker compose run --rm api python manage.py makemigrations artifacts
docker compose run --rm api python manage.py migrate
docker compose run --rm api pytest apps/artifacts/tests/test_models.py
```

Verification:

- Migration applies cleanly.
- Model stores metadata only.

Rollback:

- Reverse migration while still in development.
- Delete migration/model changes before merge if milestone is abandoned.

Human approval gate:

- Required if deletion semantics or FK `on_delete` behavior differ from this blueprint.

### Milestone 3: Storage wrapper and service layer

Purpose: implement artifact creation and URL generation in services.

Likely files touched:

- `apps/api/apps/artifacts/storage.py`
- `apps/api/apps/artifacts/services.py`
- `apps/api/apps/artifacts/tests/test_services.py`
- `apps/api/apps/artifacts/tests/test_storage.py`
- `apps/api/apps/audit/` taxonomy/service files as required by Phase 10.3 implementation

Small steps:

1. Implement safe filename normalization.
2. Implement storage key generation with artifact UUID.
3. Implement upload size validation.
4. Implement SHA-256 calculation.
5. Implement `create_from_runner_upload(...)`.
6. Implement `list_for_execution(...)`.
7. Implement `create_download_url(...)`.
8. Emit `artifact.uploaded` and `artifact.download_url_created` audit events.
9. Add service tests with temporary storage.

Commands:

```bash
docker compose run --rm api pytest apps/artifacts/tests/test_services.py apps/artifacts/tests/test_storage.py
docker compose run --rm api pytest apps/audit apps/executions
```

Verification:

- 1 KB upload writes storage and DB metadata.
- Oversize upload raises domain error.
- Checksum mismatch rejects upload.
- Download URL is time-limited.
- Audit events are emitted without storage keys or URLs in metadata.

Rollback:

- Remove service/storage files and audit taxonomy additions.
- If migration exists, leave model unused or reverse before merge.

Human approval gate:

- Required before changing audit event taxonomy if Phase 10.3 event naming differs.

### Milestone 4: Internal runner upload API

Purpose: expose Django-mediated multipart upload to runner.

Likely files touched:

- `apps/api/apps/artifacts/serializers.py`
- `apps/api/apps/artifacts/internal_views.py`
- `apps/api/apps/artifacts/urls.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/artifacts/tests/test_internal_api.py`

Small steps:

1. Add internal upload serializer.
2. Add internal upload view with `MultiPartParser`.
3. Register route under `/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/`.
4. Reuse execution runner ownership validation.
5. Add API tests for success, ownership failure, step mismatch, missing file, oversize file, and checksum mismatch.

Commands:

```bash
docker compose run --rm api pytest apps/artifacts/tests/test_internal_api.py
docker compose run --rm api pytest apps/executions/tests/test_runner_api.py
```

Verification:

- Runner-style multipart request returns `201`.
- Invalid claim token cannot upload.
- Internal endpoint does not appear under public router accidentally.

Rollback:

- Remove URL registration and internal view.
- Service remains testable and unused.

Human approval gate:

- Required if endpoint path changes from this blueprint.

### Milestone 5: Public listing and download APIs

Purpose: expose artifact metadata and controlled download URL flow to frontend.

Likely files touched:

- `apps/api/apps/artifacts/serializers.py`
- `apps/api/apps/artifacts/views.py`
- `apps/api/apps/artifacts/urls.py`
- `apps/api/apps/executions/views.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/artifacts/tests/test_public_api.py`
- `apps/api/apps/executions/tests/test_artifact_integration.py`

Small steps:

1. Add public artifact serializers that omit `storage_key`.
2. Add execution artifact list endpoint.
3. Add `POST /api/v1/artifacts/{artifact_id}/download/`.
4. Add filtering by step and kind.
5. Add pagination consistent with existing repo conventions or a small local convention.
6. Add tests for list, detail if implemented, download URL generation, and audit emission.

Commands:

```bash
docker compose run --rm api pytest apps/artifacts/tests/test_public_api.py apps/executions/tests/test_artifact_integration.py
docker compose run --rm api pytest apps/artifacts apps/executions apps/audit
```

Verification:

- Public responses omit storage keys.
- Download endpoint emits audit event.
- Listing does not emit audit events by default.

Rollback:

- Remove public URL registration and views.
- Keep service/model if internal upload is still needed.

Human approval gate:

- Required if public response shape changes from this blueprint.

### Milestone 6: Runner upload client and artifact uploader

Purpose: let runner send artifacts to Django after step execution.

Likely files touched:

- `apps/runner/runner/artifact_uploader.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/tests/test_artifact_uploader.py`
- `apps/runner/runner/tests/test_client.py`

Small steps:

1. Add Pydantic upload response model if useful.
2. Add `ApiClient.upload_artifact(...)`.
3. Implement `ArtifactUploader` with local size checks, checksum calculation, and bounded retry.
4. Add tests using mocked `httpx.Client`.
5. Ensure runner never stores or logs claim token beyond existing API payload use.

Commands:

```bash
docker compose run --rm runner pytest runner/tests/test_artifact_uploader.py runner/tests/test_client.py
```

Verification:

- Multipart body includes file and metadata.
- Oversize local file is skipped or reported before upload.
- 5xx errors retry once.
- 4xx errors do not retry.

Rollback:

- Revert runner client/uploader changes; backend APIs remain unused.

Human approval gate:

- Required if artifact upload failure is proposed to fail otherwise successful steps.

### Milestone 7: Executor collection and upload integration

Purpose: integrate artifact upload into execution flow.

Likely files touched:

- `apps/runner/runner/executor.py`
- `apps/runner/runner/log_streamer.py`
- `apps/runner/runner/tests/test_executor.py`
- `apps/runner/runner/tests/test_orchestration.py`

Small steps:

1. Capture bounded stdout/stderr for each step.
2. Upload artifacts before reporting terminal step status.
3. Add diagnostic artifact for runner exceptions if practical.
4. Keep execution outcome semantics stable when upload fails.
5. Add tests for success and failure paths.

Commands:

```bash
docker compose run --rm runner pytest runner/tests/test_executor.py runner/tests/test_orchestration.py
```

Verification:

- Failed step uploads stderr/stdout before `status=failed` update.
- Upload failures are logged and do not mask command outcome.

Rollback:

- Remove executor calls to `ArtifactUploader`; uploader can remain unused.

Human approval gate:

- Required before changing execution failure semantics.

### Milestone 8: Frontend artifact UI

Purpose: make artifacts visible and downloadable from execution detail.

Likely files touched:

- `apps/web/src/features/artifacts/types.ts`
- `apps/web/src/features/artifacts/api/artifactsApi.ts`
- `apps/web/src/features/artifacts/hooks/useExecutionArtifacts.ts`
- `apps/web/src/features/artifacts/hooks/useArtifactDownload.ts`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`

Small steps:

1. Add types and API functions.
2. Add query keys and hooks.
3. Add execution detail artifact panel.
4. Add download action flow.
5. Add UI tests.

Commands:

```bash
docker compose run --rm web npm test -- --run
docker compose run --rm web npm run build
```

Verification:

- Artifact panel renders without layout overlap.
- Download button requests a fresh URL.
- Error states are visible and do not break execution detail.

Rollback:

- Remove UI panel and feature files; backend remains usable.

Human approval gate:

- Product/design review before merge if UI layout changes significantly.

### Milestone 9: Local end-to-end manual gate

Purpose: verify the full Phase 10.4 workflow in Docker.

Files touched: none unless fixing defects.

Commands:

```bash
docker compose up --build
docker compose run --rm api python manage.py check
docker compose run --rm api pytest
docker compose run --rm runner pytest
docker compose run --rm web npm test -- --run
docker compose run --rm web npm run build
```

Manual verification:

1. Create or seed an organization, runbook, workflow, and execution.
2. Let runner claim and execute it.
3. Confirm stdout/stderr artifacts are uploaded.
4. Open execution detail in frontend.
5. Confirm artifact list appears.
6. Download stdout or stderr.
7. Confirm content matches expected captured output.
8. Confirm audit trail includes `artifact.uploaded` and download URL access events.
9. Confirm storage files exist in local storage and DB record contains no file bytes.

Rollback:

- Disable runner upload integration first if artifact failures affect executions.
- Remove URL registrations if public access has a defect.
- Reverse DB migration only before data must be preserved.

Human approval gate:

- Required before declaring Phase 10.4 complete.

---

## 12. Testing strategy

### 12.1 Django model tests

Cover:

- `Artifact` inherits UUID primary key behavior.
- Required fields and enum choices.
- `storage_key` uniqueness.
- `size_bytes` constraints.
- Relationship consistency enforced through service.
- Admin is read-only if registered.

### 12.2 Django service tests

Cover:

- `create_from_runner_upload(...)` writes bytes to storage and metadata to DB.
- Service rejects step/execution mismatch.
- Service rejects invalid runner ownership.
- Service sanitizes filenames.
- Service generates collision-proof storage keys containing artifact UUID.
- Service computes SHA-256.
- Service rejects checksum mismatch.
- Service rejects oversize upload.
- Service emits `artifact.uploaded`.
- Service creates time-limited download URL.
- Service emits `artifact.download_url_created`.
- Service never writes claim token, storage URL, or raw content into audit metadata.

### 12.3 Django API tests

Internal upload:

- Multipart success.
- Missing file -> 400.
- Oversize file -> 413.
- Invalid claim token -> failure matching execution internal API conventions.
- Wrong runner ID -> failure.
- Step not in execution -> 400.
- Invalid metadata JSON -> 400.

Public API:

- Execution artifact list returns paginated metadata.
- Filters by kind and step work.
- Public response omits `storage_key`.
- Download URL endpoint returns method, URL, expiry, filename.
- Download URL endpoint audits access.

### 12.4 Upload size tests

Cover:

- File exactly at limit succeeds.
- File one byte over limit fails.
- Multiple artifacts do not bypass per-file limit.
- Runner local limit prevents avoidable upload attempt.
- Truncated stdout/stderr metadata is set correctly.

### 12.5 Storage tests

Cover:

- Local filesystem backend writes and reads files.
- Storage wrapper handles missing key gracefully.
- URL generation works in local mode.
- S3 mode can be tested with a mocked boto3/storage backend, not live AWS.
- `storage_key` cannot traverse directories.

### 12.6 Runner unit tests

Cover:

- `ArtifactUploader` computes checksum.
- `ArtifactUploader` builds metadata.
- `ApiClient.upload_artifact(...)` posts multipart to correct `/api/v1/internal/...` path.
- Retry behavior for network/5xx errors.
- No retry for validation/4xx errors.
- Executor uploads stdout/stderr before terminal step update.
- Executor keeps command outcome stable if artifact upload fails.
- Artifact directory collection ignores symlinks and nested directories if generated files are supported.

### 12.7 Frontend tests

Cover:

- Execution detail fetches and displays artifacts.
- Empty state.
- Download click calls download endpoint.
- Download errors render without crashing page.
- Truncated artifact indicator.
- Active execution polling/refetch does not duplicate rows.

### 12.8 Infrastructure validation tests where relevant

Local:

- `docker compose up --build` persists local artifact files if a volume is configured.
- API container can write to configured artifact directory.
- Local download path works through Django.

Production readiness:

- Settings validation fails clearly when `ARTIFACT_STORAGE_BACKEND=s3` without bucket/region.
- Mocked S3 presigned URL generation uses bounded expiration.
- IAM requirements are documented in `infra/aws/README.md` if updated.

Do not require live AWS for Phase 10.4 tests.

### 12.9 Manual gate

Manual gate must prove:

- Runner uploads stdout/stderr through Django.
- UI lists artifacts.
- User can request a fresh time-limited download URL.
- Downloaded content matches captured output.
- Audit trail shows upload and download URL creation.
- Runner has no S3 credentials and no direct S3 upload path.

---

## 13. Failure modes and risks

### Large uploads

Risk: Large files block Django workers, fill disk, increase S3 costs, and slow execution completion.

Mitigations:

- Enforce `ARTIFACT_MAX_UPLOAD_BYTES`.
- Enforce stdout/stderr capture limits.
- Return 413 for oversized upload.
- Do not add compression in Phase 10.4.
- Document that very large outputs should be summarized by the workflow.

### Missing artifacts on crash

Risk: Runner crashes after command execution but before upload, losing local stdout/stderr.

Mitigations:

- Upload artifacts before reporting terminal step status.
- Keep local temporary files until upload attempts finish.
- Log upload failures in runner logs.
- Accept that persistent local retry queues are out of scope.

### MIME spoofing

Risk: Runner or generated file claims safe MIME type but contains unsafe content.

Mitigations:

- Treat MIME as metadata, not trust boundary.
- Default downloads to `Content-Disposition: attachment`.
- Do not inline previews in Phase 10.4 by default.
- Optionally normalize obvious MIME types by artifact kind.

### Storage collision

Risk: Two artifacts with the same filename overwrite each other.

Mitigations:

- Include artifact UUID in storage key.
- Make `storage_key` unique.
- Sanitize filename and never use it as unique identity.
- Do not depend on storage backend alternative names.

### Permission leakage

Risk: A user downloads another organization's artifact or receives a permanent unaudited URL.

Mitigations:

- Require artifact queries to be scoped by execution/organization.
- Enforce auth/tenant rules from the Phase 10.3 baseline or future auth phase where available.
- Keep download URL TTL short.
- Do not expose `storage_key`.
- Audit download URL creation.

### Multi-tenancy

Risk: Artifact rows are not tenant-scoped, making future auth and organization filtering error-prone.

Mitigations:

- Store `organization_id` directly on `Artifact`.
- Derive it from execution in service only.
- Validate step/execution organization consistency.
- Add organization indexes.

### Storage write succeeds but DB write fails

Risk: Orphaned object remains in storage.

Mitigations:

- Generate artifact ID and storage key first.
- Save storage, then create DB row in a transaction.
- On DB failure, attempt best-effort storage delete.
- Log cleanup failure.
- Do not add background cleanup job in this phase.

### DB write succeeds but storage write fails

Risk: Artifact metadata points to missing bytes.

Mitigations:

- Prefer storage write before DB create.
- If status rows are needed, create as `failed` only with explicit service handling.
- Public listing should show only `available` artifacts.

### Checksum mismatch

Risk: File corrupted in transit or runner bug sends wrong metadata.

Mitigations:

- Compute checksum in Django.
- Compare runner-provided checksum if present.
- Reject mismatch.
- Include checksum in response and metadata.

### Local disk exhaustion

Risk: Local artifact media fills developer disk or container volume.

Mitigations:

- Enforce size limits.
- Keep local media path obvious and documented.
- Store indefinitely in phase, but allow developers to manually clear local media.
- Do not add automated retention engine yet.

### Audit noise

Risk: Auditing every artifact list request floods audit trail.

Mitigations:

- Audit upload and download URL creation.
- Do not audit normal artifact list reads.
- Do not audit frontend polling.

---

## 14. What NOT to do

- Do not store file contents in database fields.
- Do not add DB file blobs or base64 file payloads to `Artifact`.
- Do not let the runner upload directly to S3.
- Do not give the runner S3 credentials for artifacts.
- Do not generate presigned upload URLs for the runner in Phase 10.4.
- Do not let the frontend call internal runner APIs.
- Do not expose `storage_key` in public API responses.
- Do not expose permanent local media URLs that bypass Django checks.
- Do not add artifact search or indexing.
- Do not add compression.
- Do not add deduplication.
- Do not add retention engine, lifecycle scheduler, purge command, or deletion API yet.
- Do not add queues, Celery, Kafka, RabbitMQ, SQS, EventBridge, or an outbox.
- Do not add live log streaming.
- Do not use Django signals for artifact audit emission.
- Do not put artifact logic in views or serializers.
- Do not let upload failure silently create an `available` artifact row.
- Do not audit raw stdout/stderr content.
- Do not store claim tokens in artifact metadata, audit metadata, frontend state, or logs.
- Do not provision production AWS infrastructure unless explicitly approved for this phase.

---

## 15. Definition of done

Phase 10.4 is done when:

- `Artifact` model exists with UUID primary key, execution relationship, optional step relationship, organization boundary, metadata fields, unique storage key, MIME type, size, SHA-256 checksum, and upload actor metadata.
- Django has a storage abstraction that works with local dev storage and is ready for S3 production storage.
- Storage keys include organization ID, execution ID, optional step ID, artifact UUID, and sanitized filename.
- Runner uploads artifacts only through Django internal APIs under `/api/v1/internal/`.
- Frontend lists artifacts only through Django public APIs under `/api/v1/`.
- Download access uses Django-mediated time-limited URL generation.
- Public APIs never expose storage keys or permanent object locations.
- Artifact upload size limits are enforced and tested.
- Storage-key collision prevention is tested.
- Upload and download URL creation emit appropriate audit events.
- Normal artifact listing is not audited by default.
- Runner captures and uploads stdout/stderr for each step, bounded by configured limits.
- Runner upload failure behavior is explicit, tested, and does not accidentally mask command outcomes.
- Execution detail UI displays artifacts and supports requesting a fresh download URL.
- Django service/API tests, upload size tests, storage tests, runner unit tests, frontend tests, and relevant infra validation tests pass.
- Manual gate confirms end-to-end upload, list, download, content match, and audit visibility.
- No code implements out-of-scope features such as DB blobs, direct runner-to-S3 upload, search/indexing, compression/deduplication, retention engine, queues, or live streaming.
