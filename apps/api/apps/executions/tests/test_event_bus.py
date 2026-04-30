"""
Unit tests for ExecutionEventBus (Milestone 2).

Async tests use pytest-asyncio (already in dev deps via pytest-django's
async support). Each async test gets its own fresh ExecutionEventBus so
tests are fully isolated.
"""

import asyncio
import logging
import uuid

import pytest

from apps.executions.event_bus import ExecutionEventBus, StreamEvent


def _bus() -> ExecutionEventBus:
    """Return a fresh bus for each test."""
    return ExecutionEventBus()


def _exec_id() -> str:
    return str(uuid.uuid4())


def _org_id() -> str:
    return str(uuid.uuid4())


def _event(event_type: str = "execution.status_changed", **data_kwargs) -> StreamEvent:
    return StreamEvent(
        event_type=event_type,
        data={"execution_id": _exec_id(), **data_kwargs},
    )


# ---------------------------------------------------------------------------
# Synchronous / non-async tests
# ---------------------------------------------------------------------------


def test_emit_no_subscribers_is_safe():
    """emit() with no loop and no subscribers must not raise."""
    bus = _bus()
    exec_id = _exec_id()
    # No ASGI loop set — emit should no-op.
    bus.emit(exec_id, _event())


def test_emit_without_loop_logs_dropped_event(monkeypatch, caplog):
    bus = _bus()
    exec_id = _exec_id()
    ev = _event()
    monkeypatch.setattr("apps.executions.event_bus._asgi_event_loop", None)
    caplog.set_level(logging.WARNING, logger="apps.executions.event_bus")

    bus.emit(exec_id, ev)

    assert "execution_stream.event_dropped_no_loop" in caplog.messages


def test_buffer_starts_empty():
    bus = _bus()
    exec_id = _exec_id()
    assert bus.get_buffered_events_after(exec_id, None) == []


def test_get_buffered_events_after_none_returns_empty():
    """last_event_id=None always returns empty list."""
    bus = _bus()
    exec_id = _exec_id()
    # Manually prime the buffer by calling _async_emit synchronously via
    # asyncio.run to keep this test synchronous.
    ev = _event()
    asyncio.run(bus._async_emit(exec_id, ev))
    assert bus.get_buffered_events_after(exec_id, None) == []


def test_get_buffered_events_after_unknown_id_returns_empty():
    bus = _bus()
    exec_id = _exec_id()
    ev = _event()
    asyncio.run(bus._async_emit(exec_id, ev))
    assert bus.get_buffered_events_after(exec_id, str(uuid.uuid4())) == []


def test_buffer_stores_emitted_events():
    bus = _bus()
    exec_id = _exec_id()
    ev1 = _event()
    ev2 = _event()

    async def _run():
        await bus.subscribe(exec_id, _org_id())
        await bus.emit_async(exec_id, ev1)
        await bus.emit_async(exec_id, ev2)

    asyncio.run(_run())
    # get_buffered_events_after ev1 should return [ev2]
    result = bus.get_buffered_events_after(exec_id, ev1.id)
    assert result == [ev2]


def test_buffer_maxlen_not_exceeded():
    """Emitting 200 events keeps the buffer at ≤ 128 entries."""
    bus = _bus()
    exec_id = _exec_id()

    async def _emit_many():
        await bus.subscribe(exec_id, _org_id())
        for _ in range(200):
            await bus._async_emit(exec_id, _event())

    asyncio.run(_emit_many())
    buffer = bus._buffers[exec_id]
    assert len(buffer) <= 128


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_receives_emitted_event():
    bus = _bus()
    exec_id = _exec_id()
    org_id = _org_id()

    queue = await bus.subscribe(exec_id, org_id)
    ev = _event()
    await bus.emit_async(exec_id, ev)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received is ev


@pytest.mark.asyncio
async def test_emit_async_logs_emitted_event(caplog):
    bus = _bus()
    exec_id = _exec_id()
    queue = await bus.subscribe(exec_id, _org_id())
    ev = _event()
    caplog.set_level(logging.INFO, logger="apps.executions.event_bus")

    await bus.emit_async(exec_id, ev)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received is ev
    assert "execution_stream.event_emitted" in caplog.messages


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive_event():
    bus = _bus()
    exec_id = _exec_id()
    org_id = _org_id()

    q1 = await bus.subscribe(exec_id, org_id)
    q2 = await bus.subscribe(exec_id, org_id)
    ev = _event()
    await bus.emit_async(exec_id, ev)

    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert r1 is ev
    assert r2 is ev


@pytest.mark.asyncio
async def test_subscriber_for_different_execution_does_not_receive_event():
    bus = _bus()
    exec_a = _exec_id()
    exec_b = _exec_id()
    org_id = _org_id()

    queue_b = await bus.subscribe(exec_b, org_id)
    await bus.emit_async(exec_a, _event())

    # queue_b should be empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue_b.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_organization_scoping_respected():
    """Two subscribers with different org IDs both receive the event (scoping
    is enforced by the view layer, not the bus itself — bus fans out to all
    queues for an execution_id)."""
    bus = _bus()
    exec_id = _exec_id()

    q_org1 = await bus.subscribe(exec_id, _org_id())
    q_org2 = await bus.subscribe(exec_id, _org_id())
    ev = _event()
    await bus.emit_async(exec_id, ev)

    r1 = await asyncio.wait_for(q_org1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q_org2.get(), timeout=1.0)
    assert r1 is ev
    assert r2 is ev


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving_events():
    bus = _bus()
    exec_id = _exec_id()
    org_id = _org_id()

    queue = await bus.subscribe(exec_id, org_id)
    await bus.unsubscribe(exec_id, queue)
    await bus.emit_async(exec_id, _event())

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_unsubscribe_cleans_up_empty_subscriber_set():
    bus = _bus()
    exec_id = _exec_id()

    queue = await bus.subscribe(exec_id, _org_id())
    assert exec_id in bus._subscribers
    await bus.unsubscribe(exec_id, queue)
    assert exec_id not in bus._subscribers


@pytest.mark.asyncio
async def test_bounded_queue_does_not_grow_unbounded():
    """Verify that the per-execution buffer is bounded at _MAX_BUFFER_SIZE."""
    bus = _bus()
    exec_id = _exec_id()
    # Subscribe so the buffer entry is created, then emit > 128 events.
    queue = await bus.subscribe(exec_id, _org_id())
    for _ in range(200):
        await bus.emit_async(exec_id, _event())
    buffer = bus._buffers[exec_id]
    assert len(buffer) <= 128
    # Drain the queue to avoid lingering tasks.
    while not queue.empty():
        queue.get_nowait()


@pytest.mark.asyncio
async def test_last_event_id_replay_returns_buffered_events():
    bus = _bus()
    exec_id = _exec_id()

    # Subscribe first so the buffer entry is created.
    await bus.subscribe(exec_id, _org_id())

    ev1 = _event()
    ev2 = _event()
    ev3 = _event()
    await bus.emit_async(exec_id, ev1)
    await bus.emit_async(exec_id, ev2)
    await bus.emit_async(exec_id, ev3)

    replayed = bus.get_buffered_events_after(exec_id, ev1.id)
    assert replayed == [ev2, ev3]


@pytest.mark.asyncio
async def test_last_event_id_replay_after_last_event_returns_empty():
    bus = _bus()
    exec_id = _exec_id()

    await bus.subscribe(exec_id, _org_id())
    ev1 = _event()
    await bus.emit_async(exec_id, ev1)

    replayed = bus.get_buffered_events_after(exec_id, ev1.id)
    assert replayed == []


@pytest.mark.asyncio
async def test_terminal_event_represented_cleanly():
    """stream.closed event can be emitted and received via the bus."""
    bus = _bus()
    exec_id = _exec_id()
    org_id = _org_id()

    queue = await bus.subscribe(exec_id, org_id)

    terminal_event = StreamEvent(
        event_type="stream.closed",
        data={
            "execution_id": exec_id,
            "final_status": "succeeded",
            "reason": "terminal_state",
        },
    )
    await bus.emit_async(exec_id, terminal_event)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.event_type == "stream.closed"
    assert received.data["final_status"] == "succeeded"
    assert received.data["reason"] == "terminal_state"


@pytest.mark.asyncio
async def test_emit_no_subscribers_noop():
    """emit_async with no subscribers does not raise and buffer records the event."""
    bus = _bus()
    exec_id = _exec_id()
    ev = _event()
    # No subscriber — should be a no-op delivery-wise but buffer is not set up.
    await bus.emit_async(exec_id, ev)
    # Buffer should NOT exist because subscribe() was never called.
    assert exec_id not in bus._buffers
