# Phase 10.11: UI Navigation Overhaul Blueprint

| Field | Value |
|---|---|
| Phase number | 10.11 |
| Phase name | UI Navigation Overhaul |
| Objective | Replace the Phase 1 vertical-slice scaffold UI with a real application shell: org-aware routing without query-param workarounds, proper navigation for all implemented domains, and first-class discoverability for workflows needing review. |
| Status | Blueprint only |
| Depends on | Phase 10.7 (auth/RBAC) complete and verified |
| Authored | 2026-04-29 |

---

## 1. Purpose and problem statement

The current web UI was built as a Phase 1 linear demo wizard ("Step 1 → Step 2 → Step 3 → Step 4"). Every expansion phase since (10.1–10.7) added backend features without updating the frontend to match. The result is a UI that:

- Labels itself "Phase 1 Vertical Slice" in the header
- Requires clicking through an Organizations page to inject `?organizationId=` into the query string before any other page will render
- Shows "Select an organization first" if you navigate to `/runbooks` directly, even though the authenticated user already has an `active_organization_id` from their JWT session
- Has no way to list or discover existing workflows — only to create new ones
- Has no executions list — executions are only reachable by UUID
- Buries the AI workflow review action behind a warning banner inside a workflow detail page that has no direct nav path
- Has no audit log, no execution history, and no artifact browsing accessible from the nav
- Carries "Step N" eyebrow labels and instructional wizard copy on every page

**What this phase does not do:**

- Does not change any backend API contract, model, or service
- Does not add new API endpoints
- Does not add a design system or component library
- Does not add client-side state management beyond what React Query already provides
- Does not add SSE or live-update polling (Phase 10.8)
- Does not add role-based UI element hiding beyond what is already in place

---

## 2. Current-state inspection checklist

Before implementation begins, read these files in order. Do not implement from memory.

- [ ] Read `apps/web/src/app/router.tsx` — list every route and its element
- [ ] Read `apps/web/src/app/AppLayout.tsx` — note every nav link and header copy
- [ ] Read `apps/web/src/features/auth/context/AuthContext.tsx` — confirm `activeOrganizationId` is available on the context value
- [ ] Read `apps/web/src/features/auth/context/authContext.ts` — confirm the shape of the exported context type
- [ ] Read `apps/web/src/routes/organizations/OrganizationsPage.tsx` — understand the org-selection pattern to be replaced
- [ ] Read `apps/web/src/routes/runbooks/RunbooksPage.tsx` — understand the `?organizationId` query-param dependency
- [ ] Read `apps/web/src/routes/workflows/WorkflowDetailPage.tsx` — understand the "Review now" link approach
- [ ] Read `apps/web/src/routes/workflows/WorkflowReviewPage.tsx` — confirm it already has Accept/Reject buttons
- [ ] Read `apps/web/src/routes/executions/ExecutionDetailPage.tsx` — confirm the shape of execution data rendered
- [ ] Read `apps/web/src/shared/api/client.ts` — confirm `getActiveOrganizationId()` is called and sent as `X-Organization-Id`
- [ ] Read `apps/web/src/features/auth/authTokenStore.ts` — confirm `getActiveOrganizationId` / `setActiveOrganizationId` API
- [ ] List every existing feature hook directory under `apps/web/src/features/*/hooks/` — note which domains have existing API hooks
- [ ] Run `cd apps/web && npm run lint && npm run build` — establish a clean baseline before touching anything

---

## 3. Architecture invariants

These apply to every decision in this phase. Violating one requires explicit justification.

| Invariant | Consequence |
|---|---|
| The active org comes from `AuthContext`, never from query params | Remove all `?organizationId=` query-param patterns; read `activeOrganizationId` from context instead |
| No new API endpoints | Use only existing `/api/v1/` endpoints already implemented |
| React Query for all server state | No `useState` for fetched data; follow the existing pattern in every feature hook |
| No external component libraries | Use the existing CSS utility classes (`panel`, `stack-md`, `button`, `pill`, etc.) |
| One route per page | No nested panels simulating multi-step wizards on a single route |
| Existing hooks are the source of truth for API calls | Extend hooks if needed; never write raw `fetch` in a component |

---

## 4. Org-context architecture change

### Current (broken) pattern

```
/organizations → user clicks "View runbooks" → /runbooks?organizationId=<id>
```

`RunbooksPage` reads `organizationId` from `useSearchParams()`. If absent, it renders a dead-end screen. Every other page that needs org context has a similar dependency.

### Target pattern

`AuthContext` already exposes `activeOrganizationId`. `authTokenStore` already persists it and `client.ts` already reads it and sends it as `X-Organization-Id`. The conceptual fix is simple: **every page reads org context from `useAuth()`, not from the URL**.

```ts
const { activeOrganizationId } = useAuth()
```

The backend already accepts `X-Organization-Id` from the header (set by `client.ts`) — no API changes needed. Implementation may still require coordinated updates to hooks, query keys, empty states, loading/error states, affected route components, and frontend tests.

The Organizations page becomes a settings/management page, not a required entry point. The default route after login becomes `/runbooks`.

---

## 5. New route and navigation structure

### 5.1 Route table

| Path | Page | Notes |
|---|---|---|
| `/login` | LoginPage | Unchanged |
| `/` | → redirect to `/runbooks` | Change from `/organizations` |
| `/runbooks` | RunbooksPage | Drop `?organizationId` dep; use `activeOrganizationId` from context |
| `/runbooks/:runbookId` | RunbookDetailPage | **New** — shows runbook metadata + its workflows list |
| `/workflows/:workflowId` | WorkflowDetailPage | Unchanged path, updated content |
| `/workflows/:workflowId/review` | WorkflowReviewPage | Unchanged path, now reachable from nav |
| `/executions` | ExecutionsPage | **New** — list of executions for the active org |
| `/executions/:executionId` | ExecutionDetailPage | Unchanged path |
| `/approvals` | ApprovalsInboxPage | Unchanged |
| `/policies` | PoliciesPage | Unchanged |
| `/policies/:policyId` | PolicyDetailPage | Unchanged |
| `/integrations` | IntegrationsPage | Unchanged |
| `/integrations/:integrationId` | IntegrationDetailPage | Unchanged |
| `/organizations` | OrganizationsPage | Demoted — no longer in primary nav, keep for admin use |
| `/settings` | SettingsPage | **New (minimal)** — existing auth/session/org information; replaces OrganizationsPage in nav |

### 5.2 Primary navigation

Replace the current nav with:

```
Runbooks | Executions | Approvals | Policies | Integrations | Settings
```

Remove "Organizations" from primary nav. Keep the route but don't link it from the main nav — it's an admin utility. The header drops all "Phase 1 Vertical Slice" copy.

---

## 6. New and changed pages

### 6.1 AppLayout — header and nav

**Changes:**
- Remove "Phase 1 Vertical Slice" eyebrow and lede paragraph
- Change `<h1>` to "Runbook Platform" (already correct)
- Add org name display below the branding so the user knows which org is active
- Replace nav links per section 5.2

**New header structure:**
```
[Runbook Platform]          [Ada Admin · Acme Platform Engineering]  [Log out]
Runbooks | Executions | Approvals | Policies | Integrations | Settings
```

Org name comes from `useAuth().user.memberships` filtered to `activeOrganizationId`. This is already available — no new API call needed.

---

### 6.2 RunbooksPage — remove org-selection gate

**Current:** Requires `?organizationId` in URL; renders dead-end if missing.

**Change:**
- Remove `useSearchParams()` and the `organizationId` variable derived from it
- Read `activeOrganizationId` from `useAuth()`
- Pass it to `useRunbooks(activeOrganizationId)` (hook signature unchanged)
- Remove the dead-end "Select an organization first" branch
- Keep runbook creation obvious for testing/demo readiness: creation may remain inline on the list page or be exposed through a clear "New runbook" action that opens a form/modal
- Do not hide or bury the primary demo path for creating the first runbook
- Each runbook row links to `/runbooks/:runbookId`, not to `/workflows/new?runbookId=...`
- Show runbook status as a pill on each row

**Resulting page:** A clean list of runbooks with status badges, a link to each runbook's detail page, and an obvious way to create a runbook.

---

### 6.3 RunbookDetailPage — new page

**Route:** `/runbooks/:runbookId`

**Purpose:** Single runbook view showing metadata and all its workflows.

**Content:**
- Runbook title, slug, status, raw content (truncated with expand)
- List of workflows for this runbook — name, version, status, `requires_review` badge
  - Each workflow row links to `/workflows/:workflowId`
  - Workflows with `requires_review: true` show a "Needs review" pill
- "Generate workflow" button that posts to the AI parse endpoint (existing `WorkflowCreatePage` logic, can be inlined or kept as a modal)
- "Create workflow manually" button linking to `/workflows/new?runbookId=...` (existing route)

**Data:** Uses existing `useRunbooks` + a new `useRunbookWorkflows(runbookId)` hook. Before relying on `GET /api/v1/workflows/?runbook_id=<id>` or any review/status filter, verify that the existing API already supports that filter.

> **Check before implementing:** Confirm whether `GET /api/v1/workflows/` supports filtering by `runbook_id` and any review/status filters needed for discoverability. If not, do not add backend endpoints or API contract changes in Phase 10.11. Use existing list/detail endpoints only. Client-side filtering is acceptable only as a temporary small-data demo/testing fallback, and the fallback must be documented in the implementation notes.

---

### 6.4 WorkflowDetailPage — remove wizard copy

**Changes (minimal):**
- Remove "Step 4" eyebrow
- Remove wizard-style instructional paragraph
- The "Review now" link is already present when `requires_review` is true — keep it
- No structural changes needed

---

### 6.5 ExecutionsPage — new page

**Route:** `/executions`

**Purpose:** List executions for the active org, newest first.

**Content:**
- Table/list: execution ID (truncated UUID), workflow name, status pill, started at, finished at
- Status filter buttons: All | Queued | Running | Succeeded | Failed | Cancelled
- Each row links to `/executions/:executionId`
- No creation UI — executions are created from workflow detail pages

**Data:** Use a new `useExecutions(status?: string)` hook backed by existing execution list/detail APIs. Verify existing API support before relying on `GET /api/v1/executions/?workflow_id=<id>`, `GET /api/v1/executions/?status=<status>`, `GET /api/v1/executions/?organization_id=<id>`, or any other execution filter. Org scoping should come from the `X-Organization-Id` header when supported by the existing queryset pattern.

> **Check before implementing:** If workflow/status/org filters do not already exist, do not add backend endpoints or API contract changes in Phase 10.11. Use existing list/detail endpoints only. Client-side filtering is acceptable only as a temporary small-data demo/testing fallback, and the fallback must be documented in the implementation notes.

---

### 6.6 SettingsPage — new minimal page

**Route:** `/settings`

**Purpose:** Replaces "Organizations" as the low-scope account/org information entry point in nav.

**Content:**
- Active org name and slug (read-only display)
- Session/user information already available from auth context
- Members list only if membership endpoints and hooks already exist
- Nothing else for now — no org creation form (that stays at `/organizations` for superadmin use)

**Data:** SettingsPage must not require new backend endpoints. If membership endpoints already exist, the page may read them through existing hooks. If they do not exist, SettingsPage should show only auth-context/session/org information already available from existing APIs. Do not expand Phase 10.11 into membership management.

---

### 6.7 OrganizationsPage — demote, don't delete

Keep the existing page and route at `/organizations`. Remove it from the primary nav. It remains useful as a superadmin utility reachable by direct URL. Remove the "Step 1" eyebrow label.

---

## 7. File change inventory

### Modified files

| File | What changes |
|---|---|
| `apps/web/src/app/router.tsx` | Add new routes; change `/` redirect to `/runbooks` |
| `apps/web/src/app/AppLayout.tsx` | New header copy, new nav links, add org name display |
| `apps/web/src/routes/runbooks/RunbooksPage.tsx` | Remove `?organizationId` dep; read from `useAuth()`; link to runbook detail |
| `apps/web/src/routes/workflows/WorkflowDetailPage.tsx` | Remove "Step 4" eyebrow and wizard copy |
| `apps/web/src/routes/organizations/OrganizationsPage.tsx` | Remove "Step 1" eyebrow label |

### New files

| File | Purpose |
|---|---|
| `apps/web/src/routes/runbooks/RunbookDetailPage.tsx` | Runbook + workflow list |
| `apps/web/src/routes/executions/ExecutionsPage.tsx` | Org-scoped execution list |
| `apps/web/src/routes/settings/SettingsPage.tsx` | Org/session info; members only if existing APIs support them |
| `apps/web/src/features/executions/hooks/useExecutions.ts` | List executions with optional status filter |
| `apps/web/src/features/workflows/hooks/useRunbookWorkflows.ts` | List workflows scoped to a runbook |

### Files with no changes

Everything under `apps/web/src/features/*/hooks/` that is not listed above, all existing API files (`authApi.ts`, `client.ts`, etc.), all backend files.

Frontend test files may be added or updated only as needed for the lightweight smoke coverage in section 10.1, using the existing frontend test stack.

---

## 8. Implementation sequence

Follow this order strictly. Each step produces a working (lint-passing, render-passing) app before the next begins.

### Step 1 — Org context wiring
1. Edit `RunbooksPage.tsx`: replace `useSearchParams()` org derivation with `useAuth().activeOrganizationId`. Remove the dead-end gate. Verify `npm run lint` passes.
2. Verify the runbooks list renders correctly when navigating to `/runbooks` directly (no query param).

### Step 2 — Router and nav restructure
1. Edit `router.tsx`: change `/` redirect to `/runbooks`; add placeholder routes for `/runbooks/:runbookId`, `/executions`, `/settings`; keep all existing routes.
2. Edit `AppLayout.tsx`: update header copy; update nav links; add org name from `useAuth()`.
3. Verify all existing routes still render; verify nav links go to correct pages.

### Step 3 — RunbookDetailPage
1. Write `useRunbookWorkflows.ts` hook.
2. Write `RunbookDetailPage.tsx`.
3. Update `RunbooksPage.tsx` to link rows to `/runbooks/:runbookId` instead of `/workflows/new?runbookId=...`.
4. Run `npm run lint && npm run build`.

### Step 4 — ExecutionsPage
1. Write `useExecutions.ts` hook.
2. Write `ExecutionsPage.tsx` with status filter.
3. Run `npm run lint && npm run build`.

### Step 5 — SettingsPage
1. Write `SettingsPage.tsx` using auth context and existing org/members hooks only where they already exist.
2. Run `npm run lint && npm run build`.

### Step 6 — Cleanup
1. Remove "Step N" and "Phase 1 Vertical Slice" copy from `WorkflowDetailPage.tsx` and `OrganizationsPage.tsx`.
2. Final `npm run lint && npm run build && npx vitest run`.

---

## 9. Hook patterns — reference implementation

All new hooks follow the exact same pattern as existing ones. Reference `apps/web/src/features/runbooks/hooks/useRunbooks.ts` before writing any new hook.

```ts
// useExecutions.ts — representative pattern only, verify actual endpoint before coding
import { useQuery } from '@tanstack/react-query'
import { apiRequest } from '../../../shared/api/client'
import { queryKeys } from '../../../shared/lib/queryKeys'

export function useExecutions(status?: string) {
  return useQuery({
    queryKey: queryKeys.executions(status),
    queryFn: () =>
      apiRequest<Execution[]>(`/api/v1/executions/${status ? `?status=${status}` : ''}`),
  })
}
```

Add any new query key factories to `apps/web/src/shared/lib/queryKeys.ts` following the existing pattern.

---

## 10. Verification gates

### 10.1 Frontend smoke tests

Add or update lightweight frontend tests using the existing frontend test stack. Do not introduce Playwright, Cypress, or broad E2E scope unless that stack is already present and used for equivalent smoke coverage.

Required coverage:
- `/` redirects to `/runbooks`
- `/runbooks` renders without `?organizationId=`
- App navigation links render correctly
- Execution list handles loading, error, empty, and success states
- Runbook detail shows associated workflows, including workflows requiring review
- Review-needed workflows are discoverable without manually entering UUIDs

### 10.2 Manual/build gates

Each gate must pass before moving to the next implementation step.

| Gate | Command / check |
|---|---|
| No TypeScript errors | `cd apps/web && npm run build` (tsc errors fail the build) |
| No lint errors | `cd apps/web && npm run lint` |
| Existing tests pass | `cd apps/web && npx vitest run` |
| `/runbooks` renders without `?organizationId` | Manual browser check |
| Nav links reach correct pages | Manual browser check |
| Workflow review reachable in ≤2 clicks from runbooks | Manual browser check |
| Execution list shows all status variants from seed data | Manual browser check |
| No "Phase 1" or "Step N" copy visible anywhere | Manual browser check |

### 10.3 Demo seed-data precondition

Demo/testing readiness depends on local seed data. Before final verification, confirm existing seed tooling provides enough records to exercise the new navigation:

- At least one organization
- Runbooks
- Workflows
- At least one workflow requiring review
- Executions across useful statuses where existing seed tooling supports it
- Approvals, policies, integrations, and artifacts only if those phases are implemented and already seeded

Do not require new seed-data implementation in Phase 10.11 unless this blueprint is separately amended to include seed-data work. This is a UI navigation phase.

---

## 11. What is explicitly out of scope

- Role-based element hiding (e.g., hiding "Publish" from viewers) — the backend enforces this; UI can show the button and display the error
- Pagination on any list — all lists use the existing limit/offset defaults; add pagination in a separate phase if needed
- Search or filtering beyond execution status
- Inline editing of runbooks or workflows
- Organization switching (multi-org user support) — `activeOrganizationId` is set at login and does not change during a session in this phase
- Any new backend endpoints
- Dark mode, theming, or design system changes
- Toast notifications or optimistic UI
