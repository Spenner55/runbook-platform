"""Contract tests for runner.client — all HTTP is handled through httpx.MockTransport."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from runner.client import ApiClient
from runner.schemas import (
    ClaimNextResponse,
    CompleteExecutionResponse,
    HeartbeatResponse,
    StepUpdateResponse,
)

# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------


def _make_transport(status_code: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    return httpx.MockTransport(handler)


def make_client(transport: httpx.MockTransport) -> ApiClient:
    http = httpx.Client(transport=transport)
    return ApiClient(
        base_url="http://api:8000",
        runner_id="test-runner",
        runner_version="0.1.0",
        http_client=http,
    )


def _step_dict() -> dict:
    return {
        "id": str(uuid4()),
        "position": 1,
        "step_key": "step-1",
        "name": "Step 1",
        "step_type": "shell",
        "risk_level": "low",
        "command": "",
        "requires_approval": False,
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# claim_next
# ---------------------------------------------------------------------------


def test_claim_next_no_work_returns_response():
    body = {"execution": None, "poll_after_seconds": 5}
    client = make_client(_make_transport(200, body))
    resp = client.claim_next()
    assert isinstance(resp, ClaimNextResponse)
    assert resp.execution is None
    assert resp.poll_after_seconds == 5


def test_claim_next_with_work_parses_execution():
    execution_id = str(uuid4())
    token = str(uuid4())
    body = {
        "execution": {
            "id": execution_id,
            "status": "claimed",
            "workflow_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "workflow_version": 1,
            "workflow_snapshot": {},
            "claimed_by_runner_id": "test-runner",
            "claimed_at": "2026-01-01T00:00:00Z",
            "last_heartbeat_at": "2026-01-01T00:00:00Z",
            "steps": [_step_dict()],
        },
        "claim_token": token,
        "poll_after_seconds": 5,
    }
    client = make_client(_make_transport(200, body))
    resp = client.claim_next()
    assert resp.execution is not None
    assert str(resp.execution.id) == execution_id
    assert str(resp.claim_token) == token


def test_claim_next_sends_correct_url_and_method():
    captured = {}
    body = {"execution": None, "poll_after_seconds": 5}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        payload = json.loads(request.content)
        captured["runner_id"] = payload.get("runner_id")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    client.claim_next()

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/internal/executions/claim-next/"
    assert captured["runner_id"] == "test-runner"


def test_claim_next_raises_on_non_2xx():
    client = make_client(_make_transport(500, {"error": "boom"}))
    with pytest.raises(httpx.HTTPStatusError):
        client.claim_next()


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_sends_correct_fields():
    captured = {}
    body = {
        "execution_id": str(uuid4()),
        "status": "claimed",
        "last_heartbeat_at": "2026-01-01T00:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    execution_id = uuid4()
    claim_token = uuid4()
    client = make_client(httpx.MockTransport(handler))
    resp = client.heartbeat(execution_id, claim_token, observed_status="running")

    assert captured["runner_id"] == "test-runner"
    assert captured["claim_token"] == str(claim_token)
    assert captured["observed_status"] == "running"
    assert isinstance(resp, HeartbeatResponse)
    assert resp.status == "claimed"


def test_heartbeat_raises_on_409():
    client = make_client(
        _make_transport(409, {"errors": [{"code": "claim_token_mismatch"}]})
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.heartbeat(uuid4(), uuid4())


# ---------------------------------------------------------------------------
# update_step
# ---------------------------------------------------------------------------


def test_update_step_running_sends_correct_payload():
    captured = {}
    execution_id = uuid4()
    step_id = uuid4()
    body = {
        "execution_id": str(execution_id),
        "step": {
            "id": str(step_id),
            "status": "running",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": None,
            "exit_code": None,
            "error_message": "",
        },
        "execution_status": "running",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    claim_token = uuid4()
    client = make_client(httpx.MockTransport(handler))
    resp = client.update_step(execution_id, step_id, claim_token, status="running")

    assert captured["status"] == "running"
    assert captured["claim_token"] == str(claim_token)
    assert isinstance(resp, StepUpdateResponse)
    assert resp.step.status == "running"
    assert resp.execution_status == "running"


def test_update_step_succeeded_includes_exit_code():
    captured = {}
    execution_id = uuid4()
    step_id = uuid4()
    body = {
        "execution_id": str(execution_id),
        "step": {
            "id": str(step_id),
            "status": "succeeded",
            "started_at": None,
            "finished_at": None,
            "exit_code": 0,
            "error_message": "",
        },
        "execution_status": "running",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    client.update_step(execution_id, step_id, uuid4(), status="succeeded", exit_code=0)

    assert captured["exit_code"] == 0
    assert captured["status"] == "succeeded"


# ---------------------------------------------------------------------------
# complete_execution
# ---------------------------------------------------------------------------


def test_complete_execution_sends_final_status_not_outcome():
    captured = {}
    execution_id = uuid4()
    body = {
        "id": str(execution_id),
        "status": "succeeded",
        "finished_at": "2026-01-01T00:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    claim_token = uuid4()
    client = make_client(httpx.MockTransport(handler))
    resp = client.complete_execution(
        execution_id, claim_token, final_status="succeeded"
    )

    assert "final_status" in captured
    assert captured["final_status"] == "succeeded"
    assert "outcome" not in captured
    assert isinstance(resp, CompleteExecutionResponse)
    assert resp.status == "succeeded"


def test_complete_execution_failed_path():
    captured = {}
    execution_id = uuid4()
    body = {
        "id": str(execution_id),
        "status": "failed",
        "finished_at": "2026-01-01T00:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    resp = client.complete_execution(
        execution_id, uuid4(), final_status="failed", error_message="oops"
    )

    assert captured["final_status"] == "failed"
    assert captured["error_message"] == "oops"
    assert resp.status == "failed"


def test_complete_execution_raises_on_4xx():
    client = make_client(
        _make_transport(409, {"errors": [{"code": "invalid_state_transition"}]})
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.complete_execution(uuid4(), uuid4(), final_status="succeeded")
