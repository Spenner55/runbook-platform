# Phase 10.7: Authentication and Authorization Blueprint

| Field | Value |
|---|---|
| Phase number | 10.7 |
| Phase name | Authentication and Authorization |
| Objective | Add real identity, session management, organization membership, role-based authorization, and runner token authentication. Replace every `AllowAny` permission class with enforced access control. Make every audit record reference a real actor. |
| Status | Blueprint only |
| Depends on | Phases 01–09 complete and verified; Phase 10.1 approvals complete; Phase 10.2 policies complete; Phase 10.3 audit trail complete; Phase 10.4 artifacts complete; Phase 10.5 integrations complete; Phase 10.6 richer AI parsing complete |
| Authored | 2026-04-24 |

---

## 1. Purpose and sequencing rationale

Authentication establishes identity. Authorization controls what that identity can do. Without both, the platform has no concept of "who did this", no mechanism to prevent one user from reading another organization's data, and no way to bind approval decisions to specific people.

Every previous expansion phase (10.1–10.6) was built with `DEFAULT_PERMISSION_CLASSES = [AllowAny]` and no `AUTH_USER_MODEL`. This was intentional. The rationale from the roadmap blueprint (section 4.7) remains correct:

**Auth is a cross-cutting concern that touches every model, every endpoint, and every service.** Adding it before the domain model was stable would have required wiring RBAC to models that changed with each phase — doubling implementation effort at every step. The correct pattern is: prove the domain model works, then add auth as a layer.

After Phases 10.1–10.6, the following are true and stable:

- Approval decisions reference a `decided_by` field — but that field currently has no user model to point to.
- Audit events carry `actor_type` and `actor_id` — but those are currently placeholder strings, not real FKs.
- Policy rules are org-scoped — but no enforcement prevents a user from reading another org's policies.
- Artifact upload records `uploaded_by_runner` — the runner sends no bearer token to prove its identity.
- Integration credentials are stored encrypted — but anyone who can reach the API can read the masked representation or trigger dispatch.

**Why auth comes seventh, not first:**

If auth had been added in Phase 10.1, every new model in 10.2–10.6 would have required simultaneous RBAC wiring — on models that were still being designed. By adding auth after the domain is proven, the permission model is wired once against a stable surface. The cost is that 10.1–10.6 were built `AllowAny`; the system is not publicly deployed until Phase 10.10, so this exposure window is acceptable and controlled.

**Why auth comes before live streaming (Phase 10.8):**

SSE connections carry execution updates scoped to specific organizations and users. Without identity, any browser tab can subscribe to any execution stream. Auth must be in place before streaming is added.

**What this phase does not do:**

- Does not add SSO, SAML, or OIDC. Those are sales-driven requirements for specific enterprise customers (Phase 15 in the roadmap).
- Does not add attribute-based access control (ABAC) or policy-driven permission engines. Role membership is the authorization primitive.
- Does not add multi-factor authentication.
- Does not implement approval delegation or org-level permission override flows.
- Does not change service boundary topology. Django remains the sole enforcer of authorization.
- Does not add runner user sessions. The runner authenticates with a static bearer token, not with a user account.

---

## 2. Current-state inspection checklist

Before implementation begins, re-read the source files in this order. Do not implement from memory.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` section 4.7 to confirm the auth sequencing rationale, design decisions, and key risks are still current.
- [ ] Read `docs/blueprints/phase-10-06-richer-ai-parsing-blueprint.md` section 14 (definition of done) and confirm Phase 10.6 is complete and passing.
- [ ] Inspect `apps/api/apps/users/` — confirm it contains only `__init__.py`. No `models.py` exists yet.
- [ ] Inspect `apps/api/apps/organizations/models.py` — confirm `Organization` has `name` and `slug` only. No `Membership` model exists.
- [ ] Inspect `apps/api/config/settings/base.py` — confirm `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]` is `[AllowAny]`. Confirm no `AUTH_USER_MODEL` override exists. Confirm no JWT settings exist.
- [ ] Inspect `apps/api/config/api_v1_urls.py` — list all registered routers and internal endpoint paths. These are the URLs that will need permission enforcement.
- [ ] Inspect `apps/runner/runner/client.py` — confirm `_post()` sends no `Authorization` header. Note that `RUNNER_REGISTRATION_TOKEN` exists in `.env.example` but is never injected into HTTP calls.
- [ ] Inspect `apps/web/src/shared/api/client.ts` — confirm no `Authorization` header is set. Confirm no token storage or refresh logic exists.
- [ ] Inspect `apps/api/apps/executions/models.py` — confirm all domain models have `organization` FK. Note the `Execution` and `ExecutionStep` model fields.
- [ ] Inspect `apps/api/apps/runbooks/models.py`, `apps/api/apps/workflows/models.py` — confirm both have `organization` FK.
- [ ] Inspect `apps/api/apps/approvals/` — if implemented, confirm whether `decided_by` field is present and what type it is (FK, string, null).
- [ ] Inspect `apps/api/apps/audit/` — if implemented, confirm the `actor_type`, `actor_id`, and `actor_label` fields on `AuditEvent`.
- [ ] Inspect `apps/api/apps/policies/` — if implemented, confirm `Policy` and `PolicyRule` have `organization` FK.
- [ ] Inspect `apps/api/apps/artifacts/` — if implemented, confirm `Artifact` has `organization` or `execution` FK chain.
- [ ] Inspect `apps/api/apps/integrations/` — if implemented, confirm `Integration` has `organization` FK.
- [ ] Inspect `.env.example` — confirm `RUNNER_REGISTRATION_TOKEN=change-me` is present. Note any other auth-adjacent variables.
- [ ] Inspect `apps/api/config/settings/dev.py`, `test.py` — note any existing auth overrides or test client configurations.
- [ ] Run the full test suite before starting: `docker compose exec api pytest`. Record the baseline pass count. After auth is added, fixing test failures is expected work — the baseline is the reference point.
- [ ] Check `apps/api/requirements/` for any existing `djangorestframework-simplejwt` or `django-allauth` pins. There should be none.

---

## 3. Architecture invariants and boundaries

These invariants apply to every decision in Phase 10.7. Any approach that requires violating one of them is wrong — not the invariant.

| Invariant | Phase 10.7 consequence |
|---|---|
| **INV-1: Django is the control plane.** | All authorization decisions happen in Django. The frontend does not enforce access control — it reflects auth state from the API. The AI service never checks tokens. The runner never checks user permissions. |
| **INV-2: Runner talks only to Django internal APIs.** | Runner authentication uses a static bearer token verified by a custom DRF authentication class in Django. The runner has no user account, no session, and no JWT lifecycle. |
| **INV-3: Frontend talks only to Django public APIs.** | The React app calls `/api/v1/auth/login/`, `/api/v1/auth/refresh/`, and all domain endpoints. It never calls FastAPI. It never holds long-lived credentials other than an `httpOnly` refresh token cookie. |
| **INV-4: AI service is stateless and advisory.** | The AI service has no auth. It receives requests from Django (which has already authenticated the user). It does not receive or validate user tokens. |
| **INV-5: API versioning is non-negotiable.** | All new auth endpoints go under `/api/v1/auth/`. No auth endpoint is placed at `/auth/` without the version prefix. |
| **INV-6: UUID primary keys everywhere.** | The `User` model uses a UUID primary key via `BaseModel`. No integer user IDs are exposed in URLs or responses. |
| **INV-7: Business logic in `services.py`.** | Membership creation, role assignment, login, token rotation — all live in service functions, not in views or serializers. Views validate the request and call the service. |
| **INV-8: Authorization is enforced at the queryset level, not only at the view level.** | Every domain model has a queryset that automatically scopes results to the requesting user's organization. A missing `filter()` call must result in a 404 or empty list, never a cross-tenant data leak. |

**Additional auth-specific constraints:**

- **No session-based auth for API endpoints.** Sessions don't compose with machine-to-machine runner access. DRF sessions middleware is present for Django admin only.
- **No localStorage for access tokens.** XSS in the React app would expose all stored tokens. Access token lives in memory; refresh token lives in an `httpOnly` `Secure` cookie.
- **No row-level security in PostgreSQL.** Tenancy is enforced at the Django queryset layer. Adding PG RLS would create a hidden second enforcement layer that complicates debugging without adding safety at this scale.
- **Internal endpoints reject user JWTs.** A user who discovers `/api/v1/internal/` cannot call it with their JWT. The custom `RunnerTokenAuthentication` class is the only accepted authenticator on internal views.

---

## 4. Implementation scope by repo area

### `apps/api/apps/users/`

Currently a stub with only `__init__.py`. Phase 10.7 builds it out fully:

- `models.py` — custom `User` model extending `AbstractBaseUser` and `PermissionsMixin`.
- `managers.py` — `UserManager` with `create_user` and `create_superuser`.
- `admin.py` — register `User` with Django admin.
- `apps.py` — update `ready()` if signal wiring is needed.
- `migrations/` — generated migrations for the new model.

### `apps/api/apps/organizations/`

Add to existing app:

- `models.py` — add `Membership` model (join table between `User` and `Organization` with `role` field).
- `serializers.py` — add `MembershipSerializer`.
- `services.py` — add `create_membership`, `get_membership`, `list_members`, `remove_membership`.
- `views.py` — add membership CRUD endpoints.
- `urls.py` / `api_v1_urls.py` — register new routes.
- `migrations/` — new migration for `Membership`.

### `apps/api/config/settings/`

- `base.py` — add `AUTH_USER_MODEL`, `INSTALLED_APPS` update for `users`, `REST_FRAMEWORK` auth/permission class list, `SIMPLE_JWT` config, runner token setting.
- `test.py` — override auth classes if needed to keep service-layer tests lightweight; document the pattern for authenticated test clients.

### `apps/api/config/api_v1_urls.py`

- Register auth endpoints: login, refresh, logout, current user.
- Register membership endpoints on the organization router.
- Ensure internal endpoints are routed through `InternalRunnerPermission`.

### `apps/api/apps/` — every domain app

Each domain app needs:

- A queryset mixin (`OrganizationScopedQuerySet`) applied to its model managers.
- Views updated to use `IsAuthenticated` (user-facing) or `IsRunnerAuthenticated` (internal).
- Object-level permission checks for `owner`/`admin`-only mutations.

This is the highest-volume change in Phase 10.7. Touching every app's `views.py` and `models.py` is expected.

### `apps/runner/runner/`

- `client.py` — inject `Authorization: Bearer <runner_token>` on every `_post()` call. Read token from environment.
- `main.py` — ensure `RUNNER_REGISTRATION_TOKEN` is read at startup and passed to `ApiClient`.

### `apps/web/src/`

- `src/shared/api/client.ts` — add `Authorization: Bearer <access_token>` header injection. Add 401 interceptor with token refresh flow.
- `src/features/auth/` — new feature: login page, logout action, auth state store (access token in memory, refresh via `httpOnly` cookie).
- `src/app/providers/` — add auth provider wrapping the app.
- Route protection — unauthenticated users redirected to `/login`; post-login redirect to original destination.

### `apps/api/requirements/`

- `base.txt` — add `djangorestframework-simplejwt`.
- No other new dependencies for auth at this phase.

---

## 5. Data model

### 5.1 `User` model (`apps/api/apps/users/models.py`)

```
User(BaseModel):
    email            CharField(max_length=254, unique=True)  ← used as USERNAME_FIELD
    full_name        CharField(max_length=255, blank=True)
    is_active        BooleanField(default=True)
    is_staff         BooleanField(default=False)
    password         (from AbstractBaseUser — hashed)
    last_login       (from AbstractBaseUser)
```

- `BaseModel` provides `id` (UUID), `created_at`, `updated_at`.
- `USERNAME_FIELD = "email"`. `REQUIRED_FIELDS = ["full_name"]`.
- Extends `AbstractBaseUser` and `PermissionsMixin` (for Django admin and `is_superuser`).
- Custom `UserManager` implements `create_user(email, password, **extra)` and `create_superuser(...)`.
- `AUTH_USER_MODEL = "users.User"` in `settings/base.py`. This must be set **before** any migrations are created.

**Critical note on `AUTH_USER_MODEL`:** Changing `AUTH_USER_MODEL` after initial migrations exist requires swapping the default Django auth tables. Because the system has already run migrations for other apps (organizations, runbooks, etc.) that reference Django's default `auth_user` implicitly via FKs, this must be handled with care. The correct approach is to create the `User` model and migration **first**, before creating any FK references to it. See Milestone 1 for the exact sequence.

### 5.2 `Membership` model (`apps/api/apps/organizations/models.py`)

```
Membership(BaseModel):
    user             ForeignKey(settings.AUTH_USER_MODEL, on_delete=PROTECT, related_name="memberships")
    organization     ForeignKey(Organization, on_delete=CASCADE, related_name="memberships")
    role             CharField(max_length=32, choices=Role.choices)
    invited_by       ForeignKey(settings.AUTH_USER_MODEL, on_delete=SET_NULL, null=True, related_name="+")
    joined_at        DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [UniqueConstraint(fields=["user", "organization"], name="unique_user_per_org")]
```

**Role choices** (enum `Membership.Role`):

| Role | Can do |
|---|---|
| `owner` | All actions including delete org, manage members, manage all domain objects |
| `admin` | Manage members (except other owners), manage all domain objects |
| `operator` | Create/edit runbooks, workflows; trigger executions; decide approvals |
| `viewer` | Read-only access to all domain objects within the org |

Start with these four roles. Do not add custom roles or role inheritance in Phase 10.7.

### 5.3 Runner authentication — no new model needed

The runner authenticates with a static bearer token (`RUNNER_REGISTRATION_TOKEN`) stored in the environment. There is no `RunnerCredential` model in Phase 10.7. The token is validated by a custom `RunnerTokenAuthentication` DRF class that reads a list of valid tokens from `settings.RUNNER_TOKENS` (populated from `RUNNER_REGISTRATION_TOKEN` env var). Token rotation support — storing multiple valid tokens, invalidating old ones — can be added in Phase 10.9 (hardening). For Phase 10.7, one static token is sufficient.

**Why no runner model:** A model-backed runner registration system (where each runner has a DB row) adds migration complexity and multi-runner coordination concerns that are not yet warranted. The runner is currently a single process. When the fleet scales (Phase 11), runner registration becomes a model-backed concept.

### 5.4 Relationship between existing models and `User`

After Phase 10.7, the following fields gain real FK references to `User`:

| Model | Field | Current state | After 10.7 |
|---|---|---|---|
| `ApprovalDecision` | `decided_by` | Nullable FK placeholder or null | ForeignKey to `User`, `on_delete=SET_NULL`, null=True — see K-L04 note below |
| `AuditEvent` | `actor_id` | UUID string | Keep as UUID string; `actor_label` stores display name at time of event; add `actor_user` nullable FK (`on_delete=SET_NULL`, null=True) for queryability — see K-L04 note below |
| `Integration` | `created_by` | Absent | Add ForeignKey to `User`, `on_delete=SET_NULL`, nullable |
| `Policy` | `created_by` | Absent | Add ForeignKey to `User`, `on_delete=SET_NULL`, nullable |

Do not retroactively backfill `decided_by` on existing approval decisions — those rows predate the user model. Set `null=True, blank=True` on the FK and document that pre-auth decisions have `decided_by=null`.

> **ARCHITECTURE DECISION (K-L04): Use `on_delete=SET_NULL` (not `PROTECT`) for all User FKs on audit-adjacent models.**
>
> Phase 10.3's `AuditEvent.actor_label` is a denormalized snapshot of the actor's display name at the time of the event, specifically so user accounts can be deleted without rewriting audit history. Using `on_delete=PROTECT` on `AuditEvent.actor_user` (or `ApprovalDecision.decided_by`) contradicts this rationale: a user who has ever triggered an audit event or made an approval decision could never be deleted.
>
> Rule: `ApprovalDecision.decided_by`, `AuditEvent.actor_user`, `Integration.created_by`, and `Policy.created_by` must all use `on_delete=SET_NULL`. When a user is deleted (soft-deactivation or hard delete), these FKs are set to `null` and the human-readable identity is preserved in the denormalized snapshot fields (`actor_label`, `decided_by_label`).
>
> Add a test: `test_user_deletion_leaves_audit_and_approval_rows_readable` — delete a user who has audit events and approval decisions; confirm those rows still exist and `actor_label` / `decided_by_label` are non-null.

### 5.5 `OrganizationScopedQuerySet` mixin

A single mixin applied to every domain model's custom manager:

```python
class OrganizationScopedQuerySet(models.QuerySet):
    def for_organization(self, organization_id):
        return self.filter(organization_id=organization_id)
```

Every domain view calls `.for_organization(request.user.current_organization_id)` before any further filtering. This is the primary defense against cross-tenant data leakage. The mixin must be applied to: `Runbook`, `Workflow`, `Execution`, `ExecutionStep`, `ApprovalRequest`, `Policy`, `Artifact`, `Integration`, `AuditEvent`.

**`current_organization_id`** is resolved from the authenticated user via their active `Membership`. In Phase 10.7, a user belongs to exactly one organization per session (the frontend selects which org is active and passes `X-Organization-Id` header, or the JWT encodes the current org). The simplest correct approach: require an `X-Organization-Id` header on authenticated requests. Django resolves the `Membership` for that org and user; if no membership exists, return 403.

> **ARCHITECTURE DECISION (K-M10): `X-Organization-Id` header is the single source of truth for org scope after auth.**
>
> Pre-auth endpoints (Phases 10.1–10.6) accepted `organization_id` in request bodies and query parameters. After Phase 10.7 auth is in place, two sources of org identity may coexist: the `X-Organization-Id` header AND body/query `organization_id` fields. Without a service-layer invariant, these can drift.

**Rule:** When both `X-Organization-Id` and a body or query `organization_id` are present on an authenticated request, they MUST match. Mismatch returns HTTP 400:
```json
{"error": {"code": "org_id_mismatch", "message": "X-Organization-Id header and body organization_id do not match."}}
```
The `X-Organization-Id` header is the source of truth. Body `organization_id` fields are redundant after Phase 10.7 and should be removed in a cleanup pass during Phase 10.7 implementation (or in Phase 10.8 prep).

**Endpoints that do NOT require `X-Organization-Id`:** `POST /api/v1/auth/login/`, `POST /api/v1/auth/refresh/`, `GET /api/v1/auth/me/`, `GET /health/...`, `GET /metrics/`, all internal runner endpoints (`/api/v1/internal/...`). Document this allowlist in `apps/api/apps/common/auth.py` or in a comment on the middleware.

---

## 6. API contracts

### 6.1 Auth endpoints

All under `/api/v1/auth/`.

#### `POST /api/v1/auth/login/`

**Request:**
```json
{
  "email": "user@example.com",
  "password": "hunter2"
}
```

**Response (200):**
```json
{
  "access": "<JWT access token>",
  "user": {
    "id": "<uuid>",
    "email": "user@example.com",
    "full_name": "Alice Smith"
  }
}
```

The **refresh token** is set as an `httpOnly; Secure; SameSite=Strict` cookie named `refresh_token`. It is never in the response body.

**Response (400):** Invalid credentials.
```json
{"detail": "Invalid email or password."}
```

**Response (401):** Account inactive.
```json
{"detail": "Account is inactive."}
```

#### `POST /api/v1/auth/refresh/`

Reads refresh token from cookie. No request body required. Returns a new access token.

**Response (200):**
```json
{"access": "<new JWT access token>"}
```

**Response (401):** Expired or invalid refresh token.
```json
{"detail": "Token is invalid or expired."}
```

#### `POST /api/v1/auth/logout/`

Requires `IsAuthenticated`. Blacklists the refresh token (or clears the cookie). No request body.

**Response (204):** No content. Clears the `refresh_token` cookie.

#### `GET /api/v1/auth/me/`

Requires `IsAuthenticated`. Returns the authenticated user with their memberships.

**Response (200):**
```json
{
  "id": "<uuid>",
  "email": "user@example.com",
  "full_name": "Alice Smith",
  "memberships": [
    {
      "organization_id": "<uuid>",
      "organization_name": "Acme Corp",
      "organization_slug": "acme-corp",
      "role": "operator"
    }
  ]
}
```

### 6.2 Membership endpoints

Under `/api/v1/organizations/{org_slug}/members/`.

#### `GET /api/v1/organizations/{org_slug}/members/`

Requires `IsAuthenticated` + `IsMemberOf(org)`. Returns paginated list of org members.

**Response (200):**
```json
{
  "results": [
    {"user_id": "<uuid>", "email": "alice@example.com", "full_name": "Alice", "role": "owner", "joined_at": "..."}
  ]
}
```

#### `POST /api/v1/organizations/{org_slug}/members/`

Requires `IsAuthenticated` + `IsAdminOf(org)`. Adds a user to the org by email.

**Request:**
```json
{"email": "bob@example.com", "role": "operator"}
```

**Response (201):** Created membership.

**Response (400):** User does not exist or already a member.

#### `PATCH /api/v1/organizations/{org_slug}/members/{user_id}/`

Requires `IsAuthenticated` + `IsAdminOf(org)`. Changes role. Cannot demote an `owner` if they are the last owner.

#### `DELETE /api/v1/organizations/{org_slug}/members/{user_id}/`

Requires `IsAuthenticated` + `IsAdminOf(org)`. Removes the member. Cannot remove the last owner.

### 6.3 Runner auth error contract

Internal endpoints (`/api/v1/internal/...`) must return consistent errors when the runner token is missing or invalid:

| Condition | Status | Body |
|---|---|---|
| No `Authorization` header | 401 | `{"detail": "Runner token required."}` |
| Invalid token | 401 | `{"detail": "Invalid runner token."}` |
| User JWT used on internal endpoint | 403 | `{"detail": "User sessions are not permitted on internal endpoints."}` |

These responses must be machine-readable from the runner. The runner should treat 401 on internal endpoints as a configuration error (wrong token in env) and exit with a non-zero status code rather than retrying.

> **IMPLEMENTATION CONTRACT (M-03): `RunnerTokenAuthentication.authenticate()` must actively distinguish JWT tokens from runner tokens to return 403 (not 401) when a user JWT is used on an internal endpoint.**
>
> A naive DRF `authenticate()` implementation that simply checks `token == settings.RUNNER_REGISTRATION_TOKEN` will return `None` (unauthenticated) for any other token, causing DRF to return 401 — not 403. The three-case distinction requires explicit inspection.

Required `RunnerTokenAuthentication.authenticate()` logic:
```python
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

class RunnerTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return None  # No auth header; let DRF return 401

        token = header.split(" ", 1)[1].strip()
        if token == settings.RUNNER_REGISTRATION_TOKEN:
            return (RUNNER_PSEUDO_USER, token)  # Valid runner token → proceed

        # Check if this looks like a JWT (3 dot-separated base64url segments)
        # Use PermissionDenied (not AuthenticationFailed) to return 403, not 401.
        if token.count(".") == 2:
            raise PermissionDenied(
                {"detail": "User sessions are not permitted on internal endpoints."}
            )
        # Unknown non-JWT token
        raise AuthenticationFailed({"detail": "Invalid runner token."})
```

**Why `PermissionDenied` for JWT:** DRF's `AuthenticationFailed` returns 401 (authentication failure). `PermissionDenied` returns 403 (authenticated but not authorized). For a user JWT on an internal endpoint, the semantics are: "we know who you are (user), but users are not permitted here" — which is 403. For a missing or invalid runner token, the semantics are: "we don't know who you are" — which is 401.

Confirm this behavior with tests `test_internal_endpoint_rejects_user_jwt` (→ 403) and `test_internal_endpoint_rejects_invalid_runner_token` (→ 401).

### 6.4 Standard authenticated request

All public domain endpoints (runbooks, workflows, executions, etc.) require:

```
Authorization: Bearer <access_token>
X-Organization-Id: <org_uuid>
```

Missing `Authorization` → 401.
Missing or invalid `X-Organization-Id` → 400 with `{"detail": "X-Organization-Id header required."}`.
`X-Organization-Id` references org the user is not a member of → 403 with `{"detail": "You are not a member of this organization."}`.

---

## 7. Authorization rules per domain

These rules define what each role can do within an organization. All checks happen in Django — never in the frontend, never in the runner.

### General principles

- `viewer` can read everything within the org.
- `operator` can do everything `viewer` can, plus create/edit/execute/decide approvals.
- `admin` can do everything `operator` can, plus manage org members and org-level config.
- `owner` can do everything `admin` can, plus delete the organization.
- The runner token acts as a synthetic principal with exactly the permissions needed for internal endpoints — it is not mapped to any role.

### 7.1 Organizations

| Action | Minimum role |
|---|---|
| Read org details | `viewer` |
| Update org name/slug | `admin` |
| Delete org | `owner` |
| List members | `viewer` |
| Add/change/remove members | `admin` |

### 7.2 Runbooks

| Action | Minimum role |
|---|---|
| List runbooks | `viewer` |
| Read runbook detail | `viewer` |
| Create runbook | `operator` |
| Update runbook (title, content) | `operator` |
| Change runbook status (draft→ready) | `operator` |
| Archive runbook | `admin` |
| Delete runbook | `admin` |

### 7.3 Workflows

| Action | Minimum role |
|---|---|
| List workflows | `viewer` |
| Read workflow detail | `viewer` |
| Create workflow (manual or AI-parsed) | `operator` |
| Approve AI-parsed workflow for execution | `operator` |
| Publish workflow | `operator` |
| Supersede/archive workflow | `admin` |

### 7.4 Executions

| Action | Minimum role |
|---|---|
| List executions | `viewer` |
| Read execution detail (including steps) | `viewer` |
| Create execution (trigger a workflow) | `operator` |
| Cancel execution | `operator` |
| Runner claim-next (internal) | Runner token only |
| Runner heartbeat (internal) | Runner token only |
| Runner step update (internal) | Runner token only |
| Runner complete execution (internal) | Runner token only |

### 7.5 Approvals

| Action | Minimum role |
|---|---|
| List pending approvals (inbox) | `operator` |
| View approval detail | `viewer` |
| Decide approval (approve/reject) | `operator` |
| Create approval request (internal, runner-triggered) | Runner token only |

### 7.6 Policies

| Action | Minimum role |
|---|---|
| List policies | `viewer` |
| Read policy detail | `viewer` |
| Create policy | `admin` |
| Update policy | `admin` |
| Activate/deactivate policy | `admin` |
| Delete policy | `owner` |

### 7.7 Artifacts

| Action | Minimum role |
|---|---|
| List artifacts for an execution | `viewer` |
| Download artifact (get pre-signed URL) | `viewer` |
| Upload artifact (internal, runner-triggered) | Runner token only |

### 7.8 Audit trail

| Action | Minimum role |
|---|---|
| List audit events (filtered by org) | `operator` |
| Read audit event detail | `operator` |
| Write audit event | System only (never via public API) |

### 7.9 Integrations

| Action | Minimum role |
|---|---|
| List integrations | `admin` |
| Read integration (masked credentials) | `admin` |
| Create integration | `admin` |
| Update integration | `admin` |
| Deactivate integration | `admin` |
| Delete integration | `owner` |

---

## 8. Frontend data contracts and protected route flow

### 8.1 Auth state model

The React app holds auth state in a context provider (`AuthProvider`). State shape:

```typescript
interface AuthState {
  user: {
    id: string
    email: string
    full_name: string
    memberships: Array<{
      organization_id: string
      organization_name: string
      organization_slug: string
      role: 'owner' | 'admin' | 'operator' | 'viewer'
    }>
  } | null
  activeOrgId: string | null
  isLoading: boolean
}
```

- `user` is `null` when unauthenticated.
- `activeOrgId` is set when the user selects an org (if multi-org membership) or automatically to the sole membership's org.
- `isLoading` is `true` on app init while the refresh attempt runs.

**Token storage:**

- Access token: stored in a module-level variable inside `src/features/auth/token.ts`. Never written to localStorage or sessionStorage.
- Refresh token: stored in an `httpOnly; Secure; SameSite=Strict` cookie set by the Django login response. The browser sends it automatically on `POST /api/v1/auth/refresh/`. The frontend never reads it.

### 8.2 App initialization flow

1. On mount, `AuthProvider` calls `POST /api/v1/auth/refresh/` (the browser sends the cookie automatically).
2. If the refresh succeeds, the new access token is stored in memory. `GET /api/v1/auth/me/` is called. Auth state is populated.
3. If the refresh fails (no cookie, expired), auth state is `user: null`.
4. `isLoading` becomes `false` after both attempts resolve.

### 8.3 API client changes (`src/shared/api/client.ts`)

The `apiRequest` function gains:

- Before each request: inject `Authorization: Bearer <access_token>` and `X-Organization-Id: <activeOrgId>` headers if auth state is set.
- On 401 response: call `POST /api/v1/auth/refresh/` once. If refresh succeeds, retry the original request. If refresh fails, clear auth state and redirect to `/login`.

The interceptor must be non-recursive — a failed refresh does not trigger another refresh attempt.

### 8.4 Route protection

Add a `ProtectedRoute` wrapper component:

```typescript
// Renders children if authenticated; redirects to /login with ?next=<current_path> otherwise.
// Shows a loading spinner while isLoading is true.
function ProtectedRoute({ children }: { children: ReactNode }) { ... }
```

Apply `ProtectedRoute` to every route except `/login`. The router structure becomes:

```
/login             → LoginPage (public)
/                  → ProtectedRoute → OrgSelectPage or redirect to active org
/:orgSlug/*        → ProtectedRoute → OrgLayout → [domain routes]
```

### 8.5 Login page (`src/routes/auth/login.tsx`)

- Email + password form.
- On submit: `POST /api/v1/auth/login/`. On success: store access token, set auth state, redirect to `?next` or `/`.
- On error: show `{"detail": "..."}` message.
- No "register" flow in Phase 10.7. User accounts are created by an admin or via Django management commands.

### 8.6 Org context display

The app header shows the active organization name. If the user has multiple memberships, a dropdown lets them switch. Switching org updates `activeOrgId`, clears any cached domain data, and re-fetches for the new org context.

### 8.7 Role-gated UI elements

The `AuthState` includes the user's role in the active org. Use the role to conditionally render action buttons (e.g., "Create Policy" is hidden for `viewer`). This is UI affordance only — authorization is enforced by Django. The frontend role check must never be treated as a security gate.

---

## 9. Runner contract changes and token handling

### 9.1 `RUNNER_REGISTRATION_TOKEN` → active use

The token is already in `.env.example` as `RUNNER_REGISTRATION_TOKEN=change-me`. The runner reads it at startup (already in `apps/runner/runner/main.py` or `settings.py` via env). Phase 10.7 makes the runner actually send it.

### 9.2 `ApiClient` changes (`apps/runner/runner/client.py`)

The `ApiClient.__init__` gains a `registration_token: str` parameter. The `_post()` helper adds:

```python
headers = {"Authorization": f"Bearer {registration_token}"}
response = self._http.post(url, json=payload, headers=headers)
```

All four internal API calls (`claim_next`, `heartbeat`, `update_step`, `complete_execution`) inherit this through `_post()`. No per-method changes needed.

### 9.3 Django `RunnerTokenAuthentication` class

Location: `apps/api/apps/common/authentication.py`.

```python
class RunnerTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None  # not our scheme; let the next authenticator try
        token = auth_header[len("Bearer "):]
        if token not in settings.RUNNER_TOKENS:
            raise AuthenticationFailed("Invalid runner token.")
        return (RunnerPrincipal(token), None)
```

`RunnerPrincipal` is a minimal object (not a `User` instance) with `is_authenticated = True` and `is_runner = True`. It satisfies DRF's `IsAuthenticated` check. Internal views add a second check:

```python
class IsRunnerAuthenticated(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "is_runner", False)
```

User JWTs are explicitly rejected on internal views:

```python
class InternalRunnerView(APIView):
    authentication_classes = [RunnerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]
```

By setting `authentication_classes` to only `RunnerTokenAuthentication` on internal views, user JWTs are not even considered — DRF authentication is short-circuited correctly.

### 9.4 `settings.RUNNER_TOKENS`

In `base.py`:

```python
RUNNER_TOKENS = set(filter(None, env.list("RUNNER_REGISTRATION_TOKENS", default=["change-me"])))
```

Use `RUNNER_REGISTRATION_TOKENS` (plural) as a comma-separated list to support future rotation without changing the env var name. For Phase 10.7, the `.env` uses the singular `RUNNER_REGISTRATION_TOKEN` — add an alias in `base.py`:

```python
_single = env("RUNNER_REGISTRATION_TOKEN", default="")
RUNNER_TOKENS = set(filter(None, [_single]))
```

### 9.5 Runner startup validation

In `apps/runner/runner/main.py`, before the poll loop starts:

```python
if not registration_token or registration_token == "change-me":
    logger.error("RUNNER_REGISTRATION_TOKEN is not set or is the default value. Exiting.")
    sys.exit(1)
```

This prevents a misconfigured runner from spinning in a loop producing 401s.

### 9.6 Audit events for runner actions

After auth is in place, audit events triggered by runner actions (step transitions, completion) use `actor_type="runner"` and `actor_id=<runner_id_from_claim_next>`. The runner's `runner_id` (already sent in every `ClaimNextRequest`) is stored as the actor identifier. The `actor_label` is `"runner:<runner_id>"`. This provides traceability without requiring a DB row per runner.

---

## 10. Ordered milestones

Each milestone is a small, independently verifiable unit of work. Complete and verify each before proceeding to the next. Commit at every verification gate.

---

### Milestone 1 — `User` model and `AUTH_USER_MODEL`

**Purpose:** Establish the custom user model. This must happen before any FK references to `User` are created. Changing `AUTH_USER_MODEL` after initial migrations requires squashing or a careful multi-step migration — do it first.

**Files touched:**
- `apps/api/apps/users/__init__.py` — already exists
- `apps/api/apps/users/models.py` — new
- `apps/api/apps/users/managers.py` — new
- `apps/api/apps/users/admin.py` — new
- `apps/api/apps/users/apps.py` — new
- `apps/api/apps/users/migrations/0001_initial.py` — generated
- `apps/api/config/settings/base.py` — add `AUTH_USER_MODEL = "users.User"`, add `"apps.users.apps.UsersConfig"` to `INSTALLED_APPS`

**Steps:**
1. Write `UserManager` with `create_user(email, password, **extra)` normalizing email to lowercase.
2. Write `User(AbstractBaseUser, PermissionsMixin, BaseModel)` with the fields defined in section 5.1.
3. Set `USERNAME_FIELD = "email"`, `REQUIRED_FIELDS = ["full_name"]`, `objects = UserManager()`.
4. Set `AUTH_USER_MODEL = "users.User"` in `base.py`. Add `users` to `INSTALLED_APPS`.
5. Run `docker compose exec api python manage.py makemigrations users`.
6. Run `docker compose exec api python manage.py migrate`.
7. Run `docker compose exec api python manage.py check`.

**Verification:**
```bash
docker compose exec api python manage.py check
docker compose exec api python manage.py showmigrations users
docker compose exec api pytest apps/users/tests/ -v  # will be empty; that is fine
```

**Rollback notes:** If migration fails, drop and recreate the DB (`make bootstrap`). Because auth arrives in Phase 10.7, there is no production data to preserve. In a future scenario with existing users, this would require a squash migration strategy.

**Human approval gate:** None. This is a purely additive migration with no data risk.

---

### Milestone 2 — `Membership` model and org membership service

**Purpose:** Create the join table between `User` and `Organization`. This is the authorization primitive for all subsequent permission checks.

**Files touched:**
- `apps/api/apps/organizations/models.py` — add `Membership`
- `apps/api/apps/organizations/services.py` — add membership functions
- `apps/api/apps/organizations/migrations/` — new migration
- `apps/api/config/settings/base.py` — no changes needed

**Steps:**
1. Add `Membership` model with fields from section 5.2. `Role` choices as inner class.
2. Add service functions: `create_membership(user, org, role, invited_by=None)`, `get_membership(user, org)` → `Membership | None`, `require_membership(user, org)` → `Membership` (raises `PermissionDenied` if not found), `list_org_members(org)`, `remove_membership(user, org)` (with last-owner guard), `change_role(membership, new_role, changed_by)`.
3. Run `makemigrations organizations` and `migrate`.

**Verification:**
```bash
docker compose exec api python manage.py check
docker compose exec api pytest apps/organizations/tests/ -v
```

Write tests for:
- `create_membership` creates a row.
- `require_membership` raises `PermissionDenied` when user is not a member.
- `remove_membership` raises when removing the last owner.

**Human approval gate:** None.

---

### Milestone 3 — JWT configuration and login/refresh/logout endpoints

**Purpose:** Wire `djangorestframework-simplejwt`. Expose the auth endpoints.

**Files touched:**
- `apps/api/requirements/base.txt` — add `djangorestframework-simplejwt`
- `apps/api/config/settings/base.py` — add `SIMPLE_JWT` config and `REST_FRAMEWORK` auth settings
- `apps/api/apps/users/views.py` — new: `LoginView`, `RefreshView`, `LogoutView`, `MeView`
- `apps/api/apps/users/serializers.py` — new: `LoginSerializer`, `UserSerializer`
- `apps/api/apps/users/services.py` — new: `authenticate_user(email, password)`, `build_tokens(user)`, `invalidate_refresh_token(token)`
- `apps/api/config/api_v1_urls.py` — add `path("auth/", include("apps.users.urls"))`
- `apps/api/apps/users/urls.py` — new

**SIMPLE_JWT config (in `base.py`):**
```python
from datetime import timedelta

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

REST_FRAMEWORK = {
    ...existing settings...,
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "apps.common.authentication.RunnerTokenAuthentication",
    ],
    # Keep AllowAny as default for now — per-view overrides come in Milestone 5.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}
```

The `INSTALLED_APPS` must include `"rest_framework_simplejwt.token_blacklist"` if using the blacklist feature.

**Login endpoint (`POST /api/v1/auth/login/`):** Validates email/password using `authenticate_user`. On success, calls `build_tokens(user)` which uses simplejwt to generate access + refresh pair. Sets `refresh_token` cookie. Returns access token and user data in body.

**Refresh endpoint (`POST /api/v1/auth/refresh/`):** Reads `refresh_token` from cookie (not from body). Validates and rotates token. Returns new access token.

**Logout endpoint (`POST /api/v1/auth/logout/`):** Requires `IsAuthenticated`. Blacklists the refresh token. Clears the cookie with `Max-Age=0`.

**Me endpoint (`GET /api/v1/auth/me/`):** Requires `IsAuthenticated`. Returns `UserSerializer` with memberships.

**Verification:**
```bash
docker compose exec api python manage.py migrate  # for token_blacklist tables
docker compose exec api pytest apps/users/tests/ -v
# Manual: POST /api/v1/auth/login/ with valid credentials → 200 with access token
# Manual: POST /api/v1/auth/refresh/ with cookie → 200
# Manual: POST /api/v1/auth/login/ with bad credentials → 400
```

**Human approval gate:** Pause here. Manually verify login, refresh, and me endpoints using curl or a REST client before proceeding. The JWT infrastructure must be confirmed working before layering on permissions.

---

### Milestone 4 — `RunnerTokenAuthentication` and internal endpoint locking

**Purpose:** Ensure internal runner endpoints only accept runner tokens, not user JWTs.

**Files touched:**
- `apps/api/apps/common/authentication.py` — new: `RunnerTokenAuthentication`, `RunnerPrincipal`
- `apps/api/apps/common/permissions.py` — new: `IsRunnerAuthenticated`
- `apps/api/apps/executions/internal_views.py` — add `authentication_classes` and `permission_classes`
- `apps/api/config/settings/base.py` — add `RUNNER_TOKENS` setting
- `apps/runner/runner/client.py` — inject `Authorization: Bearer <token>` in `_post()`
- `apps/runner/runner/main.py` — read `RUNNER_REGISTRATION_TOKEN`; startup validation

**Steps:**
1. Implement `RunnerPrincipal` and `RunnerTokenAuthentication` per section 9.3.
2. Implement `IsRunnerAuthenticated` permission class.
3. On all four internal views (`ClaimNextExecutionView`, `ExecutionHeartbeatView`, `ExecutionStepUpdateView`, `ExecutionCompleteView`): set `authentication_classes = [RunnerTokenAuthentication]` and `permission_classes = [IsRunnerAuthenticated]`.
4. Add `RUNNER_TOKENS` to `base.py`.
5. Update `ApiClient._post()` to include `Authorization` header.
6. Add startup validation in `main.py`.

**Verification:**
```bash
docker compose exec api pytest apps/executions/tests/ -v
# Manual: call POST /api/v1/internal/executions/claim-next/ with no header → 401
# Manual: call with user JWT → 403
# Manual: call with valid runner token → 200 (or 204 if no queued execution)
# Integration: make up && make runner logs (runner should claim successfully)
```

**Human approval gate:** Verify runner logs show successful claim-next calls with the bearer token. Verify the runner does not produce 401s.

---

### Milestone 5 — `OrganizationScopedQuerySet` mixin and per-view permission enforcement

**Purpose:** Replace `AllowAny` with `IsAuthenticated` across all public domain views. Apply queryset scoping. This is the highest-volume change and the most critical for multi-tenancy correctness.

**Files touched (one per domain app):**
- `apps/api/apps/runbooks/models.py` — add `OrganizationScopedQuerySet` to manager
- `apps/api/apps/runbooks/views.py` — `IsAuthenticated`, org scoping
- `apps/api/apps/workflows/models.py`, `views.py` — same
- `apps/api/apps/executions/models.py`, `views.py` — same
- `apps/api/apps/approvals/models.py`, `views.py` — same (if implemented)
- `apps/api/apps/policies/models.py`, `views.py` — same (if implemented)
- `apps/api/apps/artifacts/models.py`, `views.py` — same (if implemented)
- `apps/api/apps/audit/models.py`, `views.py` — same (if implemented)
- `apps/api/apps/integrations/models.py`, `views.py` — same (if implemented)
- `apps/api/apps/organizations/views.py` — `IsAuthenticated`, org scoping
- `apps/api/apps/common/mixins.py` — new: `OrgScopedViewMixin`

**`OrgScopedViewMixin` pattern:**
```python
class OrgScopedViewMixin:
    permission_classes = [IsAuthenticated]

    def get_organization(self):
        org_id = self.request.headers.get("X-Organization-Id")
        if not org_id:
            raise ValidationError({"detail": "X-Organization-Id header required."})
        membership = require_membership(self.request.user, org_id)
        return membership.organization

    def get_queryset(self):
        org = self.get_organization()
        return super().get_queryset().for_organization(org.id)
```

Apply this mixin to every domain `ViewSet`. Add object-level permission checks for write operations (create/update/delete) based on `membership.role`.

**Do this app by app, not all at once.** Commit after each app's tests pass.

**Verification (after each app):**
```bash
docker compose exec api pytest apps/<app_name>/tests/ -v
# Manual: unauthenticated GET → 401
# Manual: authenticated GET without X-Organization-Id → 400
# Manual: authenticated GET with wrong org ID → 403
# Manual: authenticated GET with correct org → 200
```

**Human approval gate:** After all views are updated, run the full test suite and review the failure list. All failures should be 401/403 on previously unauthenticated test cases, not regressions in business logic. Pause here for a human review of the failure list before proceeding to Milestone 6.

---

### Milestone 6 — Fix existing tests to use authenticated clients

**Purpose:** The test suite will have widespread failures after Milestone 5 because all existing tests hit the API without auth. This milestone makes them pass again using authenticated test clients.

**Pattern for test files:**

```python
from rest_framework.test import APIClient
from django.test import TestCase

class RunbookApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.user = User.objects.create_user(email="test@example.com", password="testpass")
        Membership.objects.create(user=self.user, organization=self.org, role=Membership.Role.OPERATOR)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.client.defaults["HTTP_X_ORGANIZATION_ID"] = str(self.org.id)
```

`force_authenticate()` bypasses JWT signature verification in tests — this is correct for service-layer tests where the focus is business logic, not auth mechanics. Reserve full JWT round-trip tests for auth-specific test cases.

**Files touched:** Every `tests/` directory under every domain app.

**Verification:**
```bash
docker compose exec api pytest
# All pre-existing tests should be green (or newly written auth tests should account for the new behavior)
```

**Human approval gate:** Full test suite must be green before proceeding. No skipped or xfail tests should be hiding regressions.

---

### Milestone 7 — Membership CRUD API endpoints

**Purpose:** Expose the membership service via API so the frontend can display org members and admins can manage them.

**Files touched:**
- `apps/api/apps/organizations/views.py` — add `MembershipViewSet` or nested actions on `OrganizationViewSet`
- `apps/api/apps/organizations/serializers.py` — add `MembershipSerializer`, `AddMemberSerializer`
- `apps/api/config/api_v1_urls.py` — register membership routes

**Verification:**
```bash
docker compose exec api pytest apps/organizations/tests/ -v
# Manual: as admin, add a member → 201
# Manual: as viewer, add a member → 403
# Manual: remove last owner → 400
```

**Human approval gate:** None.

---

### Milestone 8 — Frontend auth integration

**Purpose:** Add login page, auth provider, route protection, and API client token injection.

**Files touched:**
- `apps/web/src/features/auth/` — new: `AuthProvider.tsx`, `token.ts`, `useAuth.ts`
- `apps/web/src/routes/auth/login.tsx` — new: login page
- `apps/web/src/shared/api/client.ts` — token injection + 401 interceptor
- `apps/web/src/app/providers/` — wrap with `AuthProvider`
- `apps/web/src/app/router.tsx` (or equivalent) — add `ProtectedRoute`, `/login` route
- `apps/web/src/app/App.tsx` — add org context header to all requests

**Steps:**
1. Implement `token.ts` (module-level in-memory access token storage).
2. Implement `AuthProvider` with init flow (refresh on mount → me → populate state).
3. Add `Authorization` and `X-Organization-Id` header injection to `apiRequest`.
4. Add 401 interceptor with single-retry-on-refresh logic.
5. Implement login page; wire to `POST /api/v1/auth/login/`.
6. Add `ProtectedRoute` wrapper; apply to all domain routes.
7. Add logout action (calls `POST /api/v1/auth/logout/`, clears in-memory token, redirects to `/login`).

**Verification:**
```bash
cd apps/web && npm run lint
cd apps/web && npm run build
# Manual: navigate to any route while logged out → redirect to /login
# Manual: log in → redirect to original destination
# Manual: access token expires (simulate by shortening lifetime in dev settings) → transparent refresh and retry
# Manual: log out → token cleared, redirected to /login, refresh fails on next init
```

**Human approval gate:** Full manual walkthrough: login → browse runbooks → log out → confirm no authenticated data remains. Verify DevTools Application tab shows refresh token cookie as `httpOnly` and no access token in localStorage.

---

## 11. Testing strategy

### 11.1 Auth API tests

Location: `apps/api/apps/users/tests/`

- `test_login_success` — valid credentials return 200 with access token and set `refresh_token` cookie.
- `test_login_invalid_password` — 400 with `{"detail": "Invalid email or password."}`.
- `test_login_inactive_user` — 401.
- `test_refresh_success` — with valid cookie, returns 200 with new access token.
- `test_refresh_expired` — expired cookie returns 401.
- `test_logout_blacklists_token` — after logout, the same refresh token in the cookie returns 401 on refresh.
- `test_me_authenticated` — returns user with memberships.
- `test_me_unauthenticated` — 401.

### 11.2 Permission tests

For each domain app, write at minimum:

- `test_unauthenticated_returns_401` — `GET /<resource>/` without `Authorization` header → 401.
- `test_missing_org_header_returns_400` — authenticated but no `X-Organization-Id` → 400.
- `test_wrong_org_returns_403` — authenticated but `X-Organization-Id` for org the user is not in → 403.
- `test_viewer_cannot_create` — `operator` role required action by `viewer` role user → 403.
- `test_operator_can_create` — same action by `operator` → 201.

### 11.3 Multi-tenant isolation tests

Location: `apps/api/apps/runbooks/tests/` (and repeat for other domains)

- `test_org_a_cannot_read_org_b_runbooks` — user in org A with valid token requests list → results contain only org A runbooks.
- `test_org_a_cannot_read_org_b_runbook_detail` — user in org A requests specific runbook UUID belonging to org B → 404 (not 403; do not reveal the resource exists).
- `test_cross_org_execution_isolation` — user in org A cannot see executions of org B's workflows.

These tests are the highest-value tests in Phase 10.7. A passing multi-tenant isolation suite is the closest thing to a proof of correct tenancy enforcement.

### 11.4 Runner token tests

Location: `apps/api/apps/executions/tests/`

- `test_internal_endpoint_rejects_missing_token` — no `Authorization` header → 401.
- `test_internal_endpoint_rejects_user_jwt` — user JWT in header → 403.
- `test_internal_endpoint_rejects_invalid_runner_token` — random string → 401.
- `test_internal_endpoint_accepts_valid_runner_token` — configured token → 200.
- `test_runner_claims_are_org_scoped` — runner claims next execution; returns an execution belonging to the configured org; not an execution from a different org.

### 11.5 Frontend tests

Location: `apps/web/src/features/auth/` and `apps/web/src/test/`

- Login form submits correct payload to `/api/v1/auth/login/`.
- Failed login shows error message from API response.
- Unauthenticated app redirects to `/login`.
- After login, user is directed to original destination (`?next` param).
- `ProtectedRoute` renders loading state while `isLoading` is `true`.
- 401 interceptor retries after successful refresh.
- 401 interceptor redirects to `/login` after failed refresh.

### 11.6 Manual verification gates

1. **Full auth flow:** Create user via `python manage.py shell`, log in via UI, browse runbooks, log out. Confirm redirect to login.
2. **Multi-tenant isolation:** Create two organizations and two users (one per org). Log in as user A. Navigate to a URL containing an ID belonging to org B. Confirm 404 or 403.
3. **Runner integration:** Stop runner, clear `RUNNER_REGISTRATION_TOKEN`, restart runner. Confirm runner exits with error log rather than spinning. Re-set token. Confirm runner resumes claiming.
4. **Token refresh:** Log in. Wait for access token to expire (set `ACCESS_TOKEN_LIFETIME = timedelta(seconds=10)` temporarily in dev settings). Trigger an API call from the UI. Confirm the request succeeds without a visible re-login.
5. **Role enforcement:** Create a `viewer` user. Log in. Attempt to create a runbook. Confirm the UI shows the action as unavailable. Confirm a direct API call returns 403.

---

## 12. Failure modes and risks

### 12.1 Cross-tenant data leakage

**Risk:** A queryset that forgets `.for_organization(...)` returns all rows regardless of org. A user in org A reads org B's execution history.

**Likelihood:** High if not systematically guarded. Every view author must apply the mixin — a single missed callsite is a leak.

**Mitigations:**
- The `OrgScopedViewMixin` applies the filter at the `get_queryset()` level, not at the individual action level. Any `ViewSet` that inherits it gets filtering for free.
- The multi-tenant isolation tests (section 11.3) catch individual app regressions.
- Code review checklist: any new `ViewSet` must inherit `OrgScopedViewMixin`.

**Detection:** If the isolation tests are run in CI on every PR, the leak window is bounded to the PR lifecycle.

### 12.2 Broken internal runner endpoints

**Risk:** The runner token authentication is misconfigured; runner gets 401 on every claim-next; runner polls indefinitely and all executions queue permanently.

**Mitigations:**
- Milestone 4 verification gate explicitly tests the runner token end-to-end before any public endpoint permissions are changed (Milestone 5).
- Runner startup validation exits cleanly on missing token rather than entering a broken polling loop.
- Manual gate in Milestone 4 requires confirming runner logs show successful claims before proceeding.

**Detection:** Runner logs will show `401` errors immediately.

### 12.3 Token leakage via client-side storage

**Risk:** Access token is accidentally written to localStorage (common mistake) — XSS attack steals all user sessions.

**Mitigations:**
- `token.ts` uses a module-level variable, not storage APIs. Code review should grep for `localStorage.setItem` and `sessionStorage.setItem` near token strings.
- Refresh token is `httpOnly` — JS cannot read it.

**Detection:** Browser devtools check (Milestone 8 human gate explicitly requires verifying no token in localStorage).

### 12.4 Stale membership / privilege escalation

**Risk:** User A is demoted from `admin` to `viewer`, but their in-memory access token still carries old claims. They continue performing admin actions for up to `ACCESS_TOKEN_LIFETIME` (15 minutes).

**Mitigation:** The access token does not carry role claims — roles are re-read from the `Membership` table on every request. The `OrgScopedViewMixin` calls `require_membership(user, org)` which reads the current DB row. A demotion takes effect immediately on the next API call.

This means Django performs one extra DB query per request (the membership lookup). At this scale, this is acceptable. Caching membership reads with a 30-second TTL can be added in Phase 10.9 if it becomes a latency concern.

### 12.5 Last-owner deletion leaving orphaned org

**Risk:** The last owner removes themselves or is deleted, leaving an organization with no owner and no way to add members.

**Mitigation:** `remove_membership` raises `ValidationError` if removing would leave the org with zero owners. `User.is_active = False` path (account deactivation) also checks: if the user is the last owner of any org, deactivation is rejected until ownership is transferred.

### 12.6 `AUTH_USER_MODEL` migration ordering

**Risk:** Setting `AUTH_USER_MODEL` to `users.User` after other apps have already created migrations that implicitly reference `auth.User` (via Django admin or default FK patterns) can produce inconsistent migration state.

**Mitigation:** Milestone 1 sets `AUTH_USER_MODEL` before creating any FK references to `User`. The existing domain models (`Runbook`, `Workflow`, etc.) reference `Organization` but not `User` directly — this is safe. The `ApprovalDecision.decided_by` FK is added in the same migration wave as the `User` model. If migration dependency ordering fails, the fix is to explicitly declare `dependencies = [("users", "0001_initial")]` in the relevant migrations.

> **MANDATORY PREFLIGHT GATE (H-04): Verify database and migration state before implementing Phase 10.7.**
>
> `AUTH_USER_MODEL` cannot be changed after Django has already created an initial migration for the project without complex squashing or data loss. This is manageable in Phase 10.7 because no production user data exists yet — but the gate must be explicit.

**Before starting Milestone 1, verify:**

```bash
# 1. Confirm no user/auth tables exist in the DB:
docker compose exec api python manage.py dbshell -- -c "\dt auth_*"
# Expected: no auth_user table (or "Did not find any relation named auth_user")

# 2. Confirm Django has no applied migrations for auth with user FK references:
docker compose exec api python manage.py showmigrations auth
# Acceptable: auth migrations exist but none are FK-dependencies for domain models.

# 3. Confirm no domain migration references auth.User:
grep -r "auth.User\|auth\.user\|django.contrib.auth.models.User" apps/api/apps/*/migrations/
# Expected: no matches (domain models use Organization FK, not User FK, in phases 10.1–10.6)

# 4. Confirm no existing users data:
docker compose exec api python manage.py shell -c "
from django.db import connection
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM auth_user')
        print(f'auth_user rows: {cursor.fetchone()[0]}')
except Exception as e:
    print(f'auth_user table not found (expected): {e}')
"
```

**If any of these checks fail** (e.g., domain models reference `auth.User`, or production data exists in `auth_user`), stop and create a separate migration plan before proceeding. The correct fix for an environment with existing data is to create a squash migration that replaces `auth.User` references with `users.User` atomically — that is out of scope for Phase 10.7's blueprint and requires explicit approval.

**For dev/staging environments:** if checks fail due to prior development schema drift, run `make bootstrap` (drops and recreates the DB) and re-apply all migrations from Phase 10.1 through 10.6 before starting Milestone 1. All data in dev is synthetic and can be re-seeded.

### 12.7 Refresh token cookie not sent cross-origin

**Risk:** The frontend is served from `localhost:5173` and the API is at `localhost:8000`. SameSite cookie restrictions may prevent the browser from sending the `refresh_token` cookie on the refresh call.

**Mitigation:** Set `SameSite=Lax` (not `Strict`) on the refresh token cookie in the dev environment. `SameSite=Strict` is correct for production where frontend and API share the same domain (or are subdomains). In dev, `Lax` allows the cookie to be sent on top-level navigations and same-site POST requests. The Django CORS config (`CORS_ALLOW_CREDENTIALS = True`) must also be set.

---

## 13. What NOT to do

**Do not enforce authorization in the frontend only.** Role-gating a UI button is an affordance, not a security control. Every mutation endpoint in Django must check the role, regardless of whether the frontend hides the button.

**Do not add FastAPI auth.** The AI service is stateless and accepts calls only from Django's internal network. It has no user concept. Adding JWT validation in FastAPI would require synchronizing secret keys and token blacklists across services — complexity with no benefit. Django authenticates before calling the AI service.

**Do not create runner user accounts.** The runner is a machine. It authenticates with a static bearer token. Giving the runner a user account creates a session lifecycle management problem (password rotation, account lockout, session expiry) that is not appropriate for a machine-to-machine credential.

**Do not add SSO/SAML/OIDC in this phase.** SSO is a sales requirement for enterprise customers. It adds significant implementation complexity (SAML assertion processing, IdP configuration, attribute mapping, session federation). Phase 15 in the roadmap addresses it when a real customer requires it.

**Do not implement a complex ABAC engine.** Four roles (`owner`, `admin`, `operator`, `viewer`) cover the permission surface of this platform at current scale. Adding attribute-based conditions, resource tags, or dynamic policy expressions before a real need exists produces an untestable, unmaintainable permission system.

**Do not split Django into multiple auth microservices.** The Django monolith is the correct architecture at this scale. An "auth service" separate from the domain service would require synchronizing user state, invalidating tokens across service boundaries, and adding network hops to every authenticated request. None of these costs are justified.

**Do not store the access token in localStorage or sessionStorage.** XSS attacks can exfiltrate anything in storage. Module-level memory is not accessible to injected scripts.

**Do not skip the migration to `AUTH_USER_MODEL` by monkey-patching Django's built-in `User`.** Using `AbstractBaseUser` correctly requires a fresh migration. The monkey-patch approach is fragile and will break on any Django upgrade.

**Do not add permission caching before measuring the cost.** One DB query per request for membership lookup is fast at this scale. Premature caching adds staleness bugs (see 12.4) without a demonstrated need.

---

## 14. Definition of done

Phase 10.7 is complete when all of the following are true:

- [ ] `User` model extends `AbstractBaseUser` with UUID primary key, email as username field, `full_name`, `is_active`, `is_staff`. `AUTH_USER_MODEL = "users.User"` is set.
- [ ] `Membership` model connects `User` to `Organization` with `role` field (four roles: `owner`, `admin`, `operator`, `viewer`). Unique constraint enforces one membership per user per org.
- [ ] `POST /api/v1/auth/login/` returns access token in body and sets `httpOnly` refresh cookie.
- [ ] `POST /api/v1/auth/refresh/` rotates the refresh token and returns a new access token.
- [ ] `POST /api/v1/auth/logout/` blacklists the refresh token and clears the cookie.
- [ ] `GET /api/v1/auth/me/` returns authenticated user with their org memberships.
- [ ] Every public domain endpoint returns 401 for unauthenticated requests.
- [ ] Every public domain endpoint returns 400 when `X-Organization-Id` header is missing.
- [ ] Every public domain endpoint returns 403 when `X-Organization-Id` references an org the user is not in.
- [ ] Every domain queryset is scoped to the requesting user's active organization. A user in org A cannot read any object belonging to org B.
- [ ] Role-based permission checks are enforced: `viewer` users cannot create, update, or delete resources.
- [ ] All four internal runner endpoints (`claim-next`, `heartbeat`, `step-update`, `complete`) only accept `RunnerTokenAuthentication`. User JWTs are rejected with 403.
- [ ] The runner sends `Authorization: Bearer <token>` on every internal API call.
- [ ] Runner startup validates the token is set and non-default; exits with error if not.
- [ ] The React app stores the access token in module-level memory, not in localStorage or sessionStorage.
- [ ] The refresh token cookie is `httpOnly` and not readable by JavaScript.
- [ ] The React app transparently refreshes the access token on 401 and retries the original request.
- [ ] Unauthenticated routes redirect to `/login` with `?next=<original_path>`.
- [ ] Full Django test suite passes (including all pre-existing tests updated for authenticated clients).
- [ ] Multi-tenant isolation tests pass for at least runbooks, workflows, and executions.
- [ ] Runner token tests pass.
- [ ] All five manual verification gates (section 11.6) have been executed and pass.
- [ ] No access token appears in browser localStorage or sessionStorage (confirmed via DevTools).

---

## Summary

**File created:** `docs/blueprints/phase-10-07-authentication-authorization-blueprint.md`

**Major sections included:**
1. Purpose and sequencing rationale — why auth comes seventh, not first
2. Current-state inspection checklist — 18 files to read before writing a line of code
3. Architecture invariants — 8 non-negotiable rules plus auth-specific constraints
4. Implementation scope — one subsection per repo area (users, organizations, config, all domain apps, runner, web)
5. Data model — `User` (UUID PK, email username), `Membership` (4 roles), runner token approach (no DB model), `OrganizationScopedQuerySet` mixin, field additions to existing domain models
6. API contracts — login/refresh/logout/me endpoints with exact request/response shapes; runner error codes; `X-Organization-Id` header protocol
7. Authorization rules per domain — 9 domain areas with per-action minimum role table
8. Frontend data contracts — `AuthState` shape, app init flow, API client changes, route protection, role-gated UI affordance disclaimer
9. Runner contract changes — token injection in `_post()`, `RunnerTokenAuthentication` class, `RUNNER_TOKENS` setting, startup validation, audit event actor identity
10. 8 ordered milestones — each with purpose, files touched, numbered steps, verification commands, rollback notes, and human approval gates
11. Testing strategy — 6 categories: auth API, permission, multi-tenant isolation, runner token, frontend, manual gates
12. Failure modes — 7 risks with likelihood, mitigations, and detection strategy
13. What NOT to do — 8 explicit anti-patterns with rationale
14. Definition of done — 21 checkboxes

**Key assumptions:**
- Phases 10.1–10.6 (approvals, policies, audit, artifacts, integrations, richer AI parsing) are complete and passing at blueprint authoring time; their models and endpoints exist as described.
- No existing production users or sessions need to be migrated — the system is not publicly deployed until Phase 10.10.
- `RUNNER_REGISTRATION_TOKEN` is a single static token; multi-runner fleet management is deferred to Phase 11.
- The frontend and API run on different ports in development (`5173` and `8000`); `SameSite=Lax` is used for the refresh cookie in dev, `Strict` in production.
- `djangorestframework-simplejwt` is the JWT library; no other auth framework (django-allauth, dj-rest-auth) is introduced.
