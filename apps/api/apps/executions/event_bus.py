import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_BUFFER_SIZE = 128  # ring buffer per execution

# The ASGI event loop, captured once at startup. Sync Django service code
# (running in uvicorn threadpool workers) uses this reference via
# call_soon_threadsafe() to schedule async emit coroutines.
# None until the first ASGI request arrives or set explicitly in tests.
_asgi_event_loop: asyncio.AbstractEventLoop | None = None


def set_asgi_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _asgi_event_loop
    _asgi_event_loop = loop


def _get_asgi_event_loop() -> asyncio.AbstractEventLoop | None:
    return _asgi_event_loop


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

    Process-local only — does not work across multiple uvicorn workers.
    Run with --workers 1 until an external broker is added (Phase 10.10).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._buffers: dict[str, deque[StreamEvent]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self, execution_id: str, organization_id: str | None = None
    ) -> asyncio.Queue:
        """Return a new queue that will receive events for execution_id."""
        async with self._lock:
            if execution_id not in self._subscribers:
                self._subscribers[execution_id] = set()
            if execution_id not in self._buffers:
                self._buffers[execution_id] = deque(maxlen=_MAX_BUFFER_SIZE)
            queue: asyncio.Queue = asyncio.Queue()
            # Attach org scope so _async_emit can filter if needed.
            queue._org_id = organization_id  # type: ignore[attr-defined]
            self._subscribers[execution_id].add(queue)
            return queue

    async def unsubscribe(self, execution_id: str, queue: asyncio.Queue) -> None:
        """Remove queue from the subscriber set; clean up empty entries."""
        async with self._lock:
            subs = self._subscribers.get(execution_id, set())
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(execution_id, None)
                # Keep the buffer — late subscribers can still replay it.

    def emit(self, execution_id: str, event: StreamEvent) -> None:
        """
        Called from sync Django service code. Schedules _async_emit on the
        captured ASGI event loop via call_soon_threadsafe.

        Silently no-ops when no ASGI loop is available (management commands,
        sync tests, startup). Sync tests should mock this method directly.
        """
        loop = _get_asgi_event_loop()
        if loop is None or loop.is_closed():
            logger.warning(
                "execution_stream.event_dropped_no_loop",
                extra={
                    "execution_id": execution_id,
                    "event_type": event.event_type,
                    "event_id": event.id,
                },
            )
            return
        subscriber_count = len(self._subscribers.get(execution_id, set()))
        has_buffer = execution_id in self._buffers
        logger.info(
            "execution_stream.event_scheduled",
            extra={
                "execution_id": execution_id,
                "event_type": event.event_type,
                "event_id": event.id,
                "subscriber_count": subscriber_count,
                "has_buffer": has_buffer,
            },
        )
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                self._async_emit(execution_id, event), loop=loop
            )
        )

    async def emit_async(self, execution_id: str, event: StreamEvent) -> None:
        """Emit from async context (async views, async tests)."""
        await self._async_emit(execution_id, event)

    async def _async_emit(self, execution_id: str, event: StreamEvent) -> None:
        async with self._lock:
            buffer = self._buffers.get(execution_id)
            if buffer is not None:
                buffer.append(event)
            subscribers = list(self._subscribers.get(execution_id, set()))
            logger.info(
                "execution_stream.event_emitted",
                extra={
                    "execution_id": execution_id,
                    "event_type": event.event_type,
                    "event_id": event.id,
                    "subscriber_count": len(subscribers),
                    "buffered": buffer is not None,
                },
            )
            for queue in subscribers:
                await queue.put(event)

    def get_buffered_events_after(
        self, execution_id: str, last_event_id: str | None
    ) -> list[StreamEvent]:
        """
        Return buffered events that came after last_event_id.
        Returns [] if last_event_id is None or not found in the buffer.
        """
        buffer = self._buffers.get(execution_id, deque())
        if last_event_id is None:
            return []
        events = list(buffer)
        for i, ev in enumerate(events):
            if ev.id == last_event_id:
                replay_events = events[i + 1 :]
                logger.info(
                    "execution_stream.buffer_replay",
                    extra={
                        "execution_id": execution_id,
                        "last_event_id": last_event_id,
                        "replay_count": len(replay_events),
                    },
                )
                return replay_events
        logger.info(
            "execution_stream.buffer_replay_miss",
            extra={
                "execution_id": execution_id,
                "last_event_id": last_event_id,
                "buffer_size": len(events),
            },
        )
        return []  # last_event_id not in buffer; client must re-fetch


# Module-level singleton — shared across all requests on a single process.
execution_event_bus = ExecutionEventBus()
