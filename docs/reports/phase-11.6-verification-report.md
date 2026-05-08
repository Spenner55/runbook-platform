# Phase 11.6 Verification Report

Date: 2026-05-08

## 1. Summary

Phase 11.6 is partially complete and the implemented backend slice is safe after this verification pass.

Confirmed:

- `apps/api/apps/auditor/` exists and is registered in `INSTALLED_APPS`.
- The five required auditor model families exist.
- Auditor models are organization-scoped.
- Cross-organization FK checks are enforced in model/service paths for external references, control coverage, evidence bundles/items, and change records/targets.
- Auditor search/detail selectors read persisted Django data only.
- External refresh is explicit only.
- Auditor access grants are server-enforced for audit search/detail, active/expired/revoked aware, and read-only for auditor users.
- External snapshots are sanitized, bounded, hashed, and persisted.
- Control coverage recomputation requires sealed evidence bundles.
- Frontend API client blocks browser calls to `/api/v1/internal/`.
- Backend and frontend regression tests pass after resolving a local stale build-output ownership issue.

Small drift fixed during this pass:

- Control coverage no longer treats evidence item rows as eligible when their canonical paths are absent from the sealed bundle manifest.
- Audit metadata scrubbing now covers additional Phase 11.6 grant-scope and URL-shaped keys.

Full Phase 11.6 is not yet merge-ready against the blueprint definition of done because the React auditor workspace is absent and several blueprint search/filter affordances are not implemented.

## 2. Files Changed

Changed during this verification pass:

- `apps/api/apps/auditor/coverage.py`
- `apps/api/apps/auditor/tests/test_control_coverage.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/audit/tests/test_services.py`
- `docs/reports/phase-11.6-verification-report.md`

Phase 11.6 implementation files inspected:

- `apps/api/apps/auditor/__init__.py`
- `apps/api/apps/auditor/access.py`
- `apps/api/apps/auditor/admin.py`
- `apps/api/apps/auditor/apps.py`
- `apps/api/apps/auditor/coverage.py`
- `apps/api/apps/auditor/external_clients.py`
- `apps/api/apps/auditor/migrations/0001_initial.py`
- `apps/api/apps/auditor/models.py`
- `apps/api/apps/auditor/selectors.py`
- `apps/api/apps/auditor/serializers.py`
- `apps/api/apps/auditor/services.py`
- `apps/api/apps/auditor/urls.py`
- `apps/api/apps/auditor/views.py`
- `apps/api/apps/auditor/tests/*`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/audit/tests/test_services.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/config/settings/base.py`
- `apps/web/src/shared/api/client.ts`
- `apps/web/src/app/router.tsx`
- Phase 11.1 through 11.5 implementation files in `apps/api/apps/changes/` and `apps/api/apps/evidence/`.

## 3. Test Commands and Results

Backend:

- `docker compose exec api python manage.py check`
  - Passed: `System check identified no issues (0 silenced).`
- `docker compose exec api pytest apps/api/apps/auditor/tests/`
  - Not runnable inside the API container as written because the container workdir is `/app`; result was `file or directory not found`.
- `docker compose exec api pytest apps/auditor/tests/`
  - Passed: `41 passed in 10.85s`.
  - Note: an earlier concurrent run collided with another pytest process during test DB setup. Sequential rerun passed.
- `docker compose exec api pytest apps/audit/tests/`
  - Passed: `39 passed in 10.18s`.
- `docker compose exec api pytest apps/changes/tests/ apps/evidence/tests/`
  - Passed: `929 passed in 103.88s`.

Frontend:

- `cd apps/web && npm run lint`
  - Passed.
- `cd apps/web && npm test -- --run`
  - Passed: `27 passed`, `231 tests passed`.
- `cd apps/web && npm run build`
  - First run blocked by stale `apps/web/dist/assets` ownership (`nobody:nogroup`) causing Vite `EACCES`.
  - Fixed local output ownership with `docker compose run --rm --user root web chown -R 1000:1000 /app/dist/assets`.
  - Rerun passed: Vite built `dist/index.html`, CSS, and JS assets successfully.

## 4. Blueprint Alignment Checklist

- `apps/api/apps/auditor/` exists and is registered: Pass.
- `ExternalChangeReference` exists: Pass.
- `ServiceCatalogEntry` exists: Pass.
- `ControlMappingProfile` exists: Pass.
- `ChangeControlCoverage` exists: Pass.
- `AuditorAccessGrant` exists: Pass.
- Every auditor model is organization-scoped: Pass.
- FK organization invariants are enforced: Pass for implemented FK paths.
- Auditor grants are read-only and server-enforced: Pass for audit search/detail and mutation endpoint denial.
- Search/detail APIs never call external systems: Pass.
- Search/detail APIs never call runner/internal APIs: Pass.
- External snapshots are sanitized and bounded: Pass.
- Refresh is explicit only: Pass.
- Control coverage is computed from sealed evidence bundle sections/items: Pass after fix.
- Unsealed evidence cannot satisfy final coverage: Pass.
- Frontend calls public Django APIs only: Pass for existing frontend API client.
- Auditor UI has no mutation path for auditor-only users: No dedicated auditor UI exists. This is safe from a mutation standpoint but incomplete against the blueprint UI definition of done.
- Audit metadata scrubber covers external references, grant scopes, raw snapshots, URLs, credentials, and headers: Pass after fix.
- Required backend and frontend tests pass: Pass with container-relative API paths and after correcting stale build-output ownership.

## 5. Drift Found and Fixed

1. Control coverage manifest anchoring
   - Drift: `_item_is_eligible` allowed item rows to satisfy coverage when the sealed bundle manifest had no canonical paths.
   - Fix: evidence items now require a non-empty sealed manifest path set, and the item canonical path must be present in that set.
   - Test: added `test_items_not_in_sealed_manifest_do_not_satisfy_coverage`.

2. Audit metadata scrubber coverage
   - Drift: scrubber covered several raw snapshot and credential keys but did not explicitly cover common Phase 11.6 URL and grant-scope key names.
   - Fix: added scrub keys for `external_url`, `reference_url`, `source_url`, `url`, URL plural variants, `grant_scope`, `auditor_grant_scope`, `auditor_scope`, and `scope`.
   - Test: extended Phase 11.6 audit scrubber test.

## 6. Drift Found but Intentionally Deferred

1. React auditor workspace is not implemented
   - Blueprint expects `features/auditor`, `/audit/changes`, `/audit/changes/:changeId`, `/audit/access`, search/detail pages, external references panel, control coverage tab, and frontend tests.
   - Current frontend has no auditor feature area or auditor routes.
   - Deferred because this is product feature scope, not a small verification fix.

2. Some blueprint search filters are missing or incomplete
   - Implemented filters include service, target, risk, status, change type, bundle status, control ID, coverage status, external system, start date, end date, exception flag, ordering, limit, and offset.
   - Blueprint-required filters for approver and executor are not implemented.
   - Date filtering and grant date scope currently use `created_at`; the blueprint recommends documenting the date basis and preferably using `submitted_at`.
   - Deferred because implementing approver/executor filters correctly requires integration with approval and execution facts beyond a small audit fix.

3. Auditor grant endpoint path differs from one blueprint definition-of-done line
   - Implemented path is `/api/v1/audit/access-grants/`.
   - Blueprint definition of done also names `/api/v1/auditor-access-grants/`.
   - Deferred because existing tests and route grouping use the `/audit/` namespace consistently; changing or aliasing public API paths should be deliberate.

## 7. Remaining Risks

- The backend auditor API is safe, but the absence of a React auditor workspace means the phase is not feature-complete as an end-user workflow.
- Missing approver/executor filters could limit auditor sampling workflows and should be added before claiming full blueprint completion.
- Date basis should be made explicit in API docs/tests and aligned between search filtering and grant scope filtering.
- Grant creation can target a user without current org membership, though access still requires membership at read time. This is safe but may create inert grants and admin confusion.

## 8. Go/No-Go Recommendation

No-go for merging as the full Phase 11.6 deliverable against the blueprint definition of done.

Go for a backend-only Phase 11.6 slice if the merge scope is explicitly limited to auditor persistence, public audit search/detail APIs, external reference snapshots, control coverage computation, grant enforcement, and audit scrubber hardening. The implemented backend slice passed verification after the fixes above.
