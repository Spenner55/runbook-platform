# Frontend

## Role

`apps/web` is the React + TypeScript product frontend. It renders operator workflows and calls Django public APIs. It does not own domain state.

## Django-Only API Rule

All HTTP calls go through `src/shared/api/client.ts` and point at Django:

- `VITE_API_BASE_URL` configures the Django base URL.
- Feature API modules use `/api/v1/...` paths.
- No frontend code should call FastAPI, runner, PostgreSQL, or `/api/v1/internal/...`.

## Route Structure

Routes are defined in `src/app/router.tsx`:

| Route | Component | Status |
| --- | --- | --- |
| `/` | Redirects to `/organizations` | Implemented |
| `/organizations` | `OrganizationsPage` | Implemented |
| `/runbooks` | `RunbooksPage` | Implemented |
| `/workflows/new` | `WorkflowCreatePage` | Implemented |
| `/workflows/:workflowId` | `WorkflowDetailPage` | Implemented |
| `/executions/:executionId` | `ExecutionDetailPage` | Implemented |

## Server State Strategy

The app uses TanStack Query.

Current conventions:

- Domain API functions live under `src/features/<domain>/api`.
- Query/mutation hooks live under `src/features/<domain>/hooks`.
- Shared query client defaults live in `src/app/providers/queryClient.ts`.
- Query retry is currently `1`.
- Refetch on window focus is disabled.

## Feature Folder Conventions

Current feature folders:

- `features/organizations`
- `features/runbooks`
- `features/workflows`
- `features/executions`

Each feature may contain:

- `api/*Api.ts` for HTTP functions.
- `hooks/use*.ts` for React Query hooks.
- `types.ts` for DTO types used by that feature.

Route components live under `src/routes/<domain>`.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Django base URL. Example: `http://localhost:8000`. |

Do not add `VITE_AI_BASE_URL` or runner-facing frontend env vars.

## What Frontend Must Not Call

- FastAPI AI endpoints.
- Runner endpoints or containers.
- `/api/v1/internal/...`.
- PostgreSQL.
- Unversioned product APIs.

## Adding A New Page Safely

1. Confirm the Django public API exists or create it in an approved backend change.
2. Add feature types under `src/features/<domain>/types.ts`.
3. Add API functions under `src/features/<domain>/api`.
4. Add query/mutation hooks under `src/features/<domain>/hooks`.
5. Add a route component under `src/routes/<domain>`.
6. Register the route in `src/app/router.tsx`.
7. Add page-level tests for loading, success, and important failure states.
8. Update docs if the route exposes new product behavior.

## Error Handling Note

Django currently returns `{"errors": [...]}`. The frontend `getApiErrorMessage` helper still primarily looks for a top-level `detail`, then falls back to the HTTP status message. Future frontend polish should teach the helper to render the current error envelope.
