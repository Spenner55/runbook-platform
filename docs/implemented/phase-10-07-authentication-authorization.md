# Phase 10.7 Authentication And Authorization

Phase 10.7 adds user identity, JWT authentication, organization membership/RBAC, runner bearer-token authentication, tenant-scoped public APIs, audit actor attribution, and frontend auth integration.

## Endpoint Summary

| Area | Endpoints | Authentication | Authorization |
| --- | --- | --- | --- |
| Auth | `POST /api/v1/auth/login/`, `POST /api/v1/auth/refresh/`, `POST /api/v1/auth/logout/` | Login/refresh are public by explicit `AllowAny`; logout requires a user JWT | Login issues an access token and an httpOnly refresh cookie. Refresh operates on the refresh cookie. Logout clears the cookie for authenticated users. |
| Current user | `GET /api/v1/auth/me/` | User JWT | Authenticated user only. Returns memberships, organization names/slugs, roles, and the active/default organization id. |
| Organizations | `/api/v1/organizations/`, `/api/v1/organizations/{id}/members/` | User JWT | Organization list/retrieve is scoped to memberships. Member management requires owner/admin for writes. |
| Runbooks | `/api/v1/runbooks/` and runbook actions | User JWT | Querysets are scoped to `X-Organization-Id`. Mutations require owner/admin/operator. |
| Workflows | `/api/v1/workflows/` and workflow actions | User JWT | Querysets are scoped to `X-Organization-Id`. Publish/create/update actions require owner/admin/operator. |
| Executions | `/api/v1/executions/` and execution actions | User JWT | Querysets are scoped to `X-Organization-Id`. Execution creation/cancel requires owner/admin/operator. Viewers have read access. |
| Approvals | `/api/v1/approvals/` | User JWT | Approval requests are scoped to `X-Organization-Id`. Decisions require owner/admin/operator. |
| Policies | `/api/v1/policies/` | User JWT | Reads require membership. Policy and rule writes require owner/admin. |
| Audit | `/api/v1/audit/`, `/api/v1/executions/{id}/audit/` | User JWT | Audit reads are scoped to `X-Organization-Id`. |
| Artifacts | `/api/v1/executions/{id}/artifacts/`, `/api/v1/artifacts/{id}/download/`, `/api/v1/artifacts/{id}/content/` | User JWT | Artifact reads require organization membership and are filtered by `X-Organization-Id`. |
| Integrations | `/api/v1/integrations/` | User JWT | Reads require organization membership in `X-Organization-Id`. Connection writes require owner/admin. |
| Internal runner API | `/api/v1/internal/...` | Runner bearer token only | User JWTs are forbidden. Runner claim tokens still enforce per-execution ownership. |

DRF's global default permission is `IsAuthenticated`. Any intentionally public API endpoint must opt in explicitly with `AllowAny`. Authenticated public domain endpoints use `X-Organization-Id` as the source of truth for tenant scope. If a query string or JSON body also includes `organization_id`, it must match the header or Django returns `400 org_id_mismatch`.

## Role Matrix

| Capability | Owner | Admin | Operator | Viewer |
| --- | --- | --- | --- | --- |
| View organization data | Yes | Yes | Yes | Yes |
| Manage organization memberships | Yes | Yes | No | No |
| Create/update/archive runbooks | Yes | Yes | Yes | No |
| Create/update/publish workflows | Yes | Yes | Yes | No |
| Start/cancel executions | Yes | Yes | Yes | No |
| View executions and steps | Yes | Yes | Yes | Yes |
| View/download artifacts | Yes | Yes | Yes | Yes |
| Decide approval requests | Yes | Yes | Yes | No |
| Create/update policies and rules | Yes | Yes | No | No |
| View policy/evaluation history | Yes | Yes | Yes | Yes |
| Configure integrations | Yes | Yes | No | No |
| View audit events | Yes | Yes | Yes | Yes |

Role checks are implemented through organization memberships. Data-bearing querysets are filtered to the active organization where the authenticated user has membership, so cross-tenant IDs return no object, an org mismatch error, or a permission error instead of leaking data. Owner demotion/removal is blocked when it would leave an organization with no owners.

## Runner Token Behavior

Internal runner endpoints are registered only under `/api/v1/internal/` and use `RunnerBearerTokenAuthentication` plus `IsRunnerAuthenticated`.

Required request header:

```http
Authorization: Bearer <RUNNER_REGISTRATION_TOKEN>
```

Behavior:

| Request state | Result |
| --- | --- |
| Missing `Authorization` header | `401` |
| Invalid/non-runner bearer token | `401` |
| Valid user JWT on internal endpoint | `403` |
| Valid runner bearer token | Request proceeds |

The runner bearer token authenticates the process. Execution ownership is still enforced separately with `runner_id` and the per-execution `claim_token`, so a valid runner token alone cannot update an execution it has not claimed.

`RUNNER_REGISTRATION_TOKEN` is required for both the API and runner services. It must be unique per environment and must not use placeholder values such as `change-me`.

## Frontend Token Storage Rules

The React app stores the JWT access token only in module-level memory through `authTokenStore`. It does not write access tokens to `localStorage` or `sessionStorage`.

Refresh tokens are stored by the browser as an httpOnly cookie set by Django on the `/api/v1/auth/` path. The frontend refreshes access tokens by calling `POST /api/v1/auth/refresh/` with `credentials: "include"`.

Browser API calls must go through `apiRequest`, which:

- Sends `Authorization: Bearer <access_token>` when an in-memory access token exists.
- Sends `X-Organization-Id` from request options, query params, JSON body, or the in-memory active organization selected from `/api/v1/auth/me/`.
- Rejects paths beginning with `/api/v1/internal/`.
- Targets Django only through `VITE_API_BASE_URL`; the frontend must not call FastAPI AI, runner services, PostgreSQL, or internal runner endpoints directly.

## Audit Actor Attribution

User-initiated actions record user actors where the service layer receives a request user. Runner-initiated execution, approval, policy, and artifact events record runner/system actors instead of anonymous placeholders. Audit events remain organization-scoped for read access.

## Environment Settings

Required auth-related settings:

| Setting | Used by | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | API | Signs Django and JWT-related cryptographic material. Must be high entropy in every non-test environment. |
| `RUNNER_REGISTRATION_TOKEN` | API, runner | Shared bearer token for `/api/v1/internal/` runner API calls. Required; no default is safe. Runner startup rejects empty or `change-me` values. |
| `RUNNER_TOKENS` | API | Optional comma-separated list of accepted runner tokens for rotation-ready validation. Falls back to `RUNNER_REGISTRATION_TOKEN`. |
| `VITE_API_BASE_URL` | Web | Django API origin used by the browser client. Must not point to FastAPI AI or runner services. |

JWT lifetimes are configured in Django settings: access tokens live 15 minutes and refresh tokens live 7 days.

## Known Limitations

- Runner authentication accepts environment-level shared tokens. Per-runner token inventory, rotation workflows, and revocation are deferred.
- Refresh token rotation is disabled by default.
- Mid-session membership revocation takes effect on the next API call or token refresh; already issued access tokens remain valid until expiry.
- Internal runner endpoints are protected in Django, but production deployments should also keep `/api/v1/internal/` private or blocked at the network/load-balancer layer.
- The frontend stores access tokens only in memory, which protects browser storage but means page reloads require a refresh-cookie round trip.
