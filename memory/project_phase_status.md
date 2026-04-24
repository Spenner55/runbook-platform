---
name: Project Phase Status
description: Current implementation phase and what was completed when
type: project
---

Phase 6 (React Product Slice) completed on 2026-04-23. All prior phases (1–5) verified clean.

**Why:** Blueprints in docs/blueprints/ define phases 01–08. Each must be completed in order.

**Phase 6 deliverables in place:**
- `apps/web/src/app/` — router (createBrowserRouter), AppLayout (Outlet), AppProviders (QueryClientProvider), queryClient
- `apps/web/src/shared/api/` — apiRequest client, env (VITE_API_BASE_URL), ApiError
- `apps/web/src/shared/lib/queryKeys.ts` — centralized query keys
- `apps/web/src/features/{organizations,runbooks,workflows,executions}/` — feature API functions, hooks, and TypeScript types
- `apps/web/src/routes/` — all 5 route page components
- Execution detail polls (refetchInterval: 1500ms while active, false when terminal)
- Frontend calls Django only — no FastAPI or internal runner endpoints
- No Redux/Zustand
- Tests: OrganizationsPage + ExecutionDetailPage with Vitest + RTL (3 tests passing)

**Phase 5 deliverables (runner):**
- `runner/schemas.py` — typed contracts (RunnerSettings, ClaimNextResponse, etc.)
- `runner/client.py` — ApiClient with centralized httpx calls
- `runner/poller.py` — claim loop, no-work idle, error backoff
- `runner/executor.py` — sequential steps, FAIL_STEP, heartbeat thread
- `runner/log_streamer.py` — structured JSON logging
- `runner/main.py` — thin bootstrap only
- 46 runner tests pass (test_schemas, test_client, test_executor, test_poller, test_orchestration)

**Phase 5 fix applied on 2026-04-23:**
- Deleted dead `apps/api/apps/executions/internal_urls.py` (had broken imports, was unreferenced)
- Added `claimed_by_runner_id`, `claimed_at`, `last_heartbeat_at` to ExecutionDetail TS type
- Updated ExecutionDetailPage to render runner ownership fields

**How to apply:** Phases 1–6 are complete. Phase 7 (AI integration) is next. The system is fully runnable with `make up` and the vertical slice can be exercised from browser at http://localhost:5173.
