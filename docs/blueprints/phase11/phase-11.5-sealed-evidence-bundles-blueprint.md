# Phase 11.5: Sealed Evidence Bundles, Redaction, Retention, and Export Blueprint

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 11.5 |
| Phase name | Sealed evidence bundles, redaction, retention, and export |
| Objective | Create deterministic sealed evidence bundles that compile all required `ChangeRecord` evidence, preserve integrity, support redacted exports, and enforce retention/legal hold behavior. |
| Status | Blueprint only - do not implement code from this document without re-reading current source first |
| Depends on | Phases 11.1, 11.2, 11.3, and 11.4 complete and verified; Phases 01-10.9 complete |
| Authored | 2026-05-01 |
| Primary new app | `apps/api/apps/evidence/` |

This document is an implementation blueprint only. It intentionally does not implement code.

## 2. Executive Summary

Phase 11.5 adds the evidentiary core around the completed Phase 11 `ChangeRecord` lifecycle. A sealed evidence bundle is an immutable, deterministic package of the closed change dossier: request snapshot, targets, approvals, policy decisions, execution facts, verification plan and results, closure, exceptions, audit trail, artifacts, external references, and export receipt metadata.

The implementation adds a new Django app:

- `apps/api/apps/evidence/`

It introduces six model families:

- `EvidenceBundle`
- `EvidenceBundleItem`
- `EvidenceRedactionPolicy`
- `EvidenceExport`
- `EvidenceRetentionPolicy`
- `LegalHold`

The core behavior is:

1. A closed `ChangeRecord` can produce a synchronously materialized bundle projection.
2. The projection computes completeness for every required evidence section.
3. A complete projection can be sealed into a deterministic ZIP stored through the existing artifact storage mechanism.
4. Sealed canonical evidence is immutable. Redaction never mutates it.
5. Exports are derived packages with their own hashes, receipts, audit events, and optional redaction policy.
6. Retention cleanup can delete whole stored objects only when no active legal hold applies. Cleanup never rewrites sealed bytes.

This phase does not add workers, queues, batch processors, microservices, new runner architecture, object signing infrastructure, or a new artifact backend. Django request handling remains the control plane, and existing artifact storage remains the byte storage layer.

## 3. Current-State Inspection Checklist

The following repository facts were inspected before writing this blueprint:

- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` defines `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`, operation profiles, request hashes, lifecycle status, change approval linkage, execution binding, and the invariant that Django owns change transitions.
- [x] `docs/blueprints/phase-11.2-windows-freezes-target-locks-blueprint.md` defines `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`, dispatch preflight, target conflict behavior, and window/freeze evidence that must be included in the bundle.
- [x] `docs/blueprints/phase-11.3-verification-closure-blueprint.md` defines `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`, artifact-backed verification, manual attestation, external references, and closure immutability.
- [x] `docs/blueprints/phase-11.4-emergency-exceptions-breakglass-blueprint.md` defines `ChangeException`, `BreakglassSession`, `RetroReview`, emergency metadata, exception scope, breakglass scope, and closure blockers that must be captured as evidence.
- [x] `apps/api/apps/changes/` does not exist in this checkout. Per the task source context, Phase 11.5 implementation must assume Phases 11.1-11.4 are complete, then re-inspect the actual completed app before coding.
- [x] `apps/api/apps/evidence/` does not exist in this checkout and must be created by Phase 11.5.
- [x] `apps/api/apps/artifacts/models.py` defines `Artifact` with stable UUID, organization, execution, optional step, kind, name, MIME type, byte size, SHA-256 checksum, storage key, runner id, upload status, upload timestamp, and metadata.
- [x] `apps/api/apps/artifacts/services.py` validates runner ownership, quota, MIME type, checksum shape, checksum match, storage writes, and emits artifact audit events.
- [x] `apps/api/apps/artifacts/storage.py` provides the existing storage abstraction. Evidence bundles and exports should reuse this storage boundary instead of adding a new backend.
- [x] `apps/api/apps/audit/models.py` defines append-only `AuditEvent` rows and currently has object types for organizations, runbooks, workflows, executions, execution steps, approvals, policies, artifacts, and integrations.
- [x] `apps/api/apps/audit/services.py` scrubs sensitive metadata keys and enforces metadata size. Phase 11.5 must extend this scrubber for evidence, redaction, export, legal hold, retention, manifest, and receipt payloads.
- [x] `apps/api/config/api_v1_urls.py` registers public APIs under `/api/v1/` and runner-only APIs under `/api/v1/internal/`.
- [x] `apps/api/config/settings/base.py` registers current domain apps but not `changes` or `evidence` in this checkout.
- [x] `apps/web/src/features/` contains feature areas for approvals, artifacts, audit, executions, integrations, organizations, policies, runbooks, and workflows, but no `changes` or `evidence` feature area in this checkout.
- [x] `apps/web/src/shared/api/client.ts` blocks browser calls to `/api/v1/internal/` and injects `X-Organization-Id`.

Drift note: this blueprint intentionally refers to the expected completed Phase 11.1-11.4 models. If the actual implementation names, fields, or route layout differ, update this blueprint before coding Phase 11.5.

## 4. Architecture Invariants

| Invariant | Phase 11.5 consequence |
|---|---|
| Django remains the control plane. | Bundle materialization, completeness checks, sealing, invalidation, export creation, redaction, retention, legal hold, and audit emission live in Django services. |
| No async workers, queues, batch processors, or microservices. | Bundle creation, sealing, export creation, and legal hold actions run synchronously inside Django request/service flows. Any cleanup service is explicit and request/management-command driven, not a worker. |
| Use existing artifact storage. | Store sealed bundle ZIPs and export ZIPs through the current artifact storage abstraction or a thin evidence wrapper over it. Do not add a separate storage backend. |
| Canonical sealed evidence is immutable. | Once `EvidenceBundle.status == "sealed"`, the bundle ZIP, manifest, checksums, bundle items, and item content hashes cannot be changed. |
| Redaction is export-specific only. | Redaction policies transform derived export bytes. They never update `EvidenceBundle`, `EvidenceBundleItem`, source `AuditEvent`, source `Artifact`, or source `ChangeRecord` evidence. |
| Do not mutate audit events during export. | Export may append new audit events such as `evidence_export.created` and `evidence_export.downloaded`, but it must never update existing audit rows or reorder/alter the canonical audit trail. |
| Timestamps in manifests are normalized to UTC. | Every datetime serialized into bundle/export JSON uses aware UTC and one canonical string format. |
| Original audit event order is preserved. | `audit/audit_trail.ndjson` uses the source audit ordering and deterministic tie-breakers. Redacted exports preserve the same event order. |
| Determinism is a data contract. | For a fixed bundle row, fixed materialized source snapshot, fixed persisted timestamps, and fixed storage bytes, repeated manifest and ZIP generation must produce byte-identical outputs. |
| Sealing is a one-way transition. | A bundle can move from `compiling` to `sealed` or `invalidated`; a sealed bundle can move only to `invalidated`. No state returns to `compiling`. |
| Invalidation is not deletion. | Invalidated bundles remain immutable historical records and retain their hashes and storage unless retention cleanup later removes stored bytes. |
| Retention cannot override legal hold. | Active legal holds block cleanup of canonical bundles, exports, and staged bundle items covered by the hold. |
| Runner architecture does not change. | The runner continues uploading artifacts through existing internal artifact APIs. Phase 11.5 only requires stable artifact IDs, MIME type, byte size, and checksums. |
| Frontend uses public APIs only. | React evidence UI calls `/api/v1/changes/...`, `/api/v1/evidence-bundles/...`, and `/api/v1/evidence-exports/...`; it never calls runner or internal endpoints. |

## 5. Data Model Design

### 5.1 New Evidence App Structure

Create:

```text
apps/api/apps/evidence/
  __init__.py
  apps.py
  admin.py
  models.py
  selectors.py
  serializers.py
  services.py
  storage.py
  urls.py
  views.py
  migrations/
    __init__.py
  tests/
    __init__.py
    conftest.py
    test_api.py
    test_completeness.py
    test_exports.py
    test_hashing.py
    test_immutability.py
    test_legal_hold.py
    test_materialization.py
    test_models.py
    test_redaction.py
    test_retention.py
```

Recommended module responsibilities:

- `models.py`: persistence, enums, constraints, and sealed-row immutability guards.
- `services.py`: materialization, canonical serialization, hashing, ZIP generation, sealing, invalidation, export creation, redaction, retention, legal hold, and audit emission.
- `selectors.py`: organization-scoped bundle/export/legal-hold querysets.
- `serializers.py`: public API request/response shapes.
- `storage.py`: thin wrapper over `apps.artifacts.storage.ArtifactStorage` for evidence storage keys.
- `views.py`: public endpoints only.
- `urls.py`: public evidence routes exported for inclusion under `/api/v1/`.

### 5.2 Required Enumerations

Bundle statuses:

- `compiling`
- `sealed`
- `invalidated`

Completeness statuses:

- `complete`
- `incomplete`
- `invalid`

Bundle item types:

- `change_snapshot`
- `approval`
- `policy_decision`
- `execution`
- `audit_event`
- `artifact`
- `verification_result`
- `closure`
- `exception`
- `external_reference`
- `export_receipt`

These values must be defined as `models.TextChoices` and enforced with database check constraints. Do not use free-form status strings.

### 5.3 `EvidenceBundle`

`EvidenceBundle` is the versioned bundle aggregate for one `ChangeRecord`.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `change_record` | FK -> `changes.ChangeRecord`, `PROTECT`, related name `evidence_bundles` | Source change. |
| `version` | `PositiveIntegerField` | Monotonic per change. First bundle is `1`. |
| `status` | `CharField(24)` | `compiling`, `sealed`, or `invalidated`. |
| `completeness_status` | `CharField(24)` | `complete`, `incomplete`, or `invalid`. |
| `completeness_report` | `JSONField(default=dict)` | Deterministic checklist by section and canonical path. |
| `source_snapshot_sha256` | `CharField(64, blank=True)` | Hash of source evidence references and item content hashes. |
| `source_cutoff_at` | `DateTimeField` | UTC high-water mark for audit/event collection. Set once during materialization. |
| `source_high_watermark` | `JSONField(default=dict)` | Stable cutoffs such as max audit `(occurred_at, created_at, id)` included. |
| `manifest` | `JSONField(default=dict)` | Stored canonical manifest object after seal. Does not include `manifest_sha256`. |
| `manifest_sha256` | `CharField(64, blank=True)` | SHA-256 of canonical `manifest.json` bytes. |
| `payload_checksums_sha256` | `CharField(64, blank=True)` | SHA-256 of canonical checksum list for payload entries, excluding `manifest.json` and `checksums.sha256`. |
| `content_sha256` | `CharField(64, blank=True)` | SHA-256 of final ZIP bytes. |
| `content_size_bytes` | `PositiveBigIntegerField(null=True, blank=True)` | Final ZIP byte size. |
| `storage_key` | `CharField(1024, blank=True, unique=True)` | Storage key for final sealed ZIP. Blank until sealed. |
| `mime_type` | `CharField(128, default="application/zip")` | Always `application/zip` for sealed package. |
| `compiled_at` | `DateTimeField` | Persisted once. Reused by deterministic generation. |
| `sealed_at` | `DateTimeField(null=True, blank=True)` | Persisted before manifest generation and reused. |
| `invalidated_at` | `DateTimeField(null=True, blank=True)` | Set only by invalidation service. |
| `invalidation_reason` | `CharField(128, blank=True)` | Required when status becomes `invalidated`. |
| `previous_bundle` | FK -> self, nullable, `PROTECT` | Previous version when this bundle supersedes another. |
| `created_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor that requested materialization. |
| `sealed_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor that sealed. |
| `invalidated_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor that invalidated. |
| `retention_policy` | FK -> `EvidenceRetentionPolicy`, nullable, `PROTECT` | Policy resolved at materialization/seal. |
| `retention_expires_at` | `DateTimeField(null=True, blank=True)` | Earliest cleanup time for canonical ZIP when no hold exists. |
| `storage_deleted_at` | `DateTimeField(null=True, blank=True)` | Set only when retention cleanup deletes stored ZIP bytes. |
| `storage_delete_reason` | `CharField(128, blank=True)` | Usually `retention_expired`. |

Recommended constraints and indexes:

- unique `(change_record, version)`;
- index `(organization, change_record, version)`;
- index `(organization, status, created_at)`;
- index `(organization, completeness_status, created_at)`;
- index `(organization, retention_expires_at)`;
- check `status` in `compiling`, `sealed`, `invalidated`;
- check `completeness_status` in `complete`, `incomplete`, `invalid`;
- service invariant: `organization_id == change_record.organization_id`;
- service invariant: `sealed` requires `sealed_at`, `manifest_sha256`, `content_sha256`, `content_size_bytes`, and `storage_key`;
- service invariant: `invalidated` requires `invalidated_at` and `invalidation_reason`;
- service invariant: `storage_deleted_at` cannot be set while an active `LegalHold` covers the bundle.

Immutability rule:

- After status becomes `sealed`, only these metadata fields may change: `status` to `invalidated`, invalidation fields, legal-hold-independent retention metadata such as `storage_deleted_at`, and audit-neutral download counters if explicitly added. Manifest fields, content hashes, bundle item rows, canonical paths, and storage key must not change.

### 5.4 `EvidenceBundleItem`

`EvidenceBundleItem` records each logical evidence item and each canonical file entry that contributes to the bundle.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `bundle` | FK -> `EvidenceBundle`, `CASCADE`, related name `items` | Parent bundle. `CASCADE` is acceptable only before seal; services must block deletion after seal. |
| `item_type` | `CharField(32)` | One of the required item types. |
| `item_key` | `CharField(255)` | Stable key within item type, such as approval id, artifact id, or section key. |
| `canonical_path` | `CharField(512)` | ZIP path or containing path for logical embedded items. |
| `json_pointer` | `CharField(512, blank=True)` | Optional pointer when the item is embedded in a canonical JSON file. |
| `position` | `PositiveIntegerField(default=0)` | Deterministic order within type/path. |
| `required` | `BooleanField(default=True)` | Whether missing/invalid item blocks completeness. |
| `present` | `BooleanField(default=True)` | False for expected but missing required evidence. |
| `valid` | `BooleanField(default=True)` | False for corrupt/cross-org/checksum-invalid evidence. |
| `missing_reason` | `CharField(128, blank=True)` | Structured code for missing items. |
| `validation_errors` | `JSONField(default=list)` | Structured validation errors. |
| `source_type` | `CharField(128, blank=True)` | Example: `changes.ChangeClosure`, `audit.AuditEvent`, `artifacts.Artifact`. |
| `source_id` | `CharField(128, blank=True)` | Source primary key as lowercase string. Supports UUID and non-UUID future sources. |
| `source_updated_at` | `DateTimeField(null=True, blank=True)` | Source row `updated_at` when available. |
| `source_metadata` | `JSONField(default=dict)` | IDs, statuses, counts, and safe source descriptors only. |
| `artifact` | FK -> `artifacts.Artifact`, nullable, `PROTECT` | Required for artifact file items. |
| `staging_storage_key` | `CharField(1024, blank=True)` | Optional frozen materialized bytes before sealing. |
| `content_sha256` | `CharField(64, blank=True)` | SHA-256 of canonical bytes for this item/file. |
| `content_size_bytes` | `PositiveBigIntegerField(null=True, blank=True)` | Canonical byte size. |
| `mime_type` | `CharField(128, blank=True)` | `application/json`, `application/x-ndjson`, artifact MIME type, or `text/plain`. |

Recommended constraints and indexes:

- unique `(bundle, item_type, item_key)`;
- unique `(bundle, canonical_path, json_pointer, item_key)`;
- index `(organization, item_type)`;
- index `(bundle, item_type, position)`;
- index `(artifact)`;
- check `item_type` in the required item type values;
- service invariant: `organization_id == bundle.organization_id`;
- service invariant: artifact item `organization_id == artifact.organization_id`;
- service invariant: item rows cannot be inserted, updated, or deleted once the parent bundle is sealed.

Logical items such as `external_reference` may point at a containing canonical path plus `json_pointer` instead of creating an extra ZIP file. This preserves the fixed ZIP layout while still making external references queryable and testable.

### 5.5 `EvidenceRedactionPolicy`

`EvidenceRedactionPolicy` defines deterministic transformations for derived exports. It does not apply to canonical bundles.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `name` | `CharField(255)` | Human-readable name. |
| `description` | `TextField(blank=True)` | Policy context. |
| `is_active` | `BooleanField(default=True)` | Inactive policies cannot be used for new exports. |
| `is_default` | `BooleanField(default=False)` | Optional default redaction policy per organization. |
| `rules` | `JSONField(default=list)` | Ordered rule list. Canonicalized for hashing before export. |
| `rules_sha256` | `CharField(64)` | SHA-256 of canonical rules JSON. |
| `created_by` | FK -> `users.User`, nullable, `SET_NULL` | Creator. |
| `updated_by` | FK -> `users.User`, nullable, `SET_NULL` | Last updater. |

Recommended rule actions:

- `redact_json_pointer`: replace a JSON value at a canonical JSON pointer with the constant string `[REDACTED]`.
- `redact_ndjson_field`: replace a field in every NDJSON audit event with `[REDACTED]`.
- `omit_path`: omit a canonical path from the export and record an omission entry in the export manifest.
- `artifact_metadata_only`: omit artifact bytes but keep artifact index metadata and checksums.
- `replace_file_with_notice`: replace a file with a deterministic UTF-8 notice that includes source path, source SHA-256, policy id, and rule id.

Rules must not store secret replacement values. The only v1 replacement value should be `[REDACTED]` unless a later phase introduces approved tokenization.

Recommended constraints:

- unique `(organization, name)`;
- partial unique `(organization)` where `is_default=true`;
- service invariant: `rules_sha256` is recomputed from canonical JSON and cannot be client-supplied;
- service invariant: inactive policies cannot be selected for new exports.

### 5.6 `EvidenceExport`

`EvidenceExport` records one derived export package from a sealed bundle.

Recommended status values:

- `creating`
- `ready`
- `failed`
- `expired`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `bundle` | FK -> `EvidenceBundle`, `PROTECT`, related name `exports` | Source sealed bundle. |
| `redaction_policy` | FK -> `EvidenceRedactionPolicy`, nullable, `PROTECT` | Null means no redaction. |
| `status` | `CharField(24)` | `creating`, `ready`, `failed`, or `expired`. |
| `requested_by` | FK -> `users.User`, nullable, `SET_NULL` | Export requester. |
| `requested_at` | `DateTimeField` | Persisted before export receipt generation. |
| `ready_at` | `DateTimeField(null=True, blank=True)` | Set when ZIP is stored. |
| `expires_at` | `DateTimeField(null=True, blank=True)` | Export retention deadline. |
| `storage_key` | `CharField(1024, blank=True, unique=True)` | Stored export ZIP. |
| `content_sha256` | `CharField(64, blank=True)` | SHA-256 of export ZIP bytes. |
| `content_size_bytes` | `PositiveBigIntegerField(null=True, blank=True)` | Export ZIP byte size. |
| `manifest` | `JSONField(default=dict)` | Export manifest object. |
| `manifest_sha256` | `CharField(64, blank=True)` | SHA-256 of export `manifest.json` bytes. |
| `source_manifest_sha256` | `CharField(64)` | Copied from source bundle. |
| `source_bundle_content_sha256` | `CharField(64)` | Copied from source bundle. |
| `redaction_summary` | `JSONField(default=dict)` | Counts, rule ids, omitted paths, and transformed paths. No raw redacted values. |
| `receipt` | `JSONField(default=dict)` | `exports/export_receipt.json` object. |
| `receipt_sha256` | `CharField(64, blank=True)` | SHA-256 of canonical receipt bytes. |
| `failure_code` | `CharField(128, blank=True)` | Structured failure code. |
| `failure_message` | `TextField(blank=True)` | Safe error summary. |
| `download_count` | `PositiveIntegerField(default=0)` | Optional operational counter. |
| `last_downloaded_at` | `DateTimeField(null=True, blank=True)` | Optional audit-adjacent metadata. |
| `storage_deleted_at` | `DateTimeField(null=True, blank=True)` | Set only by retention cleanup. |

Recommended constraints and indexes:

- index `(organization, status, requested_at)`;
- index `(bundle, requested_at)`;
- index `(organization, expires_at)`;
- check `status` in `creating`, `ready`, `failed`, `expired`;
- service invariant: exports require `bundle.status == "sealed"` and source bundle storage must exist;
- service invariant: ready exports require `storage_key`, `content_sha256`, `content_size_bytes`, `manifest_sha256`, and `receipt_sha256`;
- service invariant: export ZIP bytes are immutable once `status == "ready"`;
- service invariant: `storage_deleted_at` cannot be set while an active legal hold covers the source change or bundle.

### 5.7 `EvidenceRetentionPolicy`

`EvidenceRetentionPolicy` defines organization-scoped retention periods for bundles and exports.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `name` | `CharField(255)` | Human-readable name. |
| `description` | `TextField(blank=True)` | Policy context. |
| `is_active` | `BooleanField(default=True)` | Inactive policies are not selected for new bundles. |
| `is_default` | `BooleanField(default=False)` | Default per organization. |
| `sealed_bundle_retention_days` | `PositiveIntegerField` | Retention for sealed canonical bundle bytes. |
| `invalidated_bundle_retention_days` | `PositiveIntegerField` | Retention for invalidated bundle bytes. Usually no shorter than audit policy requires. |
| `export_retention_days` | `PositiveIntegerField` | Retention for derived export ZIP bytes. |
| `cleanup_action` | `CharField(64, default="delete_content_keep_metadata")` | Only supported v1 action. |
| `created_by` | FK -> `users.User`, nullable, `SET_NULL` | Creator. |
| `updated_by` | FK -> `users.User`, nullable, `SET_NULL` | Last updater. |

Recommended constraints:

- partial unique `(organization)` where `is_default=true`;
- check retention days are greater than zero;
- check `cleanup_action == "delete_content_keep_metadata"` for v1;
- service invariant: a default policy must exist before sealing in production environments, or settings must provide a safe fallback.

### 5.8 `LegalHold`

`LegalHold` records retention override authority for a change, bundle, or export.

Recommended status values:

- `active`
- `released`

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `change_record` | FK -> `changes.ChangeRecord`, `PROTECT`, related name `legal_holds` | Required. A hold on a bundle also covers the change. |
| `evidence_bundle` | FK -> `EvidenceBundle`, nullable, `PROTECT`, related name `legal_holds` | Optional narrower hold. |
| `evidence_export` | FK -> `EvidenceExport`, nullable, `PROTECT`, related name `legal_holds` | Optional export-specific hold. |
| `status` | `CharField(24)` | `active` or `released`. |
| `reason` | `TextField` | Required legal/business reason; size-limited. |
| `external_reference` | `CharField(512, blank=True)` | Ticket, matter id, or legal case reference. |
| `placed_by` | FK -> `users.User`, nullable, `SET_NULL`, related name distinct | Actor placing hold. |
| `placed_at` | `DateTimeField` | Service timestamp. |
| `released_by` | FK -> `users.User`, nullable, `SET_NULL`, related name distinct | Actor releasing hold. |
| `released_at` | `DateTimeField(null=True, blank=True)` | Set on release. |
| `release_reason` | `TextField(blank=True)` | Required on release. |

Recommended constraints and indexes:

- index `(organization, status, placed_at)`;
- index `(change_record, status)`;
- index `(evidence_bundle, status)`;
- index `(evidence_export, status)`;
- check `status` in `active`, `released`;
- service invariant: all referenced rows must belong to the same organization and change;
- service invariant: release requires `released_by`, `released_at`, and nonblank `release_reason`;
- service invariant: active holds block retention cleanup of all covered stored bytes.

## 6. Evidence Materialization Design

### 6.1 Synchronous Projection Strategy

`POST /api/v1/changes/{id}/evidence-bundles/` creates or returns an `EvidenceBundle` projection synchronously. `status="compiling"` means the canonical projection exists and can be checked/sealed; it does not imply background work.

Materialization sequence:

1. Require JWT authentication, `X-Organization-Id`, and organization operator/admin role.
2. Lock the `ChangeRecord` row with `select_for_update()` and verify the change is closed.
3. Resolve the latest previous bundle for the change.
4. Persist a new `EvidenceBundle(status="compiling")` with `version=max(version)+1`, `compiled_at`, and `source_cutoff_at`.
5. Query all required source rows using organization-scoped selectors.
6. Serialize each section into canonical bytes.
7. Compute item-level `content_sha256` and `content_size_bytes`.
8. Create `EvidenceBundleItem` rows for required, optional, present, missing, and invalid items.
9. Compute `source_snapshot_sha256` from item metadata and content hashes.
10. Compute `completeness_report` and `completeness_status`.
11. Emit audit events after the projection row is durable.

Do not include the audit event emitted for bundle creation inside the bundle being created. Use the persisted `source_cutoff_at` and high-watermark fields to define which audit rows are in scope.

### 6.2 Source Evidence Sections

The bundle must gather evidence from the completed Phase 11 data model:

| Section | Source records | Canonical path |
|---|---|---|
| Change snapshot | `ChangeRecord` immutable request snapshot, status, profile/workflow snapshots, schedule metadata, request hashes | `change/change_record.json` |
| Targets | `ChangeTarget`, target lock summary, normalized target identifiers | `change/targets.json` |
| Approvals | Change approvals, exception approvals, approval decisions, approver identity labels | `controls/approvals.json` |
| Policy decisions | Change policy snapshot, `PolicyEvaluation`, dispatch/preflight policy checks, approved overrides | `controls/policy_decisions.json` |
| Execution | `ChangeExecutionBinding`, `Execution`, `ExecutionStep`, runner timing facts, final status | `execution/execution.json` |
| Verification plan | `VerificationPlan`, `VerificationCheck` | `verification/plan.json` |
| Verification results | `VerificationResult`, accepted/rejected evidence attempts, artifact links, manual attestations, external references | `verification/results.json` |
| Audit trail | `AuditEvent` rows for the change and related objects up to the bundle cutoff | `audit/audit_trail.ndjson` |
| Artifacts index | Available `Artifact` rows linked to bound execution and verification evidence | `artifacts/index.json` |
| Artifact bytes | Existing artifact storage bytes copied into the ZIP | `artifacts/...` |
| Exceptions | `ChangeException`, `BreakglassSession`, `RetroReview`, emergency fields, closure blockers | `exceptions/exceptions.json` |
| Export receipt | Canonical bundle receipt placeholder or derived export receipt | `exports/export_receipt.json` |

### 6.3 Canonical ZIP Layout

Every sealed canonical bundle ZIP must include these paths:

```text
manifest.json
checksums.sha256
change/change_record.json
change/targets.json
controls/approvals.json
controls/policy_decisions.json
execution/execution.json
verification/plan.json
verification/results.json
audit/audit_trail.ndjson
artifacts/index.json
artifacts/...
exceptions/exceptions.json
exports/export_receipt.json
```

Rules:

- The listed JSON/NDJSON files are always present, even when their arrays are empty.
- `artifacts/...` entries are present only for included artifact bytes. `artifacts/index.json` is always present.
- Artifact file paths must be deterministic: `artifacts/files/{artifact_id}/{safe_name}`.
- `safe_name` must use the existing artifact-safe filename rules or a stricter evidence-specific equivalent.
- If two artifact names collide under the same artifact id, the artifact id path segment still keeps paths unique.
- No absolute paths, `..`, backslashes, control characters, or platform-specific path separators are allowed in ZIP entry names.
- Canonical sealed bundle `exports/export_receipt.json` uses `receipt_type="sealed_bundle"` and `export_id=null`.
- Derived export ZIPs use the same path for `receipt_type="evidence_export"` and include the actual `EvidenceExport.id`.

### 6.4 Canonical Section Contents

Each JSON file must have a stable top-level shape with schema version and arrays sorted deterministically.

Recommended top-level JSON shape:

```json
{
  "schema_version": "1",
  "organization_id": "...",
  "change_record_id": "...",
  "bundle_id": "...",
  "bundle_version": 1,
  "generated_at": "2026-05-01T00:00:00.000000Z",
  "items": []
}
```

Section-specific rules:

- `change/change_record.json` includes request hashes, profile/workflow snapshots, lifecycle timestamps, closure status, emergency flags, and source row ids. It must not include dispatch token cleartext, claim token, raw secret inputs, raw command output, or unsanitized request bodies.
- `change/targets.json` includes target ids, target types, normalized identifiers, target lock history, conflict summaries, and freeze/window evidence relevant to dispatch.
- `controls/approvals.json` includes approval requests and decisions in chronological order with stable ids and actor labels. Notes may be included only if the approval service already treats them as safe evidence; otherwise include note hashes and redaction-ready summaries.
- `controls/policy_decisions.json` includes policy ids, rule ids, outcomes, effective outcomes, condition snapshots, override exception ids, and evaluation timestamps.
- `execution/execution.json` includes execution id, workflow version, execution status, runner id, step statuses, started/finished timestamps, exit codes, and bounded error codes/messages. It must not include raw command text if command text is considered sensitive by the audit scrubber.
- `verification/plan.json` includes plan/check ids, check keys, types, required flags, expected artifact constraints, status, and generated profile hash.
- `verification/results.json` includes result ids, check ids, outcomes, validation status, source, artifact ids/checksums, external references, manual attestation metadata, and validation errors. It must not include raw API responses, credentials, bearer tokens, or secret request payloads.
- `exceptions/exceptions.json` includes exception ids/types/statuses, approved scope hashes, breakglass scope hashes, retro-review dispositions, review due timestamps, remediation references, and closure blockers. It must not include raw privilege credentials or unsanitized scope payloads.
- `artifacts/index.json` includes artifact id, execution id, step id, kind, name, MIME type, byte size, SHA-256, upload timestamp, runner id, bundle path, and inclusion/redaction eligibility.
- `exports/export_receipt.json` in a sealed bundle records only the sealing receipt. Export-specific receipts live in derived export ZIPs and `EvidenceExport.receipt`.

### 6.5 Artifact Byte Handling

Runner artifacts are source evidence. Phase 11.5 must not change runner upload architecture.

Requirements:

- Every included artifact must have stable `Artifact.id`.
- Every included artifact must have nonblank `mime_type`.
- Every included artifact must have `size_bytes`.
- Every included artifact must have a lowercase 64-character `checksum_sha256`.
- Before sealing, read artifact bytes from existing storage and recompute SHA-256.
- If recomputed checksum differs from `Artifact.checksum_sha256`, mark the bundle `completeness_status="invalid"` and do not seal.
- If artifact storage bytes are missing for a required artifact, mark `incomplete`.
- If artifact storage bytes are missing for an optional artifact, include a missing optional entry in `artifacts/index.json` and completeness may remain `complete`.
- Copy artifact bytes into the ZIP. The sealed bundle must remain self-contained and not depend on future artifact storage availability.

## 7. Deterministic Manifest Design

### 7.1 Canonical Serialization

Implement a single canonical serialization helper and use it everywhere evidence hashes are computed.

JSON canonicalization:

- Encode as UTF-8.
- Sort object keys lexicographically.
- Use separators `(",", ":")`.
- Include documented nullable fields with `null` instead of omitting them when the schema defines the field.
- Normalize UUIDs to lowercase strings.
- Normalize datetimes to UTC strings in the format `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- Normalize decimals as strings, not floats.
- Sort arrays by explicit stable keys, never by database default ordering unless that ordering is part of the source evidence contract.
- Reject non-JSON values instead of stringifying them silently.

NDJSON canonicalization:

- One canonical JSON object per source audit event.
- Lines are joined with `\n`.
- A non-empty NDJSON file ends with exactly one trailing `\n`.
- An empty NDJSON file is zero bytes.
- Do not pretty-print.
- Preserve audit order using the source audit sequence if Phase 11.1-11.4 adds one. If no sequence exists, order by `(occurred_at ASC, created_at ASC, id ASC)`.

ZIP canonicalization:

- Use `ZIP_STORED` in v1 to avoid compression-library nondeterminism.
- Add entries in lexicographic path order.
- Use fixed ZIP entry timestamps, recommended `1980-01-01T00:00:00` because it is the ZIP minimum.
- Use fixed file permissions, recommended regular file `0644`.
- Use no archive comments and no per-file comments.
- Use forward slashes only.

### 7.2 Manifest Object

`manifest.json` is the root integrity document for the package. It must not include its own SHA-256.

Recommended manifest shape:

```json
{
  "manifest_schema_version": "1",
  "package_type": "sealed_bundle",
  "bundle": {
    "id": "...",
    "version": 1,
    "status": "sealed",
    "completeness_status": "complete",
    "compiled_at": "2026-05-01T00:00:00.000000Z",
    "sealed_at": "2026-05-01T00:00:00.000000Z"
  },
  "change": {
    "id": "...",
    "status": "closed",
    "request_snapshot_sha256": "...",
    "requested_inputs_sha256": "..."
  },
  "source": {
    "source_snapshot_sha256": "...",
    "source_cutoff_at": "2026-05-01T00:00:00.000000Z",
    "source_high_watermark": {}
  },
  "algorithms": {
    "content_hash": "sha256",
    "manifest_hash": "sha256",
    "zip_method": "zip-stored"
  },
  "entries": []
}
```

Each `entries[]` object must include:

- `path`;
- `item_type`;
- `media_type`;
- `size_bytes`;
- `sha256`;
- `required`;
- `source_refs`;
- `redaction_state` for exports only.

Entries are sorted by `path`, then `item_type`, then `item_key`.

### 7.3 SHA-256 Behavior

Use SHA-256 in four distinct places:

| Hash | Stored on | Input bytes | Purpose |
|---|---|---|---|
| Item content SHA-256 | `EvidenceBundleItem.content_sha256` | Canonical file bytes or artifact bytes for that item | Proves section/artifact content. |
| Manifest SHA-256 | `EvidenceBundle.manifest_sha256`, `EvidenceExport.manifest_sha256` | Canonical `manifest.json` bytes, excluding `manifest_sha256` | Proves manifest integrity. |
| Payload checksums SHA-256 | `EvidenceBundle.payload_checksums_sha256` | Canonical `checksums.sha256` lines for payload entries, excluding `manifest.json` and `checksums.sha256` | Detects path/hash list drift. |
| Package content SHA-256 | `EvidenceBundle.content_sha256`, `EvidenceExport.content_sha256` | Final ZIP bytes | Proves downloadable package bytes. |

`checksums.sha256` line format:

```text
{sha256_hex}  {path}\n
```

Rules:

- Lines are sorted lexicographically by path.
- Include `manifest.json`.
- Include every payload file.
- Exclude `checksums.sha256` because a file cannot contain its own final checksum without recursion.
- Use lowercase hex.
- Use LF line endings only.

### 7.4 Determinism Test Contract

Tests must prove:

- canonical JSON bytes are identical for semantically identical dictionaries with different insertion order;
- UTC timestamp normalization is stable for equivalent aware datetimes;
- audit NDJSON preserves source event order;
- repeated manifest generation for the same persisted bundle row produces the same `manifest_sha256`;
- repeated ZIP generation for the same persisted bundle row produces the same `content_sha256`;
- `checksums.sha256` changes when any payload file byte changes;
- export redaction transforms are deterministic for the same source bundle, policy hash, and export row timestamps.

## 8. Sealing and Invalidation Design

### 8.1 State Transitions

Allowed transitions:

| From | To | Trigger |
|---|---|---|
| none | `compiling` | Bundle materialization request. |
| `compiling` | `sealed` | Seal request succeeds and completeness is `complete`. |
| `compiling` | `invalidated` | Source projection is abandoned or superseded before seal. |
| `sealed` | `invalidated` | Source evidence changed after seal or an authorized actor explicitly invalidates due to evidence defect. |
| `invalidated` | none | Terminal for that bundle version. |

Do not add `deleted`, `draft`, `ready`, or `failed` statuses to `EvidenceBundle` in Phase 11.5. Use `completeness_status`, `validation_errors`, and retention metadata instead.

### 8.2 Seal Service

`seal_bundle(bundle, actor)` should:

1. Require `bundle.status == "compiling"`.
2. Lock the bundle and item rows.
3. Require `bundle.completeness_status == "complete"`.
4. Verify there are no missing required items and no invalid items.
5. Re-read staged canonical files and source artifact bytes.
6. Recompute every item SHA-256 and byte size.
7. Persist `sealed_at` before manifest generation.
8. Generate `manifest.json`.
9. Generate `checksums.sha256`.
10. Generate deterministic ZIP bytes.
11. Compute `manifest_sha256`, `payload_checksums_sha256`, `content_sha256`, and `content_size_bytes`.
12. Save ZIP bytes through evidence storage using a deterministic storage key.
13. Update the bundle to `sealed` in a transaction.
14. On database failure after storage write, attempt storage delete and re-raise.
15. Emit `evidence_bundle.sealed` audit event after commit.

Recommended storage key:

```text
evidence/org/{organization_id}/change/{change_record_id}/bundle/{bundle_id}/v{version}/sealed.zip
```

### 8.3 Immutable Sealed Bundle Rules

After sealing:

- no item rows may be added;
- no item rows may be updated;
- no item rows may be deleted;
- `manifest`, `manifest_sha256`, `payload_checksums_sha256`, `content_sha256`, `content_size_bytes`, and `storage_key` cannot change;
- source artifact changes do not affect the sealed copy;
- source audit events appended after `source_cutoff_at` do not alter the sealed audit trail;
- exports do not alter the sealed bundle or its receipt file;
- retention cleanup may delete the whole stored ZIP only when allowed by policy and no legal hold applies, while retaining metadata and hashes.

Enforce with service guards and tests. A model-level `save()` guard is recommended for sealed rows because admin or accidental ORM updates are high-risk here.

### 8.4 Invalidation and Versioning Rules

Invalidation records that a sealed or compiling bundle should not be treated as current evidence. It does not rewrite history.

Invalidation triggers:

- material source evidence changed after seal, such as a new closure record version or corrected exception/retro-review evidence;
- an artifact included in a compiling bundle failed checksum validation before seal;
- an authorized operator/admin explicitly invalidates due to a documented evidence defect;
- a newer bundle version supersedes an older incomplete compiling projection.

Rules:

- Invalidating a sealed bundle must not delete its ZIP.
- Invalidating a bundle must emit `evidence_bundle.invalidated` with reason, previous status, bundle version, and actor.
- Creating a new bundle version after invalidation uses `version=max(existing versions)+1`.
- `GET /api/v1/changes/{id}/evidence-bundles/latest/` returns the highest version non-invalidated bundle if one exists; otherwise the highest version invalidated bundle with `is_current=false` metadata.
- If a latest sealed bundle has the same `source_snapshot_sha256` as the current source projection, a create request should return the existing sealed bundle instead of creating a duplicate version.
- If the source projection differs from the latest sealed bundle, create a new `compiling` bundle. Do not silently mutate the old sealed bundle.

## 9. Redaction Design

### 9.1 Export-Only Redaction

Redaction applies only during `EvidenceExport` creation.

Hard rules:

- Do not update canonical bundle ZIP bytes.
- Do not update `EvidenceBundleItem` rows.
- Do not update source `AuditEvent` rows.
- Do not update source `Artifact` rows.
- Do not overwrite source artifacts.
- Do not store raw redacted values in `EvidenceExport.redaction_summary`, audit metadata, logs, or exception messages.

### 9.2 Redaction Pipeline

`create_export(bundle, redaction_policy, actor)` should:

1. Require `bundle.status == "sealed"`.
2. Require bundle storage exists and `sha256(zip_bytes) == bundle.content_sha256`.
3. Create `EvidenceExport(status="creating")` with persisted `requested_at`.
4. Load source ZIP entries.
5. Apply redaction rules to an in-memory derived entry set.
6. Preserve canonical paths unless a rule explicitly omits or replaces a path.
7. Preserve audit NDJSON event order.
8. Generate an export receipt.
9. Generate an export manifest with source hashes and redaction summary.
10. Generate export `checksums.sha256`.
11. Generate deterministic export ZIP bytes.
12. Store export ZIP through evidence storage.
13. Update `EvidenceExport(status="ready")` with hashes and sizes.
14. Emit `evidence_export.created` audit event after commit.

Recommended export storage key:

```text
evidence/org/{organization_id}/change/{change_record_id}/bundle/{bundle_id}/exports/{export_id}/export.zip
```

### 9.3 Audit Trail Redaction

Audit redaction must preserve the evidentiary sequence.

Rules:

- Do not remove audit events by default.
- Redact only configured fields or values in the derived NDJSON line.
- Preserve event id, event type, object type, object id, organization id, and timestamps unless a policy explicitly redacts actor fields.
- If a policy omits an event, replace it with a deterministic tombstone object that keeps original event id, original event type, original timestamp, and redaction rule id.
- Keep line count stable unless the policy is explicitly `omit_path` for the entire audit file.
- Record redaction counts in export manifest.

### 9.4 Artifact Redaction

Artifact byte redaction is intentionally limited in v1.

Allowed v1 behavior:

- include original artifact bytes;
- omit artifact bytes and retain metadata/checksum in `artifacts/index.json`;
- replace artifact bytes with a deterministic UTF-8 notice file.

Do not implement partial binary or text artifact rewriting in Phase 11.5 unless a safe parser and format-specific canonicalizer already exists. Partial artifact rewriting is easy to make nondeterministic and should be a later phase.

### 9.5 Export Receipt

Derived export `exports/export_receipt.json` should include:

- `receipt_schema_version`;
- `receipt_type="evidence_export"`;
- `export_id`;
- `bundle_id`;
- `bundle_version`;
- `change_record_id`;
- `organization_id`;
- `requested_by_user_id`;
- `requested_at`;
- `source_manifest_sha256`;
- `source_bundle_content_sha256`;
- `redaction_policy_id`;
- `redaction_policy_sha256`;
- `redaction_summary`;
- `export_manifest_sha256`;
- `export_content_sha256` if known at receipt-finalization time, otherwise omit and rely on model/API response.

Avoid recursive receipt hashing. If `export_content_sha256` is included inside the ZIP before the ZIP hash is known, determinism becomes impossible. Recommended v1 behavior: omit `export_content_sha256` from the receipt file and return/store it on `EvidenceExport`.

## 10. Retention and Legal Hold Design

### 10.1 Retention Policy Evaluation

Resolve retention policy when a bundle is materialized and again when sealed if policy changed before seal.

Recommended behavior:

- sealed bundle retention starts at `sealed_at`;
- invalidated bundle retention starts at `invalidated_at` if present, otherwise `sealed_at`;
- export retention starts at `ready_at`;
- legal hold overrides all cleanup eligibility;
- retention cleanup deletes stored ZIP bytes but keeps database rows, hashes, audit history, and legal hold history.

### 10.2 Cleanup Without Workers

No background cleanup worker is allowed in Phase 11.5.

Provide service functions that tests and future admin/management surfaces can call explicitly:

- `cleanup_expired_bundle_storage(bundle, actor, now=None)`;
- `cleanup_expired_export_storage(export, actor, now=None)`;
- `assert_no_active_legal_hold(change_record, bundle=None, export=None)`;

Cleanup service rules:

1. Lock the bundle/export row.
2. Check retention deadline.
3. Check no active legal hold covers the change, bundle, or export.
4. Verify storage exists.
5. Delete the whole stored ZIP object.
6. Set `storage_deleted_at` and safe reason metadata.
7. Emit audit event.

If a legal hold exists, raise a structured error such as `legal_hold_blocks_cleanup` and do not delete bytes.

### 10.3 Legal Hold Behavior

`POST /api/v1/evidence-bundles/{id}/legal-hold/` creates an active hold covering at least that bundle and its change.

Rules:

- Active hold blocks cleanup of the bundle ZIP.
- Active hold blocks cleanup of exports derived from the held bundle.
- Active hold blocks cleanup of staged materialized item bytes if any still exist.
- Active hold does not block creating exports.
- Active hold does not mutate sealed evidence.
- Active hold itself is not included retroactively in already sealed bundles.
- A later bundle version should include legal hold facts only if legal hold records are part of the requested source evidence scope at that time.

Legal hold audit events:

- `legal_hold.created`;
- `legal_hold.released`;
- `evidence.retention_cleanup_blocked`.

### 10.4 Retention Audit Events

Recommended evidence audit object types:

- `evidence_bundle`;
- `evidence_bundle_item`;
- `evidence_redaction_policy`;
- `evidence_export`;
- `evidence_retention_policy`;
- `legal_hold`.

Recommended audit events:

| Event | Object type | Metadata |
|---|---|---|
| `evidence_bundle.materialized` | `evidence_bundle` | change id, version, completeness status, item counts, source snapshot hash |
| `evidence_bundle.sealed` | `evidence_bundle` | change id, version, manifest hash, content hash, size |
| `evidence_bundle.invalidated` | `evidence_bundle` | change id, version, reason, previous status |
| `evidence_export.created` | `evidence_export` | bundle id, policy id, source manifest hash, export content hash, redaction counts |
| `evidence_export.downloaded` | `evidence_export` | bundle id, export id, actor id, content hash |
| `evidence_bundle.retention_deleted` | `evidence_bundle` | bundle id, content hash, retention policy id |
| `evidence_export.retention_deleted` | `evidence_export` | export id, content hash, retention policy id |
| `legal_hold.created` | `legal_hold` | change id, bundle id, external reference hash or safe reference |
| `legal_hold.released` | `legal_hold` | hold id, release reason |
| `evidence.retention_cleanup_blocked` | `legal_hold` | hold id, target type, target id |

Extend audit metadata scrubbing for:

- `manifest`;
- `manifest_json`;
- `raw_manifest`;
- `checksums`;
- `zip_bytes`;
- `bundle_bytes`;
- `export_bytes`;
- `redacted_value`;
- `original_value`;
- `redaction_payload`;
- `receipt_payload`;
- `legal_hold_reason_raw`;
- `external_reference_raw`;
- `artifact_bytes`.

## 11. Export API Design

All public endpoints require JWT authentication, `X-Organization-Id`, and organization membership. State-changing endpoints require operator/admin unless the existing Phase 11 permission model is stricter.

### 11.1 `POST /api/v1/changes/{id}/evidence-bundles/`

Materialize a bundle projection for a closed change.

Request body:

```json
{
  "force_new_version": false
}
```

Response `201 Created` when a new bundle is created, or `200 OK` when the latest sealed bundle already matches the current source snapshot:

```json
{
  "id": "...",
  "change_record_id": "...",
  "version": 1,
  "status": "compiling",
  "completeness_status": "complete",
  "source_snapshot_sha256": "...",
  "completeness_report": {},
  "created_at": "2026-05-01T00:00:00.000000Z"
}
```

Errors:

- `400 change_not_closed`;
- `400 evidence_source_invalid`;
- `403 insufficient_role`;
- `404 change_not_found`;
- `409 compiling_bundle_exists` if a compiling bundle already exists and `force_new_version=false`;
- `409 latest_bundle_current` if caller requests force behavior not allowed by policy.

### 11.2 `GET /api/v1/changes/{id}/evidence-bundles/latest/`

Return latest bundle summary and completeness checklist.

Response:

```json
{
  "id": "...",
  "version": 2,
  "status": "sealed",
  "is_current": true,
  "completeness_status": "complete",
  "manifest_sha256": "...",
  "content_sha256": "...",
  "content_size_bytes": 12345,
  "sealed_at": "2026-05-01T00:00:00.000000Z",
  "retention_expires_at": "2033-05-01T00:00:00.000000Z",
  "legal_hold_active": false,
  "completeness_report": {}
}
```

Return `404` if no bundle exists for the change.

### 11.3 `POST /api/v1/evidence-bundles/{id}/seal/`

Seal a complete compiling bundle.

Request body:

```json
{}
```

Response:

```json
{
  "id": "...",
  "status": "sealed",
  "completeness_status": "complete",
  "manifest_sha256": "...",
  "payload_checksums_sha256": "...",
  "content_sha256": "...",
  "content_size_bytes": 12345,
  "sealed_at": "2026-05-01T00:00:00.000000Z"
}
```

Errors:

- `400 bundle_not_complete`;
- `400 bundle_invalid`;
- `404 bundle_not_found`;
- `409 bundle_already_sealed`;
- `409 bundle_invalidated`;
- `409 artifact_checksum_mismatch`;
- `409 artifact_missing`.

### 11.4 `POST /api/v1/evidence-bundles/{id}/exports/`

Create a derived export ZIP.

Request body:

```json
{
  "redaction_policy_id": "optional-uuid-or-null"
}
```

Response `201 Created`:

```json
{
  "id": "...",
  "bundle_id": "...",
  "status": "ready",
  "redaction_policy_id": "...",
  "source_manifest_sha256": "...",
  "manifest_sha256": "...",
  "content_sha256": "...",
  "content_size_bytes": 12345,
  "receipt_sha256": "...",
  "expires_at": "2026-06-01T00:00:00.000000Z",
  "redaction_summary": {}
}
```

Errors:

- `400 redaction_policy_inactive`;
- `400 redaction_policy_invalid`;
- `404 bundle_not_found`;
- `404 redaction_policy_not_found`;
- `409 bundle_not_sealed`;
- `409 bundle_storage_missing`;
- `409 bundle_checksum_mismatch`;
- `409 retention_storage_deleted`.

### 11.5 `GET /api/v1/evidence-exports/{id}/download/`

Download a ready export.

Behavior:

- Authenticate user and organization membership.
- Verify export belongs to `X-Organization-Id`.
- Verify export status is `ready`.
- Verify storage exists.
- Recompute or trust stored content hash according to project performance policy; at minimum verify byte size when cheap.
- Emit `evidence_export.downloaded`.
- Stream ZIP through Django with `Content-Type: application/zip` and `Content-Disposition: attachment`.

Errors:

- `404 export_not_found`;
- `409 export_not_ready`;
- `409 export_expired`;
- `409 export_storage_missing`.

### 11.6 `POST /api/v1/evidence-bundles/{id}/legal-hold/`

Place a legal hold on a bundle and its source change.

Request body:

```json
{
  "reason": "Required for external audit matter 1234.",
  "external_reference": "MATTER-1234"
}
```

Response `201 Created`:

```json
{
  "id": "...",
  "status": "active",
  "change_record_id": "...",
  "evidence_bundle_id": "...",
  "placed_at": "2026-05-01T00:00:00.000000Z",
  "external_reference": "MATTER-1234"
}
```

Errors:

- `400 legal_hold_reason_required`;
- `404 bundle_not_found`;
- `409 legal_hold_already_active`.

Release is intentionally not part of the required Phase 11.5 public API. If implementation adds release, it must be admin-only, audited, and covered by tests.

## 12. Frontend Impact

Add evidence UI to the Phase 11 change detail experience. The React app must use public Django APIs only.

Required UI:

- evidence tab on change detail;
- completeness checklist;
- seal action;
- manifest viewer;
- export dialog;
- legal hold indicator/control.

Recommended feature structure:

```text
apps/web/src/features/evidence/
  api/evidenceApi.ts
  hooks/useLatestEvidenceBundle.ts
  hooks/useCreateEvidenceBundle.ts
  hooks/useSealEvidenceBundle.ts
  hooks/useCreateEvidenceExport.ts
  hooks/useEvidenceExportDownload.ts
  hooks/useCreateLegalHold.ts
  types.ts
```

Change route integration:

- Extend `apps/web/src/routes/changes/ChangeDetailPage.tsx` or the actual Phase 11 change detail route.
- Add an Evidence tab next to Overview, Controls, Execution, Verification, Exceptions, and Audit if those tabs exist.
- The tab should show bundle status, version, completeness, manifest hash, content hash, retention deadline, and legal hold state.
- The seal button is enabled only when `status=="compiling"` and `completeness_status=="complete"`.
- The export dialog is enabled only when `status=="sealed"` and storage is not deleted.
- The legal hold control is visible to admin/operator roles according to backend permission response.

Manifest viewer:

- Render manifest metadata, hashes, paths, sizes, and item types.
- Do not render raw artifact bytes.
- Do not render redacted source values.
- Provide copyable hashes and path filters.

Completeness checklist:

- Group by canonical section.
- Show required/missing/invalid counts.
- Link artifact-backed failures to artifact metadata only.
- Show invalid audit order or checksum mismatches as blocking errors.

Export dialog:

- Select redaction policy.
- Show whether export is unredacted or redacted.
- After creation, show export hash, receipt hash, expiry, and download action.

Legal hold indicator/control:

- Show active hold status and external reference.
- Make retention-blocking behavior clear.
- Do not expose raw legal notes beyond what the API returns.

## 13. File-by-File Implementation Plan

### Backend: Settings and Routing

| File | Plan |
|---|---|
| `apps/api/config/settings/base.py` | Register `apps.evidence.apps.EvidenceConfig` after `apps.artifacts` and after completed `apps.changes`. Add evidence retention/export settings if needed. |
| `apps/api/config/api_v1_urls.py` | Include `apps.evidence.urls` public routes under `/api/v1/`. Do not add internal runner routes. |

### Backend: Evidence App

| File | Plan |
|---|---|
| `apps/api/apps/evidence/apps.py` | Define app config. |
| `apps/api/apps/evidence/models.py` | Add `EvidenceBundle`, `EvidenceBundleItem`, `EvidenceRedactionPolicy`, `EvidenceExport`, `EvidenceRetentionPolicy`, and `LegalHold` with enums, constraints, indexes, and immutability guards. |
| `apps/api/apps/evidence/storage.py` | Wrap `apps.artifacts.storage.ArtifactStorage` for evidence storage keys. Add helpers for deterministic evidence paths and safe open/save/delete. |
| `apps/api/apps/evidence/services.py` | Implement canonical JSON/NDJSON serialization, section materialization, completeness checks, manifest generation, checksum generation, deterministic ZIP generation, sealing, invalidation, export creation, redaction transforms, retention cleanup, and legal hold creation. |
| `apps/api/apps/evidence/selectors.py` | Add organization-scoped selectors for bundles, latest bundle, exports, redaction policies, retention policies, and active legal holds. |
| `apps/api/apps/evidence/serializers.py` | Add request/response serializers for bundle create/latest/seal, export create/download summary, legal hold create, manifest summary, completeness report, and redaction policy selection. |
| `apps/api/apps/evidence/views.py` | Add public API views with organization context, role checks, service calls, and structured error propagation. |
| `apps/api/apps/evidence/urls.py` | Register required public endpoints exactly as specified. |
| `apps/api/apps/evidence/admin.py` | Read-only admin for sealed bundles/items/exports; limited admin for redaction and retention policies; legal holds read-only except release if implemented. |

### Backend: Changes Integration

| File | Plan |
|---|---|
| `apps/api/apps/changes/selectors.py` | Add or reuse selectors that return closed change evidence with approvals, policy decisions, execution binding, verification, closure, exceptions, breakglass, retro-review, targets, windows, locks, and preflight checks. |
| `apps/api/apps/changes/services.py` | Add small hooks only if needed to detect source evidence fingerprint changes or expose current source projection. Do not move evidence packaging into the changes app. |
| `apps/api/apps/changes/serializers.py` | Include latest evidence bundle summary in change detail if Phase 11 UI needs it, but avoid embedding large manifests by default. |

### Backend: Artifacts Integration

| File | Plan |
|---|---|
| `apps/api/apps/artifacts/models.py` | No schema change expected if Phase 10.4 fields remain as inspected. Verify stable id, MIME type, size, checksum, and storage key exist. |
| `apps/api/apps/artifacts/services.py` | Add a narrow helper to validate and open available artifact bytes by id/checksum if useful. Do not rewrite upload behavior. |
| `apps/api/apps/artifacts/storage.py` | Reuse as storage backend. If naming is too artifact-specific, keep compatibility and create an evidence wrapper instead of broad refactor. |

### Backend: Audit Integration

| File | Plan |
|---|---|
| `apps/api/apps/audit/models.py` | Add object types for evidence bundle, bundle item, redaction policy, evidence export, retention policy, and legal hold. |
| `apps/api/apps/audit/services.py` | Extend forbidden metadata keys for evidence manifests, receipts, redaction payloads, raw legal hold notes, and ZIP bytes. |
| `apps/api/apps/audit/tests/` | Add scrubber and append-only tests for evidence export/download events. |

### Frontend

| File | Plan |
|---|---|
| `apps/web/src/features/evidence/types.ts` | Add bundle, item, completeness, manifest, export, redaction policy, retention, and legal hold types. |
| `apps/web/src/features/evidence/api/evidenceApi.ts` | Add functions for required public endpoints. |
| `apps/web/src/features/evidence/hooks/*` | Add query/mutation hooks for latest bundle, create, seal, export, download, and legal hold. |
| `apps/web/src/routes/changes/ChangeDetailPage.tsx` | Add Evidence tab and panels to the actual Phase 11 change detail page. |
| `apps/web/src/shared/lib/queryKeys.ts` | Add stable evidence query keys if the completed web app has this helper. |
| `apps/web/src/app/router.tsx` | No new top-level route required unless completed Phase 11 routes organize change tabs as nested routes. |

## 14. Migration Plan

1. Add `apps.evidence` to `INSTALLED_APPS`.
2. Create initial evidence migration with all six models and constraints.
3. Add audit object type migration for evidence objects.
4. Add default retention policy data migration only if the product requires one before first seal. Otherwise require explicit policy setup in service validation.
5. Add optional default redaction policy data migration only if product wants a built-in metadata-only export path.
6. Deploy backend models and APIs before frontend evidence tab.
7. Keep old runners compatible; runner behavior is unchanged.
8. Seal only newly requested bundles. Do not backfill evidence bundles automatically because batch processing is out of scope.
9. If production already has closed changes, operators can create bundles on demand through the new API.
10. Rollback after real sealed bundles exist is forward-only for data. Do not delete evidence rows in rollback scripts. Disable routes if rollback is needed.

## 15. Testing Plan

### Required Backend Tests

Implement tests for the prompt-required cases:

- closed change can produce bundle;
- required sections present;
- missing section marks incomplete;
- manifest hash deterministic;
- sealed bundle immutable;
- redaction does not mutate canonical evidence;
- export audit logging;
- legal hold blocks cleanup.

### Model and Constraint Tests

- bundle status check constraint rejects invalid values;
- completeness status check constraint rejects invalid values;
- item type check constraint rejects invalid values;
- unique `(change_record, version)` is enforced;
- sealed bundle model/service guard blocks manifest/content/storage changes;
- sealed bundle item guard blocks insert/update/delete;
- export ready state requires hashes, size, receipt, and storage key;
- legal hold release requires release actor, timestamp, and reason if release API/service exists.

### Materialization Tests

- closed normal change includes change snapshot, targets, approvals, policy decisions, execution, verification, closure, audit, artifacts index, exceptions file, and sealed-bundle receipt;
- closed emergency change includes exception, breakglass, and retro-review evidence;
- missing closure marks incomplete;
- missing required verification result marks incomplete;
- artifact row with missing storage bytes marks incomplete when required;
- artifact checksum mismatch marks invalid;
- cross-organization artifact reference marks invalid;
- audit event order is preserved by `(occurred_at, created_at, id)` when no sequence exists;
- bundle creation audit event is excluded from the bundle being created.

### Hashing and ZIP Tests

- canonical JSON is stable for different dict insertion order;
- UTC timestamp format is exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ`;
- NDJSON non-empty file has exactly one trailing LF;
- `checksums.sha256` line order is lexicographic by path;
- `checksums.sha256` excludes itself and includes `manifest.json`;
- ZIP entries have fixed timestamps and permissions;
- repeated seal with same persisted projection produces same package hash in a controlled test fixture.

### API Tests

- create bundle requires auth and organization context;
- create bundle rejects non-closed change;
- latest endpoint returns latest non-invalidated version;
- seal endpoint rejects incomplete bundle;
- seal endpoint rejects invalid bundle;
- seal endpoint is idempotent for already sealed bundle only if service deliberately returns the existing sealed detail; otherwise it returns `409`;
- export endpoint rejects unsealed bundle;
- export endpoint rejects inactive redaction policy;
- download endpoint streams only ready exports in same organization;
- legal hold endpoint creates active hold and rejects duplicate active hold.

### Redaction and Export Tests

- redacted export has different content hash when policy changes bytes;
- source bundle `content_sha256` and `manifest_sha256` remain unchanged after export;
- redacted audit NDJSON preserves event order;
- omitted artifact bytes remain represented in export manifest and artifact index;
- export receipt includes source manifest hash and redaction policy hash;
- export creation emits `evidence_export.created`;
- export download emits `evidence_export.downloaded`;
- audit metadata does not include raw redacted values.

### Retention and Legal Hold Tests

- cleanup deletes expired export storage when no hold exists;
- cleanup deletes expired bundle storage when no hold exists and policy allows it;
- cleanup keeps DB rows and hashes after storage deletion;
- active change-level legal hold blocks bundle cleanup;
- active bundle-level legal hold blocks bundle cleanup;
- active bundle-level legal hold blocks derived export cleanup;
- released hold no longer blocks cleanup after retention deadline;
- cleanup emits retention audit events.

### Frontend Tests

- Evidence tab fetches latest bundle from public API;
- completeness checklist renders complete, incomplete, and invalid states;
- seal action is disabled unless bundle is complete and compiling;
- manifest viewer renders paths and hashes without artifact bytes;
- export dialog submits selected redaction policy;
- legal hold control posts to public API and refreshes bundle state;
- browser API client still rejects `/api/v1/internal/...` calls.

## 16. Codex Implementation Batching Plan

Batch 1: Evidence app, models, and migrations

- Add `apps.evidence`, all six models, constraints, admin, settings registration, URL include, and audit object type migration.
- Add model tests for enums, constraints, and sealed-row guards.

Batch 2: Canonical serialization and materialization

- Implement canonical JSON/NDJSON helpers, source selectors, section serializers, bundle item creation, source snapshot hashing, and completeness report.
- Add tests for closed changes, missing sections, artifact validation, and audit ordering.

Batch 3: Deterministic manifest and sealing

- Implement manifest generation, checksum file generation, deterministic ZIP generation, storage write, seal transition, and sealing audit.
- Add deterministic hash, immutable sealed bundle, and checksum mismatch tests.

Batch 4: Redaction and exports

- Implement redaction policy validation, export creation pipeline, export receipt, export manifest, export storage, and download endpoint.
- Add redaction does-not-mutate-canonical tests and export audit logging tests.

Batch 5: Retention and legal hold

- Implement retention policy resolution, cleanup service functions, legal hold endpoint, hold selectors, and cleanup-blocked behavior.
- Add legal hold blocks cleanup tests.

Batch 6: Frontend evidence tab

- Add evidence types, API methods, hooks, Evidence tab, checklist, seal action, manifest viewer, export dialog, and legal hold indicator/control.
- Add focused React tests.

Batch 7: Final hardening

- Re-run targeted API/web tests, audit scrubber tests, and security checks.
- Re-audit against architecture invariants.
- Update implementation status documentation if the repository uses one for Phase 11.5.

## 17. Definition of Done

- `apps/api/apps/evidence/` exists and is registered.
- All six required models exist with constraints, indexes, and organization boundaries.
- Bundle statuses are exactly `compiling`, `sealed`, and `invalidated`.
- Completeness statuses are exactly `complete`, `incomplete`, and `invalid`.
- Bundle item types include all required values.
- Closed changes can produce bundle projections.
- Required evidence sections are materialized into the canonical layout.
- Missing required evidence marks the bundle incomplete.
- Invalid/corrupt evidence marks the bundle invalid.
- Complete bundles can be sealed into immutable deterministic ZIPs.
- Manifest SHA-256 and package content SHA-256 are computed and stored.
- Redacted exports are derived packages and never mutate canonical evidence.
- Export creation and download are audited.
- Retention cleanup respects active legal holds.
- Runner architecture remains unchanged.
- Runner artifacts used as evidence carry stable IDs, MIME type, byte size, and checksum.
- React exposes evidence tab, completeness checklist, seal action, manifest viewer, export dialog, and legal hold indicator/control.
- Required backend and frontend tests pass.

## 18. Risks and Drift Traps

- Nondeterministic timestamps: using local time, variable precision, or `datetime.isoformat()` without a strict UTC format will break manifest stability.
- Nondeterministic JSON: relying on Python dict insertion order from query results instead of canonical sorting will produce unstable hashes.
- Nondeterministic ZIP metadata: default ZIP timestamps, compression, permissions, or comments will change package hashes.
- Audit recursion: including the bundle creation/export audit event in the bundle that caused it creates unstable self-referential evidence.
- Audit order drift: sorting audit events by event type or object id instead of source sequence destroys evidentiary order.
- Manifest recursion: putting `manifest_sha256` inside `manifest.json` or trying to checksum `checksums.sha256` inside itself is structurally impossible.
- Redaction mutation: updating source `AuditEvent`, source `Artifact`, or canonical bundle rows during export breaks the evidence model.
- Artifact dependency leak: a sealed bundle that references artifact storage instead of copying bytes into the ZIP is not self-contained.
- Legal hold bypass: cleanup services must check holds at change, bundle, and export scope.
- Retention overreach: retention cleanup may delete stored ZIP bytes only as whole objects; it must not rewrite packages to remove selected files.
- Version ambiguity: invalidated bundles must remain visible historical records, while latest endpoints clearly identify current vs invalidated versions.
- External reference leakage: URLs and ticket references can contain tokens. Redaction and audit scrubbers must treat external references as potentially sensitive.
- Export receipt recursion: export ZIP content hash should not be embedded in a receipt file that is itself inside the ZIP unless a two-pass non-recursive design is formally specified.
- Phase drift: actual Phase 11.1-11.4 implementation may differ from these blueprints. Re-inspect source before coding and adapt selectors rather than forcing this document's assumed field names.
