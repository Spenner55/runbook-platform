# Phase 06 Blueprint: React Product Slice

## 1. Phase Overview

| Field | Value |
| --- | --- |
| Phase number | 06 |
| Objective | Build the first usable React interface for the thin vertical slice so an operator can create and inspect organizations, runbooks, workflows, and executions entirely through Django APIs. |
| Status | Implemented; retained as planning blueprint |
| Primary outputs | App router, minimal app layout, shared Django API client, TanStack Query integration, feature-based frontend structure, page-level containers for the vertical slice, execution-detail polling, and a clear implementation/testing plan. |
| Dependencies | `/home/dylan/code/runbook-platform/docs/blueprints/phase-02-django-domain-foundation-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-03-application-service-layer-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-04-versioned-rest-apis-blueprint.md`, `/home/dylan/code/runbook-platform/docs/blueprints/phase-05-runner-real-flow-blueprint.md`, and the current Vite app in `/home/dylan/code/runbook-platform/apps/web`. |
| Frontend runtime baseline in repo | React `19.2.4`, React Router DOM `7.13.2`, TanStack Query `5.95.2`, Vite `8.0.1`, TypeScript `5.9.3` from `/home/dylan/code/runbook-platform/apps/web/package.json`. |
| Current frontend state | Implemented route/page slice exists for organizations, runbooks, workflow creation/detail, and execution detail using React Router, TanStack Query, and feature-scoped API modules. |
| Documentation basis reviewed on | 2026-03-31 |
| Official docs basis | Latest official docs reviewed first from React, Vite, React Router, and TanStack Query. |

### Current repo alignment notes

As of 2026-04-27, the frontend product slice is no longer a placeholder landing page. Current frontend architecture is documented in `docs/architecture/frontend.md`. Authentication, protected routes, approvals, policies, and live streaming remain future phases.

### Official Documentation Reviewed

- React managing state: [https://react.dev/learn/managing-state](https://react.dev/learn/managing-state)
- React sharing state: [https://react.dev/learn/sharing-state-between-components](https://react.dev/learn/sharing-state-between-components)
- React reducers: [https://react.dev/learn/extracting-state-logic-into-a-reducer](https://react.dev/learn/extracting-state-logic-into-a-reducer)
- React `<form>`: [https://react.dev/reference/react-dom/components/form](https://react.dev/reference/react-dom/components/form)
- Vite guide: [https://vite.dev/guide/](https://vite.dev/guide/)
- Vite env variables and modes: [https://vite.dev/guide/env-and-mode.html](https://vite.dev/guide/env-and-mode.html)
- React Router modes: [https://reactrouter.com/start/modes](https://reactrouter.com/start/modes)
- React Router declarative routing: [https://reactrouter.com/start/declarative/routing](https://reactrouter.com/start/declarative/routing)
- React Router data routing: [https://reactrouter.com/start/data/routing](https://reactrouter.com/start/data/routing)
- TanStack Query overview: [https://tanstack.com/query/latest/docs/framework/react/overview](https://tanstack.com/query/latest/docs/framework/react/overview)
- TanStack Query `QueryClientProvider`: [https://tanstack.com/query/latest/docs/framework/react/reference/QueryClientProvider](https://tanstack.com/query/latest/docs/framework/react/reference/QueryClientProvider)
- TanStack Query important defaults: [https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults)
- TanStack Query invalidations from mutations: [https://tanstack.com/query/latest/docs/framework/react/guides/invalidations-from-mutations](https://tanstack.com/query/latest/docs/framework/react/guides/invalidations-from-mutations)

### Version Alignment Notes

- This blueprint uses the latest official docs as the design basis, as required.
- Recommendations are restricted to patterns compatible with the versions already pinned in `/home/dylan/code/runbook-platform/apps/web/package.json`.
- No React Server Components, framework-specific route actions, or non-Vite runtime assumptions are required for this phase.

### Locked Constraints for This Phase

- Frontend must call Django only.
- Frontend must not call FastAPI directly.
- Use React Query for server-state needs first.
- Do not introduce Redux, Zustand, or a custom global store for this phase.
- Do not build dashboard chrome first.
- Focus on pages that exercise the backend vertical slice end to end.
- Keep page state simple, URL-driven where possible, and close to the page that owns it.

### Phase Goal in One Sentence

Replace the placeholder Vite page with a thin, route-driven React app that talks only to Django, uses React Query as the default server-state layer, and exposes the smallest useful UI for the runbook-to-execution vertical slice.

## 2. Frontend Architecture Decisions

### 2.1 Architectural Summary

Use a small client-side React application with:

- Vite for build/dev.
- React Router for route structure and navigation.
- TanStack Query for all server reads and write-side invalidation.
- A shared fetch-based Django API client.
- Feature folders for domain logic and components.
- Page-level route containers that compose feature hooks and presentational UI.

This phase should not attempt a full app shell, workspace switcher, notifications center, or generalized design system. The backend slice is the product. The UI should expose that slice directly.

### 2.2 Router Decision

Use React Router with a centralized route definition and `RouterProvider`, but do not use route loaders/actions as the primary data layer in Phase 06.

Recommended choice:

- `createBrowserRouter`
- nested route objects
- `RouterProvider`
- `Outlet`-based minimal layout

Reasoning:

- React Router gives a clear route tree and future nested-layout expansion.
- TanStack Query should own server-state fetching and caching for this phase.
- Using both React Router loaders and React Query for the same resource set would create duplicate fetch orchestration, duplicate caching concerns, and extra mental overhead too early.
- Route params and search params are still valuable even when loaders are intentionally deferred.

### 2.3 State Ownership Rule

Split state into only three buckets:

1. Server state: owned by TanStack Query.
2. URL state: owned by React Router search params and path params.
3. Local interaction state: owned by page or form components with `useState`, and `useReducer` only if a single form becomes meaningfully complex.

Do not create a fourth bucket with app-wide client state unless a concrete need appears.

### 2.4 Django-Only Boundary Rule

All frontend network calls must go through Django public endpoints under `/api/v1/`.

Allowed:

- `GET /api/v1/organizations/`
- `POST /api/v1/organizations/`
- `GET /api/v1/runbooks/`
- `POST /api/v1/runbooks/`
- `GET /api/v1/runbooks/{id}/`
- `POST /api/v1/workflows/`
- `GET /api/v1/workflows/{id}/`
- `POST /api/v1/workflows/{id}/publish/`
- `POST /api/v1/executions/`
- `GET /api/v1/executions/{id}/`
- optionally `POST /api/v1/executions/{id}/cancel/` if the cancel action is exposed in this phase

Disallowed:

- calling FastAPI AI endpoints
- calling runner-internal Django endpoints from the browser
- reading `AI_BASE_URL` in the frontend
- sending browser requests directly to `/api/v1/internal/...`

### 2.5 Thin-Slice Navigation Rule

Navigation should follow the backend creation flow:

1. create/select organization
2. create/list runbooks for that organization
3. create workflow from a runbook
4. inspect/publish workflow
5. create execution from the workflow
6. inspect live execution detail while runner updates it

This means the route tree should optimize for sequential task completion, not for a polished admin dashboard.

### 2.6 Query Strategy

Use React Query for:

- all list reads
- all detail reads
- all create/publish/cancel mutations
- polling execution detail while active
- post-mutation invalidation and targeted cache updates

Initial guidance:

- keep a single `QueryClient`
- define stable query keys in one module
- prefer invalidation over hand-written normalized cache logic
- set mutation retry to `0`
- tune query retry conservatively for local dev and explicit user feedback

### 2.7 Layout Rule

Build a minimal frame only:

- page width container
- small top utility nav
- page heading area
- main content column

Do not spend this phase on:

- sidebars
- resizable panels
- global breadcrumbs
- dashboard cards unrelated to the slice
- role-aware chrome

### 2.8 URL-As-State Rule

Use the URL to carry user context instead of a global store:

- `/runbooks?organizationId=<uuid>`
- `/workflows/new?runbookId=<uuid>`
- `/workflows/:workflowId`
- `/executions/:executionId`

Benefits:

- reload-safe
- shareable
- easy to reason about
- avoids overbuilding selected-organization global state

## 3. Proposed Frontend Folder/File Layout

Use the following structure under `apps/web/src`.

```text
apps/web/src/
  app/
    AppLayout.tsx
    router.tsx
    providers/
      AppProviders.tsx
      queryClient.ts
  shared/
    api/
      client.ts
      env.ts
      errors.ts
      types.ts
    lib/
      queryKeys.ts
      urls.ts
      formatters.ts
    ui/
      AsyncPageBoundary.tsx
      EmptyState.tsx
      ErrorState.tsx
      LoadingState.tsx
      PageHeader.tsx
      SectionCard.tsx
      StatusBadge.tsx
      KeyValueList.tsx
    forms/
      Field.tsx
      TextInput.tsx
      TextArea.tsx
      Select.tsx
      SubmitButton.tsx
      FormErrorSummary.tsx
  features/
    organizations/
      api/
        organizationsApi.ts
      components/
        OrganizationCreateForm.tsx
        OrganizationList.tsx
        OrganizationListItem.tsx
      hooks/
        useOrganizations.ts
        useCreateOrganization.ts
      types.ts
    runbooks/
      api/
        runbooksApi.ts
      components/
        RunbookCreateForm.tsx
        RunbookList.tsx
        RunbookListItem.tsx
        RunbookFilters.tsx
      hooks/
        useRunbooks.ts
        useRunbookDetail.ts
        useCreateRunbook.ts
      types.ts
    workflows/
      api/
        workflowsApi.ts
      components/
        WorkflowCreatePanel.tsx
        WorkflowDetailCard.tsx
        WorkflowDefinitionPreview.tsx
        WorkflowPrimaryActions.tsx
      hooks/
        useWorkflowDetail.ts
        useCreateWorkflow.ts
        usePublishWorkflow.ts
      types.ts
    executions/
      api/
        executionsApi.ts
      components/
        ExecutionHeader.tsx
        ExecutionMetadataCard.tsx
        ExecutionStepsTable.tsx
        ExecutionWorkflowSnapshot.tsx
        ExecutionPrimaryActions.tsx
      hooks/
        useCreateExecution.ts
        useExecutionDetail.ts
      types.ts
  routes/
    RootRedirect.tsx
    organizations/
      OrganizationsPage.tsx
    runbooks/
      RunbooksPage.tsx
    workflows/
      WorkflowCreatePage.tsx
      WorkflowDetailPage.tsx
    executions/
      ExecutionDetailPage.tsx
  main.tsx
  index.css
```

### Layout Principles

- `app/` owns application bootstrapping only.
- `shared/` contains generic cross-domain utilities and UI primitives.
- `features/` owns domain APIs, hooks, types, and reusable domain components.
- `routes/` owns page containers and route-specific composition.
- Keep route containers thin but still responsible for route params, search params, and page-level orchestration.

### Folder Layout Rules

- Put domain-specific fetchers in the same feature as the hooks that use them.
- Keep the shared fetch client generic and transport-oriented only.
- Do not create a top-level `store/` folder.
- Do not create a giant top-level `components/` folder that mixes all domains.
- Avoid `utils.ts` dumping grounds. Prefer named modules such as `formatters.ts`, `urls.ts`, and `queryKeys.ts`.

## 4. Route Map

### Recommended Route Inventory

| Route | Purpose | Notes |
| --- | --- | --- |
| `/` | Redirect entry | Redirect immediately to `/organizations`. |
| `/organizations` | Organizations list/create page | First entry point. Lets the user create and choose tenant context. |
| `/runbooks` | Runbook list/create page | Reads `organizationId` from the query string. |
| `/workflows/new` | Workflow create page | Reads `runbookId` from the query string, creates one workflow from one runbook. |
| `/workflows/:workflowId` | Workflow detail page | Shows definition and primary actions like publish/create execution. |
| `/executions/:executionId` | Execution detail page | Shows execution summary and steps; polls while active. |

### Route Definition Recommendation

Recommended file:

- `apps/web/src/app/router.tsx`

Recommended shape:

```tsx
const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <RootRedirect /> },
      { path: "organizations", element: <OrganizationsPage /> },
      { path: "runbooks", element: <RunbooksPage /> },
      { path: "workflows/new", element: <WorkflowCreatePage /> },
      { path: "workflows/:workflowId", element: <WorkflowDetailPage /> },
      { path: "executions/:executionId", element: <ExecutionDetailPage /> },
    ],
  },
]);
```

### Routing Rules

- Keep route definitions centralized.
- Use search params for filter/context state that should survive reload.
- Use path params only for stable entity identifiers.
- Avoid nested route depth beyond what this phase needs.
- Do not create a dashboard route if it has no direct vertical-slice utility.

## 5. Page-by-Page Blueprint

### 5.1 Organizations Page

#### Route

- `/organizations`

#### Purpose

- let the user create organizations
- let the user inspect current organizations
- provide clear next actions into the runbooks slice

#### Primary data dependencies

- `GET /api/v1/organizations/`
- `POST /api/v1/organizations/`

#### Page-level responsibilities

- call `useOrganizations()`
- call `useCreateOrganization()` if implemented in this phase
- render list, create form, and next-step links
- generate links to `/runbooks?organizationId=<id>`

#### Recommended UI structure

1. Page header with title and short purpose text.
2. Create organization form card.
3. Organizations list card.
4. Empty-state guidance if none exist yet.

#### Interaction model

- user submits `name` and `slug`
- successful create invalidates organizations list
- after success, keep user on the page and surface a clear link to the new organization’s runbooks page
- optionally auto-focus the newly created row or highlight it briefly

#### UI states

- loading: page-level skeleton or list placeholder
- success: organization list visible
- empty: “No organizations yet. Create one to start the slice.”
- error: request failure card with retry button

#### Do not add in this phase

- organization edit page
- delete flows
- organization settings chrome
- permissions management

### 5.2 Runbooks Page

#### Route

- `/runbooks?organizationId=<uuid>`

#### Purpose

- list runbooks for one selected organization
- create a runbook within that organization
- expose “Create workflow” as the next-step action

#### Primary data dependencies

- `GET /api/v1/runbooks/?organization_id=<uuid>`
- `POST /api/v1/runbooks/`
- optionally `GET /api/v1/organizations/` for validating the selected organization label if desired

#### Page-level responsibilities

- read `organizationId` from `useSearchParams()`
- if missing, render instructional empty state instead of attempting a fetch
- call `useRunbooks({ organizationId })` only when `organizationId` is present
- call `useCreateRunbook()`
- render form and list side by side or stacked depending on viewport width
- link each row to `/workflows/new?runbookId=<id>`

#### Create form fields

- `title`
- `slug`
- `raw_content`

#### Form behavior

- organization is inferred from the current `organizationId` search param
- user does not manually enter `organization_id`
- submit button disabled while mutation is pending
- after success:
  - reset title/slug/raw_content
  - invalidate runbook list for this organization
  - optionally show inline success confirmation

#### Runbook list fields

- `title`
- `slug`
- `status`
- `created_at`
- `updated_at`
- primary action: “Create workflow”

#### Useful secondary UX

- simple client-side filter input for title/slug search if API search is not implemented yet
- status badge
- short excerpt of `raw_content` only if runbook detail is not yet surfaced elsewhere

#### UI states

- missing organization context: instructional state with link back to organizations page
- loading: list skeleton while query is pending
- empty: “No runbooks yet for this organization.”
- error: list error with retry

#### Do not add in this phase

- WYSIWYG editor
- autosave drafts
- generalized filtering framework
- tabbed detail views

### 5.3 Workflow Detail/Create

Treat create and detail as two route containers sharing the same feature layer.

#### Workflow Create Route

- `/workflows/new?runbookId=<uuid>`

#### Workflow Create Purpose

- create one workflow from one selected runbook through Django
- show enough source context to confirm what is being transformed
- navigate directly to workflow detail after creation

#### Workflow Create Data Dependencies

- `GET /api/v1/runbooks/{runbookId}/` for source context
- `POST /api/v1/workflows/`

#### Workflow Create Page Responsibilities

- read `runbookId` from search params
- fetch runbook detail when `runbookId` is present
- render runbook summary and raw-content preview
- call `useCreateWorkflow()`
- on success, navigate to `/workflows/:workflowId`

#### Workflow Create UX

- show runbook title, slug, and status
- show read-only preview of `raw_content`
- present one clear action: “Generate workflow”
- keep the create action narrow; the client should not author workflow JSON directly

#### Create page empty/error states

- missing `runbookId`: instructional state
- runbook query loading: preview skeleton
- runbook query error: error card with retry
- mutation error: inline form/action error

#### Workflow Detail Route

- `/workflows/:workflowId`

#### Workflow Detail Purpose

- inspect the generated workflow definition
- publish a draft workflow
- create an execution from a published workflow

#### Workflow Detail Data Dependencies

- `GET /api/v1/workflows/{workflowId}/`
- `POST /api/v1/workflows/{workflowId}/publish/`
- `POST /api/v1/executions/`

#### Workflow Detail Page Responsibilities

- read `workflowId` from route params
- call `useWorkflowDetail(workflowId)`
- render metadata and full definition preview
- render primary actions based on workflow status
- call `usePublishWorkflow()` when status is `draft`
- call `useCreateExecution()` when status is `published`
- navigate to `/executions/:executionId` after execution creation succeeds

#### Action visibility rules

- if workflow is `draft`: show “Publish workflow”
- if workflow is `published`: show “Create execution”
- if workflow is `superseded` or `archived`: hide execution create action and explain why

#### Workflow detail sections

1. header with name/version/status
2. metadata card
3. definition card
4. step list/preview
5. action area

#### UI states

- loading: metadata and definition skeletons
- error: detail fetch error
- success: full detail and actions
- empty: not applicable for a detail route; use not-found style message if 404

### 5.4 Execution Detail

#### Route

- `/executions/:executionId`

#### Purpose

- provide the live operational read model for the slice
- show current execution state, runner metadata, and step-by-step progress
- poll while active and stop automatically when terminal

#### Primary data dependency

- `GET /api/v1/executions/{executionId}/`

#### Page-level responsibilities

- read `executionId` from route params
- call `useExecutionDetail(executionId)`
- decide whether polling should be active based on execution status
- render metadata, workflow snapshot summary, and step table/timeline
- optionally expose `cancel` only if the public cancel endpoint is implemented and the UI decision is approved

#### Recommended detail sections

1. execution header
2. execution metadata card
3. workflow snapshot summary
4. execution steps table
5. activity status note describing whether polling is active

#### Key fields to render

- execution `status`
- `workflow_version`
- `claimed_by_runner_id`
- `claimed_at`
- `last_heartbeat_at`
- `started_at`
- `finished_at`
- per-step `position`
- per-step `name`
- per-step `step_type`
- per-step `risk_level`
- per-step `status`
- per-step `started_at`
- per-step `finished_at`
- per-step `exit_code`
- per-step `error_message`

#### Status presentation guidance

- `queued`: emphasize waiting state
- `claimed`: indicate runner ownership acquired but step work may not have started
- `running`: show active polling indicator
- `succeeded`: show success summary and stop polling
- `failed`: show failure summary and stop polling
- `cancelled`: show cancellation summary and stop polling

## 6. Shared API Client Design

### 6.1 Goals

The shared client should:

- centralize base URL handling
- normalize headers and JSON parsing
- convert Django error envelopes into one frontend error shape
- remain transport-only and not become a domain god object
- support `AbortSignal` so React Query can cancel in-flight requests

### 6.2 Recommended Files

- `apps/web/src/shared/api/env.ts`
- `apps/web/src/shared/api/errors.ts`
- `apps/web/src/shared/api/client.ts`
- `apps/web/src/shared/api/types.ts`

### 6.3 Environment Rule

Read the base URL from:

- `import.meta.env.VITE_API_BASE_URL`

Do not read:

- `AI_BASE_URL`
- `API_BASE_URL`
- arbitrary `process.env` values in browser code

Recommended behavior:

- fail fast in development if `VITE_API_BASE_URL` is missing
- normalize trailing slash handling once in `env.ts`

### 6.4 Base Client Shape

Recommended transport helper:

```ts
export async function apiRequest<TResponse>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<TResponse>
```

Responsibilities:

- compose `${apiBaseUrl}${path}`
- set `Accept: application/json`
- set `Content-Type: application/json` for JSON bodies
- call `fetch`
- parse JSON if present
- throw `ApiError` for non-2xx responses
- return typed payload for success responses

### 6.5 Error Model

Represent Django errors as:

```ts
export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown> | null
}
```

Expected Django error envelope from Phase 04:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": {
      "slug": ["This field must be unique."]
    }
  },
  "status": 400
}
```

Frontend handling rule:

- never scatter raw `response.ok` handling across feature files
- always map server errors into `ApiError`
- expose field-level validation details to forms when available

### 6.6 Domain Client Recommendation

Keep domain-specific API functions close to the feature:

- `features/organizations/api/organizationsApi.ts`
- `features/runbooks/api/runbooksApi.ts`
- `features/workflows/api/workflowsApi.ts`
- `features/executions/api/executionsApi.ts`

Example shapes:

```ts
export function listOrganizations(signal?: AbortSignal)
export function createOrganization(input: CreateOrganizationInput)
export function listRunbooks(params: { organizationId: string }, signal?: AbortSignal)
export function createRunbook(input: CreateRunbookInput)
export function getRunbookDetail(runbookId: string, signal?: AbortSignal)
export function createWorkflow(input: { runbookId: string })
export function getWorkflowDetail(workflowId: string, signal?: AbortSignal)
export function publishWorkflow(workflowId: string)
export function createExecution(input: { workflowId: string })
export function getExecutionDetail(executionId: string, signal?: AbortSignal)
```

### 6.7 Fetch Layer Rules

- Keep request serialization explicit.
- Do not build a generic repository abstraction.
- Do not introduce Axios unless there is a concrete gap.
- Always pass React Query `signal` into read functions.
- Keep response types in feature `types.ts` files, not in the shared transport layer.

## 7. Hook Design

### 7.1 Shared Query-Key Convention

Recommended file:

- `apps/web/src/shared/lib/queryKeys.ts`

Recommended shape:

```ts
export const queryKeys = {
  organizations: {
    all: ["organizations"] as const,
  },
  runbooks: {
    list: (organizationId: string) => ["runbooks", "list", { organizationId }] as const,
    detail: (runbookId: string) => ["runbooks", "detail", runbookId] as const,
  },
  workflows: {
    detail: (workflowId: string) => ["workflows", "detail", workflowId] as const,
  },
  executions: {
    detail: (executionId: string) => ["executions", "detail", executionId] as const,
  },
}
```

Rules:

- keys must be deterministic
- use small serializable objects for filter dimensions
- do not inline ad hoc arrays in page files

### 7.2 `useOrganizations`

Recommended file:

- `apps/web/src/features/organizations/hooks/useOrganizations.ts`

Purpose:

- fetch organization list for the organizations page

Recommended behavior:

- query key: `queryKeys.organizations.all`
- query fn: `listOrganizations`
- retry: `1` or a small nonzero value
- stale time: `30_000` ms is reasonable for low-churn admin data

Suggested return:

- direct React Query result object, or a small wrapper that preserves `data`, `isPending`, `isError`, `error`, `refetch`

### 7.3 `useCreateRunbook`

Recommended file:

- `apps/web/src/features/runbooks/hooks/useCreateRunbook.ts`

Purpose:

- create a runbook under the currently selected organization

Recommended behavior:

- wraps `useMutation`
- mutation fn: `createRunbook`
- mutation retry: `0`
- on success:
  - invalidate `queryKeys.runbooks.list(organizationId)`
  - optionally pre-seed detail cache if a runbook detail route is added later

Recommended error handling:

- return field errors for `slug`, `title`, `raw_content` when present
- render non-field error summary above the form

### 7.4 `useCreateWorkflow`

Recommended file:

- `apps/web/src/features/workflows/hooks/useCreateWorkflow.ts`

Purpose:

- trigger workflow generation from a selected runbook

Recommended behavior:

- wraps `useMutation`
- mutation fn: `createWorkflow({ runbookId })`
- mutation retry: `0`
- on success:
  - optionally invalidate runbook-related workflow summary queries if they exist later
  - set or prefetch workflow detail cache
  - return created workflow payload so the page can navigate immediately

Page integration:

- `WorkflowCreatePage` should call `mutateAsync`
- after success, `navigate(`/workflows/${workflow.id}`)`

### 7.5 `useCreateExecution`

Recommended file:

- `apps/web/src/features/executions/hooks/useCreateExecution.ts`

Purpose:

- create a new execution from the current workflow detail page

Recommended behavior:

- wraps `useMutation`
- mutation fn: `createExecution({ workflowId })`
- mutation retry: `0`
- on success:
  - optionally set execution detail cache with the returned payload
  - navigate to `/executions/:executionId`

Important rule:

- do not optimistically fabricate execution state beyond what the server returned
- queued execution creation is cheap enough to rely on server truth

### 7.6 `useExecutionDetail`

Recommended file:

- `apps/web/src/features/executions/hooks/useExecutionDetail.ts`

Purpose:

- fetch execution detail
- encapsulate polling behavior decision

Recommended signature:

```ts
export function useExecutionDetail(executionId: string)
```

Recommended internals:

- query key: `queryKeys.executions.detail(executionId)`
- query fn: `getExecutionDetail(executionId, signal)`
- `enabled: Boolean(executionId)`
- `refetchInterval`: function based on current cached result
- `refetchOnWindowFocus`: true while active, false once terminal if desired

Status helper:

```ts
const ACTIVE_EXECUTION_STATUSES = new Set(["queued", "claimed", "running"])
```

Return helpers:

- `execution`
- `steps`
- `isActive`
- `isTerminal`
- `lastUpdatedAt`
- plus the underlying query flags

### 7.7 Additional Hooks Worth Adding

Even though not mandatory, these are useful and still aligned with the thin slice:

- `useCreateOrganization`
- `useRunbooks`
- `useRunbookDetail`
- `useWorkflowDetail`
- `usePublishWorkflow`

These should remain small wrappers, not custom abstractions over every possible query option.

## 8. Polling Strategy for Execution Detail

### 8.1 Polling Goal

The execution detail page should feel live while the runner is progressing work, without introducing websockets, SSE, or app-wide polling infrastructure.

### 8.2 Polling Rule

Poll only the execution detail query, and only while the execution is active.

Active statuses:

- `queued`
- `claimed`
- `running`

Terminal statuses:

- `succeeded`
- `failed`
- `cancelled`

### 8.3 Recommended Query Option

Use a functional `refetchInterval`:

```ts
refetchInterval: (query) => {
  const execution = query.state.data
  if (!execution) return false
  return ACTIVE_EXECUTION_STATUSES.has(execution.status) ? 3000 : false
}
```

### 8.4 Recommended Interval

Start with:

- `3000` ms while active

Reasoning:

- fast enough to show meaningful runner progress
- light enough for local dev and early operator usage
- easy to tune later if runner cadence changes

### 8.5 Stop Conditions

Stop polling when:

- status becomes `succeeded`
- status becomes `failed`
- status becomes `cancelled`
- the route unmounts

### 8.6 UX Signals During Polling

Show a small but explicit indicator:

- “Live updates active”
- last refreshed timestamp
- runner heartbeat timestamp if present

Do not:

- add a separate websocket status system
- animate the whole page on each refresh
- poll other pages globally

### 8.7 Failure Behavior

If one poll fails:

- show inline error state without wiping the last good data if cached data exists
- allow manual retry
- keep previous successful result visible where possible

If repeated failures occur:

- surface that updates may be stale
- do not fake runner progress locally

## 9. UI Component Responsibilities

### 9.1 Shared UI Components

Recommended shared responsibilities:

- `AsyncPageBoundary.tsx`: handles loading/error/empty wrappers at page section level
- `LoadingState.tsx`: generic loading skeleton or placeholder
- `ErrorState.tsx`: generic retryable error view
- `EmptyState.tsx`: generic empty instructional view
- `PageHeader.tsx`: page title, description, and action slot
- `SectionCard.tsx`: consistent card wrapper
- `StatusBadge.tsx`: map backend statuses to label/color treatment
- `KeyValueList.tsx`: simple metadata rendering

Keep these presentational. They should not own fetch logic.

### 9.2 Organizations Components

- `OrganizationCreateForm.tsx`: local form state, submit handling, server-error display
- `OrganizationList.tsx`: iterates organizations
- `OrganizationListItem.tsx`: row rendering and “View runbooks” link

### 9.3 Runbooks Components

- `RunbookCreateForm.tsx`: fields for `title`, `slug`, `raw_content`
- `RunbookFilters.tsx`: optional local text filter and status summary
- `RunbookList.tsx`: renders list state
- `RunbookListItem.tsx`: row with status badge and “Create workflow” CTA

### 9.4 Workflows Components

- `WorkflowCreatePanel.tsx`: create action and source runbook preview
- `WorkflowDetailCard.tsx`: metadata summary
- `WorkflowDefinitionPreview.tsx`: structured definition and steps preview
- `WorkflowPrimaryActions.tsx`: publish and create-execution actions

### 9.5 Executions Components

- `ExecutionHeader.tsx`: headline status and polling indicator
- `ExecutionMetadataCard.tsx`: lifecycle metadata
- `ExecutionWorkflowSnapshot.tsx`: compact workflow snapshot view
- `ExecutionStepsTable.tsx`: step-level operational state
- `ExecutionPrimaryActions.tsx`: optional cancel action if explicitly included

### 9.6 Component Boundary Rules

- Pages own hooks, routing, and mutation orchestration.
- Feature components own domain presentation and form interaction.
- Shared UI components stay domain-agnostic.
- Avoid passing React Query objects through many layers; pages should derive plain props where practical.

## 10. Form Handling Recommendations

### 10.1 Primary Recommendation

Use plain React forms with local component state for this phase.

Why:

- forms are small
- validation needs are straightforward
- React Query already handles mutation lifecycle
- adding a form library now creates more surface area than value

### 10.2 Form State Rule

Use `useState` by default.

Use `useReducer` only when:

- one form has many related fields
- multiple event handlers are mutating the same state object
- validation and reset logic become hard to follow

Expected Phase 06 outcome:

- `useState` is enough for organizations and runbooks
- workflow create and execution create may not need full form state at all because they are single-action submits

### 10.3 Submission Pattern

Recommended page/form flow:

1. keep field values in local state
2. call `event.preventDefault()`
3. run light client validation
4. call `mutateAsync`
5. display field or form errors from `ApiError.details`
6. reset only on confirmed success

### 10.4 Client Validation Guidance

Keep client validation shallow and aligned to server validation:

- required fields
- trimmed non-empty strings
- obvious slug formatting

Do not attempt to fully duplicate Django serializer logic.

### 10.5 Server Validation Guidance

Django remains the source of truth for:

- uniqueness
- referential integrity
- invalid state transitions
- any workflow/execution business rules

Frontend job:

- surface those errors clearly
- keep the user on the same page
- preserve their entered form state on failure

### 10.6 Form UX Rules

- disable submit while mutation is pending
- show inline pending text like “Creating runbook...”
- place field-level errors near the field
- place general server errors in a summary area above submit controls
- do not wipe input values on failure

## 11. Error/Loading/Empty-State Handling

### 11.1 General Rule

Every page in this phase must explicitly design for:

- loading
- success
- empty
- error

Do not treat those states as incidental.

### 11.2 Loading States

Use page-appropriate loading UI:

- list pages: skeleton rows or lightweight placeholders
- detail pages: skeleton metadata blocks
- mutation buttons: inline pending label/spinner only where the action occurs

Avoid full-screen blockers for small mutations.

### 11.3 Success States

Success does not always need a toast.

Preferred success feedback:

- updated list after invalidation
- navigation to the newly created detail route
- small inline success message when staying on the same page

### 11.4 Empty States

Examples:

- no organizations yet
- no runbooks for selected organization
- missing route/search-param context like `organizationId` or `runbookId`

Empty states should explain the next action, not just say “No data”.

### 11.5 Error States

Differentiate:

- page-fetch errors
- section-fetch errors
- mutation errors
- validation errors

Recommended handling:

- page-fetch error: show `ErrorState` with retry
- mutation validation error: show inline field mapping
- mutation conflict error: show action-level explanation
- stale polling error with cached data: keep data visible and show a warning banner

### 11.6 Error Copy Guidance

Prefer concrete, backend-aligned text:

- “Workflow must be published before execution creation is allowed.”
- “Slug must be unique within the organization.”
- “Execution updates may be stale. Retry to refresh.”

Avoid generic “Something went wrong” unless no better information exists.

## 12. File-by-File Implementation Plan

### 12.1 Bootstrapping Files

#### `apps/web/src/main.tsx`

- replace the placeholder render path
- mount `AppProviders`
- remove direct dependency on `App.tsx` if the router becomes the real entry point

#### `apps/web/src/app/providers/queryClient.ts`

- create and export one `QueryClient`
- configure conservative defaults
- recommended defaults:
  - queries `retry: 1`
  - mutations `retry: 0`
  - reasonable `staleTime` left per-hook when resource-specific

#### `apps/web/src/app/providers/AppProviders.tsx`

- wrap children in `QueryClientProvider`
- optionally include React Query Devtools later, but keep them out of the first batch unless needed

#### `apps/web/src/app/AppLayout.tsx`

- render a minimal nav and `<Outlet />`
- include links to core routes only
- do not build heavy chrome

#### `apps/web/src/app/router.tsx`

- define the route tree
- export the router instance

### 12.2 Shared Transport and Utilities

#### `apps/web/src/shared/api/env.ts`

- read and normalize `VITE_API_BASE_URL`

#### `apps/web/src/shared/api/errors.ts`

- define `ApiError`
- define parsing helpers for Django error payloads

#### `apps/web/src/shared/api/client.ts`

- implement generic `apiRequest`
- handle JSON serialization and response parsing

#### `apps/web/src/shared/lib/queryKeys.ts`

- centralize keys for organizations, runbooks, workflows, executions

#### `apps/web/src/shared/ui/*`

- create small shared state/presentation primitives

### 12.3 Organizations Feature

#### `apps/web/src/features/organizations/types.ts`

- define `Organization`
- define `CreateOrganizationInput`

#### `apps/web/src/features/organizations/api/organizationsApi.ts`

- `listOrganizations`
- `createOrganization`

#### `apps/web/src/features/organizations/hooks/useOrganizations.ts`

- query wrapper

#### `apps/web/src/features/organizations/hooks/useCreateOrganization.ts`

- mutation wrapper

#### `apps/web/src/features/organizations/components/*`

- form/list/item presentation

#### `apps/web/src/routes/organizations/OrganizationsPage.tsx`

- page container

### 12.4 Runbooks Feature

#### `apps/web/src/features/runbooks/types.ts`

- define list/detail/create types

#### `apps/web/src/features/runbooks/api/runbooksApi.ts`

- `listRunbooks`
- `createRunbook`
- `getRunbookDetail`

#### `apps/web/src/features/runbooks/hooks/useRunbooks.ts`

- list query wrapper keyed by organization

#### `apps/web/src/features/runbooks/hooks/useRunbookDetail.ts`

- detail query for workflow create page

#### `apps/web/src/features/runbooks/hooks/useCreateRunbook.ts`

- create mutation wrapper

#### `apps/web/src/features/runbooks/components/*`

- create form, list, row actions

#### `apps/web/src/routes/runbooks/RunbooksPage.tsx`

- page container keyed by `organizationId` search param

### 12.5 Workflows Feature

#### `apps/web/src/features/workflows/types.ts`

- define workflow detail/create/publish response types

#### `apps/web/src/features/workflows/api/workflowsApi.ts`

- `createWorkflow`
- `getWorkflowDetail`
- `publishWorkflow`

#### `apps/web/src/features/workflows/hooks/useCreateWorkflow.ts`

- create mutation

#### `apps/web/src/features/workflows/hooks/useWorkflowDetail.ts`

- detail query

#### `apps/web/src/features/workflows/hooks/usePublishWorkflow.ts`

- publish mutation with detail invalidation

#### `apps/web/src/features/workflows/components/*`

- create panel, detail card, definition preview, action area

#### `apps/web/src/routes/workflows/WorkflowCreatePage.tsx`

- route container for generation

#### `apps/web/src/routes/workflows/WorkflowDetailPage.tsx`

- route container for publish and execution-create actions

### 12.6 Executions Feature

#### `apps/web/src/features/executions/types.ts`

- define execution list/detail/create types and step types

#### `apps/web/src/features/executions/api/executionsApi.ts`

- `createExecution`
- `getExecutionDetail`
- optionally `cancelExecution`

#### `apps/web/src/features/executions/hooks/useCreateExecution.ts`

- create mutation with navigation-on-success support

#### `apps/web/src/features/executions/hooks/useExecutionDetail.ts`

- detail query with polling

#### `apps/web/src/features/executions/components/*`

- header, metadata, steps table, workflow snapshot

#### `apps/web/src/routes/executions/ExecutionDetailPage.tsx`

- polling detail page container

## 13. Step-by-Step Implementation Checklist With Commands and Verification

These commands are for the future implementation pass. They should not be run as part of this blueprint creation step.

### Step 1. Install frontend dependencies and verify the baseline

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm install
npm run build
npm run lint
```

Verification:

- dependencies install cleanly
- placeholder app still builds
- lint passes before structural refactor begins

### Step 2. Wire providers and router

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run dev
```

Verification:

- app boots with `QueryClientProvider`
- router redirects `/` to `/organizations`
- no page still depends on the placeholder `App.tsx`

### Step 3. Add shared API client and environment handling

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run build
npm run lint
```

Verification:

- `VITE_API_BASE_URL` is read via `import.meta.env`
- network calls are composed from the shared client
- no frontend file references FastAPI URLs

### Step 4. Implement organizations page

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run dev
```

Manual verification:

- `/organizations` loads
- list request hits Django only
- create organization works
- created organization appears in the list without full reload
- “View runbooks” link carries the correct `organizationId`

### Step 5. Implement runbooks page

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run dev
```

Manual verification:

- `/runbooks` with missing `organizationId` shows instructional state
- `/runbooks?organizationId=<id>` lists only that organization’s runbooks
- create runbook works
- new runbook appears after invalidation
- each runbook row links to workflow creation

### Step 6. Implement workflow create/detail flow

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run dev
```

Manual verification:

- `/workflows/new?runbookId=<id>` loads runbook context
- workflow generation POST hits Django only
- successful create navigates to `/workflows/:workflowId`
- detail page renders definition
- publish action updates status correctly

### Step 7. Implement execution create/detail flow with polling

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run dev
```

Manual verification:

- execution creation works only from an allowed workflow state
- successful create navigates to `/executions/:executionId`
- detail page polls while `queued`, `claimed`, or `running`
- polling stops on terminal status
- step statuses update from runner-driven backend changes

### Step 8. Final verification

Commands:

```bash
cd /home/dylan/code/runbook-platform/apps/web
npm run build
npm run lint
```

If a test stack is added:

```bash
npm run test
```

Repository-level verification:

```bash
cd /home/dylan/code/runbook-platform
git status --short
```

Manual end-to-end verification with backend/runner running:

1. create organization
2. create runbook
3. create workflow
4. publish workflow
5. create execution
6. confirm execution detail live-updates until terminal

## 14. Frontend Test Plan

### 14.1 Recommended Tooling

For the implementation phase, add:

- Vitest
- React Testing Library
- `@testing-library/user-event`
- MSW for request mocking

This is the lightest reasonable stack for route, query, and mutation behavior.

### 14.2 Shared API Client Tests

Test:

- success JSON parsing
- non-2xx response conversion into `ApiError`
- validation envelope parsing
- missing/invalid response body handling

### 14.3 Hook Tests

Test:

- `useOrganizations` success, loading, and error states
- `useCreateRunbook` invalidation behavior
- `useCreateWorkflow` success navigation trigger contract
- `useCreateExecution` success payload handling
- `useExecutionDetail` polling enable/disable by status

### 14.4 Page Tests

Organizations page:

- renders loading state
- renders empty state
- renders list
- create form submission surfaces validation errors

Runbooks page:

- missing `organizationId` state
- list renders when query succeeds
- create mutation updates the UI

Workflow create/detail:

- missing `runbookId` state
- create flow navigates to detail
- publish action respects workflow status

Execution detail:

- renders step list
- shows polling-active indicator when status is active
- stops polling when terminal

### 14.5 What Not to Over-Test

Do not spend the phase on:

- snapshot-heavy styling tests
- pixel-level visual assertions
- testing React Query internals
- exhaustive router-library behavior tests

Prioritize user flows and boundary behavior.

## 15. Best Practices / Anti-Patterns

### Best Practices

- Keep server state in React Query, not in local component copies.
- Keep selected entity context in the URL when practical.
- Use one shared fetch client and small feature API modules.
- Keep route containers focused on composition and navigation.
- Invalidate queries after mutations instead of inventing complex local cache reconciliation.
- Stop polling automatically when the execution becomes terminal.
- Surface backend validation and conflict errors directly in the relevant action area.

### Anti-Patterns to Avoid

- calling FastAPI directly from the browser
- using React Router loaders and React Query for the same data in Phase 06
- introducing Redux or another global store just to hold fetched records
- building dashboard chrome before the vertical slice pages work
- creating a giant `api.ts` file with every endpoint in one place
- hiding route/search-param logic inside random utility hooks
- polling the whole app instead of only execution detail
- optimistic creation flows that fabricate workflow or execution status
- writing components that both fetch and render multiple unrelated domains

## 16. Codex Batching Plan With Approval Gates

The implementation should be delivered in small, reviewable batches.

### Batch 1. App foundation

Scope:

- providers
- router
- minimal layout
- shared API client
- shared query keys
- shared loading/error/empty components

Approval gate:

- confirm the app boot path, route map, and shared transport shape before feature pages are added

### Batch 2. Organizations and runbooks

Scope:

- organizations feature
- runbooks feature
- `/organizations`
- `/runbooks`

Approval gate:

- confirm URL-based organization context and runbook create/list UX before workflow work begins

### Batch 3. Workflow create/detail

Scope:

- workflow create page
- workflow detail page
- publish action

Approval gate:

- confirm that workflow generation remains Django-driven and that execution creation will hang off the workflow detail page, not a broader dashboard

### Batch 4. Execution detail and polling

Scope:

- execution create mutation
- execution detail page
- polling strategy
- step presentation

Approval gate:

- confirm polling cadence and terminal-state behavior before polish/testing

### Batch 5. Tests and cleanup

Scope:

- shared API client tests
- hook/page tests
- lint/build cleanup

Approval gate:

- confirm the slice is done before any optional enhancements like richer filters or cancel UI

## 17. Definition of Done

Phase 06 is done when all of the following are true:

- the placeholder frontend has been replaced with a real routed app
- the frontend calls Django only
- no frontend code calls FastAPI directly
- React Query is the default server-state mechanism for list/detail/mutation flows
- no Redux or equivalent global state has been introduced
- `/organizations` supports list/create
- `/runbooks?organizationId=<id>` supports list/create for the selected organization
- `/workflows/new?runbookId=<id>` creates a workflow from a runbook through Django
- `/workflows/:workflowId` renders workflow detail and allows publish/create-execution actions as appropriate
- `/executions/:executionId` renders execution detail and polls while active
- loading, success, empty, and error states are explicitly handled on each page
- the app builds and lints successfully
- the end-to-end thin slice can be exercised manually from organization creation through execution observation

## Short Chat Summary

- file created: `docs/blueprints/phase-06-react-product-slice-blueprint.md`
- primary pages covered: organizations, runbooks, workflow create/detail, execution detail
- biggest state-management rule for this phase: use React Query first for server state and keep the rest in URL/local state, not Redux/global store
