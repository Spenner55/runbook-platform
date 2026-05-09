# Pilot Phase E: Durable Artifact and Evidence Storage Blueprint

| Field | Value |
|---|---|
| Blueprint ID | `pilot-phase-e-durable-artifact-evidence-storage` |
| Objective | Replace local-only artifact and evidence byte storage with a durable, private, S3-compatible storage architecture while preserving Django-owned authorization, audit, checksum, retention, and immutability semantics. |
| Status | Blueprint only |
| Authored | 2026-05-08 |
| Primary gap | Artifact storage is local-only. `ArtifactStorage` raises when `ARTIFACT_STORAGE_BACKEND != "local"`, and evidence bundles/exports reuse that local-only storage boundary. |
| Depends on | Existing artifact and evidence implementations; Phase 10.4 artifact contracts; Phase 11.5 sealed evidence bundle contracts; Pilot Phase C runner identity/pools for production deployment topology; Pilot Phase D secret/credential controls for cloud credentials. |

## Current State Summary

Files inspected for this blueprint:

- `apps/api/apps/artifacts/`
- `apps/api/apps/evidence/`
- `docs/report/real-world-readiness-after-phase-11-6.md`
- `docs/blueprints/phase-10-04-artifacts-blueprint.md`
- `docs/blueprints/phase-11.5-sealed-evidence-bundles-blueprint.md`
- `docs/blueprints/pilot-phase-c-runner-pools-target-connectivity-blueprint.md`
- `docs/blueprints/pilot-phase-d-secrets-credential-brokerage-blueprint.md`

Important current facts:

- Django is already the control plane for artifact metadata, runner upload validation, download authorization, audit emission, evidence materialization, sealing, export creation, retention cleanup, and legal holds.
- Runner artifact upload already goes through Django internal APIs. The runner does not upload to S3 and does not need object-storage credentials.
- React uses public Django APIs. The frontend does not construct storage keys and does not receive storage credentials.
- `Artifact` stores `storage_key`, `size_bytes`, `checksum_sha256`, tenant, execution, step, upload status, and safe metadata.
- `ArtifactService.create_from_runner_upload(...)` computes SHA-256, validates optional runner-declared checksum, writes storage, creates the DB row, emits `artifact.uploaded`, and rolls back storage on DB failure.
- `ArtifactService.create_download_url(...)` currently returns a short-lived Django content URL and audits `artifact.download_url_created`.
- `ArtifactStorage` is a local filesystem wrapper with `save`, `open`, `exists`, `size`, `delete`, and `local_path`. It intentionally rejects non-local backends.
- `EvidenceStorage` is a thin wrapper over `ArtifactStorage`, so sealed bundles and exports inherit the same local-only limitation.
- `EvidenceBundle` and `EvidenceExport` store immutable storage keys, content hashes, manifest hashes, size, retention timestamps, and storage deletion timestamps.
- Evidence retention cleanup is explicit via `cleanup_evidence_storage`; it deletes stored ZIP bytes only after expiry and only when no active legal hold blocks cleanup.
- Settings already include placeholders for `ARTIFACT_STORAGE_BACKEND=s3`, `ARTIFACT_S3_BUCKET`, `ARTIFACT_S3_REGION`, `ARTIFACT_S3_PREFIX`, and bounded download URL TTLs, but there is no S3 backend implementation.

The Phase E rule: storage backend durability must improve without weakening control-plane ownership. Django remains the only authority for upload acceptance, storage-key generation, checksum verification, download grants, retention deletion, legal-hold enforcement, and audit events.

## Pilot Scope

This blueprint targets a narrow production pilot:

- One private S3-compatible bucket per deployment environment, or a clearly isolated prefix per environment if account topology requires sharing.
- Django API role has object-store access. Runners and browsers do not receive object-store credentials.
- Existing local backend remains available for development and tests.
- Artifact uploads remain Django-mediated multipart uploads for the pilot.
- Downloads may use short-lived object-store signed URLs after Django authorization.
- Large direct-to-object-store browser or runner uploads are future work unless later approved.
- Evidence bundle and export storage use the same durable backend through the existing `EvidenceStorage` wrapper.

## 1. Storage Abstraction Architecture

Phase E should turn `apps/api/apps/artifacts/storage.py` into a real backend-dispatch boundary while keeping service call sites stable.

Recommended interface:

```text
ArtifactStorage.save(storage_key, file_obj, *, content_type="", checksum_sha256="") -> StoredObject
ArtifactStorage.open(storage_key) -> binary file-like object
ArtifactStorage.exists(storage_key) -> bool
ArtifactStorage.size(storage_key) -> int
ArtifactStorage.head(storage_key) -> StoredObjectMetadata
ArtifactStorage.delete(storage_key) -> None
ArtifactStorage.create_download_url(storage_key, *, filename, content_type, disposition, expires_in_seconds) -> SignedDownload
ArtifactStorage.verify_available(storage_key, *, expected_size, expected_sha256) -> None
```

`StoredObjectMetadata` should include:

- `storage_key`
- `size_bytes`
- `etag` where the backend provides one
- `checksum_sha256` where stored as object metadata or provider checksum
- `last_modified`
- encryption metadata if available and safe to expose internally

`SignedDownload` should include:

- `url`
- `method`
- `expires_at`
- `headers` if any client headers are required
- `backend`

Architecture rules:

- Services depend only on `ArtifactStorage` and `EvidenceStorage`, not on boto3, MinIO SDKs, raw filesystem paths, or provider-specific clients.
- `ArtifactStorage` chooses backend from settings and delegates to `LocalArtifactStorageBackend` or `S3ArtifactStorageBackend`.
- `EvidenceStorage` remains a thin wrapper over `ArtifactStorage`; it should not fork a separate backend family.
- `local_path()` is local-backend-only. Shared service code must not require local filesystem paths.
- Object-store exceptions must be mapped to domain-safe exceptions such as storage unavailable, object missing, permission denied, checksum mismatch, throttled, and invalid configuration.
- Storage backends should be injectable in tests so service behavior can be tested without live AWS.

## 2. Local vs Object-Storage Backend Strategy

Local backend purpose:

- Development.
- Unit tests and integration tests that need deterministic files.
- Small demo environments where durability is explicitly not promised.

Local backend expectations:

- Continue using `ARTIFACT_MEDIA_ROOT`.
- Preserve path traversal protection.
- Stream local downloads through Django with short-lived signed Django tokens.
- Avoid pretending local storage is production durable.

Object-storage backend purpose:

- Staging and production.
- Any pilot environment where artifacts or evidence must survive container restarts, host loss, or API redeploys.
- All sealed evidence bundles and exports used for audit or customer-facing compliance review.

Backend selection:

- `ARTIFACT_STORAGE_BACKEND=local` for development/test.
- `ARTIFACT_STORAGE_BACKEND=s3` for staging/production.
- Production settings should fail startup if `ARTIFACT_STORAGE_BACKEND=local` unless an explicit breakglass setting such as `ALLOW_LOCAL_ARTIFACT_STORAGE_IN_PROD=false` is overridden.

Compatibility rule:

- Existing artifact and evidence DB rows remain valid because `storage_key` is a logical key. The meaning of a key is backend-relative. Migration must copy bytes to the object backend before flipping production reads.

## 3. S3-Compatible Backend Design

The S3-compatible backend should support AWS S3 first while allowing MinIO or another S3-compatible service for local integration testing.

Required behavior:

- Private bucket only. No public bucket, public object ACLs, or website hosting.
- Block public access at bucket/account level where AWS S3 is used.
- Server-side encryption enabled for every object.
- Prefer SSE-KMS in production; allow SSE-S3 only for lower-risk staging if compliance accepts it.
- API task role can `PutObject`, `GetObject`, `HeadObject`, `DeleteObject` where retention cleanup is enabled, `ListBucket` only for scoped migration/repair tooling, and multipart permissions only if multipart upload is implemented.
- Runner role has no object-storage permissions for artifacts/evidence.
- Browser has no object-storage credentials.
- Signed GET URLs are created only after Django public API authorization.
- Signed URLs must include response content disposition and type where supported.
- Object metadata should store safe integrity metadata, especially `sha256`, object class, artifact/evidence IDs, organization ID, and created-by subsystem. Do not store secrets, raw command text, claims, JWTs, or customer PII in object metadata.

Recommended implementation choices:

- Use boto3 directly behind the storage abstraction, or use Django `STORAGES` plus a thin wrapper if it can expose all required methods cleanly.
- Configure client endpoint URL for S3-compatible testing.
- Use path-style addressing only when required by the compatible provider.
- Use bounded timeouts and retry settings. Do not let object-store calls hang Django workers indefinitely.
- For pilot artifact sizes, single PUT is acceptable under `ARTIFACT_MAX_UPLOAD_BYTES`. Multipart should be designed but not required until limits increase.

## 4. Storage Key Strategy

Current artifact key shape is sound and should remain stable:

```text
artifacts/org/{organization_id}/execution/{execution_id}/step/{step_id_or_execution}/artifact/{artifact_id}/{safe_filename}
```

Current evidence key shape is also sound and should remain stable:

```text
evidence/org/{organization_id}/change/{change_record_id}/bundle/{bundle_id}/bundle.zip
evidence/org/{organization_id}/change/{change_record_id}/bundle/{bundle_id}/exports/{export_id}/export.zip
```

Key rules:

- The key is an internal logical path, not a user-facing URL.
- Include organization ID in every key for tenant-level forensics and scoped lifecycle rules.
- Include immutable object IDs to prevent collisions.
- Never trust runner-supplied filenames for directory segments.
- Keep sanitized filenames only as the final artifact path segment for operator readability.
- Do not reuse keys after retention deletion. A later export or re-sealed bundle must use a new ID and therefore a new key.
- Do not use content hash alone as a key in Phase E. Deduplication would complicate legal hold, deletion, tenant isolation, and audit semantics.

Optional environment prefix:

```text
{ARTIFACT_S3_PREFIX}/{environment}/artifacts/...
{ARTIFACT_S3_PREFIX}/{environment}/evidence/...
```

If used, the environment prefix must be configured by deployment settings, not supplied by request data.

## 5. Upload and Download Authorization Flow

Upload flow remains Django-mediated:

1. Runner authenticates to Django internal API.
2. Django resolves the authenticated runner identity and validates execution ownership/claim.
3. Django validates change binding, step relationship, execution state, artifact kind, size, quotas, MIME type, metadata, and checksum shape.
4. Django generates the storage key.
5. Django writes bytes to the configured storage backend.
6. Django verifies stored size and checksum where backend support allows.
7. Django creates the `Artifact` row and emits `artifact.uploaded`.
8. If DB creation fails after storage write, Django attempts best-effort object deletion.

Download flow for artifacts:

1. User calls `POST /api/v1/artifacts/{artifact_id}/download/` with organization context.
2. Django verifies authentication, organization membership, artifact tenant, artifact availability, and any future role or evidence-access restrictions.
3. Django emits `artifact.download_url_created`.
4. Local backend returns a Django content URL with a signed token.
5. S3 backend returns a short-lived signed GET URL.

Download flow for sealed bundles:

1. User calls `POST /api/v1/evidence-bundles/{bundle_id}/download/`.
2. Django verifies organization membership, bundle tenant, `status=sealed`, storage not retention-deleted, and storage existence.
3. Django emits the existing evidence download audit event.
4. Local backend may stream through Django; S3 backend should return a signed GET URL.

Download flow for evidence exports:

- The current export endpoint streams bytes through Django via `download_export(...)`.
- Phase E should align exports with the same signed-URL pattern used by artifacts and bundles, or explicitly keep streaming for exports if product needs stronger "actual download" audit semantics.
- If exports move to signed URLs, audit should record URL grant creation; actual object retrieval must be observed through S3 access logs, CloudTrail data events, or provider logs, not Django.

Authorization rules:

- Storage key possession alone must never authorize access.
- Signed URL creation is the authorization event.
- Signed URLs must not bypass legal-hold or retention-deleted checks because those checks happen before URL generation.
- A URL may remain usable until TTL expiry after a permission change. Keep TTL short to bound this window.

## 6. Signed URL Strategy

Defaults:

- `ARTIFACT_DOWNLOAD_URL_TTL_SECONDS=300`.
- Hard maximum `ARTIFACT_DOWNLOAD_URL_MAX_TTL_SECONDS=900`.
- Use GET-only signed URLs for downloads.
- Do not create signed PUT URLs in Phase E.

Signed URL requirements:

- Include response filename/content disposition where provider supports it.
- Include content type where provider supports it.
- Use HTTPS endpoints only outside local S3-compatible testing.
- Expiration must be computed server-side by Django.
- Returned payload shape should remain compatible with the existing artifact download descriptor:

```json
{
  "artifact_id": "uuid",
  "download_url": "https://time-limited-url",
  "expires_at": "2026-05-08T18:05:00Z",
  "method": "GET",
  "content_disposition": "attachment",
  "filename": "stdout.txt"
}
```

Evidence bundle/export descriptors should use the same shape with `bundle_id` or `export_id`.

Audit limitation:

- With signed object-store URLs, Django can reliably audit URL creation but not successful byte transfer.
- If auditors require actual retrieval proof, enable provider access logs or CloudTrail data events and define a later ingestion/reporting phase.

## 7. Checksum Verification Model

Artifact upload:

- Runner should continue sending `checksum_sha256`.
- Django computes SHA-256 while reading upload bytes.
- If `ARTIFACT_REQUIRE_CHECKSUM=true`, missing checksum fails upload.
- Mismatch fails upload before object write.
- After object write, Django should verify:
  - backend-reported size equals `size_bytes`;
  - stored checksum metadata equals computed checksum where supported;
  - optional read-back verification in strict mode for staging can detect backend metadata bugs.

S3 object metadata:

- Store `x-amz-meta-sha256` or provider-equivalent user metadata with the computed checksum.
- Do not rely on S3 ETag as SHA-256. ETag is not a SHA-256 checksum and changes semantics for multipart/KMS.
- If AWS checksum headers are used, treat them as additive verification, not a replacement for the DB `checksum_sha256` contract.

Evidence sealing:

- Evidence bundle/package generation already computes `manifest_sha256`, `payload_checksums_sha256`, `content_sha256`, and per-item content hashes.
- Object storage must preserve the exact ZIP bytes for `content_sha256`.
- After saving a sealed bundle or export, the storage layer should verify size and checksum metadata match `content_size_bytes` and `content_sha256`.
- If storage verification fails during sealing, invalidate the bundle only through existing evidence service rules; never rewrite sealed bytes after a successful seal.

Download-time integrity:

- Signed URL downloads cannot be checksum-verified by Django during transfer.
- Response descriptors may include expected SHA-256 for clients that want to verify downloaded bytes.
- Django content streaming in local mode may optionally verify storage metadata before opening the file.

## 8. Retention and Legal-Hold Implications

Current evidence retention behavior must remain authoritative:

- Retention cleanup deletes stored ZIP bytes only after expiry.
- Metadata rows, hashes, manifests, receipts, and audit events remain.
- Active legal holds block cleanup.
- Cleanup is explicit via management command, not a background worker.

Object-storage implications:

- Django retention cleanup must be the primary deletion authority for evidence bundles and exports because it understands legal holds.
- Bucket lifecycle rules must not delete canonical evidence objects earlier than Django retention allows.
- If bucket lifecycle is used, it should be conservative and scoped to temporary/staging prefixes, incomplete multipart uploads, or non-evidence transient objects.
- S3 Object Lock can be considered later for compliance mode, but Phase E should not enable irreversible bucket-level retention without a separate legal review and operational runbook.

Artifact retention:

- Plain execution artifacts currently have no deletion lifecycle equivalent to evidence retention.
- Phase E should not add silent artifact deletion that could break sealed evidence source references.
- If artifact cleanup is introduced later, it must check whether any `EvidenceBundleItem` references the artifact or whether the related change has an active legal hold.

Legal hold rules:

- A legal hold on a change or bundle must prevent deletion of canonical bundle/export bytes.
- If source artifacts are required to reproduce or validate sealed evidence, legal hold must also prevent deleting those source artifact bytes until the policy explicitly says the sealed package is sufficient.
- Releasing a hold does not delete immediately; it only allows the next retention cleanup run to evaluate expiry.

## 9. Bundle Immutability Implications

Sealed evidence immutability is a data contract, not a backend convenience.

Rules:

- A sealed bundle's `storage_key`, manifest, content hash, size, item rows, and payload checksums cannot change.
- Migrating bytes from local storage to S3 must not alter `storage_key` unless the migration is designed as an explicit metadata migration with full audit and verification. Preferred strategy: preserve logical `storage_key` and change only backend configuration after copy.
- Rewriting ZIP metadata, compression method, or timestamps during migration is forbidden because it changes `content_sha256`.
- If a sealed object's stored bytes are missing or checksum-invalid after migration, mark the bundle invalid or storage-missing through an explicit repair/invalidation path. Do not silently regenerate the object under the same sealed bundle record.
- Evidence exports are immutable once ready. The same migration and checksum rules apply.

Object versioning:

- Enable bucket versioning in staging/production where possible.
- Application reads should target the current version by key.
- Version IDs may be stored in internal metadata after Phase E if needed for recovery, but the app must not depend on mutable overwrites.
- The application should never overwrite an existing sealed bundle or export key.

## 10. Storage Lifecycle Expectations

Lifecycle by object class:

| Object class | Creation | Access | Deletion |
|---|---|---|---|
| Execution artifact | Runner upload through Django | Authorized signed URL or local stream | No automatic deletion in Phase E |
| Sealed evidence bundle | Django sealing service | Authorized signed URL or local stream | Evidence retention cleanup only |
| Evidence export | Django export service | Authorized signed URL or current stream | Export expiry cleanup only |
| Temporary multipart parts | Storage provider | Not user-accessible | Provider lifecycle for incomplete multipart uploads |
| Migration staging copies | Migration tooling | Operator-only | Explicit migration cleanup after verification |

Expected lifecycle policies:

- Abort incomplete multipart uploads after 1 to 7 days if multipart is enabled.
- Transition older non-held artifacts to cheaper storage only after download latency expectations are accepted.
- Do not transition recent pilot artifacts/evidence to archive classes that break signed URL download expectations.
- Do not expire evidence prefixes by bucket rule unless the rule is demonstrably later than all app-level retention windows and legal-hold constraints.

Operational metrics:

- Bytes uploaded by object class and organization.
- Object count by prefix and organization.
- Signed URL grants by object class.
- Storage write/read/head/delete errors by backend.
- Retention cleanup deleted/skipped/blocked counts.
- Checksum mismatch count.

## 11. Cost-Control Considerations

Controls to preserve or add:

- Keep `ARTIFACT_MAX_UPLOAD_BYTES`.
- Keep `ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION`.
- Keep `ARTIFACT_MAX_ARTIFACTS_PER_STEP`.
- Keep `ARTIFACT_DAILY_BYTES_PER_RUNNER`.
- Keep stdout/stderr byte caps.
- Add per-organization monthly storage reporting before broad rollout.
- Add per-object-class tags or metadata to support cost allocation.
- Keep signed URL TTLs short to reduce uncontrolled transfer windows.
- Prefer single private bucket with clear prefixes for pilot if that simplifies operational visibility, but do not mix staging and production without an environment prefix and IAM boundary.

Cost risks:

- Evidence bundles duplicate artifact bytes into ZIPs. This is intentional for immutability but increases storage.
- Exports duplicate sealed bytes again, especially unredacted exports. Short export retention is important.
- Debug artifacts can grow quickly if real execution uploads large generated files.
- Object access logs and CloudTrail data events add cost. Enable them selectively if actual download proof is required.

## 12. Required Settings and Environment Variables

Existing settings to preserve:

- `ARTIFACT_STORAGE_BACKEND`
- `ARTIFACT_MEDIA_ROOT`
- `ARTIFACT_S3_BUCKET`
- `ARTIFACT_S3_REGION`
- `ARTIFACT_S3_PREFIX`
- `ARTIFACT_ALLOWED_MIME_TYPES`
- `ARTIFACT_REQUIRE_CHECKSUM`
- `ARTIFACT_MAX_UPLOAD_BYTES`
- `ARTIFACT_MAX_ARTIFACTS_PER_STEP`
- `ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION`
- `ARTIFACT_DAILY_BYTES_PER_RUNNER`
- `ARTIFACT_DOWNLOAD_URL_TTL_SECONDS`
- `ARTIFACT_MAX_METADATA_BYTES`
- `ARTIFACT_STDOUT_STDERR_MAX_BYTES`

New or clarified settings:

| Setting | Purpose |
|---|---|
| `ARTIFACT_DOWNLOAD_URL_MAX_TTL_SECONDS` | Hard cap for signed download TTL. Default `900`. |
| `ARTIFACT_S3_ENDPOINT_URL` | Optional S3-compatible endpoint for MinIO/non-AWS. Empty for AWS. |
| `ARTIFACT_S3_ADDRESSING_STYLE` | Optional `virtual` or `path`. |
| `ARTIFACT_S3_USE_SSL` | Must be true outside local tests. |
| `ARTIFACT_S3_KMS_KEY_ID` | Optional KMS key for SSE-KMS. |
| `ARTIFACT_S3_SERVER_SIDE_ENCRYPTION` | `aws:kms` or `AES256`; production should prefer `aws:kms`. |
| `ARTIFACT_S3_STORAGE_CLASS` | Optional default storage class, usually `STANDARD` for pilot. |
| `ARTIFACT_S3_CONNECT_TIMEOUT_SECONDS` | Bounded client connect timeout. |
| `ARTIFACT_S3_READ_TIMEOUT_SECONDS` | Bounded client read timeout. |
| `ARTIFACT_S3_MAX_ATTEMPTS` | Bounded retry attempts. |
| `ARTIFACT_STORAGE_VERIFY_AFTER_WRITE` | Verify head metadata after write. Default true in production. |
| `ARTIFACT_STORAGE_STRICT_READBACK_VERIFY` | Optional expensive read-back verification for staging tests. Default false. |
| `ALLOW_LOCAL_ARTIFACT_STORAGE_IN_PROD` | Explicit escape hatch; default false. |
| `EVIDENCE_BUNDLE_RETENTION_DAYS` | Existing fallback for sealed bundles when no policy exists. |
| `EVIDENCE_EXPORT_RETENTION_DAYS` | Existing fallback for exports when no policy exists. |

Credential source:

- AWS credentials should come from the API service role, IRSA, ECS task role, or equivalent workload identity.
- Do not store object-store access keys in Django settings for production.
- Local S3-compatible testing may use env vars, but they must be treated as dev-only secrets.

## 13. API and Service Changes Required

Storage layer:

- Split local filesystem logic into a local backend class.
- Add an S3-compatible backend class.
- Add backend `head`, `create_download_url`, and verification methods.
- Make `local_path` unsupported for S3 and remove shared service reliance on it.

Artifact services:

- Update `create_download_url(...)` to ask storage for a signed URL when backend is S3.
- Preserve current response shape.
- Include expected checksum/size in response only if product wants client-side verification.
- Verify stored object metadata after upload.
- Keep DB row creation semantics: storage first, DB row second, best-effort storage delete on DB failure.

Artifact views:

- Keep public endpoints stable.
- `ArtifactContentView` remains local-token streaming only or becomes a fallback/debug path.
- In S3 mode, content endpoint should either reject with a clear error or remain available only for internal repair/admin use.

Evidence services:

- Add signed URL creation for bundles through `EvidenceStorage`.
- Decide whether exports use signed URL descriptors or keep current Django streaming. Preferred Phase E direction is signed URLs for consistency and large export safety.
- Verify sealed/export object metadata after save.
- Ensure retention cleanup uses object-store delete and handles missing object idempotently.

Evidence views:

- Keep existing route names stable where possible.
- If export download changes from streaming to signed URL grant, introduce a response shape compatible with artifact/bundle grants and update frontend accordingly.
- Continue enforcing organization membership and operator/admin roles for creation, sealing, legal holds, and release.

Audit:

- Preserve `artifact.uploaded` and `artifact.download_url_created`.
- Preserve evidence bundle/export creation, download, retention, and legal-hold audit events.
- If downloads become signed URL grants, event names should distinguish grant creation from confirmed download only if provider logs are later ingested.

Infrastructure docs:

- Add IAM and bucket policy requirements under `infra/aws/` in a later implementation task.
- Do not require runners to receive S3 permissions.

## 14. Migration Strategy from Local Storage

Migration must be explicit, verified, and reversible until cutover.

Recommended phases:

1. Inventory:
   - List all `Artifact`, sealed/invalidated `EvidenceBundle` rows with `storage_key`, and ready `EvidenceExport` rows with `storage_key`.
   - Record expected size and SHA-256 from DB.
   - Mark rows whose local file is missing before copy.
2. Dry run:
   - Validate local file exists.
   - Compute local SHA-256 and compare with DB.
   - Report missing, mismatched, zero-byte, and inaccessible files.
3. Copy:
   - Upload bytes to S3 under the same logical `storage_key`.
   - Set object metadata with expected SHA-256, object type, organization ID, and source row ID.
   - Do not update application DB rows if logical keys are preserved.
4. Verify:
   - Head every copied object for existence and size.
   - Verify stored checksum metadata.
   - Optionally sample read-back bytes and recompute SHA-256.
5. Dual-read canary:
   - In staging, run S3 backend against copied data.
   - Exercise artifact downloads, bundle downloads, export downloads, retention dry runs, and legal-hold blocked cleanup.
6. Cutover:
   - Flip `ARTIFACT_STORAGE_BACKEND=s3` for staging first.
   - Run smoke tests and manual download checks.
   - Repeat for production during a maintenance window.
7. Post-cutover hold:
   - Keep local bytes read-only for a defined rollback window.
   - Freeze local cleanup until S3 backups/versioning and restore drills are verified.
8. Cleanup:
   - Remove local bytes only after written approval, successful restore test, and a final inventory match.

Migration tooling requirements:

- Read-only dry-run mode.
- Batch size and resume cursor.
- Per-row status output.
- No deletion by default.
- Strict checksum mismatch failure.
- Audit or operator log artifact for the migration run.

Rollback:

- If DB `storage_key` values are unchanged, rollback is a settings flip back to local as long as local bytes are retained.
- If any future implementation changes keys, rollback requires a mapping table and is materially riskier. Avoid this for Phase E.

## 15. Backup and Recovery Considerations

Durability controls:

- Enable bucket versioning in staging/production.
- Enable server-side encryption.
- Restrict delete permissions to the API role and tightly scoped operator breakglass role.
- Consider cross-region replication after pilot if recovery objectives require it.
- Back up PostgreSQL separately; object bytes without DB metadata are not sufficient to reconstruct authorization, evidence manifests, retention, or audit state.

Recovery scenarios:

- Lost DB, bucket intact: restore DB from backup first; object keys remain valid if restored DB predates object creation, but newer orphaned objects require inventory reconciliation.
- Lost object, DB intact: detect via `head`/checksum audit; restore from object versioning/replica/backups; if sealed evidence cannot be restored, mark storage missing or invalidate through evidence service.
- Accidental object delete: recover current version from bucket versioning if enabled.
- Corrupt object metadata, bytes intact: repair metadata only after byte checksum verifies and operator approval is recorded.
- Region outage: use replicated bucket and deployment-level failover only after signed URL endpoint, IAM, KMS, and DNS behavior are tested.

Restore drills:

- Quarterly or pre-pilot restore drill for a sample artifact, sealed bundle, and export.
- Verify downloaded bytes match DB SHA-256.
- Verify evidence ZIP manifest hash and content hash.
- Verify legal-hold blocked cleanup still blocks after restore.

## 16. Test Strategy

Unit tests:

- Local backend path traversal still fails.
- S3 backend `save`, `head`, `exists`, `size`, `delete`, and signed URL creation with mocked boto3/client.
- S3 backend maps provider failures to safe domain exceptions.
- S3 signed URL TTL is bounded by max TTL.
- S3 upload stores checksum metadata and encryption parameters.
- `local_path` raises or is unavailable in S3 mode.

Artifact service tests:

- Upload writes to injected object backend and creates DB row.
- Storage write failure creates no DB row.
- DB failure after storage write attempts delete.
- Checksum mismatch fails before storage write.
- Post-write size/checksum verification failure fails upload and deletes object if possible.
- Download grant in S3 mode returns signed URL and emits audit event.

Evidence service tests:

- Sealed bundle save uses object backend and verifies content SHA-256.
- Export save uses object backend and verifies content SHA-256.
- Storage verification failure during seal follows existing invalidation behavior.
- Retention cleanup deletes S3 object and preserves metadata.
- Legal hold blocks cleanup before delete call.
- Missing object during cleanup is idempotent only when retention is otherwise allowed.

Migration tests:

- Dry run detects missing local file.
- Dry run detects local checksum mismatch.
- Copy preserves logical key.
- Resume skips already verified matching objects.
- Mismatched destination object fails rather than overwrites silently.

Integration tests:

- Local filesystem mode remains green.
- S3-compatible mode runs against MinIO or a mocked service in CI where practical.
- API download response shape remains compatible.
- Evidence bundle/export download flows work in both local and S3 modes.

Manual pilot gate:

- Runner uploads stdout/stderr and a file artifact.
- UI lists artifacts and downloads via signed URL.
- Sealed evidence bundle includes artifact bytes and downloads via signed URL.
- Evidence export downloads or grants URL according to final Phase E API choice.
- Retention dry run reports eligible objects.
- Legal hold blocks cleanup.
- API/runner/browser credentials are verified: runner and browser have no S3 credentials.

## 17. Rollout Plan

1. Design freeze:
   - Confirm signed URL response shape for artifacts, bundles, and exports.
   - Confirm whether exports switch from streaming to signed URL grants in Phase E.
   - Confirm production encryption mode and KMS key ownership.
2. Implement behind settings:
   - Add S3 backend without changing default local behavior.
   - Add backend tests and mocked S3 service tests.
3. Staging infrastructure:
   - Create private bucket/prefix, IAM role, encryption, versioning, and lifecycle for incomplete multipart uploads.
   - Deploy API with `ARTIFACT_STORAGE_BACKEND=s3`.
4. Staging validation:
   - Upload/download artifacts.
   - Seal/download bundles.
   - Create/download exports.
   - Run retention dry-run and legal-hold tests.
5. Local-to-S3 migration rehearsal:
   - Run inventory, dry run, copy, and verify against staging-like data.
   - Produce migration report artifact.
6. Production preflight:
   - Confirm bucket policy, IAM, KMS, backups, versioning, monitoring, alarms, and rollback window.
   - Freeze local cleanup.
7. Production copy and verify:
   - Copy existing local bytes to S3 preserving keys.
   - Verify all copied objects by size/checksum.
8. Production cutover:
   - Flip backend setting.
   - Run smoke tests for artifact, bundle, export, retention dry run, and legal hold.
9. Observation window:
   - Monitor storage errors, signed URL grants, download failures, upload latency, and cost metrics.
   - Keep local bytes available for rollback.
10. Finalize:
   - Complete restore drill.
   - Remove or archive local bytes only after approval.
   - Document operational runbooks.

## 18. Explicit Non-Goals

Phase E does not include:

- Direct runner-to-S3 uploads.
- Direct browser-to-S3 uploads.
- Long-lived public URLs.
- Public buckets or object ACLs.
- Artifact search, indexing, previews, virus scanning, deduplication, or compression.
- Rewriting sealed evidence ZIPs.
- Changing evidence manifest formats except where download descriptors require API response additions.
- New background workers, queues, or asynchronous retention services.
- General cloud infrastructure deployment beyond storage requirements.
- S3 Object Lock compliance-mode rollout.
- Cross-region disaster recovery automation.
- Customer-managed bucket onboarding.
- A new retention model for ordinary execution artifacts.
- Actual-download audit ingestion from S3 access logs or CloudTrail data events.
- Increasing artifact size limits or implementing multipart uploads, unless a later pilot explicitly requires it.

## Acceptance Criteria

Phase E is ready for implementation when:

- The storage abstraction has a stable backend interface and S3-compatible design.
- Local and S3 behavior are clearly separated.
- Django remains the authorization and audit authority.
- Storage keys are stable and migration preserves existing logical keys.
- Checksums are verified before and after object writes.
- Evidence immutability, retention, and legal holds remain enforceable.
- Required settings, IAM expectations, rollout, rollback, backup, and tests are defined.
- No implementation work is hidden inside this blueprint.
