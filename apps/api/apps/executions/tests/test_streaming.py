import asyncio
import json
import logging
import uuid

import pytest
from django.test import AsyncClient, Client
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.executions import services as execution_services
from apps.executions.event_bus import StreamEvent, execution_event_bus
from apps.executions.models import Execution, ExecutionStep
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.runbooks.models import Runbook
from apps.users.models import User
from apps.workflows.models import Workflow

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def clear_event_bus():
    execution_event_bus._subscribers.clear()
    execution_event_bus._buffers.clear()
    yield
    execution_event_bus._subscribers.clear()
    execution_event_bus._buffers.clear()


@pytest.fixture
def streaming_setup(db):
    org = Organization.objects.create(name="Stream Org", slug="stream-org")
    other_org = Organization.objects.create(name="Other Org", slug="other-stream-org")
    user = User.objects.create_user(
        email="streamer@example.com", password="s3cr3tpass!"
    )
    outsider = User.objects.create_user(
        email="outsider-streamer@example.com", password="s3cr3tpass!"
    )
    Membership.objects.create(organization=org, user=user, role=MembershipRole.VIEWER)
    Membership.objects.create(
        organization=other_org, user=outsider, role=MembershipRole.VIEWER
    )
    runbook = Runbook.objects.create(
        organization=org,
        title="Streaming Runbook",
        slug="streaming-runbook",
        raw_content="Run one step",
    )
    workflow = Workflow.objects.create(
        organization=org,
        runbook=runbook,
        name="Streaming Workflow",
        version=1,
        status=Workflow.Status.PUBLISHED,
        definition={"steps": [{"id": "step-1", "name": "Step 1"}]},
    )
    execution = Execution.objects.create(
        organization=org,
        workflow=workflow,
        workflow_version=workflow.version,
        workflow_snapshot=workflow.definition,
        status=Execution.Status.QUEUED,
    )
    step = ExecutionStep.objects.create(
        execution=execution,
        position=1,
        step_key="step-1",
        name="Step 1",
        step_type="shell",
        risk_level="low",
        command="echo ok",
    )
    return {
        "org": org,
        "other_org": other_org,
        "user": user,
        "outsider": outsider,
        "execution": execution,
        "step": step,
    }


def _token(user):
    return str(RefreshToken.for_user(user).access_token)


def _headers(user, org, **extra):
    headers = {
        "authorization": f"Bearer {_token(user)}",
        "x-organization-id": str(org.id),
    }
    headers.update(extra)
    return headers


def _stream_url(execution):
    return f"/api/v1/executions/{execution.id}/stream/"


async def _next_chunk(aiter):
    chunk = await anext(aiter)
    if isinstance(chunk, bytes):
        return chunk.decode()
    return chunk


def _event_names(chunk):
    return [
        line.removeprefix("event: ")
        for line in chunk.splitlines()
        if line.startswith("event: ")
    ]


def _event_data(chunk):
    data_line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


@pytest.mark.asyncio
async def test_authenticated_org_member_gets_stream_response(streaming_setup):
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_unauthenticated_gets_401(streaming_setup):
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers={"x-organization-id": str(streaming_setup["org"].id)},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_org_user_gets_403(streaming_setup):
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers=_headers(streaming_setup["outsider"], streaming_setup["org"]),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_stream_headers_are_correct(streaming_setup):
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )

    assert response["Content-Type"].startswith("text/event-stream")
    assert response["Cache-Control"] == "no-cache"
    assert response["X-Accel-Buffering"] == "no"
    assert response["Connection"] == "keep-alive"


@pytest.mark.asyncio
async def test_live_step_status_event_is_streamed(streaming_setup):
    client = AsyncClient()
    execution = streaming_setup["execution"]
    step = streaming_setup["step"]
    response = await client.get(
        _stream_url(execution),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry

    event = StreamEvent(
        event_type="step.status_changed",
        data={
            "execution_id": str(execution.id),
            "step_id": str(step.id),
            "position": step.position,
            "status": ExecutionStep.Status.RUNNING,
            "timestamp": timezone.now().isoformat(),
            "started_at": timezone.now().isoformat(),
            "finished_at": None,
            "exit_code": None,
            "error_message": "",
        },
    )
    await execution_event_bus.emit_async(str(execution.id), event)

    chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)
    assert _event_names(chunk) == ["step.status_changed"]
    assert _event_data(chunk)["step_id"] == str(step.id)
    await aiter.aclose()


@pytest.mark.asyncio
async def test_stream_lifecycle_logs_accept_and_sent_event(streaming_setup, caplog):
    caplog.set_level(logging.INFO, logger="apps.executions.stream_views")
    client = AsyncClient()
    execution = streaming_setup["execution"]
    step = streaming_setup["step"]
    response = await client.get(
        _stream_url(execution),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry/subscription setup

    event = StreamEvent(
        event_type="step.status_changed",
        data={
            "execution_id": str(execution.id),
            "step_id": str(step.id),
            "position": step.position,
            "status": ExecutionStep.Status.RUNNING,
            "timestamp": timezone.now().isoformat(),
            "started_at": timezone.now().isoformat(),
            "finished_at": None,
            "exit_code": None,
            "error_message": "",
        },
    )
    await execution_event_bus.emit_async(str(execution.id), event)

    chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)
    assert _event_names(chunk) == ["step.status_changed"]
    assert "execution_stream.accepted" in caplog.messages
    assert "execution_stream.subscribed" in caplog.messages
    assert "execution_stream.event_sent" in caplog.messages
    await aiter.aclose()


@pytest.mark.asyncio
async def test_terminal_execution_closes_stream(streaming_setup):
    client = AsyncClient()
    execution = streaming_setup["execution"]
    response = await client.get(
        _stream_url(execution),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry

    event = StreamEvent(
        event_type="execution.status_changed",
        data={
            "execution_id": str(execution.id),
            "status": Execution.Status.SUCCEEDED,
            "timestamp": timezone.now().isoformat(),
            "started_at": timezone.now().isoformat(),
            "finished_at": timezone.now().isoformat(),
        },
    )
    await execution_event_bus.emit_async(str(execution.id), event)

    status_chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)
    closed_chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)
    assert _event_names(status_chunk) == ["execution.status_changed"]
    assert _event_names(closed_chunk) == ["stream.closed"]
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(_next_chunk(aiter), timeout=1)


@pytest.mark.asyncio
async def test_already_terminal_execution_returns_final_events_then_closes(
    streaming_setup,
):
    execution = streaming_setup["execution"]
    execution.status = Execution.Status.FAILED
    execution.started_at = timezone.now()
    execution.finished_at = timezone.now()
    await Execution.objects.filter(pk=execution.pk).aupdate(
        status=execution.status,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
    )

    client = AsyncClient()
    response = await client.get(
        _stream_url(execution),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry
    status_chunk = await _next_chunk(aiter)
    closed_chunk = await _next_chunk(aiter)

    assert _event_names(status_chunk) == ["execution.status_changed"]
    assert _event_data(status_chunk)["status"] == Execution.Status.FAILED
    assert _event_names(closed_chunk) == ["stream.closed"]
    with pytest.raises(StopAsyncIteration):
        await _next_chunk(aiter)


@pytest.mark.asyncio
async def test_last_event_id_replay_works(streaming_setup):
    execution = streaming_setup["execution"]
    org = streaming_setup["org"]
    queue = await execution_event_bus.subscribe(str(execution.id), str(org.id))
    first = StreamEvent(
        event_type="step.status_changed",
        data={"execution_id": str(execution.id), "status": "running"},
    )
    second = StreamEvent(
        event_type="step.status_changed",
        data={"execution_id": str(execution.id), "status": "succeeded"},
    )
    await execution_event_bus.emit_async(str(execution.id), first)
    await execution_event_bus.emit_async(str(execution.id), second)
    await execution_event_bus.unsubscribe(str(execution.id), queue)

    client = AsyncClient()
    headers = _headers(streaming_setup["user"], org)
    headers["Last-Event-ID"] = first.id
    response = await client.get(
        _stream_url(execution),
        headers=headers,
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry
    replay_chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)

    assert f"id: {second.id}" in replay_chunk
    assert _event_data(replay_chunk)["status"] == "succeeded"
    await aiter.aclose()


@pytest.mark.asyncio
async def test_idle_heartbeat_event_is_streamed(streaming_setup, monkeypatch):
    monkeypatch.setattr("apps.executions.stream_views.HEARTBEAT_INTERVAL_SECONDS", 0.01)
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry

    chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)
    assert _event_names(chunk) == ["execution.heartbeat"]
    assert "id: " not in chunk
    await aiter.aclose()


@pytest.mark.asyncio
async def test_idle_stream_reconciles_missed_terminal_event(
    streaming_setup, monkeypatch
):
    monkeypatch.setattr("apps.executions.stream_views.HEARTBEAT_INTERVAL_SECONDS", 0.01)
    client = AsyncClient()
    execution = streaming_setup["execution"]
    response = await client.get(
        _stream_url(execution),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # retry

    finished_at = timezone.now()
    await Execution.objects.filter(pk=execution.pk).aupdate(
        status=Execution.Status.SUCCEEDED,
        started_at=finished_at,
        finished_at=finished_at,
    )

    status_chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)
    closed_chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=1)

    assert _event_names(status_chunk) == ["execution.status_changed"]
    assert _event_data(status_chunk)["status"] == Execution.Status.SUCCEEDED
    assert _event_names(closed_chunk) == ["stream.closed"]
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(_next_chunk(aiter), timeout=1)


# ---------------------------------------------------------------------------
# Auth contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_execution_returns_404(streaming_setup):
    """Execution that exists but belongs to a different org must return 404, not 403."""
    client = AsyncClient()
    # Request the execution using the other_org's id as the header org.
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers={
            "authorization": f"Bearer {_token(streaming_setup['user'])}",
            "x-organization-id": str(streaming_setup["other_org"].id),
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_runner_bearer_token_cannot_open_user_stream(streaming_setup):
    """Runner bearer tokens must be rejected from the SSE endpoint."""
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers={
            "authorization": "Bearer test-runner-token",
            "x-organization-id": str(streaming_setup["org"].id),
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_org_header_returns_400(streaming_setup):
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers={"authorization": f"Bearer {_token(streaming_setup['user'])}"},
    )

    assert response.status_code == 400
    body = json.loads(response.content)
    assert "X-Organization-Id" in body["detail"]


@pytest.mark.asyncio
async def test_malformed_org_header_returns_400(streaming_setup):
    """A header value that is not a valid UUID must be treated as missing."""
    client = AsyncClient()
    response = await client.get(
        _stream_url(streaming_setup["execution"]),
        headers={
            "authorization": f"Bearer {_token(streaming_setup['user'])}",
            "x-organization-id": "not-a-uuid",
        },
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# E2E service-to-stream integration test
# ---------------------------------------------------------------------------

_RUNNER_TOKEN = "test-runner-token"
_CLAIM_URL = "/api/v1/internal/executions/claim-next/"


def _runner_client():
    return Client(HTTP_AUTHORIZATION=f"Bearer {_RUNNER_TOKEN}")


def _step_update_url(execution_id, step_id):
    return f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/update/"


@pytest.mark.asyncio
async def test_step_update_via_service_delivers_stream_event(streaming_setup):
    """
    Real service path: claim execution → open SSE stream → update step via
    services.update_execution_step() → assert event delivered through emit().

    This test exercises the full sync service → on_commit → emit() → ASGI
    loop → subscriber queue path.
    """
    execution = streaming_setup["execution"]
    step = streaming_setup["step"]
    runner_id = "e2e-runner-1"
    claim_token = str(uuid.uuid4())

    # Manually claim so we can call update_execution_step without HTTP.
    now = timezone.now()
    await Execution.objects.filter(pk=execution.pk).aupdate(
        status=Execution.Status.CLAIMED,
        claimed_by_runner_id=runner_id,
        claim_token=claim_token,
        claimed_at=now,
        last_heartbeat_at=now,
    )
    await execution.arefresh_from_db()

    # Open the SSE stream.
    client = AsyncClient()
    response = await client.get(
        _stream_url(execution),
        headers=_headers(streaming_setup["user"], streaming_setup["org"]),
    )
    aiter = response.streaming_content.__aiter__()
    await _next_chunk(aiter)  # consume retry directive

    # Give the ASGI event loop a tick to register the subscriber.
    await asyncio.sleep(0)

    # Call the sync service from async context via sync_to_async.
    from asgiref.sync import sync_to_async

    def _do_update():
        execution_services.update_execution_step(
            execution=execution,
            step_id=str(step.id),
            runner_id=runner_id,
            claim_token=claim_token,
            new_status=ExecutionStep.Status.RUNNING,
        )

    await sync_to_async(_do_update)()

    # Allow the ASGI loop to process the call_soon_threadsafe callback.
    await asyncio.sleep(0.05)

    chunk = await asyncio.wait_for(_next_chunk(aiter), timeout=2)
    assert _event_names(chunk) == ["step.status_changed"]
    data = _event_data(chunk)
    assert data["step_id"] == str(step.id)
    assert data["status"] == ExecutionStep.Status.RUNNING
    await aiter.aclose()
