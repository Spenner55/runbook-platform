# Phase 11.5 Readiness Audit

Prepared: 2026-05-07

Scope: read-only implementation readiness audit for Phase 11.5 sealed evidence bundles. No application code was modified. The only created file is this report.

## Verdict

Phase 11.5 is ready to start in small backend-first batches. Phase 11.1-11.4 are actually implemented in this checkout, and the current validation gates pass.

The main readiness risk is blueprint drift: Phase 11.5 must be implemented against the current `apps/api/apps/changes/` surface, not the older blueprint checklist that said the changes app was absent. The new `apps/api/apps/evidence/` app is not present yet, which is expected Phase 11.5 scope.

## Verification Run

| Command | Result |
|---|---|
| `docker compose ps` | Stack running; api, web, postgres, pgbouncer, ai healthy/up; runner up. |
| `docker compose exec api python manage.py check` | Passed: no system check issues. |
| `docker compose exec api pytest` | Passed: 1422 tests, 1 existing teardown warning about `test_runbook_platform` still having one DB session. |
| `docker compose exec web npm test -- --run` | Passed: 26 files, 212 tests. Existing test stderr includes expected "No routes matched location" messages in navigation tests. |
| `docker compose exec web npm run build` | Recommended but not run, because Vite writes build output and this audit was allowed to create only this markdown report. |

## Phase 11.1-11.4 Status

| Phase | Implemented? | Evidence |
|---|---:|---|
| 11.1 Change dossier | Yes | `apps/api/apps/changes/models.py` has `OperationProfile`, `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`; migrations `0001` and `0002`; public `/api/v1/changes/`; internal bind route under `/api/v1/internal/changes/`. |
| 11.2 Windows/freezes/locks | Yes | `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`; migrations `0003` and `0004`; `/api/v1/freeze-rules/`; preflight and timing callback tests present. |
| 11.3 Verification/closure | Yes | `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`; migration `0005`; public verification plan/result/close routes and internal runner verification route. |
| 11.4 Emergency/exceptions/breakglass | Yes | `ChangeException`, `BreakglassSession`, `RetroReview`, emergency fields on `ChangeRecord`; migration `0006`; approval subject type `change_exception`; breakglass heartbeat and frontend components/tests present. |

## Blueprint Drift

- `apps/api/apps/changes/` exists and is registered in `INSTALLED_APPS`; the Phase 11.5 blueprint's current-state note saying it was absent is stale.
- `apps/api/apps/evidence/` does not exist. That remains the primary new app for Phase 11.5.
- All Phase 11.1-11.4 models are co-located in `apps/api/apps/changes/models.py`; there are no separate apps for windows, verification, exceptions, or breakglass.
- Public change routes are included under `/api/v1/changes/`; freeze rules are a separate public root at `/api/v1/freeze-rules/`.
- Runner-only routes use `/api/v1/internal/changes/...`, not `/internal/v1/...`.
- `ChangeRecordDetailSerializer` is a UI dossier summary, not a complete evidence source. Phase 11.5 services should query models/selectors directly for request snapshots, verification results, closure, exceptions, audit events, and artifacts.
- The frontend change detail page is a single composed page, not a tabbed layout. Phase 11.5 can add an Evidence section/panel there unless the UI is deliberately refactored to tabs.

## Blockers

No hard blocker was found for starting Phase 11.5 Batch 1.

Before shipping seal/export behavior, these must be resolved:

| ID | Area | Finding | Required decision/fix |
|---|---|---|---|
| B-01 | Retention policy | The blueprint allows either a default retention policy or a settings fallback, but the repo has no evidence retention setting or policy model yet. | Decide in Batch 1 whether sealing requires an explicit per-org default policy or uses safe settings defaults. Do not leave `retention_expires_at` undefined for sealed bundles. |
| B-02 | Storage backend | `ArtifactStorage` is local-only at runtime and raises if `ARTIFACT_STORAGE_BACKEND != "local"`, while settings accept `s3`. | Evidence storage must either explicitly share the local-only limitation or Phase 11.5 must not claim production S3 evidence storage readiness. Do not introduce a separate backend silently. |
| B-03 | Audit object constraints | `AuditEvent.ObjectType` has a DB check constraint and currently lacks evidence object types. | Add evidence object types and migration before emitting any `evidence_*` or `legal_hold.*` audit events. |
| B-04 | Artifact write API shape | `ArtifactStorage.save()` expects a file object with `.chunks()`. Evidence ZIP generation will likely produce `bytes`/`BytesIO`. | Add a thin evidence storage wrapper using `ContentFile` or compatible chunking; do not broaden artifact upload behavior unnecessarily. |

## Warnings

- The audit trail has no sequence field. Use deterministic ordering `(occurred_at ASC, created_at ASC, id ASC)` for `audit/audit_trail.ndjson`.
- Audit append-only protection is application-level. Direct SQL or privileged migrations can still alter rows; evidence bundles should be treated as sealed snapshots, not proof that the source DB is tamper-proof.
- Approval notes, manual attestation text, external references, breakglass scope, policy payloads, and artifact names can contain sensitive data. The evidence service needs its own allowlist/summary rules, not just API serializers.
- Source records such as exceptions, breakglass sessions, retro reviews, preflights, and target locks are append/update lifecycle records. Materialization must persist `source_cutoff_at` and exclude bundle/export audit events caused by the materialization itself.
- Existing artifact rows have the necessary fields (`id`, `mime_type`, `size_bytes`, `checksum_sha256`, `storage_key`), but sealed bundles must copy bytes and verify checksums. Referencing live artifact storage is not enough.
- Redaction must be export-only. Any implementation that updates `AuditEvent`, `Artifact`, `EvidenceBundle`, or `EvidenceBundleItem` during export should stop.

## Safe Assumptions

- Django remains the control plane; no workers, queues, or runner changes are needed for Phase 11.5.
- Current Phase 11.1-11.4 model names are authoritative: `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`, `ChangeWindow`, `FreezeRule`, `TargetLock`, `DispatchEligibilityCheck`, `VerificationPlan`, `VerificationCheck`, `VerificationResult`, `ChangeClosure`, `ChangeException`, `BreakglassSession`, and `RetroReview`.
- Current route convention is authoritative: public `/api/v1/...`, internal runner `/api/v1/internal/...`.
- Existing frontend API guard already blocks `/api/v1/internal/` and `/internal/v1/`.
- Existing tests are a valid baseline for regression detection; the full API and web suites pass before Phase 11.5 work.

## Exact Files Phase 11.5 Must Touch

Backend new files:

- `apps/api/apps/evidence/__init__.py`
- `apps/api/apps/evidence/apps.py`
- `apps/api/apps/evidence/admin.py`
- `apps/api/apps/evidence/models.py`
- `apps/api/apps/evidence/selectors.py`
- `apps/api/apps/evidence/serializers.py`
- `apps/api/apps/evidence/services.py`
- `apps/api/apps/evidence/storage.py`
- `apps/api/apps/evidence/urls.py`
- `apps/api/apps/evidence/views.py`
- `apps/api/apps/evidence/migrations/0001_initial.py`
- `apps/api/apps/evidence/tests/test_models.py`
- `apps/api/apps/evidence/tests/test_materialization.py`
- `apps/api/apps/evidence/tests/test_hashing.py`
- `apps/api/apps/evidence/tests/test_immutability.py`
- `apps/api/apps/evidence/tests/test_api.py`
- `apps/api/apps/evidence/tests/test_exports.py`
- `apps/api/apps/evidence/tests/test_redaction.py`
- `apps/api/apps/evidence/tests/test_retention.py`
- `apps/api/apps/evidence/tests/test_legal_hold.py`

Backend existing files:

- `apps/api/config/settings/base.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/audit/migrations/0010_add_evidence_object_types.py`
- `apps/api/apps/audit/tests/test_models.py`
- `apps/api/apps/audit/tests/test_services.py`
- `apps/api/apps/changes/selectors.py`
- optionally `apps/api/apps/changes/serializers.py`
- optionally `apps/api/apps/artifacts/services.py` or only `apps/api/apps/evidence/storage.py`

Frontend new files:

- `apps/web/src/features/evidence/types.ts`
- `apps/web/src/features/evidence/api/evidenceApi.ts`
- `apps/web/src/features/evidence/hooks/useLatestEvidenceBundle.ts`
- `apps/web/src/features/evidence/hooks/useCreateEvidenceBundle.ts`
- `apps/web/src/features/evidence/hooks/useSealEvidenceBundle.ts`
- `apps/web/src/features/evidence/hooks/useCreateEvidenceExport.ts`
- `apps/web/src/features/evidence/hooks/useEvidenceExportDownload.ts`
- `apps/web/src/features/evidence/hooks/useCreateLegalHold.ts`

Frontend existing files:

- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/routes/changes/ChangeDetailPage.tsx`
- `apps/web/src/routes/changes/ChangeDetailPage.test.tsx`

## Recommended Implementation Order

1. Add evidence app skeleton, models, constraints, audit object types, settings registration, and URL include. Add model/constraint tests first.
2. Implement canonical JSON, NDJSON, datetime, checksum, and ZIP helpers with deterministic tests before source materialization.
3. Implement organization-scoped source selectors and bundle materialization for a closed change. Add completeness tests for normal and emergency changes.
4. Implement artifact byte validation and self-contained artifact inclusion. Stop on missing required bytes or checksum mismatch.
5. Implement sealing, immutable guards, manifest generation, `checksums.sha256`, storage write/delete-on-failure, and sealing audit.
6. Implement redaction policies, derived exports, export receipts, export download, and export audit events.
7. Implement retention policy resolution, explicit cleanup services, legal hold creation, and legal-hold cleanup blockers.
8. Add frontend evidence API/hooks and a focused Evidence section on the current change detail page.
9. Run targeted evidence tests, then full API/web suites, migration checks, lint, and production checks.

## Stop Conditions

Stop implementation and re-audit if any of these occurs:

- `makemigrations --check --dry-run` shows unexpected changes to existing Phase 11.1-11.4 models.
- Evidence audit events are needed before the audit object type migration is in place.
- A sealed bundle cannot be generated byte-identically twice from the same persisted projection.
- `manifest.json` includes its own hash, or `checksums.sha256` includes its own checksum.
- Bundle/export audit events are included in the source audit trail for the bundle/export that emitted them.
- Required artifact bytes are missing or checksum validation fails.
- Redaction code mutates source bundle rows, bundle items, audit events, artifacts, or source change records.
- Retention cleanup can delete bytes while a change-, bundle-, or export-level legal hold is active.
- Browser code attempts `/api/v1/internal/...` or `/internal/v1/...`.
- `docker compose exec api python manage.py check`, targeted evidence tests, or the full API/web suites fail.

## First Implementation Step

Create `apps/api/apps/evidence/` with the six model families, exact enum values, DB constraints, sealed-row immutability guards, and audit object type migration. Register `apps.evidence.apps.EvidenceConfig` in `apps/api/config/settings/base.py` and include empty/initial public evidence URL patterns in `apps/api/config/api_v1_urls.py`. The first passing gate should be model tests plus `python manage.py check`, before materialization or ZIP generation is added.
