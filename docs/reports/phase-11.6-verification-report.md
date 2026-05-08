# Phase 11.6 Verification Report

Date: 2026-05-08

## 1. Summary

Phase 11.6 is now complete against the blueprint definition of done.

This patch closed the previously deferred gaps:

- Added the React auditor workspace under `/audit/changes`, `/audit/changes/:changeId`, and `/audit/access`.
- Added auditor search filters for `approver` and `executor`.
- Made the audit date basis explicit: filters and grant date scopes use `submitted_at` when present and fall back to `created_at` only when `submitted_at` is absent.
- Added API response metadata documenting the date basis.
- Added the blueprint-compatible grant route alias `/api/v1/auditor-access-grants/` while preserving `/api/v1/audit/access-grants/`.
- Added grant creation validation requiring the target user to be a current member of the organization.

Architecture invariants remain intact:

- Search/detail APIs read persisted Django data only.
- No auditor search/detail path calls ServiceNow, Jira, PagerDuty, AI, runner, storage, internal APIs, queues, workers, webhooks, or schedulers.
- Auditor detail views are read-only.
- Scoped grants are still enforced server-side.
- Frontend calls use public Django APIs only and the shared client still blocks `/api/v1/internal/`.

## 2. Files Changed

Backend:

- `apps/api/apps/auditor/access.py`
- `apps/api/apps/auditor/selectors.py`
- `apps/api/apps/auditor/serializers.py`
- `apps/api/apps/auditor/services.py`
- `apps/api/apps/auditor/urls.py`
- `apps/api/apps/auditor/views.py`
- `apps/api/apps/auditor/tests/test_access.py`
- `apps/api/apps/auditor/tests/test_api_audit_changes.py`

Frontend:

- `apps/web/src/features/auditor/types.ts`
- `apps/web/src/features/auditor/api/auditorApi.ts`
- `apps/web/src/features/auditor/hooks/useAuditChangeSearch.ts`
- `apps/web/src/features/auditor/hooks/useAuditChangeDetail.ts`
- `apps/web/src/features/auditor/hooks/useAuditorAccessGrants.ts`
- `apps/web/src/features/auditor/hooks/useCreateAuditorAccessGrant.ts`
- `apps/web/src/features/auditor/hooks/useRevokeAuditorAccessGrant.ts`
- `apps/web/src/routes/auditor/AuditorSearchPage.tsx`
- `apps/web/src/routes/auditor/AuditorSearchPage.test.tsx`
- `apps/web/src/routes/auditor/AuditChangeDetailPage.tsx`
- `apps/web/src/routes/auditor/AuditChangeDetailPage.test.tsx`
- `apps/web/src/routes/auditor/AuditorAccessAdminPage.tsx`
- `apps/web/src/routes/auditor/AuditorAccessAdminPage.test.tsx`
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/shared/lib/queryKeys.ts`

Documentation:

- `docs/reports/phase-11.6-verification-report.md`

## 3. Backend Patch Details

Search filters:

- `approver` maps to persisted approval facts on `ChangeRecord.approval_request -> ApprovalDecision`:
  - `ApprovalDecision.decided_by_user.id`
  - `ApprovalDecision.decided_by_user.email`
  - `ApprovalDecision.decided_by_label`
- `executor` maps to persisted execution and verification facts:
  - `ChangeExecutionBinding.bound_by_runner_id`
  - `Execution.claimed_by_runner_id`
  - `VerificationResult.runner_id`
  - `VerificationResult.submitted_by.id`
  - `VerificationResult.submitted_by.email`

Date basis:

- Search `start_date` and `end_date` now filter on `submitted_at` when present.
- Rows with no `submitted_at` intentionally fall back to `created_at`.
- Auditor grant `date_from` and `date_to` use the same basis.
- Audit search responses include:
  - `meta.date_basis = submitted_at_with_created_at_fallback`
  - `meta.date_filter_fields = ["submitted_at", "created_at"]`
- Search/detail rows include `audit_date` and `audit_date_basis`.

Grant access:

- `/api/v1/auditor-access-grants/` is an alias to the same list/create view used by `/api/v1/audit/access-grants/`.
- Grant creation now rejects non-members and members of other organizations with `auditor_user_not_organization_member`.
- Existing read-time active membership enforcement remains unchanged.

## 4. Frontend Patch Details

The React auditor workspace now includes:

- Auditor search page with filters for service, target, risk, status, change type, bundle status, control ID, coverage status, external system, exception flag, start/end date, approver, executor, ordering, limit, and offset-backed pagination.
- Read-only audit change detail page showing change summary, status/risk/type, target/service context, bundle status, control coverage summary/details, external reference snapshots, and evidence metadata.
- Auditor access page for owner/admin UX to list, create, and revoke grants.
- React Query hooks and API functions that call only public Django endpoints.
- Route and navigation wiring for `/audit/changes`, `/audit/changes/:changeId`, and `/audit/access`.
- Focused tests for filter query mapping, date parameters, read-only detail rendering, external snapshots, control coverage, empty states, grant creation, grant validation errors, and internal API blocking.

## 5. Test Commands and Results

Backend:

- `docker compose exec api python manage.py check`
  - Passed: `System check identified no issues (0 silenced).`
- `docker compose exec api pytest apps/auditor/tests/`
  - Passed: `49 passed in 13.18s`.
- `docker compose exec api pytest apps/audit/tests/`
  - Passed: `39 passed in 9.96s`.
- `docker compose exec api pytest apps/changes/tests/ apps/evidence/tests/`
  - Passed: `929 passed in 104.16s`.

Frontend:

- `cd apps/web && npm run lint`
  - Passed.
- `cd apps/web && npm test -- --run`
  - Passed: `30 passed`, `238 tests passed`.
- `cd apps/web && npm run build`
  - Passed. Vite emitted the existing advisory chunk-size warning for a 511 kB JS bundle; build completed successfully.

## 6. Blueprint Alignment Checklist

- `apps/api/apps/auditor/` exists and is registered: Pass.
- `ExternalChangeReference` exists: Pass.
- `ServiceCatalogEntry` exists: Pass.
- `ControlMappingProfile` exists: Pass.
- `ChangeControlCoverage` exists: Pass.
- `AuditorAccessGrant` exists: Pass.
- Every auditor model is organization-scoped: Pass.
- FK organization invariants are enforced: Pass.
- Auditor grants are read-only and server-enforced: Pass.
- Search/detail APIs never call external systems: Pass.
- Search/detail APIs never call runner/internal APIs: Pass.
- External snapshots are sanitized and bounded: Pass.
- Refresh is explicit only: Pass.
- Control coverage is computed from sealed evidence bundle sections/items: Pass.
- Unsealed evidence cannot satisfy final coverage: Pass.
- React auditor workspace exists: Pass.
- Auditor routes exist: Pass.
- Audit search supports approver and executor filters: Pass.
- Date basis is explicit and consistent across search and grant scope: Pass.
- Grant route alias is handled: Pass.
- Grant creation validates current org membership: Pass.
- Frontend calls public Django APIs only: Pass.
- Frontend auditor detail view exposes no mutation controls: Pass.
- Required backend and frontend tests pass: Pass.

## 7. Previously Deferred Gaps

- React auditor workspace: Closed.
- Approver and executor filters: Closed.
- Date filtering and grant date scope using `created_at` implicitly: Closed.
- Auditor grant endpoint alias drift: Closed.
- Inert grant creation for users without current org membership: Closed.

## 8. Remaining Intentionally Deferred Items

None for the Phase 11.6 blueprint definition of done.

## 9. Final Recommendation

Go.

Phase 11.6 is merge-ready against the blueprint definition of done based on the implemented backend/frontend patches and the passing verification commands listed above.
