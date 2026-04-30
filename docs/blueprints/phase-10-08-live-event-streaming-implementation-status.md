# Phase 10.8 Live Event Streaming Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-29 |
| Scope | Read-only implementation audit of Phase 10.8 Live Event Streaming |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-08-live-event-streaming-blueprint.md`, and prior Phase 10 implementation-status docs |
| Verdict | **Not ready to move to Phase 10.9 yet.** The implementation is substantial and automated gates are green, but transaction-boundary, tenant-scoped error-contract, reconnect/backoff, and missing live-service-stream coverage should be fixed before Production Hardening starts. |

## 1. Executive verdict

Phase 10.8 is mostly implemented: the API runs under uvicorn, an in-process execution event bus exists, an authenticated SSE endpoint is registered at `/api/v1/executions/{id}/stream/`, execution and step status changes are emitted from Django service paths, the frontend uses `@microsoft/fetch-event-source` with authorization and organization headers, and polling fallback remains available.

The automated verification state is clean:

```sh
make lint
# passed

make test-api
# 516 passed

make test-runner
# 76 passed

make test-web
# 85 passed
```

Do not advance to Phase 10.9 until the required fixes in section 7 are complete or explicitly accepted. The highest-risk issue is that some step-start and approval-status paths wrap service calls in an outer `transaction.atomic()` while the called services emit stream events after only their inner transaction exits. That can publish a state event before the request's outer transaction commits, violating the blueprint's "emit after commit" rule.

## 2. Implemented scope

- `uvicorn[standard]` is present in API requirements.
- `apps/api/Dockerfile` runs `uvicorn config.asgi:application --workers 1` and documents the process-local event bus constraint.
- `ExecutionEventBus`, `StreamEvent`, `subscribe`, `unsubscribe`, `emit`, `emit_async`, and `get_buffered_events_after` are implemented.
- The event bus uses a per-execution subscriber set and 128-entry in-memory replay buffer.
- `GET /api/v1/executions/<uuid:execution_id>/stream/` is registered under `/api/v1/`.
- The stream endpoint authenticates JWTs, requires `X-Organization-Id`, checks organization membership, and returns `text/event-stream`.
- SSE responses include `Cache-Control: no-cache`, `X-Accel-Buffering: no`, and `Connection: keep-alive`.
- Already-terminal executions send `execution.status_changed` and `stream.closed`, then close.
- Active streams send `retry: 3000`, replay buffered events after `Last-Event-ID`, emit idle heartbeats, unsubscribe in `finally`, and close on terminal state.
- Service emit hooks exist for `claim_next_execution`, `update_execution_step`, `complete_execution`, `cancel_execution`, and approval-created `waiting_for_approval` transitions.
- Runner code remains unaware of SSE and continues to use Django internal APIs.
- Frontend installs `@microsoft/fetch-event-source`.
- `useExecutionStream` opens the stream with `Authorization: Bearer` and `X-Organization-Id` headers, updates the React Query cache, aborts on `stream.closed`, and tracks fallback state.
- `useExecutionDetail` disables active polling while streaming is healthy and re-enables 1500ms polling on stream fallback.
- `ExecutionDetailPage` shows live-update and polling-fallback status text.

## 3. Missing scope

- No manual live execution verification record was found for the required browser/DevTools gate.
- No backend test proves a real sync Django service or internal runner endpoint call delivers an SSE event to a live subscriber through `emit()` and the captured ASGI event loop. Current streaming tests mostly call `execution_event_bus.emit_async(...)`; service emit tests mock `emit`.
- No test enforces `404` for "execution not in requested organization"; the current endpoint returns `403`.
- No stream permission test covers a runner bearer token attempting to open a user stream.
- No test covers malformed `X-Organization-Id` distinctly from a missing header.
- No frontend test covers reconnect resync behavior when `Last-Event-ID` replay misses and the client must refetch canonical REST state.
- No frontend test covers premature server close after a successful `200 text/event-stream` open; this matters because failure counting resets on each successful open.
- No hard maximum stream duration is implemented. This is not in the definition of done, but the blueprint lists it as the mitigation for connection accumulation.

## 4. Blueprint drift

- `StreamExecutionView` fetches the execution by UUID first and then compares `execution.organization_id` to the header. For an existing execution in another organization, it returns `403` with "You are not a member of this organization." The blueprint says execution not found or not in org should return `404`.
- The missing/malformed org-header path returns `"X-Organization-Id header is required."`; the blueprint text says `"X-Organization-Id header required."`. This is minor contract drift, but tests should lock the intended envelope.
- `ExecutionStepStartView` and `ApprovalStatusView` call stream-emitting services inside outer `transaction.atomic()` blocks. The dedicated blueprint requires events to be emitted only after the relevant transaction commits.
- `applyStreamEvent` still has a fallback step match by `position` when `step_id` is absent. The blueprint says do not match by position. The server does send `step_id`, so this is non-blocking but should be removed.
- `useExecutionStream` returns `0` from `onerror`, which requests immediate retry rather than honoring the blueprint's 3-second reconnect interval.
- The stream endpoint uses a raw Django async view with manual JWT authentication. This matches an allowed blueprint option, but it should be kept covered by auth tests because it bypasses normal DRF viewset machinery.

## 5. Test coverage review

Covered:

- Event bus subscription, unsubscribe, multiple subscribers, replay buffer, buffer max length, terminal event handling, and no-loop no-op logging.
- Service emit hook calls for claim, step update, execution running, completion, cancellation, and heartbeat non-emission.
- SSE auth success, unauthenticated rejection, non-member rejection, headers, live event delivery via `emit_async`, terminal close behavior, already-terminal behavior, `Last-Event-ID` replay, heartbeat, and idle DB reconciliation of missed terminal state.
- Frontend cache patching for execution and step events, `stream.closed`, polling fallback after three explicit errors, and token absence from the stream URL.
- Execution detail page live-update and polling-fallback banners.
- Full automated gates pass: lint, API, runner, and web.

Gaps:

- The most important missing test is the real service-to-stream path: open the stream, call `update_execution_step` or the internal step update API, and assert the subscriber receives `step.status_changed` through `ExecutionEventBus.emit()`.
- No rollback/phantom-event test exists for stream emits inside nested transaction paths.
- No API test asserts cross-org execution lookup returns `404` instead of `403`.
- No API test asserts runner bearer credentials cannot open a user SSE stream.
- No frontend test proves reconnect attempts are delayed rather than immediate.
- No frontend test proves fallback activates after repeated premature closes that each briefly return `200`.
- Manual browser verification through DevTools has not been recorded.

## 6. Streaming/security/operational risks

- **Pre-commit event delivery:** Step-start and approval-status paths can emit before the outer transaction commits. A rollback or later exception could leave subscribers with a phantom state.
- **Tenant error leak:** Returning `403` for an execution that exists but is outside the requested org leaks more than the blueprint's tenant-scoped `404` contract.
- **Immediate reconnect loop:** Returning `0` from frontend `onerror` can create rapid retries during outages, weakening the reconnect-storm mitigation.
- **Process-local bus:** The event bus is single-process only. The Dockerfile enforces `--workers 1`, but Production Hardening must preserve that constraint or externalize the bus.
- **No real-time auth revocation:** Stream auth is checked only at connection time. This is accepted by the blueprint for Phase 10.8 but remains a Phase 10.9 risk to document.
- **Connection accumulation:** Streams close on terminal state and heartbeat on idle, but there is no hard stream lifetime cap.
- **Proxy buffering:** The app sends `X-Accel-Buffering: no`, but real proxy behavior still needs manual verification behind any production-like ingress.
- **Replay is best-effort:** Buffers exist only after a subscription creates the per-execution buffer. This matches the non-source-of-truth design, but the frontend must reliably refetch canonical state on reconnect misses.

## 7. Required fixes before Phase 10.9

1. Move stream emission onto `transaction.on_commit()` or otherwise guarantee emit-after-commit for every path, including `ExecutionStepStartView`, `ApprovalStatusView`, and `request_step_approval`.
2. Add an end-to-end async test that opens the SSE stream, triggers a real sync Django service/internal endpoint state transition, and verifies the event is delivered through `emit()` on the captured ASGI loop.
3. Change the stream endpoint to tenant-scope the execution lookup by `execution_id` plus `organization_id`, returning `404` when the execution is not in the requested org.
4. Add stream auth tests for missing, malformed, expired/invalid JWT, missing/malformed org header, wrong org, non-member, cross-org execution, viewer/operator access, and runner bearer token rejection.
5. Fix frontend retry behavior so reconnects honor the intended delay and fallback activates after repeated premature stream closes, not only explicit network/open errors.
6. Record the manual live execution gate from the blueprint, including DevTools proof that the access token is only in the Authorization header and not in the stream URL.

## 8. Recommended non-blocking follow-ups

- Add `MAX_STREAM_DURATION_SECONDS` and close long-lived streams with a documented reason.
- Remove the frontend step-position fallback in `applyStreamEvent`; require `step_id`.
- Add jitter to stream reconnect delays in Phase 10.9.
- Add metrics or structured counters for open streams, dropped-no-loop events, reconnect failures, heartbeat count, and stream duration.
- Add a production note that `uvicorn --workers > 1` breaks the in-memory bus unless an external transport is added.
- Add a small operator runbook for validating SSE through nginx/ALB with `curl -N`.
- Consider a periodic membership recheck in the heartbeat loop after Phase 10.9 decides the revocation requirement.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-08-live-event-streaming-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-implementation-status.md`
- `docs/blueprints/phase-10-02-policies-implementation-status.md`
- `docs/blueprints/phase-10-03-audit-trail-implementation-status.md`
- `docs/blueprints/phase-10-04-artifacts-implementation-status.md`
- `docs/blueprints/phase-10-05-integrations-implementation-status.md`
- `docs/blueprints/phase-10-07-authentication-authorization-implementation-status.md`
- `docker-compose.yml`
- `apps/api/Dockerfile`
- `apps/api/requirements/base.txt`
- `apps/api/config/asgi.py`
- `apps/api/config/api_v1_urls.py`
- `apps/api/config/settings/base.py`
- `apps/api/apps/executions/event_bus.py`
- `apps/api/apps/executions/stream_views.py`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/serializers.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/views.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/tests/test_streaming.py`
- `apps/api/apps/executions/tests/test_event_bus.py`
- `apps/api/apps/executions/tests/test_services_emit.py`
- `apps/api/apps/executions/tests/test_runner_api.py`
- `apps/api/apps/executions/tests/test_approval_runner_api.py`
- `apps/api/apps/approvals/services.py`
- `apps/web/package.json`
- `apps/web/package-lock.json`
- `apps/web/src/shared/api/client.ts`
- `apps/web/src/features/auth/authTokenStore.ts`
- `apps/web/src/features/auth/context/AuthContext.tsx`
- `apps/web/src/features/executions/types.ts`
- `apps/web/src/features/executions/api/executionsApi.ts`
- `apps/web/src/features/executions/hooks/useExecutionDetail.ts`
- `apps/web/src/features/executions/hooks/useExecutionStream.ts`
- `apps/web/src/features/executions/hooks/executionStreamEvents.ts`
- `apps/web/src/features/executions/hooks/executionStreamEvents.test.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx`
- `apps/web/src/routes/executions/ExecutionDetailPage.test.tsx`

## 10. Commands to run for verification

Focused backend streaming checks:

```sh
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/executions/tests/test_event_bus.py -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/executions/tests/test_services_emit.py -v
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/executions/tests/test_streaming.py -v
```

Focused frontend streaming checks:

```sh
docker compose exec web npm test -- --run src/features/executions/hooks/executionStreamEvents.test.tsx src/routes/executions/ExecutionDetailPage.test.tsx
```

Full regression gates:

```sh
make lint
make test-api
make test-runner
make test-web
```

Manual live gate before Phase 10.9:

```sh
make up
make logs-api
curl -N -H "Authorization: Bearer <token>" -H "X-Organization-Id: <org_uuid>" http://localhost:8000/api/v1/executions/<execution_uuid>/stream/
```

Manual verification must prove:

- The API logs show uvicorn, not `manage.py runserver`.
- A live execution detail page opens one SSE request for an active execution.
- Step states update without repeated REST polling while streaming is healthy.
- The stream closes after terminal execution state.
- The access token is not present in the URL query string.
- Polling fallback activates after repeated stream failure.
- Cross-org execution stream access returns the intended tenant-safe error.

## Short summary

Phase 10.8 has the main architecture in place and the automated suites pass. Treat it as near-complete, but not ready for Phase 10.9 until emit-after-commit behavior, tenant-safe stream lookup, frontend retry behavior, and the missing live service-to-stream test/manual gate are addressed.
