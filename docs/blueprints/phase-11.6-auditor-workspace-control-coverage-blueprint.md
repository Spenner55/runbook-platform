# Phase 11.6: Auditor Workspace, External References, and Control Coverage Blueprint

## 1. Phase Metadata

| Field | Value |
|---|---|
| Phase number | 11.6 |
| Phase name | Auditor workspace, external references, and control coverage |
| Objective | Add auditor-facing evidence search, read-only audit change detail views, external change references, service catalog metadata, control coverage mapping, and scoped auditor access. |
| Status | Blueprint only - do not implement code from this document without re-reading current source first |
| Depends on | Phases 11.1-11.5 complete and verified; Phases 01-10.9 complete |
| Authored | 2026-05-01 |
| Primary new app | `apps/api/apps/auditor/` |

This document is an implementation blueprint only. It intentionally does not implement code.

## 2. Executive Summary

Phase 11.6 creates the audit-facing workspace around already sealed production change evidence. It lets authorized auditors search persisted Django data, open read-only audit detail views, inspect external system references captured as snapshots, and review deterministic control coverage computed from sealed evidence bundle sections.

The implementation adds a new Django app:

- `apps/api/apps/auditor/`

It introduces five model families:

- `ExternalChangeReference`
- `ServiceCatalogEntry`
- `ControlMappingProfile`
- `ChangeControlCoverage`
- `AuditorAccessGrant`

The core behavior is:

1. Operators or admins link a `ChangeRecord` to external references from ServiceNow, Jira, PagerDuty, or custom systems.
2. Link time captures a bounded snapshot of the external reference. Search and audit detail pages read that persisted snapshot only.
3. External snapshots can be refreshed only by explicit on-demand action. Refresh never changes the change lifecycle, approval, execution, closure, or canonical evidence facts.
4. Service metadata is stored as a small audit-support catalog and can be associated with changes and targets for filtering.
5. Control coverage is computed deterministically from sealed evidence bundle sections and the active mapping profile.
6. Auditors use scoped, read-only grants that limit which services, targets, risks, statuses, and date ranges they can inspect.
7. Audit search and detail APIs return audit-ready projections without granting mutation paths to auditor users.

This phase does not build a generic GRC product, a ticketing workflow engine, a ServiceNow or Jira orchestration layer, or a full CMDB sync engine. External systems are references and mirrors only. The platform remains the source of truth for approval, execution, closure, evidence, and sealed bundle integrity.

## 3. Current-State Inspection Checklist

The following repository facts were inspected before writing this blueprint:

- [x] `docs/blueprints/phase-11.1-change-dossier-blueprint.md` defines `ChangeRecord`, `ChangeTarget`, `ChangeExecutionBinding`, operation profiles, lifecycle status, target production scope, immutable request snapshots, and Django-owned transitions.
- [x] `docs/blueprints/phase-11.5-sealed-evidence-bundles-blueprint.md` defines `EvidenceBundle`, `EvidenceBundleItem`, sealed bundle immutability, canonical section/item paths, completeness reports, redacted exports, legal hold, retention, and export receipts.
- [x] In this checkout, `apps/api/apps/changes/`, `apps/api/apps/evidence/`, and `apps/api/apps/authz/` are not present yet. Per this task's source context, Phase 11.6 implementation must assume Phases 11.1-11.5 are complete, then re-inspect the actual completed apps before coding.
- [x] `apps/api/apps/audit/models.py` defines append-only `AuditEvent`, object type choices, UUID object IDs, metadata, and database check constraints.
- [x] `apps/api/apps/audit/services.py` centralizes audit emission and metadata scrubbing. Phase 11.6 must extend object type choices and forbidden metadata keys for auditor grants, external snapshots, control mapping, and service catalog records.
- [x] `apps/api/apps/integrations/models.py` currently models delivery-oriented integrations, including PagerDuty. Phase 11.6 must not reuse delivery attempts as live search data or turn integration connections into ticket workflow state.
- [x] `apps/api/apps/common/org_context.py` enforces `X-Organization-Id` and query/body organization mismatch detection.
- [x] `apps/api/apps/common/permissions.py` currently has owner/admin/operator/viewer role helpers. Phase 11.6 needs a narrow auditor read path, preferably via the completed Phase 11 `authz` layer if it exists by implementation time.
- [x] `apps/api/config/api_v1_urls.py` registers public APIs under `/api/v1/` and internal runner APIs under `/api/v1/internal/`. Auditor APIs must be public Django APIs, not internal runner APIs.
- [x] `apps/web/src/shared/api/client.ts` blocks browser calls to `/api/v1/internal/` and injects `X-Organization-Id`.
- [x] `apps/web/src/features/` currently contains feature areas for approvals, artifacts, audit, executions, integrations, organizations, policies, runbooks, and workflows. Per the Phase 11 assumptions, implementation must re-inspect any added `changes` and `evidence` feature areas before adding auditor UI.
- [x] `apps/web/src/app/router.tsx` and `apps/web/src/app/AppLayout.tsx` currently have no auditor routes or navigation.

Drift note: this blueprint intentionally references the expected completed Phase 11.1-11.5 models. If the actual implementation names, fields, route layout, or RBAC primitives differ, update this blueprint before coding Phase 11.6.

## 4. Architecture Invariants

| Invariant | Phase 11.6 consequence |
|---|---|
| Django remains the control plane and source of truth. | Audit search, external reference persistence, control coverage computation, service catalog metadata, grant enforcement, and audit emission live in Django services/selectors. |
| External systems are references/mirrors only. | ServiceNow, Jira, PagerDuty, and custom references can be linked and snapshotted, but they cannot authorize, execute, close, verify, or mutate a `ChangeRecord`. |
| Search uses persisted Django data only. | `GET /api/v1/audit/changes/` must never call ServiceNow, Jira, PagerDuty, custom URLs, AI services, or runner/internal APIs. |
| On-demand refresh only. | External snapshots update only through an explicit refresh service/API added in implementation if needed. There is no background sync, polling loop, webhook-driven rewrite, or automatic search-time refresh. |
| Auditor role is read-only. | Auditor users and auditor access grants can call only `GET` audit workspace endpoints. They cannot create changes, approve, execute, verify, close, seal, export, refresh snapshots, or recompute control coverage. |
| Scoped grants are enforced server-side. | Every audit search/detail queryset intersects organization membership with active `AuditorAccessGrant` scope before returning results. UI filtering is only a convenience. |
| Sealed evidence remains authoritative. | Control coverage is computed from sealed `EvidenceBundle` sections and `EvidenceBundleItem` metadata. Unsealed or compiling bundles cannot satisfy final coverage. |
| AI summaries are non-authoritative. | If displayed, AI text must be labeled and serialized as supplemental metadata. It must not affect coverage, status, completeness, or grant decisions. |
| Do not build a generic GRC product. | Control mapping supports narrow evidence coverage for production change controls only. No policy attestation campaigns, vendor risk, audit project management, questionnaire workflow, or arbitrary control lifecycle management. |
| Do not build ITSM workflow orchestration. | No ServiceNow/Jira/PagerDuty status transitions, assignments, approvals, comments-as-approval, SLA workflows, or bidirectional ticket synchronization. |
| Do not build a CMDB sync engine. | `ServiceCatalogEntry` is small, manually/API-maintained metadata for audit filtering and ownership context. It is not a full configuration item graph. |
| Tenant boundaries are mandatory. | Every model includes `organization`; all FKs must match organization; all selectors filter by organization and grant scope. |
| Evidence metadata stays sanitized. | Audit events and snapshots must omit tokens, credentials, headers, raw request bodies, raw API responses, secrets, private URLs with credentials, and oversized payloads. |

## 5. Data Model Design

### 5.1 New Auditor App Structure

Create:

```text
apps/api/apps/auditor/
  __init__.py
  apps.py
  admin.py
  models.py
  selectors.py
  serializers.py
  services.py
  urls.py
  views.py
  external_clients.py
  coverage.py
  access.py
  migrations/
    __init__.py
  tests/
    __init__.py
    conftest.py
    test_access.py
    test_api_audit_changes.py
    test_control_coverage.py
    test_external_references.py
    test_models.py
    test_no_live_calls.py
```

Recommended module responsibilities:

- `models.py`: persistence, `TextChoices`, constraints, indexes, and narrow immutability guards.
- `selectors.py`: organization-scoped, grant-scoped read querysets and audit detail projections.
- `services.py`: create external references, snapshot refresh, service catalog changes, grant creation, coverage recomputation, audit emission, and cross-org validation.
- `external_clients.py`: adapter interfaces for explicit snapshot refresh only. Tests must prove search selectors do not import or call this module.
- `coverage.py`: deterministic bundle-section-to-control computation.
- `access.py`: helper functions that resolve active auditor grants and apply scope restrictions to querysets.
- `serializers.py`: public request/response shapes.
- `views.py`: public API views that validate input, assert roles/grants, and call selectors/services.
- `urls.py`: public auditor and change-adjacent routes for inclusion under `/api/v1/`.

### 5.2 Required Enumerations

External reference systems:

- `servicenow`
- `jira`
- `pagerduty`
- `custom`

Reference types:

- `ticket`
- `incident`
- `problem`
- `cmdb_ci`
- `release`

Control standards:

- `soc2`
- `iso27001`
- `nist`
- `custom`

Control coverage statuses:

- `covered`
- `partially_covered`
- `not_covered`
- `not_applicable`
- `stale`

Auditor grant statuses:

- `active`
- `expired`
- `revoked`

These values must be implemented as `models.TextChoices` and enforced with database check constraints. Do not use free-form status/system/standard strings.

### 5.3 `ExternalChangeReference`

`ExternalChangeReference` links one `ChangeRecord` to one external reference and stores a sanitized snapshot for audit display.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `change_record` | FK -> `changes.ChangeRecord`, `PROTECT`, related name `external_references` | Source change. |
| `system` | `CharField(32)` | `servicenow`, `jira`, `pagerduty`, or `custom`. |
| `reference_type` | `CharField(32)` | `ticket`, `incident`, `problem`, `cmdb_ci`, or `release`. |
| `external_id` | `CharField(255)` | Stable external key or sys_id. |
| `external_key` | `CharField(255, blank=True)` | Human-readable key such as `CHG0012345` or `PROJ-123`. |
| `display_label` | `CharField(255)` | UI label derived from system/key/type. |
| `external_url` | `URLField(max_length=2048, blank=True)` | Sanitized deep link. Must reject credential-bearing URLs. |
| `snapshot` | `JSONField(default=dict)` | Bounded, sanitized mirror fields only. |
| `snapshot_sha256` | `CharField(64, blank=True)` | Hash of canonical snapshot JSON. |
| `snapshot_source` | `CharField(32)` | `manual`, `api_refresh`, or `imported`. |
| `snapshot_status` | `CharField(32)` | Suggested: `current`, `stale`, `refresh_failed`, `unavailable`. |
| `snapshot_taken_at` | `DateTimeField(null=True, blank=True)` | Set at link and refresh time. |
| `last_refresh_attempted_at` | `DateTimeField(null=True, blank=True)` | Explicit refresh tracking. |
| `last_refresh_error_code` | `CharField(64, blank=True)` | Structured code only. No raw exception secrets. |
| `linked_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor who linked it. |
| `notes` | `TextField(blank=True)` | Optional internal note, not authoritative evidence. |

Recommended constraints and indexes:

- unique `(organization, change_record, system, reference_type, external_id)`;
- index `(organization, system, reference_type)`;
- index `(organization, external_key)`;
- index `(change_record, system)`;
- check `system` in required external reference systems;
- check `reference_type` in required reference types;
- service invariant: `organization_id == change_record.organization_id`;
- service invariant: duplicate references are prevented before insert and by database constraint;
- service invariant: snapshots cannot include credentials, authorization headers, raw API response bodies, or fields larger than the configured snapshot budget.

The snapshot should contain a bounded schema such as:

```json
{
  "title": "string",
  "state": "string",
  "priority": "string",
  "owner": "string",
  "service": "string",
  "updated_at": "UTC datetime string",
  "created_at": "UTC datetime string",
  "summary": "short sanitized text",
  "source_fields": {
    "safe_field_name": "safe scalar value"
  }
}
```

Do not copy comments, attachments, credentials, authorization material, full ticket histories, private user profile data, or arbitrary nested external payloads into `snapshot`.

### 5.4 `ServiceCatalogEntry`

`ServiceCatalogEntry` stores small service metadata used for audit filtering and context. It is not a CMDB graph.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `service_key` | `SlugField(128)` | Stable per-organization key. |
| `name` | `CharField(255)` | Human-readable service name. |
| `description` | `TextField(blank=True)` | Short service context. |
| `owner_team` | `CharField(255, blank=True)` | Audit context only. |
| `business_owner` | `CharField(255, blank=True)` | Audit context only. |
| `criticality` | `CharField(32, blank=True)` | Suggested values: `low`, `medium`, `high`, `critical`; do not over-model in v1. |
| `environment` | `CharField(64, blank=True)` | Example: `production`, `staging`. |
| `target_patterns` | `JSONField(default=list)` | Optional exact/prefix patterns used to map `ChangeTarget` values. |
| `metadata` | `JSONField(default=dict)` | Safe tags only, no CMDB object graph. |
| `is_active` | `BooleanField(default=True)` | Inactive services remain historical filter values. |
| `created_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor. |
| `updated_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor. |

Recommended constraints and indexes:

- unique `(organization, service_key)`;
- index `(organization, is_active, service_key)`;
- index `(organization, criticality)`;
- service invariant: `target_patterns` is a list of bounded strings/objects; no remote query expressions;
- service invariant: catalog metadata is optional context and cannot override `ChangeTarget` truth.

If Phase 11.1 already stores `service` on `ChangeRecord` or `ChangeTarget`, keep `ServiceCatalogEntry` additive. Do not migrate change identity into the catalog.

### 5.5 `ControlMappingProfile`

`ControlMappingProfile` defines how sealed bundle sections satisfy production change evidence controls for one organization.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `key` | `SlugField(128)` | Stable profile key. |
| `name` | `CharField(255)` | Human-readable profile name. |
| `standard` | `CharField(32)` | `soc2`, `iso27001`, `nist`, or `custom`. |
| `version` | `PositiveIntegerField(default=1)` | Increment when mappings change. |
| `description` | `TextField(blank=True)` | Profile context. |
| `mapping_rules` | `JSONField(default=list)` | Deterministic rules from control IDs to required sealed bundle sections/items. |
| `is_active` | `BooleanField(default=True)` | Only active profiles are default candidates. |
| `created_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor. |
| `updated_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor. |

Recommended constraints and indexes:

- unique `(organization, key, version)`;
- index `(organization, standard, is_active)`;
- check `standard` in required control standards;
- service invariant: at most one active `(organization, standard, key)` version unless implementation deliberately supports explicit profile selection;
- service invariant: `mapping_rules` references sealed bundle section keys and item types, not arbitrary model fields or external live systems.

Recommended `mapping_rules` shape:

```json
[
  {
    "control_id": "CC8.1",
    "control_title": "Change authorization",
    "standard": "soc2",
    "required_sections": ["request", "approval", "policy_decision"],
    "optional_sections": ["external_references"],
    "required_item_types": ["change_snapshot", "approval", "policy_decision"],
    "applicability": {
      "risk": ["high", "critical"],
      "change_type": ["standard", "emergency"]
    }
  }
]
```

Keep mappings declarative and small. Do not add expression languages, custom Python hooks, workflow-specific control engines, or multi-tenant mapping templates in Phase 11.6.

### 5.6 `ChangeControlCoverage`

`ChangeControlCoverage` stores the deterministic result of applying a mapping profile to one sealed bundle/change.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `change_record` | FK -> `changes.ChangeRecord`, `PROTECT`, related name `control_coverages` | Source change. |
| `evidence_bundle` | FK -> `evidence.EvidenceBundle`, `PROTECT`, related name `control_coverages` | Sealed bundle used for computation. |
| `mapping_profile` | FK -> `ControlMappingProfile`, `PROTECT`, related name `coverages` | Profile version used. |
| `standard` | `CharField(32)` | Copied from profile for filtering. |
| `control_id` | `CharField(128)` | Example: `CC8.1`, `A.8.32`, `CM-3`. |
| `control_title` | `CharField(255, blank=True)` | Copied from mapping rule. |
| `coverage_status` | `CharField(32)` | `covered`, `partially_covered`, `not_covered`, `not_applicable`, or `stale`. |
| `matched_sections` | `JSONField(default=list)` | Deterministic list of sealed section keys/items found. |
| `missing_sections` | `JSONField(default=list)` | Deterministic list of required section keys/items missing. |
| `evidence_paths` | `JSONField(default=list)` | Canonical bundle paths/pointers supporting the result. |
| `coverage_fingerprint_sha256` | `CharField(64)` | Hash of canonical inputs and result payload. |
| `computed_at` | `DateTimeField` | Persisted time. |
| `computed_by` | FK -> `users.User`, nullable, `SET_NULL` | Actor or system. |

Recommended constraints and indexes:

- unique `(evidence_bundle, mapping_profile, control_id)`;
- index `(organization, standard, control_id)`;
- index `(organization, change_record, standard)`;
- index `(organization, coverage_status)`;
- check `standard` in required control standards;
- check `coverage_status` in required coverage statuses;
- service invariant: `evidence_bundle.status == "sealed"`;
- service invariant: all organization IDs match;
- service invariant: recomputation for unchanged sealed bundle + unchanged profile version produces identical coverage rows except `computed_at` and `computed_by`.

### 5.7 `AuditorAccessGrant`

`AuditorAccessGrant` defines a scoped read-only audit workspace permission. It must not replace organization membership for admins/operators; it restricts auditor-specific access.

Recommended fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | Use existing `BaseModel`. |
| `organization` | FK -> `organizations.Organization`, `PROTECT` | Tenant boundary. |
| `user` | FK -> `users.User`, `CASCADE`, related name `auditor_access_grants` | Auditor principal. |
| `status` | `CharField(32)` | `active`, `expired`, or `revoked`. |
| `scope` | `JSONField(default=dict)` | Server-enforced scope definition. |
| `reason` | `TextField(blank=True)` | Why access was granted. |
| `starts_at` | `DateTimeField(null=True, blank=True)` | Optional not-before time. |
| `expires_at` | `DateTimeField(null=True, blank=True)` | Optional expiry. Strongly recommended. |
| `created_by` | FK -> `users.User`, nullable, `SET_NULL`, related name `created_auditor_grants` | Admin actor. |
| `revoked_by` | FK -> `users.User`, nullable, `SET_NULL`, related name `revoked_auditor_grants` | Admin actor. |
| `revoked_at` | `DateTimeField(null=True, blank=True)` | Revocation time. |
| `last_used_at` | `DateTimeField(null=True, blank=True)` | Optional observability. Update outside search transaction if needed. |

Recommended constraints and indexes:

- index `(organization, user, status)`;
- index `(organization, status, expires_at)`;
- check `status` in required grant statuses;
- service invariant: grant creation requires organization admin/owner;
- service invariant: grant does not grant mutation permissions;
- service invariant: expired grants are treated as inactive even before status cleanup;
- service invariant: `revoked` requires `revoked_at`.

Recommended `scope` shape:

```json
{
  "service_keys": ["payments-api"],
  "target_ids": ["prod-cluster-a"],
  "risk_levels": ["high", "critical"],
  "statuses": ["closed", "verified"],
  "change_types": ["standard", "emergency"],
  "bundle_statuses": ["sealed"],
  "date_from": "2026-01-01T00:00:00Z",
  "date_to": "2026-03-31T23:59:59Z",
  "include_exceptions": true
}
```

Empty arrays must mean no access for that dimension unless the scope explicitly uses `"all": true` for a vetted dimension. Avoid ambiguous empty-means-all behavior.

## 6. Audit Search Design

### 6.1 Search Endpoint Purpose

`GET /api/v1/audit/changes/` returns a paginated, auditor-safe list projection of production change evidence. It is optimized for evidence discovery and sampling, not for operating the change lifecycle.

Search must be backed by Django-controlled persisted data:

- `ChangeRecord` request/status/risk/change type fields from Phase 11.1+;
- `ChangeTarget` target data from Phase 11.1+;
- service mapping from `ServiceCatalogEntry` or persisted change/target service fields;
- `EvidenceBundle` sealed status/completeness from Phase 11.5;
- `ChangeException` or exception metadata from Phase 11.4;
- `ExternalChangeReference` persisted snapshots;
- `ChangeControlCoverage` persisted rows.

It must not call:

- ServiceNow;
- Jira;
- PagerDuty;
- custom external URLs;
- AI service endpoints;
- runner/internal APIs;
- artifact storage byte reads unless the query explicitly needs bundle metadata already persisted in DB.

### 6.2 Required Filters

Support these query filters:

| Filter | Query parameter | Data source | Notes |
|---|---|---|---|
| service | `service` | `ServiceCatalogEntry.service_key` or change/target service snapshot | Accept exact keys. No fuzzy external search in v1. |
| target | `target` | `ChangeTarget` persisted identifier/name | Exact or bounded `icontains` depending existing target fields. |
| risk | `risk` | change risk/risk level | Match Phase 11 risk vocabulary. |
| status | `status` | `ChangeRecord.status` | Auditors commonly filter `closed`, `verified`, `verification_pending`. |
| change type | `change_type` | Phase 11 change type/exception fields | Match existing Phase 11 values. |
| approver | `approver` | approval decision user snapshot | Use persisted approval records only. |
| executor | `executor` | execution binding/runner/user snapshot | Use persisted execution facts only. |
| start date | `start_date` | scheduled/submitted/running/closed timestamp | Implementation must choose one documented date basis, preferably `submitted_at` default with explicit `date_basis`. |
| end date | `end_date` | same as start date | Inclusive or exclusive semantics must be documented and tested. |
| has exception | `has_exception` | Phase 11.4 `ChangeException`/breakglass/retro review | Boolean. |
| bundle status | `bundle_status` | latest `EvidenceBundle.status` | At minimum support `sealed`, `compiling`, `invalidated`, `missing`. |

Recommended additional query parameters:

- `standard`: filter by `ChangeControlCoverage.standard`;
- `control_id`: filter by control ID;
- `coverage_status`: filter by coverage status;
- `external_system`: filter by linked external reference system;
- `limit` and `offset`: use the existing audit pagination style;
- `ordering`: constrained values only, such as `-submitted_at`, `submitted_at`, `-closed_at`, `risk`.

### 6.3 Grant Scope Intersection

Search results must satisfy both:

1. user is authenticated and belongs to the organization or has a recognized auditor membership path from Phase 11 authz; and
2. user has an active `AuditorAccessGrant` whose scope includes the row, unless the user is an organization admin/owner using admin audit mode.

Grant scope intersection rules:

- services: result service must be in grant service set;
- targets: at least one target must be in grant target set;
- risks: change risk must be allowed;
- statuses: change status must be allowed;
- change types: change type must be allowed;
- bundle statuses: latest bundle status must be allowed;
- dates: the search date basis must fall within grant date bounds;
- exceptions: if grant disallows exceptions, exception-bearing changes are excluded.

If multiple active grants exist, access is the union of grant scopes after each grant's own date/status restrictions are applied. Do not merge scopes dimension-by-dimension in a way that creates broader access than any single grant grants.

### 6.4 List Projection

Recommended list item shape:

```json
{
  "id": "uuid",
  "title": "string",
  "status": "closed",
  "risk": "high",
  "change_type": "standard",
  "service": {
    "service_key": "payments-api",
    "name": "Payments API"
  },
  "targets": [
    {"id": "uuid", "label": "prod-cluster-a", "type": "kubernetes_cluster"}
  ],
  "submitted_at": "datetime",
  "approved_at": "datetime",
  "closed_at": "datetime",
  "has_exception": false,
  "bundle": {
    "id": "uuid",
    "status": "sealed",
    "completeness_status": "complete",
    "version": 1
  },
  "external_references": [
    {"system": "jira", "reference_type": "ticket", "external_key": "PROJ-123"}
  ],
  "coverage_summary": {
    "soc2": {"covered": 4, "partially_covered": 1, "not_covered": 0}
  }
}
```

The list projection should include counts, statuses, IDs, labels, and hashes. It should not include raw evidence payloads, artifact bytes, full external snapshots, or long audit trails.

## 7. External Reference Link-and-Snapshot Design

### 7.1 Link Behavior

`POST /api/v1/changes/{id}/external-references/` links a persisted external reference to a change. This endpoint is for operators/admins, not auditors.

Required input:

```json
{
  "system": "jira",
  "reference_type": "ticket",
  "external_id": "10001",
  "external_key": "PROJ-123",
  "external_url": "https://jira.example.com/browse/PROJ-123",
  "snapshot": {
    "title": "Production change ticket",
    "state": "Done",
    "priority": "High"
  },
  "notes": "Optional internal context"
}
```

Service rules:

- assert organization operator/admin permission;
- load the `ChangeRecord` by organization and ID;
- validate `system` and `reference_type`;
- normalize `external_id`, `external_key`, and URL;
- sanitize `snapshot`;
- compute `snapshot_sha256` from canonical JSON;
- prevent duplicates with service validation and DB uniqueness;
- emit `external_reference.linked` audit event on the change and/or reference object;
- do not mutate change status, approval status, execution status, closure status, bundle status, or control coverage automatically.

### 7.2 Snapshot Behavior

Snapshots are evidence-adjacent mirrors. They can show what the external ticket/reference said at link or refresh time, but they are not authoritative for platform decisions.

Allowed snapshot fields:

- title/summary;
- state/status label;
- priority/severity label;
- owner/team label;
- service label;
- created/updated/resolved timestamps;
- safe scalar fields configured per adapter;
- source URL and external display key.

Forbidden snapshot fields:

- authorization headers, cookies, tokens, credentials, private keys;
- raw API response bodies;
- comments or attachments copied wholesale;
- user emails unless already approved as safe metadata by the existing privacy/security policy;
- full workflow histories;
- ticket approval decisions used as platform approvals;
- command text, runner output, or evidence artifact bytes.

### 7.3 On-Demand Refresh Only

Implement a refresh service but keep it explicitly invoked. The public refresh endpoint is optional for Phase 11.6 unless product requirements need it; if added, it should be admin/operator-only:

```text
POST /api/v1/changes/{id}/external-references/{reference_id}/refresh/
```

Refresh rules:

- refresh may call external adapters only inside this explicit service path;
- refresh uses configured integration credentials where available;
- refresh updates only snapshot fields, hash, status, and refresh timestamps;
- refresh emits `external_reference.snapshot_refreshed` or `external_reference.snapshot_refresh_failed`;
- refresh failures do not break audit search or detail views;
- refresh must not run from list/detail serializers, selectors, or React page load effects.

Tests must monkeypatch external clients and assert `GET /api/v1/audit/changes/` and `GET /api/v1/audit/changes/{id}/` make zero external client calls.

## 8. Control Coverage Mapping Design

### 8.1 Source of Coverage

Control coverage is derived from sealed evidence bundles created in Phase 11.5. The coverage computation must inspect persisted bundle metadata and bundle item rows, not mutable live change state.

Authoritative inputs:

- sealed `EvidenceBundle.status == "sealed"`;
- `EvidenceBundle.completeness_status`;
- `EvidenceBundle.manifest`;
- `EvidenceBundleItem.item_type`;
- `EvidenceBundleItem.canonical_path`;
- `EvidenceBundleItem.json_pointer`;
- `EvidenceBundleItem.present`;
- `EvidenceBundleItem.valid`;
- `EvidenceBundleItem.content_sha256`;
- selected `ControlMappingProfile.mapping_rules`.

Non-authoritative inputs:

- AI summaries;
- external ticket state;
- unsealed bundle projections;
- live ServiceNow/Jira/PagerDuty/custom calls;
- UI labels.

### 8.2 Computation Algorithm

For each mapping rule:

1. Determine applicability using persisted change metadata copied into or associated with the sealed bundle. If not applicable, create/update coverage row as `not_applicable`.
2. Resolve required sections and item types against sealed `EvidenceBundleItem` rows.
3. A section/item counts as matched only when it is present, valid, belongs to the same organization/bundle, and references a canonical path or JSON pointer in the sealed manifest.
4. If every required section/item is matched, status is `covered`.
5. If at least one but not all required section/items are matched, status is `partially_covered`.
6. If no required section/items are matched, status is `not_covered`.
7. If the bundle has been invalidated after computation, or the profile version is no longer active and implementation chooses to flag old rows, mark existing rows `stale` only through an explicit service path.
8. Store deterministic `matched_sections`, `missing_sections`, `evidence_paths`, and `coverage_fingerprint_sha256`.

The fingerprint should hash canonical JSON containing:

- organization ID;
- change ID;
- evidence bundle ID and `content_sha256`;
- mapping profile ID and version;
- control ID;
- sorted matched/missing/evidence path arrays;
- final coverage status.

Exclude `computed_at` and actor fields from the fingerprint.

### 8.3 Recompute Behavior

`POST /api/v1/changes/{id}/control-coverage/recompute/` recomputes coverage for a change's selected sealed bundle and mapping profile.

Rules:

- endpoint is admin/operator-only, not auditor-callable;
- require a sealed bundle, or return a validation error such as `sealed_bundle_required`;
- default to latest sealed non-invalidated bundle unless request specifies `evidence_bundle_id`;
- default to active mapping profiles unless request specifies `mapping_profile_id`;
- perform the operation in a transaction;
- upsert coverage rows by `(evidence_bundle, mapping_profile, control_id)`;
- delete or mark stale rows for controls no longer present in the selected profile according to a documented service rule;
- emit `control_coverage.recomputed` with counts and fingerprints only;
- do not mutate the sealed bundle, change status, approvals, execution, closure, or external references.

Determinism tests must recompute twice from unchanged inputs and assert identical statuses, matched/missing arrays, evidence paths, and fingerprints.

## 9. Auditor Access/RBAC Design

### 9.1 Role Model

Use the completed Phase 11 authz implementation if it already introduced fine-grained roles. If the repository still has only `MembershipRole` values from earlier phases, add the narrowest compatible auditor access path:

- either add `auditor` as a membership role, if the existing authz design expects organization roles; or
- keep roles unchanged and require `AuditorAccessGrant` for users with base viewer membership.

Prefer not to expand admin/operator powers. The key invariant is that auditor access is read-only and server-scoped.

### 9.2 Permission Matrix

| Action | Owner/Admin | Operator | Auditor with grant | Viewer without grant |
|---|---:|---:|---:|---:|
| Search audit changes | Yes | Optional per product policy | Yes, scoped | No unless existing viewer policy allows read-only audit |
| View audit change detail | Yes | Optional per product policy | Yes, scoped | No unless existing viewer policy allows read-only audit |
| Link external reference | Yes | Yes | No | No |
| Refresh external snapshot | Yes | Yes | No | No |
| Recompute control coverage | Yes | Yes | No | No |
| Create auditor access grant | Yes | No | No | No |
| Revoke auditor access grant | Yes | No | No | No |
| Mutate change lifecycle | Existing Phase 11 rules | Existing Phase 11 rules | No | No |

### 9.3 Grant Enforcement

Every auditor selector must:

- require `X-Organization-Id`;
- resolve active grants for `request.user`;
- filter out expired/revoked/not-yet-started grants;
- build a queryset for each grant scope and union the allowed querysets;
- apply requested filters after or within grant scope without widening access;
- return 404 for detail rows outside scope, not a distinguishable 403 that leaks existence;
- emit minimal access audit events if required by product policy, avoiding per-row audit storms in list views.

Admin grant management must emit:

- `auditor_access_grant.created`;
- `auditor_access_grant.revoked`;
- `auditor_access_grant.expired` only if an explicit cleanup command/service changes status.

## 10. API Design

### 10.1 `GET /api/v1/audit/changes/`

Purpose: auditor-facing search over persisted production change evidence.

Permissions:

- authenticated;
- organization context required;
- admin/operator according to product policy, or active auditor grant;
- auditor results scoped by grant.

Query parameters:

- `service`
- `target`
- `risk`
- `status`
- `change_type`
- `approver`
- `executor`
- `start_date`
- `end_date`
- `date_basis`
- `has_exception`
- `bundle_status`
- `standard`
- `control_id`
- `coverage_status`
- `external_system`
- `limit`
- `offset`
- `ordering`

Response:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "uuid",
      "title": "Deploy payments service",
      "status": "closed",
      "risk": "high",
      "change_type": "standard",
      "service": {"service_key": "payments-api", "name": "Payments API"},
      "targets": [{"id": "uuid", "label": "prod-cluster-a", "type": "cluster"}],
      "submitted_at": "2026-05-01T10:00:00Z",
      "approved_at": "2026-05-01T10:15:00Z",
      "closed_at": "2026-05-01T11:00:00Z",
      "has_exception": false,
      "bundle": {"id": "uuid", "status": "sealed", "completeness_status": "complete", "version": 1},
      "coverage_summary": {"soc2": {"covered": 4, "partially_covered": 0, "not_covered": 0}},
      "external_references": [{"system": "jira", "reference_type": "ticket", "external_key": "PROJ-123"}]
    }
  ]
}
```

### 10.2 `GET /api/v1/audit/changes/{id}/`

Purpose: read-only audit detail projection for one change.

Permissions:

- same as list;
- return 404 if outside grant scope.

Response sections:

- change summary and immutable request snapshot metadata;
- target list and service metadata;
- approval facts and approver identities already safe to display;
- execution binding and executor/runner facts;
- verification/closure facts;
- exception/breakglass/retro review summary if present and grant allows exceptions;
- latest sealed bundle metadata, manifest hash, content hash, completeness report summary;
- external references with sanitized snapshots;
- control coverage rows grouped by standard/profile/control;
- audit event timeline summary or link to existing audit event endpoint, scoped to safe metadata only;
- AI summary only if already persisted as non-authoritative supplemental text.

Do not include:

- raw command output;
- artifact bytes;
- secrets;
- dispatch tokens;
- runner bearer tokens;
- raw external payloads;
- unredacted exports unless the user is explicitly authorized by existing evidence export permissions.

### 10.3 `POST /api/v1/changes/{id}/external-references/`

Purpose: operator/admin creates a link-and-snapshot external reference.

Permissions:

- authenticated organization operator/admin;
- auditors cannot call.

Request fields:

- `system`;
- `reference_type`;
- `external_id`;
- `external_key`;
- `external_url`;
- `display_label`;
- `snapshot`;
- `notes`.

Response: serialized `ExternalChangeReference`.

Errors:

- `duplicate_external_reference`;
- `invalid_reference_system`;
- `invalid_reference_type`;
- `unsafe_external_url`;
- `snapshot_too_large`;
- `change_not_found`;
- `organization_mismatch`.

### 10.4 `POST /api/v1/changes/{id}/control-coverage/recompute/`

Purpose: recompute deterministic control coverage from sealed evidence bundle sections.

Permissions:

- authenticated organization operator/admin;
- auditors cannot call.

Request fields:

- optional `evidence_bundle_id`;
- optional `mapping_profile_id`;
- optional `standard`.

Response:

```json
{
  "change_id": "uuid",
  "evidence_bundle_id": "uuid",
  "mapping_profile_id": "uuid",
  "created": 4,
  "updated": 0,
  "stale": 0,
  "coverage": [
    {
      "standard": "soc2",
      "control_id": "CC8.1",
      "coverage_status": "covered",
      "coverage_fingerprint_sha256": "hex"
    }
  ]
}
```

Errors:

- `sealed_bundle_required`;
- `mapping_profile_required`;
- `mapping_rule_invalid`;
- `organization_mismatch`;
- `change_not_found`.

### 10.5 `POST /api/v1/auditor-access-grants/`

Purpose: admin creates scoped read-only access for an auditor user.

Permissions:

- authenticated organization admin/owner only.

Request fields:

- `user_id` or `email` according to existing user APIs;
- `scope`;
- `reason`;
- `starts_at`;
- `expires_at`.

Response: serialized grant with normalized scope and computed status.

Recommended companion endpoints, if consistent with repo patterns:

- `GET /api/v1/auditor-access-grants/` for admin grant management;
- `GET /api/v1/auditor-access-grants/{id}/`;
- `POST /api/v1/auditor-access-grants/{id}/revoke/`.

Only `POST /api/v1/auditor-access-grants/` is required by this phase prompt. Revoke/list/detail can be included if needed for the admin UI, but keep them narrow.

## 11. Frontend Impact

### 11.1 Feature Area

Add a focused frontend feature area:

```text
apps/web/src/features/auditor/
  api/auditorApi.ts
  hooks/useAuditChanges.ts
  hooks/useAuditChangeDetail.ts
  hooks/useCreateExternalReference.ts
  hooks/useRecomputeControlCoverage.ts
  hooks/useCreateAuditorAccessGrant.ts
  types.ts
```

If Phase 11.1-11.5 created `features/changes` or `features/evidence`, reuse their shared types rather than duplicating large model shapes.

### 11.2 Routes and Pages

Add route pages:

```text
apps/web/src/routes/auditor/AuditorSearchPage.tsx
apps/web/src/routes/auditor/AuditChangeDetailPage.tsx
apps/web/src/routes/auditor/AuditorAccessAdminPage.tsx
```

Recommended routes:

- `/audit/changes`
- `/audit/changes/:changeId`
- `/audit/access`

Navigation should expose audit workspace links only to users who are admins/operators or have active auditor access. The backend remains authoritative; frontend hiding is not security.

### 11.3 Auditor Search Page

Build a dense, work-focused search interface:

- filter bar for service, target, risk, status, change type, approver, executor, date range, exception flag, and bundle status;
- optional control filters for standard/control/coverage;
- result table with status, risk, service, targets, dates, bundle status, exception indicator, and coverage summary;
- pagination using API `count/next/previous` pattern;
- no live external refresh on page load;
- no mutation controls when user is acting as auditor.

### 11.4 Audit Change Detail Page

Build a read-only detail page with tabs or sections:

- Overview;
- Evidence bundle;
- External references;
- Control coverage;
- Timeline/audit events;
- Exceptions if present and authorized.

The detail page must not present lifecycle action buttons to auditor users. If admins/operators see link/recompute actions on the same page, conditionally render them from explicit permissions and still rely on backend checks.

### 11.5 External References Panel

The panel displays:

- system icon/label;
- reference type;
- external key and sanitized link;
- snapshot title/state/priority/owner/updated timestamp;
- snapshot hash and snapshot timestamp;
- refresh status.

For operator/admin contexts, include an add-reference form. Do not auto-refresh snapshots from this panel.

### 11.6 Control Coverage Tab

The tab displays:

- grouped standards (`soc2`, `iso27001`, `nist`, `custom`);
- profile name/version;
- control ID/title;
- coverage status;
- matched/missing sections;
- canonical evidence paths/pointers;
- fingerprint hash.

For operator/admin contexts, include a recompute button. Auditor users see read-only coverage only.

### 11.7 Auditor Access Admin Page

Build an admin-only page for grant creation:

- select user or enter email, matching existing user lookup capabilities;
- define scope dimensions: service, target, risk, status, change type, bundle status, date range, include exceptions;
- set reason and expiry;
- list current grants if companion list endpoint is implemented;
- revoke grants if companion revoke endpoint is implemented.

Avoid generic RBAC builders. The form should map directly to `AuditorAccessGrant.scope`.

## 12. File-by-File Implementation Plan

### 12.1 Backend App Files

| File | Plan |
|---|---|
| `apps/api/apps/auditor/__init__.py` | Create empty app marker. |
| `apps/api/apps/auditor/apps.py` | Define `AuditorConfig`. |
| `apps/api/apps/auditor/models.py` | Add the five models, enums, indexes, constraints, and narrow validation helpers described above. |
| `apps/api/apps/auditor/admin.py` | Register models with read/search fields useful for local inspection. Keep snapshots read-only in admin after creation unless service method is used. |
| `apps/api/apps/auditor/selectors.py` | Implement grant-scoped audit search queryset, detail lookup, latest bundle subqueries, coverage summaries, and no-live-call projections. |
| `apps/api/apps/auditor/access.py` | Resolve active grants, evaluate scope dictionaries, and apply grant union safely without dimension widening. |
| `apps/api/apps/auditor/services.py` | Implement external reference link, optional snapshot refresh, service catalog save helpers, mapping profile validation, coverage recomputation wrapper, grant creation/revocation, and audit emission. |
| `apps/api/apps/auditor/coverage.py` | Implement deterministic sealed bundle coverage algorithm and fingerprinting. |
| `apps/api/apps/auditor/external_clients.py` | Define adapter interface and provider stubs for explicit snapshot refresh only. Search/detail code must not call these adapters. |
| `apps/api/apps/auditor/serializers.py` | Add query serializers, list/detail serializers, create external reference serializer, recompute serializer, coverage serializer, grant create serializer, and grant response serializer. |
| `apps/api/apps/auditor/views.py` | Add API views for required endpoints. Views should be thin and call selectors/services. |
| `apps/api/apps/auditor/urls.py` | Export public URL patterns for audit changes, external reference creation, recompute, and grant creation. |
| `apps/api/apps/auditor/tests/conftest.py` | Provide factories/fixtures for orgs, users, changes, sealed bundles, references, mappings, coverages, and grants. |
| `apps/api/apps/auditor/tests/test_api_audit_changes.py` | Cover search/detail filters and response scoping. |
| `apps/api/apps/auditor/tests/test_external_references.py` | Cover link snapshot sanitization, hashing, duplicates, and refresh isolation. |
| `apps/api/apps/auditor/tests/test_control_coverage.py` | Cover deterministic coverage, sealed-bundle requirement, and recompute API. |
| `apps/api/apps/auditor/tests/test_access.py` | Cover auditor read-only behavior and scope restrictions. |
| `apps/api/apps/auditor/tests/test_no_live_calls.py` | Assert search/detail never call external clients. |

### 12.2 Existing Backend Files

| File | Plan |
|---|---|
| `apps/api/config/settings/base.py` | Add `apps.auditor` to `INSTALLED_APPS` after confirmed Phase 11 apps. |
| `apps/api/config/api_v1_urls.py` | Include `apps.auditor.urls` under `/api/v1/` without placing browser endpoints under `/internal/`. |
| `apps/api/apps/audit/models.py` | Extend `AuditEvent.ObjectType` choices for `external_change_reference`, `service_catalog_entry`, `control_mapping_profile`, `change_control_coverage`, and `auditor_access_grant`; add migration. |
| `apps/api/apps/audit/services.py` | Extend `FORBIDDEN_METADATA_KEYS` for snapshot credentials, external auth, API response bodies, refresh tokens, and coverage internals if needed. |
| `apps/api/apps/common/permissions.py` or completed `apps/api/apps/authz/` | Add/read auditor permission helpers only if Phase 11 authz has not already provided them. Keep mutation denied for auditor role. |
| `apps/api/apps/changes/models.py` | Re-inspect only. Add optional service metadata linkage only if Phase 11.1-11.5 did not already provide a persisted service field needed for filtering. |
| `apps/api/apps/evidence/models.py` | Re-inspect only. Coverage code should rely on sealed bundle/item metadata and avoid changing bundle immutability behavior. |

### 12.3 Frontend Files

| File | Plan |
|---|---|
| `apps/web/src/features/auditor/types.ts` | Add API response/request types for audit change search/detail, external references, coverage, and grants. |
| `apps/web/src/features/auditor/api/auditorApi.ts` | Add typed calls for required APIs using shared `apiRequest`; never call `/api/v1/internal/`. |
| `apps/web/src/features/auditor/hooks/useAuditChanges.ts` | Query hook for search filters and pagination. |
| `apps/web/src/features/auditor/hooks/useAuditChangeDetail.ts` | Query hook for detail page. |
| `apps/web/src/features/auditor/hooks/useCreateExternalReference.ts` | Mutation hook for operator/admin link action. |
| `apps/web/src/features/auditor/hooks/useRecomputeControlCoverage.ts` | Mutation hook for operator/admin recompute action. |
| `apps/web/src/features/auditor/hooks/useCreateAuditorAccessGrant.ts` | Mutation hook for admin grant creation. |
| `apps/web/src/routes/auditor/AuditorSearchPage.tsx` | Implement search filters/table/pagination. |
| `apps/web/src/routes/auditor/AuditChangeDetailPage.tsx` | Implement read-only detail with external references and coverage tabs. |
| `apps/web/src/routes/auditor/AuditorAccessAdminPage.tsx` | Implement grant creation and optional grant list/revoke UI. |
| `apps/web/src/app/router.tsx` | Register `/audit/changes`, `/audit/changes/:changeId`, and `/audit/access`. |
| `apps/web/src/app/AppLayout.tsx` | Add audit navigation entry gated by local user permissions as a UX hint only. |
| `apps/web/src/routes/auditor/*.test.tsx` | Add focused render/filter/read-only tests using existing frontend test conventions. |

## 13. Migration Plan

Recommended migration sequence:

1. Create `apps.auditor` app and initial migration for `ServiceCatalogEntry`, `ExternalChangeReference`, `ControlMappingProfile`, `ChangeControlCoverage`, and `AuditorAccessGrant`.
2. Add audit object type choices for new auditor models in a separate audit migration if the existing audit app requires database check constraint replacement.
3. Add optional indexes after verifying actual Phase 11.1-11.5 field names and query plans.
4. Seed no default control mapping profiles automatically unless product has reviewed them. If defaults are needed, add a deliberate data migration with clearly labeled starter mappings and tests.
5. Do not backfill external references from existing integrations. External links must be deliberately created or imported by an explicit admin/operator process.
6. Do not backfill service catalog entries from external CMDB systems. Manual/API-created entries are sufficient for Phase 11.6.
7. Backfill coverage only through explicit recompute commands/API calls after sealed bundles exist. Do not compute coverage inside the migration.

Rollback considerations:

- dropping `apps.auditor` tables removes audit workspace metadata but must not modify `ChangeRecord`, `EvidenceBundle`, audit events, approvals, executions, or artifacts;
- evidence bundle integrity must remain valid if coverage rows are removed;
- external reference deletion should be restricted in product code, but DB rollback should not mutate external systems.

## 14. Testing Plan

### 14.1 Backend API and Selector Tests

Required tests:

- auditors can filter by date;
- auditors can filter by service;
- auditors can filter by target;
- auditors can filter by risk;
- auditors can filter by status;
- auditors can filter by exception flag;
- auditors can filter by bundle status;
- combined filters do not widen grant scope;
- detail endpoint returns 404 for changes outside auditor scope;
- admin/operator paths can see expected records according to product policy.

### 14.2 External Reference Tests

Required tests:

- external references snapshot correctly at link time;
- snapshots are sanitized and bounded;
- `snapshot_sha256` is stable for canonical-equivalent snapshot data;
- duplicate external reference is prevented by service validation and DB constraint;
- unsafe URLs and forbidden systems/types are rejected;
- refresh updates snapshot only when explicitly invoked;
- search/detail APIs make no live external calls.

### 14.3 Control Coverage Tests

Required tests:

- recomputation requires sealed bundle;
- coverage recomputation is deterministic for unchanged bundle/profile inputs;
- covered, partially covered, not covered, and not applicable statuses are produced from fixture bundle items;
- evidence paths reference sealed bundle canonical paths/pointers;
- coverage fingerprint excludes `computed_at`;
- invalidated bundle/profile drift is handled according to documented stale behavior.

### 14.4 RBAC Tests

Required tests:

- auditor role is read-only;
- auditor cannot link external references;
- auditor cannot refresh snapshots;
- auditor cannot recompute control coverage;
- auditor cannot create/revoke auditor grants;
- auditor scope restrictions are enforced for service, target, risk, status, date, exception, and bundle status;
- expired/revoked/not-yet-started grants deny access;
- multiple grants are unioned without dimension widening.

### 14.5 Frontend Tests

Required tests:

- auditor search sends the selected filters and renders returned rows;
- detail page renders read-only sections without mutation buttons for auditor users;
- external references panel renders persisted snapshot data and does not trigger refresh on mount;
- control coverage tab renders grouped controls and missing sections;
- grant admin form serializes scope correctly;
- API client paths stay under public `/api/v1/` and never use `/api/v1/internal/`.

Recommended commands after implementation:

```text
make test-api
make test-web
make lint
```

If Phase 11.6 touches production hardening checks, also run:

```text
make check-prod
make security-scan
```

## 15. Codex Implementation Batching Plan

Implementation should be split into small reviewable batches:

1. **Backend foundation**
   Add `apps.auditor`, models, migrations, admin registrations, audit object type updates, and basic service validation helpers. Tests: model constraints and serializer validation.

2. **External references**
   Implement link-and-snapshot service/API, snapshot sanitization, duplicate prevention, audit events, and no-live-call guard tests. Do not implement automatic refresh.

3. **Control mapping and coverage**
   Implement mapping profile validation, coverage algorithm, recompute API, deterministic fingerprinting, and sealed-bundle requirement tests.

4. **Auditor access enforcement**
   Implement grant creation API, active grant resolution, scope filtering, detail 404 behavior, read-only auditor denial tests, and multi-grant union tests.

5. **Audit search/detail APIs**
   Implement list/detail serializers and selectors with all required filters. Add query efficiency checks where practical and tests for no external calls in search/detail.

6. **Frontend search/detail**
   Add auditor feature API/types/hooks, search page, detail page, external references panel, and control coverage tab. Keep auditor views read-only.

7. **Frontend admin grant UI**
   Add auditor access admin page and optional list/revoke support if backend companion endpoints were implemented.

8. **Final hardening**
   Re-run targeted and full tests, inspect audit metadata scrubbing, verify URL registration, verify no internal endpoint usage, and re-audit scope against this blueprint.

Each batch should preserve a passing backend test subset before moving to the next. Do not mix broad frontend polish with backend RBAC changes in one batch.

## 16. Definition of Done

Phase 11.6 is done when:

- `apps/api/apps/auditor/` exists and is registered.
- All five models exist with organization boundaries, required choices, constraints, and indexes.
- External references support ServiceNow, Jira, PagerDuty, and custom systems as persisted references/mirrors.
- Reference types include ticket, incident, problem, CMDB CI, and release.
- Duplicate external references are prevented.
- Link-time snapshots are sanitized, hashed, persisted, and displayed.
- Search and detail endpoints never call external systems.
- Snapshot refresh, if implemented, is explicit on-demand only and does not affect source-of-truth change state.
- Control standards include SOC 2, ISO 27001, NIST, and custom.
- Control coverage recomputation reads sealed bundle sections/items and produces deterministic rows/fingerprints.
- Auditor access grants are scoped, server-enforced, expirable/revocable, and read-only.
- `GET /api/v1/audit/changes/` supports all required filters.
- `GET /api/v1/audit/changes/{id}/` returns a read-only audit-ready detail projection.
- `POST /api/v1/changes/{id}/external-references/` is operator/admin-only.
- `POST /api/v1/changes/{id}/control-coverage/recompute/` is operator/admin-only.
- `POST /api/v1/auditor-access-grants/` is admin/owner-only.
- React includes auditor search, audit change detail, external references panel, control coverage tab, and auditor access admin page.
- Tests prove filter behavior, snapshot behavior, duplicate prevention, deterministic recomputation, auditor read-only behavior, scope enforcement, and no live external calls in search results.
- The implementation remains wedge-locked to audit-ready production change evidence and does not drift into ITSM, GRC, CMDB, or ticketing workflow product scope.

## 17. Risks and Drift Traps

| Risk | Mitigation |
|---|---|
| Search accidentally calls external systems for freshness. | Keep all search/detail code in selectors using DB querysets only. Add tests that monkeypatch external clients to fail if called. |
| External references become implicit approvals or closure evidence. | Label snapshots as references. Never map external ticket state to change lifecycle state. Coverage can reference external reference presence, not external approval truth. |
| Control mapping becomes a generic GRC engine. | Keep mapping rules declarative and tied to sealed bundle sections/items. No campaigns, attestations, questionnaire workflows, or arbitrary control lifecycle. |
| Service catalog becomes a CMDB sync project. | Store only keys, labels, ownership, criticality, and bounded target patterns. No dependency graphs, discovery jobs, or live CMDB sync. |
| Auditor grant scopes widen when multiple grants are merged. | Evaluate each grant independently and union allowed rows. Do not merge dimensions globally. |
| Auditor UI exposes mutation affordances. | Render auditor pages read-only by default and require explicit operator/admin permission for link/recompute/admin controls. Backend checks remain authoritative. |
| Snapshot payloads leak sensitive external data. | Sanitize allowlisted fields only, cap size, scrub audit metadata, reject credential-bearing URLs, and test forbidden keys. |
| Coverage recomputation mutates sealed evidence. | Coverage rows are derived records only. Never update `EvidenceBundle`, `EvidenceBundleItem`, artifact bytes, or canonical manifests. |
| Bundle invalidation creates stale coverage confusion. | Define stale behavior explicitly and surface bundle ID/content hash/profile version beside every coverage row. |
| AI summaries are treated as authoritative. | Keep summaries outside coverage inputs and label them non-authoritative in serializers/UI. |
| Phase 11.1-11.5 implementation differs from blueprint assumptions. | Re-inspect actual `changes`, `evidence`, `authz`, and frontend feature files before coding; update this plan if names or invariants changed. |
| Audit metadata check constraints block new object types. | Add audit object type migration in the same backend foundation batch and test audit emission for every new model family. |
