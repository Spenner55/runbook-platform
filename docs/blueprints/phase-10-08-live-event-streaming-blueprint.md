# Phase 10.8: Live Event Streaming Blueprint

| Field | Value |
|---|---|
| Phase number | 10.8 |
| Phase name | Live Event Streaming |
| Objective | Replace the 1.5-second polling loop on the execution detail page with server-sent events so the UI reflects step state changes in real time, without introducing queue infrastructure or violating service boundaries. |
| Status | Blueprint only |
| Depends on | Phases 01–09 complete and verified; Phase 10.7 authentication and authorization complete and verified |
| Authored | 2026-04-24 |

---

## 1. Purpose and sequencing rationale

### What the system does today

`useExecutionDetail` in `apps/web/src/features/executions/hooks/useExecutionDetail.ts` calls `GET /api/v1/executions/{id}/` on a 1,500 ms `refetchInterval` while the execution is in an active state (`queued`, `claimed`, `running`). Every open browser tab drives at least one Postgres query per 1.5 seconds. With multiple concurrent executions and multiple users watching, this compounds into unnecessary steady-state read load on Django and Postgres.

The execution detail page (`ExecutionDetailPage.tsx`) explicitly tells the user: *"This page polls Django while the execution is active."* The banner is a placeholder — the intent was always to replace polling with streaming.

### What this phase changes

This phase adds a Server-Sent Events endpoint at `GET /api/v1/executions/{id}/stream/`. When the React app opens a stream for an active execution, Django holds the connection open and pushes small event payloads each time a step or execution status changes. The browser no longer needs to poll. When the execution reaches a terminal state, the stream closes automatically.

Polling is preserved as a fallback — if the SSE connection fails three times, `useExecutionDetail` resumes polling.

### Why SSE, not WebSockets

Execution status updates are **unidirectional**: the server pushes to the browser; the browser never sends data back through the stream. WebSockets are bidirectional. Adding bidirectional overhead for a unidirectional use case is waste. SSE is an HTTP response with `Content-Type: text/event-stream`. It works through any reverse proxy that supports HTTP/1.1 keep-alive, requires no client library beyond `EventSource` (or a fetch-based polyfill for header injection), and reconnects automatically. The roadmap blueprint (section 4.8) recommends SSE explicitly.

### Why streaming requires auth first (10.7 → 10.8)

The SSE stream carries execution-specific and organization-specific data. Without auth:
- Any browser tab can subscribe to any execution's stream.
- There is no identity to scope what events a subscriber receives.
- There is no way to detect when a user's session is revoked and the stream should be closed.

Phase 10.7 established JWT access tokens, the `X-Organization-Id` header convention, and org-scoped querysets. Phase 10.8 builds on all three: the stream endpoint validates the JWT and org membership before opening the stream, and the event bus scopes events to the execution's organization.

### Why streaming comes before production hardening (10.8 → 10.9)

The ASGI server change (from `manage.py runserver` to `uvicorn`) and the in-process event bus are architectural changes that affect every subsequent performance measurement in Phase 10.9. Hardening decisions — worker counts, connection pool sizing, health check tuning — depend on knowing which server process model the system uses. Do the ASGI migration in 10.8; measure and harden in 10.9.

### What this phase does not do

- Does not add WebSockets.
- Does not add Redis, Kafka, RabbitMQ, Celery, or any external broker.
- Does not replace the canonical execution state in the database. The stream is derived from state transitions, not the source of truth.
- Does not let the runner push directly to the browser.
- Does not stream audit events, integration events, or approval state through the SSE channel.
- Does not add streaming AI responses.
- Does not add unauthenticated streams.

---

## 2. Current-state inspection checklist

Before implementation begins, read the following files in order. Do not implement from memory.

- [ ] Read `docs/blueprints/phase-10-platform-expansion-roadmap-blueprint.md` section 4.8 — confirm SSE decision, in-process event bus rationale, and risk list are still current.
- [ ] Read `docs/blueprints/phase-10-07-authentication-authorization-blueprint.md` section 14 — confirm Phase 10.7 is complete and all checkboxes are satisfied.
- [ ] Read `apps/api/config/asgi.py` — confirm it contains only `get_asgi_application()` with no SSE or channel routing.
- [ ] Read `apps/api/Dockerfile` — confirm `CMD` is `python manage.py runserver 0.0.0.0:8000`. This must change to `uvicorn`.
- [ ] Read `docker-compose.yml` — confirm `api` service has no `command:` override. Note current port mapping (`8000:8000`).
- [ ] Read `apps/api/config/settings/base.py` — confirm `ASGI_APPLICATION = "config.asgi.application"` and `WSGI_APPLICATION` are both set. Confirm `REST_FRAMEWORK` auth classes as left by Phase 10.7.
- [ ] Read `apps/api/config/api_v1_urls.py` — list all registered routes. Note the pattern for internal vs. public endpoints. The SSE endpoint will be added here.
- [ ] Read `apps/api/apps/executions/services.py` — identify all state-transition points where SSE events must be emitted: `claim_next_execution`, `heartbeat_execution`, `update_execution_step`, `complete_execution`, `cancel_execution`.
- [ ] Read `apps/api/apps/executions/views.py` and `internal_views.py` — understand the existing view structure. The SSE view will be a new `APIView` (or plain async Django view), not part of `ExecutionViewSet`.
- [ ] Read `apps/api/apps/executions/serializers.py` — note field names in `ExecutionDetailSerializer` and `ExecutionStepSerializer`. SSE event payloads must use the same field names to avoid frontend surprises.
- [ ] Read `apps/api/apps/executions/models.py` — confirm the `Execution.Status` and `ExecutionStep.Status` choices. These are the values that appear in event payloads.
- [ ] Read `apps/web/src/features/executions/hooks/useExecutionDetail.ts` — confirm the current polling interval is 1,500 ms and the active status set. This hook will be modified or augmented.
- [ ] Read `apps/web/src/routes/executions/ExecutionDetailPage.tsx` — confirm the polling banner text. It will be replaced with a streaming status indicator.
- [ ] Read `apps/web/src/shared/api/client.ts` — confirm `apiRequest` sends `Authorization: Bearer` and `X-Organization-Id` headers (as wired in Phase 10.7). SSE connections cannot use `apiRequest` — they use a separate fetch-based EventSource call.
- [ ] Read `apps/api/requirements/base.txt` — confirm current contents. `uvicorn[standard]` and `anyio` will be added.
- [ ] Run `docker compose exec api python manage.py check` — confirm zero errors before starting.
- [ ] Run `docker compose exec api pytest` — record the full passing count. All existing tests must remain green after this phase.

---

## 3. Architecture invariants and boundaries

These invariants are inherited from the platform roadmap. Each has a specific consequence for Phase 10.8.

| Invariant | Phase 10.8 consequence |
|---|---|
| **INV-1: Django is the control plane.** | The event bus lives in Django. Events are derived from Django service-layer state transitions, not from runner pushes or AI service callbacks. |
| **INV-2: Runner talks only to Django internal APIs.** | The runner never pushes events to the SSE bus directly. When the runner calls `update_step` or `complete_execution`, Django's service layer emits the SSE event as a side-effect of the state transition. The runner has no awareness that SSE exists. |
| **INV-3: Frontend talks only to Django public APIs.** | The SSE stream is a Django endpoint under `/api/v1/`. The browser never connects to the AI service, the runner, or any external service. |
| **INV-4: AI service is stateless and advisory.** | The AI service has no connection to the event bus. It remains a pure transformer. |
| **INV-5: API versioning is non-negotiable.** | The SSE endpoint is `GET /api/v1/executions/{id}/stream/`. No exception. |
| **INV-6: UUID primary keys everywhere.** | `execution_id` in the SSE path is a UUID. Step IDs in event payloads are UUIDs. |
| **INV-7: Business logic in `services.py`.** | `ExecutionEventBus.emit()` is called from `services.py`, not from `views.py` or serializers. |
| **INV-8: Streaming must not become a second source of truth.** | The stream is read-only. Clients that miss events must re-fetch from `GET /api/v1/executions/{id}/` — which returns the current canonical state. Events are not authoritative; the database is. |

**Additional streaming-specific constraints:**

- **No Django Channels in Phase 10.8.** Django Channels adds a dependency on a channel layer backend (Redis or in-memory with limitations). Native Django async views with an `asyncio.Queue`-based event bus are sufficient for a single-server deployment. Channels is appropriate when multiple API server processes need to share events — that is a Phase 10.9 / Phase 10.10 concern.
- **No LISTEN/NOTIFY.** PostgreSQL's `LISTEN/NOTIFY` mechanism requires a persistent database connection held open outside the request/response cycle. With PgBouncer in transaction pooling mode (added in Phase 10.9), `LISTEN/NOTIFY` breaks. Avoid it.
- **No event persistence.** The event bus is in-memory only. Events that were emitted before a subscriber connected are not replayed from the database — the client re-fetches the full execution state and then opens the stream. Only events emitted during the live stream window (within the last 60 seconds) are bufferable for `Last-Event-ID` replay.
- **SSE auth at connection time only.** The JWT is validated when the stream connection opens. It is not re-validated on every event. If a user's access is revoked mid-stream, the revocation takes effect on the next connection attempt (after the current stream closes). This is acceptable for the 15-minute access token lifetime established in Phase 10.7 — most executions complete within this window.

---

## 4. Implementation scope by repo area

### `apps/api/apps/executions/`

Core of the phase. Four changes:

1. **`event_bus.py` (new)** — the in-process event bus: `ExecutionEventBus` singleton with `emit`, `subscribe`, and `unsubscribe` methods backed by `asyncio.Queue`.
2. **`services.py` (modified)** — add `ExecutionEventBus.emit()` calls at every state transition point. Synchronous service code emits via `asyncio.get_event_loop().call_soon_threadsafe()` because the service layer runs in sync Django views.
3. **`stream_views.py` (new)** — the async Django view for `GET /api/v1/executions/{id}/stream/`. Performs auth and permission checks, opens a subscriber queue, streams `text/event-stream`, and closes the queue when the execution reaches terminal state.
4. **`tests/test_streaming.py` (new)** — Django async test cases for the SSE endpoint.

### `apps/api/config/`

Two changes:

1. **`asgi.py` (modified)** — optionally add URL routing to serve SSE paths through the ASGI application explicitly. In practice, Django 5's `get_asgi_application()` already handles async views natively; no routing change is required as long as `uvicorn` is the server. Verify this during Milestone 1.
2. **`api_v1_urls.py` (modified)** — add `path("executions/<uuid:execution_id>/stream/", ...)` pointing to the new `StreamExecutionView`.

### `apps/api/Dockerfile` (modified)

Change `CMD` from `python manage.py runserver 0.0.0.0:8000` to `uvicorn config.asgi:application --host 0.0.0.0 --port 8000`. Add `uvicorn[standard]` to requirements.

### `apps/api/requirements/base.txt` (modified)

Add `uvicorn[standard]>=0.29,<1.0`. No other new dependencies for the server-side streaming implementation. `anyio` is a transitive dependency of `uvicorn[standard]` — it provides the async primitives Django uses internally.

### `docker-compose.yml` (modified)

Add a `command:` override on the `api` service to run uvicorn, so the Dockerfile `CMD` does not need to be the canonical entrypoint (keeping dev/prod parity clean). Alternatively, change the Dockerfile `CMD` — either approach is acceptable; the blueprint recommends Dockerfile `CMD` change for simplicity.

### `apps/web/src/features/executions/`

Three changes:

1. **`hooks/useExecutionStream.ts` (new)** — a React hook that opens an SSE connection using `@microsoft/fetch-event-source`. Accepts `executionId`. On mount: opens the stream. On each event: calls a provided callback. On terminal state event: closes the stream. On connection failure (3 retries): sets a `streamFailed` flag.
2. **`hooks/useExecutionDetail.ts` (modified)** — augmented to use `useExecutionStream` as the primary update mechanism. Polling fallback activates when `streamFailed` is `true` or when `EventSource`/fetch-event-source is unavailable.
3. **`api/executionsApi.ts` (no change)** — the REST API calls remain unchanged. The SSE connection is managed entirely within the hook layer.

### `apps/web/src/routes/executions/ExecutionDetailPage.tsx` (modified)

Replace the `"This page polls Django while the execution is active."` banner with a streaming status indicator showing whether the live stream is connected or falling back to polling.

### `apps/web/package.json` (modified)

Add `@microsoft/fetch-event-source` dependency (see section 8 for rationale on this library choice over native `EventSource`).

### `apps/runner/runner/`

No changes. The runner talks to Django internal endpoints exactly as before. The runner has no awareness of the SSE bus. The service layer emits SSE events as a side-effect when it processes the runner's API calls.

---

## 5. Streaming contract

### 5.1 Endpoint

```
GET /api/v1/executions/{execution_id}/stream/
```

**Headers required:**
```
Authorization: Bearer <access_token>
X-Organization-Id: <org_uuid>
```

**Response headers (on success):**
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

`X-Accel-Buffering: no` tells nginx (and ALB origin response buffering) not to buffer the response body — critical for SSE to work through a reverse proxy.

### 5.2 Event names

| Event name | When emitted | Who emits |
|---|---|---|
| `execution.status_changed` | Execution status transitions: `queued→claimed`, `claimed→running`, `running→succeeded/failed/cancelled` | Execution service (`claim_next_execution`, `complete_execution`, `cancel_execution`) |
| `step.status_changed` | Step status transitions: `pending→running`, `running→succeeded/failed` | Execution service (`update_execution_step`) |
| `execution.heartbeat` | Optional: emitted periodically to keep the connection alive through idle proxies | Event bus keep-alive coroutine |
| `stream.closed` | Execution has reached a terminal state; the stream will close after this event | Event bus, after emitting the final `execution.status_changed` |

**Do not stream:**
- Audit events
- Integration dispatch events
- Approval decisions (approval state is on `ExecutionStep.status` via `waiting_for_approval` — if 10.1 is implemented, include that status in `step.status_changed`)
- Heartbeat timing from the runner

### 5.3 Event payload contracts

All payloads are JSON objects sent as `data:` fields in the SSE format.

#### `execution.status_changed`

```
id: <event_uuid>
event: execution.status_changed
data: {"execution_id": "<uuid>", "status": "running", "timestamp": "2026-04-24T12:00:00Z", "started_at": "2026-04-24T12:00:00Z", "finished_at": null}
```

Fields:
- `execution_id` (string UUID) — identifies the execution.
- `status` (string) — new status. One of: `queued`, `claimed`, `running`, `succeeded`, `failed`, `cancelled`.
- `timestamp` (ISO 8601) — when the transition occurred in Django.
- `started_at` (ISO 8601 or null) — mirrors the `started_at` field from `ExecutionDetailSerializer`.
- `finished_at` (ISO 8601 or null) — mirrors `finished_at`.

#### `step.status_changed`

```
id: <event_uuid>
event: step.status_changed
data: {"execution_id": "<uuid>", "step_id": "<uuid>", "position": 2, "status": "running", "timestamp": "2026-04-24T12:00:01Z", "started_at": "2026-04-24T12:00:01Z", "finished_at": null, "exit_code": null, "error_message": ""}
```

Fields mirror `ExecutionStepSerializer` exactly. `position` allows the frontend to update the correct step without needing to look up the step by ID.

#### `execution.heartbeat`

```
event: execution.heartbeat
data: {"execution_id": "<uuid>", "timestamp": "2026-04-24T12:00:15Z"}
```

Emitted every 25 seconds if no other event has been sent in that window. Keeps the connection alive through proxies that close idle connections after 30 seconds. No `id:` field — heartbeats are not replay-eligible.

#### `stream.closed`

```
id: <event_uuid>
event: stream.closed
data: {"execution_id": "<uuid>", "final_status": "succeeded", "timestamp": "2026-04-24T12:05:00Z", "reason": "terminal_state"}
```

`reason` is always `terminal_state` in Phase 10.8. Future reasons might include `auth_revoked` or `timeout`. On receiving this event, the frontend must close the `EventSource`/fetch connection and stop reconnecting.

### 5.4 SSE wire format

Each event follows the standard `text/event-stream` format:

```
id: 550e8400-e29b-41d4-a716-446655440000\n
event: step.status_changed\n
data: {"execution_id": "...", "step_id": "...", ...}\n
\n
```

Rules:
- Every event that carries state information has an `id:` line (a UUID generated at emit time). This populates `Last-Event-ID` in the browser.
- Heartbeat events do not have an `id:` line.
- The `stream.closed` event has an `id:` line (it is a real event, not a comment).
- Each field is on its own line. The event is terminated by a blank line.
- The `data:` field value is a single-line JSON string (no embedded newlines).

### 5.5 Retry behavior

The browser (or `@microsoft/fetch-event-source`) will automatically reconnect after a dropped connection. To control reconnect timing, include `retry: 3000` at the top of each connected stream (after the first event):

```
retry: 3000\n
```

This tells the browser to wait 3 seconds before reconnecting, preventing reconnect storms if the server restarts.

### 5.6 `Last-Event-ID` replay

The event bus maintains a per-execution ring buffer of the last 60 seconds of events (implemented as a `collections.deque` with a max length based on estimated event rate — 128 entries is sufficient for any conceivable execution within 60 seconds).

When a subscriber connects with a `Last-Event-ID` header, the SSE view:
1. Reads `Last-Event-ID` from the request.
2. Looks up the ring buffer for the execution.
3. Replays all events in the buffer whose `id` follows the `Last-Event-ID` in the deque sequence.
4. Then resumes live streaming.

If no matching `Last-Event-ID` is found in the buffer (the ID is too old), the subscriber gets no replay — they must re-fetch from `GET /api/v1/executions/{id}/` to restore state, then open a fresh stream. The frontend handles this case by calling the REST endpoint before opening the stream on every connection attempt.

---

## 6. Data model and event source approach

### 6.1 Why no new database model

The event bus is **not persisted**. Events are not stored in a database table. The reasons:

1. **Events are derived state.** The authoritative record of every execution and step status is the `Execution` and `ExecutionStep` model rows. Events are a real-time notification that state has changed — they are not the record of the change. The audit trail (`AuditEvent`) already provides an immutable history if one is needed.

2. **Polling as source-of-truth fallback.** If a client misses events (network drop, page refresh), it calls `GET /api/v1/executions/{id}/` and gets the full current state from the database. There is no scenario where the event log is needed for correctness.

3. **No queue infrastructure.** Adding a `StreamEvent` database table and polling it from the SSE view would create a polling loop inside the streaming implementation — exactly the problem being solved. The in-process async queue is faster and simpler.

4. **INV-8.** The stream is not a source of truth. Do not make it one by persisting events.

### 6.2 `ExecutionEventBus` design

Location: `apps/api/apps/executions/event_bus.py`

```python
import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_MAX_BUFFER_SIZE = 128  # ring buffer per execution

@dataclass
class StreamEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


class ExecutionEventBus:
    """
    In-process SSE event bus. Singleton. Thread-safe for Django sync views
    via call_soon_threadsafe; async-native for async views.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._buffers: dict[str, deque[StreamEvent]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, execution_id: str) -> asyncio.Queue:
        async with self._lock:
            if execution_id not in self._subscribers:
                self._subscribers[execution_id] = set()
                self._buffers[execution_id] = deque(maxlen=_MAX_BUFFER_SIZE)
            queue: asyncio.Queue = asyncio.Queue()
            self._subscribers[execution_id].add(queue)
            return queue

    async def unsubscribe(self, execution_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            subs = self._subscribers.get(execution_id, set())
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(execution_id, None)

    def emit(self, execution_id: str, event: StreamEvent) -> None:
        """
        Called from sync Django service code. Schedules _async_emit on the
        event loop that was captured at application startup.

        IMPORTANT: Do NOT use asyncio.get_running_loop() here. Sync Django
        views and services run in uvicorn threadpool workers — there is no
        running loop in the calling thread. get_running_loop() would silently
        return without delivering any event (B-04 BLOCKER).

        The correct pattern is to capture the ASGI event loop once at startup
        (in ExecutionsConfig.ready() after the first ASGI request) and use
        loop.call_soon_threadsafe() against the captured reference.
        """
        loop = _get_asgi_event_loop()
        if loop is None or loop.is_closed():
            return  # No ASGI loop yet (startup, management commands, tests)
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._async_emit(execution_id, event))
        )

    async def _async_emit(self, execution_id: str, event: StreamEvent) -> None:
        async with self._lock:
            buffer = self._buffers.get(execution_id)
            if buffer is not None:
                buffer.append(event)
            for queue in list(self._subscribers.get(execution_id, set())):
                await queue.put(event)

    def get_buffered_events_after(
        self, execution_id: str, last_event_id: str | None
    ) -> list[StreamEvent]:
        buffer = self._buffers.get(execution_id, deque())
        if last_event_id is None:
            return []
        events = list(buffer)
        for i, ev in enumerate(events):
            if ev.id == last_event_id:
                return events[i + 1:]
        return []  # last_event_id not found in buffer; no replay possible


# Module-level singleton — shared across all requests on a single process.
execution_event_bus = ExecutionEventBus()
```

**Key design decisions in the bus:**

- The `asyncio.Lock` ensures the subscriber set and buffer are not corrupted by concurrent modifications.
- `emit()` is the sync-safe entry point: called from Django service code (which runs in sync threadpool workers under uvicorn), it schedules the async `_async_emit` coroutine on the event loop. **The implementation MUST use a captured ASGI event loop reference, not `asyncio.get_running_loop()`** — sync workers in uvicorn's threadpool have no running loop. The implementation module must expose a `_get_asgi_event_loop() -> asyncio.AbstractEventLoop | None` function that returns a loop reference captured once at application startup (e.g., in `ExecutionsConfig.ready()` via `asyncio.get_event_loop()` on the first ASGI request, or stored explicitly by an ASGI lifespan hook). **An integration test MUST verify:** create an execution, call the Django sync service (`update_execution_step`) through the runner's internal API endpoint, and assert an SSE subscriber on the same process receives the event within 100ms. Without this test the emit bug (silently dropping all events) will recur on every refactor.
- The bus is a module-level singleton. It is **process-local** and **dev/test only for multi-process deployments**: two `uvicorn` processes will not share event state. This is acceptable for Phase 10.8 (single API process in development and staging). Phase 10.10 must make an explicit decision before enabling live streaming in production. **Sticky sessions on the ALB do NOT solve this problem** — the runner and the browser are different clients and there is no guarantee they land on the same API task. The only production-safe options are (a) fix API task count at 1 (documented availability tradeoff, acceptable only for staging/non-critical), or (b) externalize the bus to Redis pub/sub, Postgres LISTEN/NOTIFY (requires non-transaction-pooling connection), or AWS EventBridge before enabling live streaming across multiple API tasks. See Phase 10.10 release gate for the mandatory decision.
- Buffer maxlen is 128 events — more than enough for any execution (typical execution has 5–10 steps, each with 2 transitions = ~20 events maximum).

### 6.3 Service-layer emit points

Add `ExecutionEventBus.emit()` calls to `apps/api/apps/executions/services.py` at these points:

| Function | After which operation | Event type |
|---|---|---|
| `claim_next_execution` | After `execution.save(...)` | `execution.status_changed` (status=`claimed`) |
| `heartbeat_execution` | No emit — heartbeats are internal runner state, not user-visible status changes | (none) |
| `update_execution_step` | After `step.save(...)` | `step.status_changed` |
| `update_execution_step` | After `execution.save(...)` (the CLAIMED→RUNNING transition) | `execution.status_changed` (status=`running`) |
| `complete_execution` | After `execution.save(...)` | `execution.status_changed` (terminal status) + `stream.closed` |
| `cancel_execution` | After `execution.save(...)` | `execution.status_changed` (status=`cancelled`) + `stream.closed` |

**Do not emit inside `atomic()` blocks before the transaction commits.** The event bus delivers events to live subscribers immediately. If the transaction rolls back after the event is emitted, subscribers receive a phantom state change. Solution: emit *after* the `atomic()` block exits (i.e., after the `with transaction.atomic():` block in `claim_next_execution`), or use Django's `transaction.on_commit()` callback.

For functions like `complete_execution` that do not use an explicit `atomic()` block, the emit can follow `execution.save(...)` directly. For `claim_next_execution`, which wraps in `with transaction.atomic():`, emit after the block:

```python
# In claim_next_execution:
with transaction.atomic():
    # ... claim logic ...
    result = {"execution": execution, "steps": steps, "claim_token": ...}

# After the transaction commits:
execution_event_bus.emit(
    str(execution.id),
    StreamEvent(event_type="execution.status_changed", data={...})
)
return result
```

---

## 7. API contracts and auth/permission requirements

### 7.1 Stream endpoint

```
GET /api/v1/executions/{execution_id}/stream/
```

**Authentication:** Requires `JWTAuthentication`. Passing `Authorization: Bearer <access_token>` is mandatory. The native browser `EventSource` API does not support custom headers — the frontend must use `@microsoft/fetch-event-source` (see section 8.2).

**Permission:** User must be an authenticated member of the execution's organization. Equivalent to the `IsAuthenticated` + `OrgScopedViewMixin` check applied to all domain endpoints in Phase 10.7, adapted for a non-ViewSet view:

```python
class StreamExecutionView(View):
    async def get(self, request, execution_id):
        # 1. Auth: DRF authentication is sync; call it via sync_to_async.
        # 2. Permission: check org membership.
        # 3. Fetch execution (confirm it exists and belongs to the org).
        # 4. If execution is already in terminal state: emit one event and close.
        # 5. Open subscriber queue.
        # 6. Stream events until terminal event or client disconnect.
        # 7. Unsubscribe queue on exit.
```

Django 5's async views work natively with `uvicorn`. `request.user` is populated by DRF's authentication middleware *if* the view is routed through DRF. Because SSE requires a raw Django `StreamingHttpResponse`, integrate auth manually:

**Option A (recommended):** Use `sync_to_async(authenticate)(request)` to run DRF's `JWTAuthentication` inside the async view, then proceed with async streaming logic.

**Option B:** Create a thin sync DRF `APIView` subclass that performs auth and permission checks, returns the execution object, then hands off to an async streaming generator.

The blueprint recommends **Option A** — a pure async view — to avoid running the HTTP worker thread synchronously while holding a streaming connection open.

**Error responses (non-streaming):**

| Condition | Status | Body |
|---|---|---|
| Missing `Authorization` header | 401 | `{"detail": "Authentication credentials were not provided."}` |
| Invalid or expired JWT | 401 | `{"detail": "Given token not valid for any token type."}` |
| Missing `X-Organization-Id` | 400 | `{"detail": "X-Organization-Id header required."}` |
| User not in org | 403 | `{"detail": "You are not a member of this organization."}` |
| Execution not found or not in org | 404 | `{"detail": "Not found."}` |

These are returned as plain JSON responses (not SSE) because the connection has not yet upgraded to `text/event-stream` when the check fails.

**Success response (streaming):**

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

Body: SSE event stream as defined in section 5.

### 7.2 Already-terminal execution behavior

If `GET /api/v1/executions/{id}/stream/` is called for an execution that is already in a terminal state (`succeeded`, `failed`, `cancelled`):

1. Return the normal streaming response headers.
2. Immediately emit one `execution.status_changed` event with the current terminal status.
3. Immediately emit one `stream.closed` event.
4. Close the response.

This prevents the frontend from opening a stream, waiting indefinitely, and never receiving any events for completed executions. The frontend should not open a stream for a terminal execution (it knows the status from the initial REST fetch), but if it does, the server handles it gracefully.

### 7.3 URL registration in `api_v1_urls.py`

```python
from apps.executions.stream_views import StreamExecutionView

urlpatterns = [
    ...existing routes...,
    path(
        "executions/<uuid:execution_id>/stream/",
        StreamExecutionView.as_view(),
        name="execution-stream",
    ),
]
```

The `uuid:` converter ensures Django validates the `execution_id` format before the view runs, returning a 404 for malformed UUIDs without reaching the view.

### 7.4 No new internal runner endpoints

The runner does not know about SSE. It calls the same `update_step` and `complete_execution` internal endpoints as before. The service layer emits SSE events as a side-effect. The runner's API contract is unchanged.

---

## 8. Frontend data contracts, fallback polling, and reconnection behavior

### 8.1 Why not native `EventSource`

The browser's native `EventSource` API has one critical limitation: it does not support custom request headers. The `Authorization: Bearer <access_token>` header (established in Phase 10.7) cannot be sent with a native `EventSource` connection. Options:

1. **Query parameter token:** Pass the access token as `?token=<jwt>`. Tokens in URLs appear in server access logs, browser history, and Referer headers — this is a meaningful security downgrade from the in-memory storage established in Phase 10.7.
2. **Separate short-lived SSE token:** Create a `POST /api/v1/executions/{id}/stream-token/` endpoint that issues a 60-second-lived one-time token for SSE. The frontend fetches the SSE token and uses it as a query parameter. This avoids the log-exposure problem but adds an extra round-trip and a new token management surface.
3. **`@microsoft/fetch-event-source`:** A thin library that reimplements `EventSource` using `fetch`, which fully supports custom headers. The access token is sent as `Authorization: Bearer`. Token storage security is unchanged.

**Decision: use `@microsoft/fetch-event-source` (option 3).** It is the approach that makes no tradeoffs on security, requires no new API endpoints, and has minimal additional dependency surface. The library is maintained by Microsoft and widely used for this exact pattern.

### 8.2 `useExecutionStream` hook

Location: `apps/web/src/features/executions/hooks/useExecutionStream.ts`

```typescript
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useEffect, useRef, useState } from 'react'

import { buildApiUrl } from '../../../shared/api/env'
import { getAccessToken, getActiveOrgId } from '../../auth/token'  // from Phase 10.7

export type StreamEvent =
  | { type: 'execution.status_changed'; data: ExecutionStatusChangedPayload }
  | { type: 'step.status_changed'; data: StepStatusChangedPayload }
  | { type: 'execution.heartbeat'; data: HeartbeatPayload }
  | { type: 'stream.closed'; data: StreamClosedPayload }

interface UseExecutionStreamOptions {
  executionId: string | null
  isActive: boolean  // only open stream when execution is active
  onEvent: (event: StreamEvent) => void
  onStreamFailed: () => void  // called after maxRetries consecutive failures
}

const MAX_RETRIES = 3

export function useExecutionStream({
  executionId,
  isActive,
  onEvent,
  onStreamFailed,
}: UseExecutionStreamOptions) {
  const [isStreaming, setIsStreaming] = useState(false)
  const failureCount = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!executionId || !isActive || failureCount.current >= MAX_RETRIES) {
      return
    }

    const controller = new AbortController()
    abortRef.current = controller
    setIsStreaming(true)

    fetchEventSource(buildApiUrl(`/api/v1/executions/${executionId}/stream/`), {
      headers: {
        Authorization: `Bearer ${getAccessToken()}`,
        'X-Organization-Id': getActiveOrgId() ?? '',
      },
      signal: controller.signal,
      onopen: async (response) => {
        if (response.ok) {
          failureCount.current = 0  // reset on successful connect
        } else {
          throw new Error(`Stream open failed: ${response.status}`)
        }
      },
      onmessage: (msg) => {
        if (!msg.event) return
        try {
          const data = JSON.parse(msg.data)
          onEvent({ type: msg.event as StreamEvent['type'], data })
          if (msg.event === 'stream.closed') {
            controller.abort()
            setIsStreaming(false)
          }
        } catch {
          // malformed JSON: ignore; the REST fallback will correct state
        }
      },
      onerror: () => {
        failureCount.current += 1
        if (failureCount.current >= MAX_RETRIES) {
          controller.abort()
          setIsStreaming(false)
          onStreamFailed()
        }
        // returning without throwing causes fetch-event-source to retry automatically
      },
    })

    return () => {
      controller.abort()
      setIsStreaming(false)
    }
  }, [executionId, isActive])

  return { isStreaming }
}
```

**Notes:**
- `getAccessToken()` and `getActiveOrgId()` are the module-level accessors added in Phase 10.7's `token.ts`.
- The hook does not manage `Last-Event-ID` internally — `@microsoft/fetch-event-source` tracks the last event ID from the `id:` field and sends it as `Last-Event-ID` on reconnect automatically.
- If `failureCount` reaches `MAX_RETRIES`, `onStreamFailed()` is called. This triggers the fallback in `useExecutionDetail`.

### 8.3 Modified `useExecutionDetail` hook

```typescript
const ACTIVE_EXECUTION_STATUSES = new Set(['queued', 'claimed', 'running'])
const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled'])

export function useExecutionDetail(executionId: string | null) {
  const queryClient = useQueryClient()
  const [streamFailed, setStreamFailed] = useState(false)

  const query = useQuery({
    queryKey: queryKeys.execution(executionId ?? 'missing'),
    enabled: Boolean(executionId),
    queryFn: () => getExecution(executionId ?? ''),
    // Polling only active when streaming has failed or is not yet available.
    refetchInterval: (q) => {
      if (!streamFailed) return false
      const status = q.state.data?.status
      if (!status || !ACTIVE_EXECUTION_STATUSES.has(status)) return false
      return 1500
    },
  })

  const isActive = Boolean(
    query.data && ACTIVE_EXECUTION_STATUSES.has(query.data.status)
  )

  useExecutionStream({
    executionId,
    isActive: isActive && !streamFailed,
    onEvent: (event) => {
      if (!executionId) return
      // Apply patch: update queryClient cache with the event data.
      queryClient.setQueryData(
        queryKeys.execution(executionId),
        (old: ExecutionDetail | undefined) => {
          if (!old) return old
          return applyStreamEvent(old, event)
        }
      )
    },
    onStreamFailed: () => setStreamFailed(true),
  })

  return query
}
```

`applyStreamEvent` is a pure function that takes the current cached execution and a `StreamEvent` and returns an updated copy. For `execution.status_changed`, it updates `status`, `started_at`, `finished_at`. For `step.status_changed`, it finds the step by **`step_id`** (UUID) and updates its fields. For `stream.closed` and `execution.heartbeat`, it is a no-op (the query cache is not modified).

> **Do NOT match steps by `position`** — positions can be reordered and are not guaranteed unique if a workflow has duplicate position values. Always match by `step_id`. The `position` field in the event payload is informational only (useful for display ordering). Step IDs are UUIDs and are stable.

### 8.4 `applyStreamEvent` contract

```typescript
function applyStreamEvent(
  execution: ExecutionDetail,
  event: StreamEvent,
): ExecutionDetail {
  switch (event.type) {
    case 'execution.status_changed':
      return {
        ...execution,
        status: event.data.status,
        started_at: event.data.started_at,
        finished_at: event.data.finished_at,
      }
    case 'step.status_changed':
      return {
        ...execution,
        steps: execution.steps.map((step) =>
          step.id === event.data.step_id   // match by UUID, not position
            ? {
                ...step,
                status: event.data.status,
                started_at: event.data.started_at,
                finished_at: event.data.finished_at,
                exit_code: event.data.exit_code,
                error_message: event.data.error_message,
              }
            : step
        ),
      }
    case 'stream.closed':
    case 'execution.heartbeat':
      return execution
    default:
      return execution
  }
}
```

### 8.5 Connection open protocol

Every time the stream is opened (initial connection or reconnect), the frontend:

1. Does NOT await current REST state before connecting. The stream may replay missed events via `Last-Event-ID`.
2. If this is an initial page load (no cached execution state), calls `GET /api/v1/executions/{id}/` first to populate the cache, then opens the stream.
3. On reconnect after a dropped connection, `@microsoft/fetch-event-source` sends `Last-Event-ID` automatically. If the server replays missed events, the cache is updated. If no events are replayed, the frontend calls `GET /api/v1/executions/{id}/` to re-sync state.

### 8.6 Reconnection behavior

- `@microsoft/fetch-event-source` retries automatically after a dropped connection.
- The server sends `retry: 3000` in the stream so the library waits 3 seconds between reconnect attempts.
- After 3 consecutive failures (tracked by `failureCount` in the hook), polling fallback activates.
- Polling fallback uses `refetchInterval: 1500` — identical to the pre-Phase-10.8 behavior.
- `streamFailed` state persists for the component's lifetime. It does not reset unless the component unmounts and remounts.

### 8.7 `ExecutionDetailPage` changes

Replace:
```tsx
<p className="muted">This page polls Django while the execution is active.</p>
```

With a conditional indicator:
```tsx
{isActive && (
  <p className="muted">
    {isStreaming ? 'Receiving live updates.' : 'Polling for updates (streaming unavailable).'}
  </p>
)}
```

The `isStreaming` value comes from `useExecutionStream` (exposed back through `useExecutionDetail`).

---

## 9. Runner impact

The runner is not changed in Phase 10.8.

The runner calls four Django internal endpoints: `claim-next`, `heartbeat`, `update_step`, `complete_execution`. These endpoints continue to exist unchanged. The runner sends no `EventSource` connections, receives no SSE events, and has no awareness of the event bus.

The only visible change from the runner's perspective: the Django API server process model changes from Django's development server to `uvicorn`. The runner's `httpx` client calls the same URLs on the same port. The HTTP protocol difference (sync runserver vs. ASGI uvicorn) is transparent to the runner.

**Important note on the runner's synchronous HTTP client:** The runner uses `httpx.Client` (synchronous). The uvicorn server handles synchronous requests via its threadpool — Django ASGI correctly offloads sync views to threads. No runner changes are required.

**Risk note on heartbeat timing:** `uvicorn` with the default worker configuration processes requests in async mode. Long-running sync operations (like artifact uploads or slow DB queries) are offloaded to a thread pool. The heartbeat endpoint is a fast DB write — it will not block the event loop. No heartbeat timing concerns are introduced.

---

## 10. Ordered milestones

Each milestone is a small, independently verifiable unit of work. Commit at every verification gate. Do not proceed to the next milestone if the current gate fails.

---

### Milestone 1 — Switch API server from runserver to uvicorn

**Purpose:** `manage.py runserver` uses Django's single-threaded development server, which blocks on open connections. Streaming responses over runserver will block the process for the duration of each open stream. `uvicorn` serves Django's ASGI application with an async event loop that can hold open many concurrent streaming connections without blocking.

**Files touched:**
- `apps/api/requirements/base.txt` — add `uvicorn[standard]>=0.29,<1.0`
- `apps/api/Dockerfile` — change `CMD` to `uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --reload`

The `--reload` flag is appropriate for development. For production (Phase 10.10), remove `--reload` and set worker count via `--workers`.

**Steps:**
1. Add `uvicorn[standard]>=0.29,<1.0` to `apps/api/requirements/base.txt`.
2. Change `CMD` in `apps/api/Dockerfile` from `python manage.py runserver 0.0.0.0:8000` to `uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --reload`.
3. Run `make down && make up`.
4. Watch `make logs` — confirm uvicorn starts successfully, confirms ASGI application loaded.
5. Run `docker compose exec api python manage.py check` — confirm zero errors.

**Verification:**
```bash
make down && make up
make logs
# Look for: "Started server process", "Uvicorn running on http://0.0.0.0:8000"
curl http://localhost:8000/api/v1/executions/ -H "Authorization: Bearer <token>" -H "X-Organization-Id: <uuid>"
# Expect: 200 with execution list (auth from Phase 10.7 must still work)
docker compose exec api pytest
# All existing tests must pass
```

**Rollback notes:** If uvicorn fails to start, revert `Dockerfile` CMD and `requirements/base.txt`. The system works exactly as before with runserver. The only capability lost is streaming.

**Human approval gate:** Confirm via `make logs` that the API is running under uvicorn, not runserver. Confirm all Phase 10.7 manual auth flows still work before proceeding.

---

### Milestone 2 — Implement `ExecutionEventBus`

**Purpose:** Create the in-process event bus that all subsequent milestones depend on.

**Files touched:**
- `apps/api/apps/executions/event_bus.py` — new

**Steps:**
1. Create `apps/api/apps/executions/event_bus.py` with `StreamEvent`, `ExecutionEventBus`, and the module-level `execution_event_bus` singleton as designed in section 6.2.
2. Do not wire any emit calls yet — this milestone only creates the bus.

**Verification:**
```bash
docker compose exec api python manage.py check
docker compose exec api python -c "
from apps.executions.event_bus import execution_event_bus, StreamEvent
print('EventBus imported OK:', execution_event_bus)
"
# Should print without errors
```

Write a standalone sync unit test (no async test runner required at this stage):
```bash
docker compose exec api pytest apps/executions/tests/test_event_bus.py -v
```

Test cases:
- `test_emit_no_subscribers_is_safe` — calling `emit()` with no subscribers does not raise.
- `test_buffer_stores_events` — after emit, `get_buffered_events_after(exec_id, None)` returns empty list; after two emits, buffer has two events.
- (Async tests for subscribe/emit round-trip are deferred to Milestone 4 stream tests.)

**Rollback notes:** Delete `event_bus.py`. No other files touched.

**Human approval gate:** None.

---

### Milestone 3 — Wire emit calls into execution services

**Purpose:** Make the service layer notify the event bus on every state transition.

**Files touched:**
- `apps/api/apps/executions/services.py` — add `execution_event_bus.emit(...)` calls at the five transition points identified in section 6.3

**Steps:**

1. Import `execution_event_bus` and `StreamEvent` at the top of `services.py`.

2. In `claim_next_execution`, after the `with transaction.atomic():` block exits, emit:
   ```python
   execution_event_bus.emit(
       str(execution.id),
       StreamEvent(
           event_type="execution.status_changed",
           data={
               "execution_id": str(execution.id),
               "status": execution.status,
               "timestamp": execution.claimed_at.isoformat(),
               "started_at": None,
               "finished_at": None,
           },
       ),
   )
   ```

3. In `update_execution_step`, after `step.save(...)`, emit `step.status_changed`. After the CLAIMED→RUNNING execution save, emit `execution.status_changed`.

4. In `complete_execution`, after `execution.save(...)`, emit `execution.status_changed` then `stream.closed`.

5. In `cancel_execution`, after `execution.save(...)`, emit `execution.status_changed` then `stream.closed`.

**Verification:**
```bash
docker compose exec api python manage.py check
docker compose exec api pytest apps/executions/tests/ -v
```

Existing tests must all pass. The emit calls are no-ops in the sync test environment (no event loop running) — they silently skip via the `except RuntimeError: return` guard in `emit()`.

Add one new test:
```bash
docker compose exec api pytest apps/executions/tests/test_services_emit.py -v
```

Test: `test_emit_called_on_step_update` — mock `execution_event_bus.emit` and call `update_execution_step`; assert `emit` was called once with `event_type="step.status_changed"`.

**Rollback notes:** Remove the import and emit calls from `services.py`. No migration, no schema change.

**Human approval gate:** None.

---

### Milestone 4 — Implement the SSE stream view

**Purpose:** Expose the streaming endpoint. This is the core deliverable of Phase 10.8 on the backend.

**Files touched:**
- `apps/api/apps/executions/stream_views.py` — new
- `apps/api/config/api_v1_urls.py` — register the stream URL
- `apps/api/apps/executions/tests/test_streaming.py` — new

**Steps:**

1. Create `apps/api/apps/executions/stream_views.py` with `StreamExecutionView` as an async Django `View`. The view:
   - Runs DRF `JWTAuthentication` via `sync_to_async`.
   - Validates `X-Organization-Id` header and org membership.
   - Fetches the `Execution` object via `sync_to_async(get_object_or_404)(Execution, pk=execution_id, organization_id=org.id)`.
   - If execution is already terminal: returns one `execution.status_changed` event + one `stream.closed` event, then closes.
   - Otherwise: subscribes to `execution_event_bus`, returns a `StreamingHttpResponse` with the async generator, unsubscribes in a `finally` block.

   The async generator (`async def _event_generator`):
   - Sends `retry: 3000\n\n` as the first bytes.
   - Checks `Last-Event-ID` header; replays buffered events if present.
   - Loops: `await asyncio.wait_for(queue.get(), timeout=25.0)` — if timeout, emit heartbeat; otherwise format and yield the event. If `stream.closed` event received, yield it and return.
   - `asyncio.CancelledError` on client disconnect — no action needed; generator exits.

2. Add to `api_v1_urls.py`:
   ```python
   path(
       "executions/<uuid:execution_id>/stream/",
       StreamExecutionView.as_view(),
       name="execution-stream",
   )
   ```

3. Write `test_streaming.py` using Django's async test client (`AsyncClient`).

**Verification:**
```bash
docker compose exec api python manage.py check
docker compose exec api pytest apps/executions/tests/test_streaming.py -v
```

Key test cases:
- `test_stream_unauthenticated_returns_401` — no `Authorization` header → 401 JSON response (not SSE).
- `test_stream_wrong_org_returns_403` — wrong org → 403.
- `test_stream_unknown_execution_returns_404` — non-existent UUID → 404.
- `test_stream_terminal_execution_closes_immediately` — already-`succeeded` execution → receives `execution.status_changed` + `stream.closed`, then response closes.
- `test_stream_receives_events_on_step_update` — open stream; in a separate async task, call `update_execution_step` service function; assert `step.status_changed` event received via stream.
- `test_stream_closes_on_complete_execution` — open stream; call `complete_execution`; assert `stream.closed` event received.

**Manual verification:**
```bash
# In one terminal, run a multi-step execution (from UI or via API)
# In another terminal, curl the stream endpoint:
curl -N \
  -H "Authorization: Bearer <token>" \
  -H "X-Organization-Id: <uuid>" \
  http://localhost:8000/api/v1/executions/<exec_id>/stream/
# Should see events flowing as the runner processes steps
```

**Rollback notes:** Delete `stream_views.py`. Remove the stream URL from `api_v1_urls.py`. No schema change, no migration.

**Human approval gate:** Manual curl verification confirms events arrive in real time while the runner executes steps. The stream closes within 1 second of the execution reaching terminal state.

---

### Milestone 5 — Frontend: install library and implement `useExecutionStream`

**Purpose:** Add the client-side infrastructure for SSE.

**Files touched:**
- `apps/web/package.json` — add `@microsoft/fetch-event-source`
- `apps/web/src/features/executions/hooks/useExecutionStream.ts` — new
- `apps/web/src/features/executions/types.ts` — add `StreamEvent` type definitions
- `apps/web/src/features/executions/hooks/useExecutionStream.test.ts` — new

**Steps:**
1. `cd apps/web && npm install @microsoft/fetch-event-source`.
2. Create `useExecutionStream.ts` per section 8.2.
3. Add `StreamEvent` union type and payload interfaces to `types.ts`.
4. Write tests for `useExecutionStream` using `msw` (if already in dev dependencies) or a manual fetch mock.

**Verification:**
```bash
cd apps/web && npm run lint
cd apps/web && npm run build
# Build must succeed with no TypeScript errors
```

**Human approval gate:** None. This milestone adds a hook that is not yet wired to any component.

---

### Milestone 6 — Frontend: wire streaming into `useExecutionDetail` and update page

**Purpose:** Connect the event stream to the execution detail page and enable the polling fallback.

**Files touched:**
- `apps/web/src/features/executions/hooks/useExecutionDetail.ts` — modify
- `apps/web/src/routes/executions/ExecutionDetailPage.tsx` — modify

**Steps:**
1. Modify `useExecutionDetail` per section 8.3 to use `useExecutionStream` and `applyStreamEvent`.
2. Implement `applyStreamEvent` per section 8.4.
3. Update `ExecutionDetailPage` per section 8.7 to show streaming vs. polling status.
4. Remove the `"This page polls Django while the execution is active."` static banner.

**Verification:**
```bash
cd apps/web && npm run lint
cd apps/web && npm run build
```

**Manual verification (golden path):**
1. Start a multi-step execution from the UI.
2. Navigate to the execution detail page.
3. Observe step statuses updating in real-time without polling.
4. Confirm the status indicator reads "Receiving live updates."
5. After execution completes, confirm the page shows terminal status immediately.
6. Confirm browser DevTools → Network shows one long-lived SSE connection (not repeated short requests).

**Manual verification (fallback):**
1. Open execution detail page for an active execution.
2. Stop the `api` container temporarily: `docker compose stop api`.
3. `useExecutionStream` fails 3 times. Status indicator changes to "Polling for updates (streaming unavailable)."
4. Restart `api`: `docker compose start api`. Polling continues.
5. Refresh the page. Streaming resumes.

**Rollback notes:** Revert changes to `useExecutionDetail.ts` and `ExecutionDetailPage.tsx`. Restore the original polling-only `refetchInterval: 1500` logic.

**Human approval gate:** Full manual golden-path verification. Step statuses must update in real time. The polling fallback must activate on stream failure. Confirm in DevTools that the access token is **not** in the SSE URL as a query parameter — it is only in the `Authorization` header (visible in the fetch-event-source XHR headers).

---

## 11. Testing strategy

### 11.1 Django SSE endpoint tests (`apps/executions/tests/test_streaming.py`)

Use Django's `AsyncClient` (available since Django 4.1) to make requests against the async view.

- **Auth enforcement:**
  - `test_stream_no_auth_returns_401`
  - `test_stream_expired_token_returns_401`
  - `test_stream_missing_org_header_returns_400`
  - `test_stream_wrong_org_returns_403`

- **Execution access:**
  - `test_stream_execution_not_in_org_returns_404`
  - `test_stream_unknown_uuid_returns_404`

- **Terminal state behavior:**
  - `test_stream_already_succeeded_closes_immediately` — response contains `execution.status_changed` and `stream.closed` events, then ends.
  - `test_stream_already_failed_closes_immediately`
  - `test_stream_already_cancelled_closes_immediately`

- **Live event delivery:**
  - `test_stream_receives_step_started_event` — call `update_execution_step` service; assert `step.status_changed` event appears in stream.
  - `test_stream_receives_step_completed_event`
  - `test_stream_receives_execution_completed_event` — call `complete_execution`; assert `execution.status_changed` and `stream.closed` appear.
  - `test_stream_closes_within_one_second_of_terminal_state` — timing assertion.

- **Reconnection and replay:**
  - `test_stream_last_event_id_replays_buffered_events` — emit two events; connect with `Last-Event-ID` set to the first event's ID; assert only the second event is replayed.
  - `test_stream_unknown_last_event_id_does_not_crash` — connect with an unknown `Last-Event-ID`; no replay, stream opens normally.

- **Heartbeat:**
  - `test_stream_sends_heartbeat_after_idle_period` — no events for 25+ seconds; assert heartbeat event received. (Use `asyncio.wait_for` with a short timeout in test; mock the idle timeout to 0.1s.)

### 11.2 Event bus unit tests (`apps/executions/tests/test_event_bus.py`)

- `test_emit_no_subscribers_noop`
- `test_subscribe_receive_emit` (async test)
- `test_multiple_subscribers_all_receive_event` (async test)
- `test_unsubscribe_stops_events` (async test)
- `test_buffer_maxlen_not_exceeded` — emit 200 events; buffer has ≤ 128.
- `test_get_buffered_events_after_known_id` — correct slice returned.
- `test_get_buffered_events_after_unknown_id` — empty list returned.
- `test_emit_from_sync_context` — call `emit()` from a non-async context; no error raised.

### 11.3 Service emit tests (`apps/executions/tests/test_services_emit.py`)

- `test_claim_next_emits_status_changed` — mock `emit`; call `claim_next_execution`; assert emit called with `execution.status_changed`.
- `test_update_step_emits_step_status_changed` — mock `emit`; call `update_execution_step`; assert emit called with `step.status_changed`.
- `test_update_step_emits_execution_running_on_first_step` — first step goes RUNNING; assert two emit calls: `step.status_changed` and `execution.status_changed`.
- `test_complete_execution_emits_status_and_closed` — assert emit called twice: `execution.status_changed` and `stream.closed`.
- `test_cancel_execution_emits_status_and_closed`
- `test_emit_not_called_on_heartbeat` — call `heartbeat_execution`; assert emit not called.

### 11.4 Frontend hook tests

Location: `apps/web/src/features/executions/hooks/`

- `useExecutionStream.test.ts`:
  - `opens stream on mount when isActive=true`
  - `does not open stream when isActive=false`
  - `calls onEvent with parsed payload on message received`
  - `calls onStreamFailed after MAX_RETRIES failures`
  - `aborts stream on stream.closed event`
  - `aborts stream on unmount`

- `useExecutionDetail.test.ts`:
  - `updates query cache on step.status_changed event`
  - `activates polling when streamFailed=true`
  - `does not poll when streaming is active`

- `applyStreamEvent` unit tests (pure function, no React):
  - Updates correct step by position on `step.status_changed`
  - Updates execution status on `execution.status_changed`
  - Returns execution unchanged on `execution.heartbeat`
  - Returns execution unchanged on `stream.closed`

### 11.5 Permission tests (reuse Phase 10.7 pattern)

- `test_viewer_can_subscribe_to_execution_stream` — `viewer` role → 200.
- `test_operator_can_subscribe_to_execution_stream` — `operator` role → 200.
- `test_runner_token_cannot_open_user_stream` — runner bearer token → 403.

### 11.6 Manual live execution gate

**Required before marking Phase 10.8 complete:**

1. Start the full stack: `make up`.
2. Log in to the UI as a valid user.
3. Create a workflow with at least 3 steps and at least 1 high-risk step.
4. Create an execution for the workflow.
5. Navigate to the execution detail page.
6. Observe: the page shows "Receiving live updates." status indicator.
7. Watch each step status change from `pending` → `running` → `succeeded` in real time.
8. Observe: execution status changes to `running` then `succeeded` with no page refresh.
9. Observe: stream status indicator disappears or changes after execution completes.
10. Open browser DevTools → Network → filter by `EventStream`. Confirm exactly one SSE connection was open for the execution, and it closed after the terminal event.
11. Run the execution again while watching the DevTools XHR payload. Confirm the `Authorization: Bearer` header is present in the SSE connection headers and the token does **not** appear in the URL query string.
12. Simulate a network interruption (disable network in DevTools for 5 seconds). After re-enabling: confirm the stream reconnected automatically (or polling fallback activated after 3 failures).

---

## 12. Failure modes and risks

### 12.1 Connection accumulation (high risk)

**Description:** Each open browser tab on the execution detail page holds one SSE connection to Django. With N active executions and M users watching, there are potentially N×M open connections, each holding an async generator in the uvicorn worker.

**Impact:** Memory accumulation (each queue + generator has a small footprint, but at scale this adds up); file descriptor exhaustion on the OS.

**Mitigations:**
- The stream closes automatically when the execution reaches terminal state. Well-behaved clients hold streams only for the duration of executions.
- The `asyncio.wait_for(queue.get(), timeout=25.0)` ensures the generator is not blocking indefinitely — it wakes every 25 seconds to emit a heartbeat, providing a natural "are you still there?" check.
- Add a hard `MAX_STREAM_DURATION_SECONDS = 3600` (1 hour) wall-clock limit on any single stream. If a stream has been open for 1 hour, emit `stream.closed` with `reason: "max_duration"` and close. No execution should take more than 1 hour; if it does, it is stuck, and the UI should be informed.
- Monitor open connection count in Phase 10.9 via uvicorn metrics.

### 12.2 Proxy buffering (high risk in production)

**Description:** nginx, ALB, and CloudFront may buffer the response body before forwarding it to the browser. Buffered SSE responses are not live — events accumulate and are sent in batches when the buffer flushes.

**Impact:** Real-time updates become delayed batch updates, defeating the purpose of streaming.

**Mitigations:**
- Send `X-Accel-Buffering: no` response header from the SSE view (disables nginx buffering for this response).
- In AWS deployment (Phase 10.10): configure ALB target group with `proxy_buffering off` equivalent — ALB does not buffer for HTTP/1.1 SSE responses natively; verify with a curl test from behind the ALB.
- Document this in Phase 10.9 production hardening checklist: "verify SSE events arrive within 100ms of emission when behind nginx/ALB."

**Detection:** If events arrive in batches after a delay, proxy buffering is the cause. Test by placing a 1-second delay between step transitions and checking whether events arrive with that delay or bundled.

### 12.3 Stale streams after auth revocation (medium risk)

**Description:** A user's org membership is revoked or their account is deactivated while an SSE stream is open. The stream continues delivering events because auth is only checked at connection time.

**Impact:** Revoked users receive execution updates for up to the duration of the open stream (at most 1 hour, or until the execution completes).

**Mitigations:**
- For Phase 10.8: accept this risk. The access token lifetime is 15 minutes. A revoked user's stream will close when they attempt to refresh their access token (which happens outside the stream channel). On the next page load, their JWT will fail and they will be redirected to login.
- For future phases: add a `revocation check` to the SSE heartbeat loop — every 60 seconds, `sync_to_async`-call `require_membership(user, org)`. If membership is gone, emit `stream.closed` with `reason: "auth_revoked"`.

**Document:** Phase 10.8 does not implement real-time revocation. This is a known limitation. Document in the Phase 10.9 hardening backlog.

### 12.4 Missed events before subscribe (low risk, mitigated by design)

**Description:** The runner updates a step between the moment the frontend fetches the execution via REST and the moment the SSE connection opens.

**Impact:** A step transition is missed; the UI shows the wrong step status.

**Mitigation:** The frontend always fetches the full execution state via `GET /api/v1/executions/{id}/` before opening the stream. The REST response reflects the current state in the database. The stream then applies future events as patches. The window of missed events is bounded by the REST fetch → stream open latency (typically < 200ms). Even if an event is missed, the next state transition (e.g., step succeeds after step started) will bring the UI up to date. For executions that complete very quickly (< 200ms), the REST poll will have already captured the terminal state.

### 12.5 Browser reconnect storm (medium risk)

**Description:** If the API server restarts or the stream endpoint crashes, all connected browsers attempt to reconnect simultaneously. With 100 connected users and a 3-second retry interval, this is 33 requests per second on restart — unlikely to overwhelm the API but worth documenting.

**Mitigations:**
- `retry: 3000` in the stream response sets a 3-second base retry delay.
- `@microsoft/fetch-event-source` does not add jitter by default. For Phase 10.9, consider adding jitter to the retry delay in the frontend hook to spread reconnect load.
- After 3 failures, the hook switches to polling (1500ms). Polling is less resource-intensive than rapid SSE reconnects.

### 12.6 Process-local event bus in multi-process deployment (high risk for Phase 10.10)

**Description:** The `execution_event_bus` singleton is process-local. If `uvicorn` is started with multiple worker processes (e.g., `--workers 4`), each process has its own event bus. A runner calling `update_step` via one process emits to that process's bus. A browser connected to a different process subscribes to a different bus. The browser never receives the event.

**Impact:** SSE silently fails in multi-process uvicorn deployments.

**Mitigations:**
- **Phase 10.8:** Run uvicorn with `--workers 1` (single process). This is documented and enforced in the Dockerfile `CMD`. Document the constraint explicitly.
- **Phase 10.10 (MANDATORY GATE):** Before live streaming is enabled in any production environment with multiple API tasks, the Phase 10.10 blueprint must explicitly choose one of: (a) fix API task count at 1 with a documented availability tradeoff, or (b) add an externalized event transport (Redis pub/sub, Postgres LISTEN/NOTIFY without PgBouncer transaction pooling, or AWS EventBridge). **Sticky sessions on the ALB are NOT a valid solution** — the runner and the browser subscriber are separate clients with no shared session to make sticky. Do not document sticky sessions as a mitigation.

**Detection:** Events stop arriving despite the runner successfully updating steps. Occurs only when `--workers > 1`.

### 12.7 `asyncio` event loop not available in sync test context (low risk)

**Description:** `execution_event_bus.emit()` calls `asyncio.get_running_loop()`. In synchronous Django tests (using `TestCase`), there is no running event loop. The `except RuntimeError: return` guard silently skips the emit.

**Impact:** Service layer tests that run synchronously cannot assert that events are emitted via the actual bus mechanism. The `test_services_emit.py` tests use mocking (`unittest.mock.patch`) to detect emit calls without requiring an event loop.

**Mitigation:** This is the correct design. Sync tests mock the emit call. Async tests (using `AsyncClient` in `test_streaming.py`) test the full end-to-end flow with a real event loop. No risk to production behavior.

### 12.8 Django `manage.py runserver` left in dev usage (low risk)

**Description:** A developer runs `python manage.py runserver` directly for local debugging. This works for most development but breaks SSE — the sync server cannot hold streaming connections open without blocking.

**Mitigation:** Update `apps/api/Dockerfile` and `docker-compose.yml` to use uvicorn. Developers who bypass Docker use `uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --reload` directly. Document in `CLAUDE.md` under "Common Commands" that the API server is now uvicorn.

---

## 13. What NOT to do

**Do not add WebSockets.** Execution updates are unidirectional. WebSockets require a bidirectional protocol, a WebSocket handshake, a WebSocket close handshake, and typically Django Channels with a channel layer. SSE accomplishes the same goal with standard HTTP. If the future requires bidirectional communication (e.g., a live console for interactive steps), that is a separate feature with a separate design.

**Do not add Redis, Kafka, RabbitMQ, or any external broker in Phase 10.8.** The in-process event bus is sufficient for a single-server deployment. The roadmap blueprint (INV-8) prohibits premature event infrastructure. When multi-process scaling is required (Phase 10.10), add Redis pub/sub as part of the production hardening strategy — not before.

**Do not add Django Channels.** Django Channels solves the multi-process channel layer problem, but it adds ASGI routing complexity, a channel layer dependency, and a different programming model for views. Native Django async views with `asyncio.Queue` are simpler, faster to implement, and sufficient for Phase 10.8.

**Do not let the runner push events directly to the browser.** The runner talks to Django's internal API. Django's service layer emits events. The runner has no direct connection to connected browsers. INV-2 is absolute.

**Do not stream audit events, approval state, policy evaluations, or integration events through the SSE channel.** The execution stream is scoped to execution and step status changes only. Mixing other event types increases coupling and creates a risk of information disclosure (an `operator` watching a stream should not receive raw audit event payloads that may contain system internals).

**Do not treat the stream as the source of truth.** The stream is a real-time notification channel. The database is the source of truth. If the frontend needs the current state of an execution, it calls `GET /api/v1/executions/{id}/`. The frontend never assumes that the stream has delivered all events since the execution started.

**Do not pass the access token as a URL query parameter.** Tokens in URLs appear in server access logs, browser history, the address bar, and the `Referer` header on navigation. The Phase 10.7 security model (token in memory, never in storage) must be preserved. Use `@microsoft/fetch-event-source` to send the `Authorization` header.

**Do not open streams for terminal-state executions.** The frontend must check execution status before opening a stream. If the status is already `succeeded`, `failed`, or `cancelled`, open the stream only if the server immediately sends `stream.closed` (which it does, per section 7.2). Better: check status from the initial REST fetch; if terminal, don't open the stream at all.

**Do not run uvicorn with `--workers > 1` in Phase 10.8.** Multiple workers mean multiple event buses. Events emitted by the service layer in one process will not reach subscribers in other processes. Phase 10.8 is single-worker. This constraint is explicitly documented and enforced via the Dockerfile `CMD`.

**Do not use `asyncio.sleep(0)` in the event generator as a heartbeat.** A busy loop with `asyncio.sleep(0)` burns CPU. Use `asyncio.wait_for(queue.get(), timeout=25.0)` — this yields control to the event loop during the wait and wakes only when an event arrives or the 25-second timeout fires.

---

## 14. Definition of done

Phase 10.8 is complete when all of the following are true:

- [ ] The API service runs under `uvicorn config.asgi:application`, not `manage.py runserver`. Confirmed via `make logs`.
- [ ] `uvicorn[standard]` is in `apps/api/requirements/base.txt`.
- [ ] `ExecutionEventBus` exists at `apps/api/apps/executions/event_bus.py` with `emit`, `subscribe`, `unsubscribe`, and `get_buffered_events_after` methods.
- [ ] `execution_event_bus.emit()` is called in `services.py` at all five state-transition points: `claim_next_execution`, `update_execution_step` (step change), `update_execution_step` (execution CLAIMED→RUNNING), `complete_execution`, `cancel_execution`.
- [ ] `GET /api/v1/executions/{id}/stream/` returns `200 text/event-stream` for authenticated org members.
- [ ] `GET /api/v1/executions/{id}/stream/` returns `401` for unauthenticated requests.
- [ ] `GET /api/v1/executions/{id}/stream/` returns `403` for users not in the execution's organization.
- [ ] The SSE stream includes `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers.
- [ ] `step.status_changed` events arrive within 200ms of `update_execution_step` being called.
- [ ] `stream.closed` event is emitted within 1 second of the execution reaching a terminal state.
- [ ] `Last-Event-ID` reconnection replays buffered events from the in-memory ring buffer.
- [ ] A 25-second idle connection emits one `execution.heartbeat` event.
- [ ] Already-terminal executions return two events (`execution.status_changed` + `stream.closed`) and close.
- [ ] `@microsoft/fetch-event-source` is in `apps/web/package.json`.
- [ ] `useExecutionStream` hook exists, opens SSE connection for active executions, applies `applyStreamEvent` to the React Query cache on each event, and closes cleanly on `stream.closed`.
- [ ] After 3 consecutive SSE connection failures, `useExecutionDetail` falls back to 1500ms polling.
- [ ] The `ExecutionDetailPage` shows "Receiving live updates." when the stream is active.
- [ ] The `ExecutionDetailPage` shows "Polling for updates (streaming unavailable)." when the fallback is active.
- [ ] The access token does **not** appear in any SSE request URL (confirmed via DevTools Network tab).
- [ ] All existing Django tests pass after the uvicorn migration.
- [ ] Event bus unit tests pass.
- [ ] Service emit tests pass.
- [ ] SSE endpoint tests pass (auth, permission, terminal-state, live event, reconnection, heartbeat).
- [ ] Frontend hook tests pass (`useExecutionStream`, `useExecutionDetail`, `applyStreamEvent`).
- [ ] Manual live execution gate (section 11.6, all 12 steps) has been completed and all steps pass.
- [ ] No access token in browser localStorage, sessionStorage, or URL query strings (confirmed via DevTools).
- [ ] `uvicorn` is running with `--workers 1`. The single-worker constraint is documented in a code comment in the Dockerfile `CMD`.

---

## Summary

**File created:** `docs/blueprints/phase-10-08-live-event-streaming-blueprint.md`

**Major sections included:**
1. Purpose and sequencing rationale — why SSE over WebSockets, why auth must precede streaming, why streaming precedes hardening
2. Current-state inspection checklist — 16 files/commands to verify before writing code
3. Architecture invariants — 8 platform invariants mapped to streaming-specific consequences, plus streaming-specific constraints
4. Implementation scope — 9 repo areas with specific files touched and changes described
5. Streaming contract — SSE endpoint path, 4 event types, per-event payload contracts with exact field names, wire format, retry configuration, `Last-Event-ID` replay protocol
6. Data model and event source approach — `ExecutionEventBus` design (in-memory, asyncio.Queue, ring buffer), service-layer emit wiring, rationale for no database model
7. API contracts — stream endpoint auth requirements, error response table, already-terminal behavior, URL registration, runner unchanged
8. Frontend contracts — `@microsoft/fetch-event-source` rationale, `useExecutionStream` hook design, `useExecutionDetail` augmentation, `applyStreamEvent` pure function, connection open protocol, fallback and reconnection behavior, page UI changes
9. Runner impact — no changes; runner is unaware of SSE
10. 6 ordered milestones — each with purpose, files touched, steps, verification commands, rollback notes, and human approval gates
11. Testing strategy — 6 categories: SSE endpoint (12+ cases), event bus (8 cases), service emit (6 cases), frontend hooks, permission tests, manual live gate (12-step checklist)
12. Failure modes — 8 risks with description, impact, mitigations, and detection strategy
13. What NOT to do — 10 explicit prohibitions with rationale
14. Definition of done — 26 checkboxes

**Key assumptions:**
- Phase 10.7 (authentication and authorization) is complete and all 21 checkboxes in its definition of done are satisfied before Phase 10.8 begins.
- The API currently runs `manage.py runserver`; Phase 10.8's first act is switching to `uvicorn`.
- `uvicorn` is run with `--workers 1` throughout Phase 10.8. Multi-process scaling is deferred to Phase 10.9/10.10.
- The event bus is process-local (in-memory); horizontal API scaling requires Redis pub/sub, which is a Phase 10.9/10.10 concern.
- JWT access tokens are stored in module-level memory (not localStorage), as established in Phase 10.7. `@microsoft/fetch-event-source` is used so the `Authorization: Bearer` header can be sent with the SSE connection.
- `@microsoft/fetch-event-source` is available as an npm package and has no conflicting peer dependency with the existing web stack.
- The runner executes steps sequentially (one at a time), so concurrent step events from a single execution are not a concern — no event ordering race condition exists for Phase 10.8.
- Approval gates (if Phase 10.1 is complete) that add a `waiting_for_approval` step status would produce a `step.status_changed` event with `status: "waiting_for_approval"` — this is handled by the existing `step.status_changed` event type without modification to the streaming contract.
