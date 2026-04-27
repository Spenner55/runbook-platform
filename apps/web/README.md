# Web App

Vite + React + TypeScript frontend for the Runbook Platform.

## Current Scope

- React Router app shell.
- Routes for organizations, runbooks, workflow creation/detail, and execution detail.
- Feature-scoped API modules and TanStack Query hooks.
- Page-level tests with Vitest and Testing Library.

## Boundary Rules

- The frontend calls only Django public APIs under `/api/v1/`.
- All HTTP calls should go through `src/shared/api/client.ts`.
- Do not call FastAPI AI, runner services, PostgreSQL, or `/api/v1/internal/`.

## Commands

Inside the container through repo-root Makefile:

```sh
make test-web
make logs-web
make web-shell
```

Inside `apps/web`:

```sh
npm run dev
npm run build
npm run lint
npm run format
npm run format:check
npm test -- --run
```

## Environment

The frontend reads `VITE_API_BASE_URL` from `.env`. It should point to Django, for example `http://localhost:8000`.

See `docs/architecture/frontend.md` for frontend architecture guidance.
