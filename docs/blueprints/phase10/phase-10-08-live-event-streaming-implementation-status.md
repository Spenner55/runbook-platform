# Phase 10.8 Live Event Streaming Implementation Status

| Field | Value |
|---|---|
| Audit date | 2026-04-30 |
| Scope | Read-only implementation audit of Phase 10.8 Live Event Streaming |
| Audited against | `phase-10-platform-expansion-roadmap-blueprint.md`, `phase-10-08-live-event-streaming-blueprint.md`, and prior Phase 10 implementation-status docs |
| Verdict | **Not ready to move to Phase 10.9 yet.** The streaming implementation is functionally close and automated lint/test gates are now clean, but the required manual live execution gate is not recorded. |

## 1. Executive verdict

Phase 10.8 is substantially implemented in the current working tree:

- Django exposes an authenticated SSE endpoint at `GET /api/v1/executions/{execution_id}/stream/`.
- Execution and step stream events are derived from Django state transitions, not from runner-side pushes.
- Stream authorization uses JWT user auth plus `X-Organization-Id` membership checks.
- The frontend uses `@microsoft/fetch-event-source` so the access token stays in the `Authorization` header, not the URL.
- Polling fallback remains available after repeated stream failures.
- Streams close on terminal execution state.

However, Phase 10.8 should not be signed off for Phase 10.9 Production Hardening until the manual live-streaming gate is complete. Current command results:

```sh
make lint
# passed

make test-api
# 521 passed, 1 teardown warning

make test-web
# 87 passed

make test-runner
# 76 passed

docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.test api pytest apps/approvals/tests/test_services.py apps/executions/tests/test_services.py -v
# 37 passed
```

The implementation is near-ready from an application behavior perspective, but not ready by the blueprint's gate discipline because the manual browser/DevTools live-streaming gate is still missing.

## 2. Implemented scope

- `uvicorn[standard]` is present in `apps/api/requirements/base.txt`.
- `apps/api/Dockerfile` runs `uvicorn config.asgi:application --workers 1` and documents the process-local event bus constraint.
- `ExecutionEventBus` exists with subscribe, unsubscribe, sync `emit`, async `emit_async`, and `Last-Event-ID` replay buffer support.
- The bus uses an in-memory per-execution subscriber set and bounded 128-event buffer.
- `GET /api/v1/executions/<uuid:execution_id>/stream/` is registered under `/api/v1/`.
- The stream endpoint authenticates with `JWTAuthentication`, rejects runner bearer tokens, requires a valid organization header, tenant-scopes execution lookup, and checks membership.
- SSE responses include `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, and `Connection: keep-alive`.
- Active streams send `retry: 3000`, replay buffered events after `Last-Event-ID`, emit idle heartbeats, unsubscribe in `finally`, and reconcile missed terminal state from the database.
- Already-terminal executions immediately send `execution.status_changed` and `stream.closed`, then close.
- Service emit hooks cover claim, step status change, execution `claimed -> running`, completion, cancellation, and approval-created `waiting_for_approval`.
- Stream emits use `transaction.on_commit()`, including nested transaction paths.
- Runner code remains unaware of SSE and continues to call Django internal APIs.
- Frontend streaming uses `@microsoft/fetch-event-source` with `Authorization` and `X-Organization-Id` headers.
- `useExecutionStream` updates React Query cache from stream events, aborts on `stream.closed`, invalidates the canonical execution query on close, and activates fallback after repeated failures.
- `useExecutionDetail` disables 1500ms active polling while streaming is healthy and re-enables it in fallback mode.
- `ExecutionDetailPage` shows live-update and polling-fallback status text.

## 3. Missing scope

- No recorded manual live execution gate was found for the required UI/DevTools checklist in the Phase 10.8 blueprint.
- No hard maximum stream duration is implemented.
- Replay buffering is count-bounded, but not pruned by the blueprint's "last 60 seconds" time window.
- No explicit test was found for expired JWTs on the stream endpoint, though invalid runner bearer credentials are covered.
- No production-like proxy/ingress verification was found for streaming latency and buffering behavior.

## 4. Blueprint drift

- The Dockerfile, not `docker-compose.yml`, is the canonical uvicorn entrypoint. This is acceptable because the blueprint allowed either approach, and the container command runs uvicorn with one worker.
- `config/asgi.py` did not need custom routing because Django's native ASGI application serves the async view. This is acceptable and simpler than the early roadmap wording.
- The event buffer is a 128-event deque, not a 60-second time-pruned buffer.
- `useExecutionStream` counts failures cumulatively per execution component lifetime. The blueprint says "three consecutive failures"; the implementation intentionally does not reset on every successful open so premature-close loops still trip fallback.
- The stream view synthesizes a `stream.closed` event after a terminal `execution.status_changed` event even though service code also emits `stream.closed`. This prevents subscribers from hanging if only the terminal status event arrives, but it is worth documenting because the exact close event ID sent to the live client may differ from the bus-buffered close event.
- Missing and malformed `X-Organization-Id` both return `400` with the same header-required style message.

## 5. Test coverage review

Covered:

- Event bus subscribe/unsubscribe, fanout, bounded buffer, replay, dropped-no-loop logging, and terminal event representation.
- Service emit points for claim, step update, execution running, completion, cancellation, and heartbeat non-emission.
- SSE auth success, unauthenticated rejection, non-member rejection, cross-org `404`, runner bearer rejection, missing/malformed org headers, response headers, live event delivery, terminal close, already-terminal close, replay, heartbeat, missed terminal reconciliation, lifecycle logging, and real service-to-stream delivery through sync service -> `on_commit` -> captured ASGI loop -> subscriber queue.
- Frontend cache patching for execution and step events, `stream.closed`, token-not-in-URL behavior, server retry interval handling, explicit failure fallback, and premature-close fallback.
- Execution detail page streaming banner, fallback banner, and close-triggered canonical refetch.
- Full API, web, and runner test suites pass.

Gaps:

- No manual browser/DevTools evidence is recorded.
- No explicit expired-token stream test was found.
- No test enforces a hard stream duration cap because no cap exists.
- No test enforces time-based event replay expiry.
- No production ingress/proxy test proves `X-Accel-Buffering: no` is sufficient behind the eventual deployment path.

## 6. Streaming/security/operational risks

- **Manual-gate risk:** automated tests do not prove browser Network behavior, token placement in DevTools, or real fallback ergonomics.
- **Process-local bus:** live streaming only works with one API process. The Dockerfile enforces `--workers 1`; Phase 10.9 must preserve this, and Phase 10.10 must not scale API workers/tasks without externalizing the bus.
- **Connection accumulation:** streams close on terminal state and heartbeat while idle, but there is no hard wall-clock stream lifetime.
- **Replay limitation:** events emitted before any subscriber creates a buffer are not replayable, and buffered events are count-bounded rather than time-bounded. Canonical REST refetch remains the correctness fallback.
- **Auth revocation:** stream permissions are checked at connection time only. This is accepted by the Phase 10.8 blueprint but remains a hardening consideration.
- **Proxy buffering:** the app sends the expected headers, but production-like ingress behavior still needs verification.
- **Reconnect behavior:** fallback is present, but no jitter is applied to reconnect delays.

## 7. Required fixes before Phase 10.9

1. Complete and record the Phase 10.8 manual live execution gate:
   - uvicorn is running, not `manage.py runserver`.
   - active execution detail page opens one long-lived SSE request.
   - step and execution statuses update live without repeated REST polling.
   - the stream closes after terminal execution state.
   - access token is present only in the `Authorization` header, not the URL.
   - fallback activates after repeated stream failure or interruption.

## 8. Recommended non-blocking follow-ups

- Add `MAX_STREAM_DURATION_SECONDS` and close long-lived streams with a documented reason.
- Add time-based replay pruning if the "last 60 seconds" contract matters operationally.
- Add explicit expired-token SSE coverage.
- Add reconnect jitter.
- Add metrics in Phase 10.9 for open streams, stream duration, reconnect failures, fallback activation, heartbeats, replay hits/misses, and dropped-no-loop events.
- Document the synthesized-vs-service-emitted `stream.closed` behavior.
- Add an operator runbook with `curl -N` verification through the same proxy path used in staging/production.

## 9. Exact files reviewed

- `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md`
- `docs/blueprints/phase-10-08-live-event-streaming-blueprint.md`
- `docs/blueprints/phase-10-01-approvals-implementation-status.md`
- `docs/blueprints/phase-10-02-policies-implementation-status.md`
- `docs/blueprints/phase-10-03-audit-trail-implementation-status.md`
- `docs/blueprints/phase-10-04-artifacts-implementation-status.md`
- `docs/blueprints/phase-10-05-integrations-implementation-status.md`
- `docs/blueprints/phase-10-07-authentication-authorization-implementation-status.md`
- `docs/blueprints/phase-10-08-live-event-streaming-implementation-status.md`
- `docs/verification/phase-10-04-readiness-record.md`
- `docker-compose.yml`
- `apps/api/Dockerfile`
- `apps/api/requirements/base.txt`
- `apps/api/config/api_v1_urls.py`
- `apps/api/apps/executions/event_bus.py`
- `apps/api/apps/executions/stream_views.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/executions/tests/test_event_bus.py`
- `apps/api/apps/executions/tests/test_services.py`
- `apps/api/apps/executions/tests/test_services_emit.py`
- `apps/api/apps/executions/tests/test_streaming.py`
- `apps/api/apps/approvals/services.py`
- `apps/api/apps/approvals/tests/test_services.py`
- `apps/web/package.json`
- `apps/web/package-lock.json`
- `apps/web/src/shared/api/client.ts`
- `apps/web/src/features/auth/authTokenStore.ts`
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
make test-web
make test-runner
```

Manual live gate:

```sh
make up
make logs-api
curl -N \
  -H "Authorization: Bearer <token>" \
  -H "X-Organization-Id: <org_uuid>" \
  http://localhost:8000/api/v1/executions/<execution_uuid>/stream/
```

Manual verification must record:

- API logs show uvicorn.
- The execution detail page uses a single SSE request while active.
- Step states update without repeated REST polling while streaming is healthy.
- The stream closes after terminal state.
- The access token is not present in the URL query string.
- Polling fallback activates after repeated stream failure.
- Cross-org stream access returns tenant-safe errors.

## Short summary

Phase 10.8 has the intended live-streaming architecture in place and automated lint/test gates are clean. Do not move to Phase 10.9 until the required manual live-streaming gate is recorded.
