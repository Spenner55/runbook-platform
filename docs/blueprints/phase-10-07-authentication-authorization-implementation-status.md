# Phase 10.7 Authentication and Authorization Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-29 |
| Scope | Read-only implementation audit of Phase 10.7 Authentication and Authorization |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-07-authentication-authorization-blueprint.md`, prior Phase 10.1-10.5 implementation status docs, and `docs/implemented/phase-10-07-authentication-authorization.md` |
| Verdict | **Remediated after audit.** The original read-only audit found Phase 10.7 was not ready for Phase 10.8. The blocking org-context, current-user membership, RBAC role naming, last-owner, logout/cookie, runner token, and lint/test issues were fixed on 2026-04-29. |

## 0. Remediation update

Post-audit remediation completed on 2026-04-29:

- Backend public domain endpoints now use `X-Organization-Id` as the source of truth and reject query/body mismatches with `400 org_id_mismatch`.
- `/api/v1/auth/me/` returns memberships, organization names/slugs, roles, and an active/default organization id.
- Frontend auth state stores the active organization in memory and `apiRequest` sends it as `X-Organization-Id` when a request does not already provide org context.
- Membership roles are aligned to `owner/admin/operator/viewer`; a migration maps existing `member` rows to `operator`.
- Last-owner demotion/removal is blocked.
- Public registration routing is disabled for Phase 10.7.
- Logout requires authentication and refresh cookies use `SameSite=Strict`.
- API runner validation supports `RUNNER_TOKENS`; runner startup rejects empty or `change-me` registration tokens.
- `make lint`, `make test-api`, `make test-runner`, and `make test-web` pass after remediation.

## 1. Executive verdict

Phase 10.7 has a working foundation: custom users, JWT login/refresh/logout, authenticated default DRF permissions, membership-backed RBAC, header-scoped public querysets, runner bearer authentication, frontend in-memory access-token and active-org handling, protected routes, and tests for public/internal auth paths.

The original audit verdict was "do not move to Phase 10.8 yet" because Live Event Streaming depends on a single, reliable authenticated organization context for SSE subscriptions. That blocker has been remediated: backend public domain endpoints enforce the blueprint's `X-Organization-Id` source-of-truth contract and reject header/body or header/query drift.

The remediation verification state is clean:

```sh
make lint
# passed

make test-api
# 475 passed

make test-runner
# 75 passed

make test-web
# 66 passed
```

The sections below preserve the original audit findings for traceability; section 0 records the remediation status.

## 2. Implemented scope

- `AUTH_USER_MODEL = "users.User"` is configured and `apps.users` is installed.
- `User` model and manager exist with UUID primary key, email login, password hashing, staff/superuser support, and admin registration.
- `/api/v1/auth/login/`, `/refresh/`, `/logout/`, `/me/`, and an additional `/register/` endpoint exist.
- Global DRF default permission is `IsAuthenticated`; public auth endpoints explicitly opt into `AllowAny`.
- JWT access tokens are returned by login/refresh and refresh tokens are stored in an httpOnly cookie.
- `Organization`, `Membership`, membership serializers, membership service functions, and membership API routes exist.
- Organization list/retrieve querysets are scoped to organizations where the user is a member.
- Public domain views require authentication and use membership checks for writes or admin-only actions.
- Shared permission helpers define admin/member/operator read/write role sets.
- Shared queryset helper scopes organization-owned rows to the authenticated user's memberships.
- Internal execution and artifact endpoints use `RunnerBearerTokenAuthentication` plus `IsRunnerAuthenticated`.
- Internal runner endpoints reject missing/invalid runner tokens and valid user JWTs.
- Runner `ApiClient` sends `Authorization: Bearer <RUNNER_REGISTRATION_TOKEN>` on internal JSON and artifact-upload calls.
- Approval decisions can persist `decided_by_user` with `SET_NULL` and user labels.
- Audit actor helpers can produce user, runner, system, and unknown actors.
- Frontend auth provider stores access tokens in module memory, refreshes from cookie on boot, clears auth state on unauthorized, and protects all non-login routes.
- Frontend API client injects `Authorization`, derives an `X-Organization-Id` header from request options/query/body, retries once after 401 refresh, and blocks browser calls to `/api/v1/internal/`.
- API, runner, and web test suites pass.

## 3. Missing scope

- Backend does not make `X-Organization-Id` the authoritative organization scope. Views still read `organization_id` from query params or request bodies.
- No backend mismatch guard exists for `X-Organization-Id` versus body/query `organization_id`; `org_id_mismatch` is not implemented.
- `/api/v1/auth/me/` does not return memberships, organization names/slugs, roles, or any active organization context.
- Frontend auth state has no `activeOrgId`, no selected active membership, and no role-aware auth state; organization selection is still route/query-string driven.
- Membership roles are `owner/admin/member/viewer`; the blueprint requires `owner/admin/operator/viewer`.
- Membership model lacks `invited_by` and `joined_at`.
- Member creation uses `user_id`, not the blueprint's email-based contract.
- Membership detail paths use organization UUID plus membership UUID, not `/organizations/{org_slug}/members/{user_id}/`.
- Last-owner protections are missing for demotion and removal.
- `LogoutView` is public `AllowAny`; the blueprint requires authenticated logout.
- Refresh cookie uses `SameSite=Lax`, not the blueprint's `SameSite=Strict`.
- A public `/auth/register/` endpoint was added even though the blueprint explicitly excludes registration.
- Audit events do not add `actor_user`; they keep only string `actor_id` and `actor_label`.
- `Policy` and `IntegrationConnection` do not have `created_by` user FKs.
- Runner settings use only one `RUNNER_REGISTRATION_TOKEN`; the blueprint's `RUNNER_TOKENS`/plural rotation-ready setting is not present.
- Runner startup does not fail fast when the token is empty or `change-me`.
- No model-level `OrganizationScopedQuerySet` manager mixin is applied to domain models; scoping is implemented through view/queryset helper functions.
- `make lint` is failing.

## 4. Blueprint drift

- The implementation uses first/last name fields plus a computed `full_name`; the blueprint specified a stored `full_name` field and API responses containing `full_name`.
- Role naming drifted from `operator` to `member`. Capability intent mostly maps to the same middle role, but this will leak into API contracts, frontend role checks, docs, and any future SSE authorization logic.
- The current org scope model is body/query `organization_id` with optional frontend-added `X-Organization-Id`; the blueprint requires the header as source of truth after auth.
- The auth API includes registration, which was out of scope for Phase 10.7.
- Membership APIs are UUID/membership-id based rather than slug/user-id based.
- `AuditEvent.actor_user`, `Policy.created_by`, and `Integration.created_by` were not added despite the blueprint's user-FK table.
- Runner token validation checks only `settings.RUNNER_REGISTRATION_TOKEN`, not `settings.RUNNER_TOKENS`.
- The implementation uses `SameSite=Lax` for refresh cookies instead of `Strict`.
- The frontend does not implement the blueprint's org switcher, active org state, or cache clearing on org switch.

## 5. Test coverage review

Verification run during this audit:

```sh
make lint
# failed: 3 ruff I001 import-order errors

make test-api
# 472 passed in 32.76s

make test-runner
# 73 passed in 0.70s

make test-web
# 65 passed
```

Covered:

- User model creation, normalization, password checking, staff/superuser creation.
- Login, refresh, logout, `/me/`, registration, duplicate registration.
- Organization list/create and membership list/create/update/delete happy paths.
- Viewer/member/admin membership permissions.
- Non-member membership access rejection and membership detail cross-org boundary.
- Public API auth scoping across runbooks, workflows, executions, approvals, policies, audit, artifacts, and integrations.
- Internal runner missing token, invalid token, and user JWT rejection.
- Runner client `Authorization` header on claim and artifact upload.
- Frontend access-token header injection, org header derivation, refresh retry, and internal endpoint blocking.
- Protected route and login flow behavior indirectly through route tests.

Gaps:

- No tests assert `X-Organization-Id` is required by the backend for public domain endpoints.
- No tests assert header/body or header/query organization mismatch returns `400 org_id_mismatch`.
- No `/auth/me/` tests cover memberships, roles, organization slugs, or active-org selection.
- No tests prove last owner cannot be demoted or removed.
- No tests cover role name compatibility with the blueprint's `operator` contract.
- No tests assert logout requires authentication.
- No tests assert refresh cookie `SameSite=Strict`.
- No tests cover runner startup rejecting missing/default registration token.
- No tests cover `AuditEvent.actor_user`, `Policy.created_by`, or `Integration.created_by` because those fields are absent.
- No frontend tests cover active org switching, role-gated UI, or cache clearing on org switch.

## 6. Auth/security risks

- Phase 10.8 SSE authorization would be built on an ambiguous org-source model unless the backend header contract is fixed first.
- Query/body `organization_id` remains a confused-deputy risk for future endpoints that may accidentally trust body scope differently than header scope.
- `/auth/me/` lacks membership data, so frontend routing and future stream subscription UI cannot reliably derive allowed orgs from authenticated identity.
- Last-owner deletion/demotion can leave an organization without an owner, creating administrative lockout.
- The public registration endpoint allows open account creation unless deployment routing blocks it.
- `SameSite=Lax` is weaker than the blueprint's refresh-cookie target.
- A valid but misplaced user JWT on internal endpoints is correctly rejected, but runner token configuration has no startup hard fail for missing/default tokens.
- Audit remains denormalized by string actor IDs only; user deletion readability is preserved, but queryable user FK support from the blueprint is absent.
- Admin/service edits to policies and integrations do not have `created_by` user FK attribution.
- Lint failure means the phase cannot be considered green even though tests pass.

## 7. Required fixes before Phase 10.8

1. Implement backend `X-Organization-Id` enforcement for all authenticated public domain endpoints, including the explicit allowlist for auth, health/metrics, and internal runner endpoints.
2. Reject mismatched header/body/query organization IDs with the blueprint's `400 org_id_mismatch` contract.
3. Update `/api/v1/auth/me/` and frontend auth state to include memberships, role, organization slug/name, and active organization handling.
4. Align role naming and contracts with `owner/admin/operator/viewer`, or document and update the blueprint if `member` is intentionally the operator role.
5. Add last-owner safeguards for membership demotion and deletion.
6. Remove or explicitly defer/disable public registration for Phase 10.7.
7. Make logout authenticated, or document why cookie clearing without authentication is accepted.
8. Change refresh cookie policy to `SameSite=Strict` unless there is a documented cross-site deployment requirement.
9. Add runner startup validation for missing/default `RUNNER_REGISTRATION_TOKEN`.
10. Fix lint import-order failures and rerun all verification gates.
11. Add tests for the org header contract, mismatch rejection, `/me/` memberships, last-owner protections, and runner startup token validation.

## 8. Recommended non-blocking follow-ups

- Add `invited_by` and `joined_at` to `Membership` if invitation provenance matters before production.
- Add `AuditEvent.actor_user`, `Policy.created_by`, and `Integration.created_by` with `SET_NULL` semantics if queryable user attribution remains a hard requirement.
- Introduce plural `RUNNER_REGISTRATION_TOKENS`/`RUNNER_TOKENS` support for token rotation in Phase 10.9.
- Replace membership create-by-user-id with create-by-email if the API should match the blueprint exactly.
- Add org slug routes for membership management if URL readability matters.
- Add frontend role-gated controls after backend contracts are settled.
- Add end-to-end browser auth flow coverage once the active organization model is implemented.
- Add deployment documentation to keep `/api/v1/internal/` private at the load balancer even though Django rejects user JWTs.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-07-authentication-authorization-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-implementation-status.md`
- `docs/blueprints/phase-10-02-policies-implementation-status.md`
- `docs/blueprints/phase-10-03-audit-trail-implementation-status.md`
- `docs/blueprints/phase-10-04-artifacts-implementation-status.md`
- `docs/blueprints/phase-10-05-integrations-implementation-status.md`
- `docs/implemented/phase-10-07-authentication-authorization.md`
- `.env.example`
- `docker-compose.yml`
- `apps/api/config/settings/base.py`
- `apps/api/config/settings/test.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/conftest.py`
- `apps/api/apps/common/authentication.py`
- `apps/api/apps/common/permissions.py`
- `apps/api/apps/common/querysets.py`
- `apps/api/apps/common/tests.py`
- `apps/api/apps/users/models.py`
- `apps/api/apps/users/managers.py`
- `apps/api/apps/users/admin.py`
- `apps/api/apps/users/apps.py`
- `apps/api/apps/users/serializers.py`
- `apps/api/apps/users/services.py`
- `apps/api/apps/users/urls.py`
- `apps/api/apps/users/views.py`
- `apps/api/apps/users/migrations/0001_initial.py`
- `apps/api/apps/users/tests/test_api.py`
- `apps/api/apps/users/tests/test_models.py`
- `apps/api/apps/users/tests/test_services.py`
- `apps/api/apps/organizations/models.py`
- `apps/api/apps/organizations/admin.py`
- `apps/api/apps/organizations/serializers.py`
- `apps/api/apps/organizations/services.py`
- `apps/api/apps/organizations/urls.py`
- `apps/api/apps/organizations/views.py`
- `apps/api/apps/organizations/migrations/0003_membership.py`
- `apps/api/apps/organizations/tests/test_api.py`
- `apps/api/apps/organizations/tests/test_membership_api.py`
- `apps/api/apps/organizations/tests/test_services.py`
- `apps/api/apps/runbooks/views.py`
- `apps/api/apps/workflows/views.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/approvals/views.py`
- `apps/api/apps/approvals/models.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/policies/views.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/audit/views.py`
- `apps/api/apps/audit/models.py`
- `apps/api/apps/audit/services.py`
- `apps/api/apps/artifacts/views.py`
- `apps/api/apps/artifacts/internal_views.py`
- `apps/api/apps/integrations/views.py`
- `apps/api/apps/integrations/models.py`
- `apps/runner/runner/client.py`
- `apps/runner/runner/main.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/tests/test_client.py`
- `apps/runner/runner/tests/test_schemas.py`
- `apps/web/src/app/router.tsx`
- `apps/web/src/app/AppLayout.tsx`
- `apps/web/src/app/providers/AppProviders.tsx`
- `apps/web/src/features/auth/AuthStatus.tsx`
- `apps/web/src/features/auth/ProtectedRoute.tsx`
- `apps/web/src/features/auth/authTokenStore.ts`
- `apps/web/src/features/auth/types.ts`
- `apps/web/src/features/auth/api/authApi.ts`
- `apps/web/src/features/auth/context/AuthContext.tsx`
- `apps/web/src/features/auth/context/authContext.ts`
- `apps/web/src/features/auth/context/useAuth.ts`
- `apps/web/src/features/auth/hooks/useCurrentUser.ts`
- `apps/web/src/routes/auth/LoginPage.tsx`
- `apps/web/src/shared/api/client.ts`
- `apps/web/src/shared/api/client.test.ts`
- `apps/web/src/shared/lib/queryKeys.ts`
- `apps/web/src/routes/organizations/OrganizationsPage.tsx`
- `apps/web/src/routes/organizations/OrganizationsPage.test.tsx`

## 10. Commands to run for verification

```sh
make lint
make test-api
make test-runner
make test-web
```

Recommended targeted checks after required fixes:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest \
  apps/users/tests/ apps/organizations/tests/ apps/common/tests.py \
  apps/executions/tests/test_runner_api.py apps/artifacts/tests/test_internal_api.py

docker compose exec web npm test -- --run src/shared/api/client.test.ts
docker compose exec runner pytest runner/tests/test_client.py runner/tests/test_schemas.py
```

## Short summary

Phase 10.7 is close but not ready for Phase 10.8. The main blocker is not raw authentication; it is the missing backend organization-context contract that Live Event Streaming will need for safe subscription authorization. Fix that, `/auth/me/` memberships, last-owner protections, runner startup validation, and lint before starting SSE work.
