# Phase 11.6 Implementation Plan

This report is based on read-only inspection of the Phase 11.1, 11.5, and 11.6 blueprints plus the current `runbook-platform` source. The only repository write for this task is this markdown plan.

## 1. Current Repo State

Phase 11.1 through 11.5 foundations are present in this checkout:

- `apps/api/apps/changes/` exists, is registered as `apps.changes.apps.ChangesConfig`, and is included under public `/api/v1/changes/` plus runner-only `/api/v1/internal/changes/`.
- `apps/api/apps/evidence/` exists, is registered as `apps.evidence.apps.EvidenceConfig`, and exposes public evidence routes at `/api/v1/changes/{id}/evidence-bundles/`, `/api/v1/evidence-bundles/...`, `/api/v1/evidence-exports/...`, and `/api/v1/legal-holds/...`.
- `apps/api/apps/audit/` exists and exposes append-only audit events at `/api/v1/audit/` and execution-scoped audit events at `/api/v1/executions/{execution_id}/audit/`.
- `apps/api/apps/authz/` is absent. Current authorization is role-helper based in `apps/api/apps/common/permissions.py`.
- `apps/api/apps/auditor/` is absent. None of the Phase 11.6 model families are implemented.
- `apps/web/src/features/changes/` and `apps/web/src/features/evidence/` exist. `apps/web/src/features/auditor/` is absent.
- `apps/web/src/app/router.tsx` has routes for runbooks, workflows, executions, approvals, policies, integrations, changes, retro reviews, freeze rules, and settings. It has no auditor routes.
- `apps/web/src/app/AppLayout.tsx` has no auditor navigation entry.

The browser API client in `apps/web/src/shared/api/client.ts` already injects `X-Organization-Id` and rejects calls to `/api/v1/internal/`, so Phase 11.6 frontend work should continue using that client.

## 2. Phase 11.6 Dependencies Verified/Missing

Verified dependencies:

- Change dossier aggregate exists: `OperationProfile`, `ChangeRecord`, `ChangeTarget`, and `ChangeExecutionBinding`.
- Phase 11.2 dispatch guard data exists in `ChangeWindow`, `FreezeRule`, `TargetLock`, and `DispatchEligibilityCheck`.
- Phase 11.3 verification and closure data exists in `VerificationPlan`, `VerificationCheck`, `VerificationResult`, and `ChangeClosure`.
- Phase 11.4 emergency/exception data exists in `ChangeException`, `BreakglassSession`, and `RetroReview`.
- Phase 11.5 sealed evidence data exists in `EvidenceBundle`, `EvidenceBundleItem`, `EvidenceRedactionPolicy`, `EvidenceExport`, `EvidenceRetentionPolicy`, and `LegalHold`.
- `EvidenceBundleItem.ItemType.EXTERNAL_REFERENCE` and canonical path `references/external_references.json` already exist.
- Organization context enforcement exists in `require_organization_id()` and `require_matching_organization_id()`.
- Audit metadata scrubbing and append-only audit constraints exist.

Missing dependencies for Phase 11.6:

- No `authz` app or grant-aware authorization layer.
- No `auditor` app.
- No `ExternalChangeReference`, `ServiceCatalogEntry`, `ControlMappingProfile`, `ChangeControlCoverage`, or `AuditorAccessGrant` models.
- No auditor search/detail API.
- No service catalog data or service-to-target mapping.
- No persisted control coverage computation.
- No scoped auditor access grants.
- No 11.6 audit object types in `AuditEvent.ObjectType`.
- No governed external reference snapshots. Existing external references are only strings/configs from verification checks/results and retro reviews.
- No frontend auditor workspace, audit change detail route, or auditor grant admin route.

## 3. Actual Model and Field Names From Phases 11.1-11.5

Changes app:

- `OperationProfile`: `organization`, `key`, `name`, `description`, `is_active`, `risk_level`, `requires_approval`, `verification_required`, `verification_mode`, `verification_plan_template`, `requires_independent_reviewer`, `verification_timeout_seconds`, `approval_ttl_seconds`, `dispatch_ttl_seconds`, `allowed_target_types`, `requested_inputs_schema`, `target_schema`, `allowed_workflows`, `created_by`, `updated_by`, plus emergency config `allow_emergency_changes`, `max_breakglass_seconds`, `retro_review_sla_seconds`.
- `ChangeRecord`: `organization`, `operation_profile`, `workflow`, `requested_by`, `submitted_by`, `title`, `summary`, `justification`, `status`, `requested_inputs`, `requested_inputs_sha256`, `request_snapshot`, `request_snapshot_sha256`, `operation_profile_key_snapshot`, `workflow_version_snapshot`, `workflow_definition_sha256`, `approval_request`, `policy_evaluation`, `policy_decision_snapshot`, `scheduled_for`, lifecycle timestamps through `expired_at`, `verification_failed_at`, `terminal_reason`, emergency fields `is_emergency`, `emergency_reason`, `emergency_declared_by`, `emergency_declared_at`, retro-review fields, and freeze exception fields.
- `ChangeRecord.Status`: `draft`, `pending_approval`, `approved`, `scheduled`, `dispatchable`, `running`, `verification_pending`, `verification_failed`, `verified`, `closed`, `rejected`, `canceled`, `expired`.
- `ChangeTarget`: `change_record`, `organization`, `position`, `target_type`, `target_identifier`, `normalized_identifier`, `display_name`, `environment`, `metadata`.
- `ChangeExecutionBinding`: one-to-one `change_record`, one-to-one `execution`, `organization`, `operation_profile_key`, `requested_inputs_sha256`, dispatch token nonce/hash/expiry, reservation/bind/timing fields, `bound_by_runner_id`, and `runner_payload_snapshot`.
- `VerificationPlan`: `organization`, `change_record`, `operation_profile`, `mode`, `status`, profile snapshot/hash fields, required/optional/satisfied/failed counts, and lifecycle timestamps.
- `VerificationCheck`: `organization`, `plan`, `change_record`, `position`, `key`, `name`, `description`, `check_type`, `required`, `status`, `verification_key`, `source_step_key`, artifact fields, `api_assertion`, `external_reference_config`, `manual_attestation_config`, `last_result`, timestamps.
- `VerificationResult`: `organization`, `change_record`, `plan`, `verification_check`, `source`, `outcome`, `validation_status`, `submitted_by`, `runner_id`, `verification_key`, `artifact`, `artifact_checksum_sha256`, `external_reference`, `api_assertion_snapshot`, `manual_attestation_text`, `observed_value`, `validation_errors`, timestamps.
- `ChangeClosure`: `organization`, one-to-one `change_record`, `outcome`, `closed_by`, `independent_reviewer`, `summary`, `verification_plan`, `verification_summary`, `execution_summary`, `closed_at`.
- `ChangeWindow`, `FreezeRule`, `TargetLock`, and `DispatchEligibilityCheck` are present with production window, freeze, lock, and preflight snapshot fields.
- `ChangeException`, `BreakglassSession`, and `RetroReview` are present for exception and emergency evidence.

Evidence app:

- `EvidenceBundle`: `organization`, `change_record`, `version`, `status`, `completeness_status`, `completeness_report`, source snapshot/high-water fields, manifest/hash/content/storage metadata, compile/seal/invalidate timestamps, `previous_bundle`, actor fields, retention fields, and immutable-after-seal guards.
- `EvidenceBundle.Status`: `compiling`, `sealed`, `invalidated`.
- `EvidenceBundle.CompletenessStatus`: `complete`, `incomplete`, `invalid`.
- `EvidenceBundleItem`: `organization`, `bundle`, `item_type`, `item_key`, `canonical_path`, `json_pointer`, `position`, `required`, `present`, `valid`, `missing_reason`, `validation_errors`, source refs, optional `artifact`, staging/content metadata.
- `EvidenceBundleItem.ItemType`: `change_snapshot`, `approval`, `policy_decision`, `execution`, `audit_event`, `artifact`, `verification_result`, `closure`, `exception`, `external_reference`, `export_receipt`.
- `EvidenceRedactionPolicy`, `EvidenceExport`, `EvidenceRetentionPolicy`, and `LegalHold` are implemented.

Audit and authorization:

- `AuditEvent.ObjectType` currently ends at `legal_hold`; it does not include Phase 11.6 object types.
- `FORBIDDEN_METADATA_KEYS` already covers many sensitive fields, including `raw_response`, `request_body`, `requested_inputs`, `storage_key`, `external_access_token`, `external_reference_raw`, `raw_scope`, and export/receipt byte keys.
- Membership roles are `owner`, `admin`, `operator`, and `viewer`. Permission helpers are `assert_organization_member`, `assert_organization_operator`, and `assert_organization_admin`.

## 4. Drift From The Blueprint

- The Phase 11.6 blueprint says `changes`, `evidence`, and `authz` were absent when authored. In this repo, `changes` and `evidence` are implemented; `authz` remains absent.
- `ChangeRecord.Status` includes `verification_failed`, which auditor filters and serializers must support.
- `ChangeRecord` has no `change_type` field. Phase 11.6 should derive `change_type = "emergency"` from `is_emergency`, otherwise `standard`.
- `ChangeRecord` and `ChangeTarget` have no service key field. Service filtering must either use `ServiceCatalogEntry.target_patterns` against `ChangeTarget.target_type` and `normalized_identifier`, or a later approved schema change must add an explicit service link.
- `ChangeRecordDetailSerializer` currently omits `verification_failed_at` even though the model has it. Auditor serializers should include it if exposing lifecycle timestamps.
- Evidence materialization already emits `references/external_references.json`, but only from `VerificationResult.external_reference`, `VerificationCheck.external_reference_config`, and `RetroReview.remediation_reference`. Phase 11.6 must add governed snapshot references without rewriting sealed bundles.
- Evidence public routes are included at the API root, not under `/api/v1/evidence/`.
- There is no auditor membership role. Scoped read-only auditor access should be modeled as `AuditorAccessGrant` for existing organization members, with server-side grant checks.
- Current audit list endpoint grants any org member read access to audit events. Phase 11.6 auditor search/detail must be narrower and grant-scoped.

## 5. Proposed Implementation Batches

### Batch 1: Backend Auditor App and Persistence

Create `apps/api/apps/auditor/` with `apps.py`, `admin.py`, `models.py`, `migrations/0001_initial.py`, and tests. Register `apps.auditor.apps.AuditorConfig` after `apps.evidence.apps.EvidenceConfig`.

Implement model families:

- `ExternalChangeReference`
- `ServiceCatalogEntry`
- `ControlMappingProfile`
- `ChangeControlCoverage`
- `AuditorAccessGrant`

Add `AuditEvent.ObjectType` values:

- `external_change_reference`
- `service_catalog_entry`
- `control_mapping_profile`
- `change_control_coverage`
- `auditor_access_grant`

Do not create data migrations or backfills.

### Batch 2: External References and Evidence Inclusion

Add snapshot sanitization, canonical JSON hashing, duplicate protection, URL validation, and link service/API for `ExternalChangeReference`. Add only explicit refresh plumbing if the product needs it; refresh must never run during search/detail or page mount.

Extend future evidence materialization to include `ExternalChangeReference` rows in `references/external_references.json`. Sealed bundles remain immutable; later links require a new bundle version to appear in evidence.

### Batch 3: Control Coverage Engine

Implement deterministic coverage evaluation from sealed `EvidenceBundle`, `EvidenceBundleItem`, bundle manifest entries, and `ControlMappingProfile.mapping_rules`.

Coverage must reject unsealed bundles, validate same-organization references, avoid expression languages or Python hooks, and compute stable `coverage_fingerprint_sha256` values.

### Batch 4: Auditor Access Grants

Implement grant creation/list/detail/revoke services and access helpers. Enforce membership plus active `AuditorAccessGrant` for viewer auditor users. Owner/admin may manage grants; operator/admin may link references or recompute coverage if product policy allows.

Grant scopes must be applied per grant and unioned across grants without dimension widening.

### Batch 5: Audit Search and Detail API

Add grant-scoped read-only endpoints:

- `GET /api/v1/audit/changes/`
- `GET /api/v1/audit/changes/{change_id}/`

Add operator/admin mutation endpoints:

- `POST /api/v1/changes/{change_id}/external-references/`
- `POST /api/v1/changes/{change_id}/control-coverage/recompute/`
- `POST /api/v1/auditor-access-grants/`
- `POST /api/v1/auditor-access-grants/{grant_id}/revoke/`

Search uses persisted Django data only. Detail endpoints return 404 for changes outside grant scope.

### Batch 6: Frontend Auditor Workspace

Add `apps/web/src/features/auditor/` API functions, hooks, and types. Add `apps/web/src/routes/auditor/` pages for search and detail. Register `/audit/changes` and `/audit/changes/:changeId` in the router and add an `Audit` navigation entry.

The UI is read-only for auditor users. Admin/operator-only controls for linking external references or recomputing coverage must still rely on backend permission checks.

### Batch 7: Frontend Auditor Access Admin

Add `/audit/access` for owner/admin scoped grant management if the backend companion list/detail/revoke endpoints are implemented in Batch 4. Keep this form specific to `AuditorAccessGrant.scope`; do not build a generic RBAC builder.

## 6. Files To Create/Modify Per Batch

Batch 1:

- Create `apps/api/apps/auditor/__init__.py`
- Create `apps/api/apps/auditor/apps.py`
- Create `apps/api/apps/auditor/admin.py`
- Create `apps/api/apps/auditor/models.py`
- Create `apps/api/apps/auditor/migrations/__init__.py`
- Create `apps/api/apps/auditor/migrations/0001_initial.py`
- Modify `apps/api/config/settings/base.py`
- Modify `apps/api/apps/audit/models.py`
- Create audit migration for the object type constraint
- Create `apps/api/apps/auditor/tests/test_models.py`
- Update `apps/api/apps/audit/tests/test_models.py` and `apps/api/apps/audit/tests/test_services.py`

Batch 2:

- Create `apps/api/apps/auditor/services.py`
- Create `apps/api/apps/auditor/serializers.py`
- Create `apps/api/apps/auditor/views.py`
- Create `apps/api/apps/auditor/urls.py`
- Create `apps/api/apps/auditor/external_clients.py`
- Modify `apps/api/config/api_v1_urls.py`
- Modify `apps/api/apps/evidence/selectors.py`
- Modify `apps/api/apps/evidence/services.py`
- Create `apps/api/apps/auditor/tests/test_external_references.py`
- Create `apps/api/apps/auditor/tests/test_no_live_calls.py`
- Update evidence materialization tests

Batch 3:

- Create `apps/api/apps/auditor/coverage.py`
- Extend `apps/api/apps/auditor/services.py`
- Extend `apps/api/apps/auditor/serializers.py`
- Extend `apps/api/apps/auditor/views.py`
- Extend `apps/api/apps/auditor/urls.py`
- Create `apps/api/apps/auditor/tests/test_control_coverage.py`

Batch 4:

- Create `apps/api/apps/auditor/access.py`
- Extend `apps/api/apps/auditor/services.py`
- Extend `apps/api/apps/auditor/serializers.py`
- Extend `apps/api/apps/auditor/views.py`
- Optionally add small reusable helpers to `apps/api/apps/common/permissions.py`
- Create `apps/api/apps/auditor/tests/test_access.py`

Batch 5:

- Create `apps/api/apps/auditor/selectors.py`
- Extend `apps/api/apps/auditor/serializers.py`
- Extend `apps/api/apps/auditor/views.py`
- Extend `apps/api/apps/auditor/urls.py`
- Modify `apps/api/config/api_v1_urls.py` if not already included
- Create `apps/api/apps/auditor/tests/test_api_audit_changes.py`

Batch 6:

- Create `apps/web/src/features/auditor/types.ts`
- Create `apps/web/src/features/auditor/api/auditorApi.ts`
- Create auditor hooks under `apps/web/src/features/auditor/hooks/`
- Create `apps/web/src/routes/auditor/AuditorSearchPage.tsx`
- Create `apps/web/src/routes/auditor/AuditChangeDetailPage.tsx`
- Modify `apps/web/src/app/router.tsx`
- Modify `apps/web/src/app/AppLayout.tsx`
- Add route/page tests under `apps/web/src/routes/auditor/`

Batch 7:

- Create `apps/web/src/routes/auditor/AuditorAccessAdminPage.tsx`
- Add grant hooks in `apps/web/src/features/auditor/hooks/`
- Extend `apps/web/src/features/auditor/api/auditorApi.ts`
- Extend `apps/web/src/features/auditor/types.ts`
- Modify `apps/web/src/app/router.tsx`
- Add grant admin tests

## 7. Test Plan Per Batch

Batch 1 tests:

- Model choices and database constraints for all five auditor model families.
- Organization matching for every FK.
- Audit object type emission accepts new object types.
- Audit scrubber still rejects/scrubs sensitive keys.
- Migration check confirms no data backfill.

Batch 2 tests:

- External reference link creates sanitized bounded snapshots and deterministic `snapshot_sha256`.
- Duplicate `(organization, change_record, system, reference_type, external_id)` is rejected.
- Credential-bearing URLs and unsafe snapshot keys are rejected or stripped.
- Linking references does not mutate `ChangeRecord`, approval, execution, closure, bundle, export, or coverage state.
- Evidence materialization includes persisted `ExternalChangeReference` rows only in newly materialized bundle versions.
- Search/detail paths do not import or call `external_clients.py`.

Batch 3 tests:

- Coverage recompute rejects unsealed bundles.
- Required paths/item types produce `covered`, `partially_covered`, `not_covered`, and `not_applicable`.
- Invalidated bundle/profile drift can mark `stale` only through explicit stale logic.
- Fingerprints are deterministic for semantically identical inputs.
- Mapping rules cannot reference paths outside sealed manifest data or invoke arbitrary expressions.

Batch 4 tests:

- Active, expired, revoked, and not-yet-started grants behave correctly.
- Viewer with grant can read only scoped audit workspace rows.
- Viewer without grant cannot read audit workspace rows.
- Auditor users cannot call mutation endpoints.
- Multi-grant union does not widen dimensions across grants.
- Grant scope date, service, target, status, risk, bundle status, change type, and exception filters are enforced server-side.

Batch 5 tests:

- `GET /api/v1/audit/changes/` supports pagination and filters for service, target, risk, status including `verification_failed`, change type, approver, executor, date basis/range, exceptions, bundle status, standard/control/coverage status, and external system.
- `GET /api/v1/audit/changes/{change_id}/` returns audit-ready read-only projections.
- Detail returns 404 outside grant scope.
- List/detail never expose storage keys, artifact bytes, command output, raw snapshots, tokens, or internal runner endpoints.
- Querysets use organization scope and persisted Django data only.

Batch 6 tests:

- Auditor search sends filters through `apiRequest` and renders table rows.
- Auditor detail renders overview, evidence bundle, external references, control coverage, timeline, and exceptions sections without lifecycle action buttons for auditors.
- Frontend auditor API never calls `/api/v1/internal/`.
- Route registration and navigation work for expected roles/grant-aware user state.

Batch 7 tests:

- Grant admin form serializes exact scope dimensions.
- Grant list/detail/revoke UI calls public endpoints only.
- Non-admin users do not see grant management navigation, while backend remains authoritative.

Recommended verification commands after implementation:

```text
make test-api
make test-web
make lint
```

If hardening-sensitive files change, also run:

```text
make check-prod
make security-scan
```

## 8. Rollback Notes

- Batch 1 rollback drops only the new auditor metadata tables and removes the audit object type migration. It must not alter `changes`, `evidence`, approvals, executions, artifacts, legal holds, or existing audit rows.
- Batch 2 rollback removes link/refresh endpoints and evidence inclusion of governed external references. Already sealed bundles remain untouched. Unsealed bundles with auditor reference items can be invalidated or regenerated before deployment rollback if needed.
- Batch 3 rollback removes coverage recompute endpoints and `ChangeControlCoverage` rows. Coverage is derived metadata, so deleting it must not affect evidence bundle integrity.
- Batch 4 rollback revokes or ignores `AuditorAccessGrant` rows and removes grant enforcement endpoints. Do not replace it with broad audit access.
- Batch 5 rollback removes audit workspace list/detail routes. Existing operator change/evidence APIs remain unchanged.
- Batch 6 and 7 rollback removes frontend routes/navigation/hooks only. Backend permissions must remain the source of truth.
- No rollback path may rewrite sealed bundle bytes, manifests, checksums, bundle items, audit events, legal holds, exports, change lifecycle state, approvals, execution bindings, or closure rows.

## 9. Explicit No-Go Risks

Do not start implementation if any of these are true:

- A plan requires frontend calls to `/api/v1/internal/` or direct runner/external-system calls.
- Audit search/detail would call ServiceNow, Jira, PagerDuty, custom URLs, AI services, artifact byte storage, or refresh adapters.
- Auditor grants are enforced only in React or only through route hiding.
- Scope union logic merges dimensions globally across grants.
- The implementation adds a generic GRC workflow, ticketing workflow engine, CMDB sync engine, background sync, polling loop, webhook rewrite path, or bidirectional ITSM state sync.
- External reference snapshots can authorize, approve, dispatch, verify, close, or otherwise mutate `ChangeRecord` lifecycle.
- Coverage is computed from unsealed bundles, raw artifact bytes, live external systems, or mutable frontend state.
- Sealed evidence bundles, manifests, checksums, storage keys, or item rows would be rewritten to include later external references.
- New serializers expose raw snapshots, raw external responses, credentials, storage keys, command output, artifact bytes, or private URLs.
- The implementation requires changing existing membership roles without a separate authorization design.
