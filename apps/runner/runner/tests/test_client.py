"""Contract tests for runner.client — all HTTP is handled through httpx.MockTransport."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from runner.client import (
    ARTIFACT_UPLOAD_TIMEOUT,
    RETRY_DELAYS_SECONDS,
    RUNNER_API_TIMEOUT,
    ApiClient,
)
from runner.schemas import (
    ApprovalStatusResponse,
    ClaimNextResponse,
    CompleteExecutionResponse,
    HeartbeatResponse,
    StepStartResponse,
    StepUpdateRequest,
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


def make_client(transport: httpx.MockTransport, **kwargs) -> ApiClient:
    http = httpx.Client(transport=transport)
    return ApiClient(
        base_url="http://api:8000",
        runner_id="test-runner",
        runner_token="test-runner-token",
        runner_version="0.1.0",
        http_client=http,
        **kwargs,
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


class _RecordingHttpClient:
    def __init__(self) -> None:
        self.timeouts = []

    def post(self, url: str, **kwargs) -> httpx.Response:
        self.timeouts.append(kwargs["timeout"])
        path = httpx.URL(url).path
        execution_id = str(uuid4())
        step_id = str(uuid4())
        if path.endswith("/claim-next/"):
            body = {"execution": None, "poll_after_seconds": 5}
            status_code = 200
        elif path.endswith("/heartbeat/"):
            body = {
                "execution_id": execution_id,
                "status": "claimed",
                "last_heartbeat_at": "2026-01-01T00:00:00Z",
            }
            status_code = 200
        elif path.endswith("/update/"):
            body = {
                "execution_id": execution_id,
                "step": {
                    "id": step_id,
                    "status": "succeeded",
                    "started_at": None,
                    "finished_at": None,
                    "exit_code": 0,
                    "error_message": "",
                },
                "execution_status": "running",
            }
            status_code = 200
        elif path.endswith("/start/"):
            body = {
                "execution_id": execution_id,
                "execution_status": "running",
                "step": {"id": step_id, "status": "running"},
                "runner_action": "run",
                "poll_after_seconds": 0,
            }
            status_code = 200
        elif path.endswith("/approval-status/"):
            body = {
                "execution_id": execution_id,
                "execution_status": "running",
                "step_id": step_id,
                "step_status": "running",
                "approval_request": None,
                "runner_action": "run",
                "poll_after_seconds": 0,
            }
            status_code = 200
        elif path.endswith("/complete/"):
            body = {
                "id": execution_id,
                "status": "succeeded",
                "finished_at": "2026-01-01T00:00:00Z",
            }
            status_code = 200
        elif path.endswith("/artifacts/"):
            body = {
                "id": str(uuid4()),
                "execution_id": execution_id,
                "step_id": step_id,
                "kind": "stdout",
                "name": "stdout.txt",
                "mime_type": "text/plain",
                "size_bytes": 5,
                "checksum_sha256": "a" * 64,
                "uploaded_by_runner_id": "test-runner",
                "uploaded_at": "2026-01-01T00:00:00Z",
            }
            status_code = 201
        else:
            body = {"error": "unexpected path"}
            status_code = 500
        return httpx.Response(
            status_code, json=body, request=httpx.Request("POST", url)
        )

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Timeout and retry policy
# ---------------------------------------------------------------------------


def test_runner_api_timeout_uses_explicit_phases():
    assert RUNNER_API_TIMEOUT.connect == 2.0
    assert RUNNER_API_TIMEOUT.read == 10.0
    assert RUNNER_API_TIMEOUT.write == 10.0
    assert RUNNER_API_TIMEOUT.pool == 2.0


def test_standard_runner_methods_use_same_timeout_object():
    http = _RecordingHttpClient()
    client = ApiClient(
        base_url="http://api:8000",
        runner_id="test-runner",
        runner_token="test-runner-token",
        runner_version="0.1.0",
        http_client=http,  # type: ignore[arg-type]
    )
    execution_id = uuid4()
    step_id = uuid4()
    claim_token = uuid4()

    client.claim_next()
    client.heartbeat(execution_id, claim_token)
    client.update_step(execution_id, step_id, claim_token, status="succeeded")
    client.start_step(execution_id, step_id, claim_token)
    client.get_step_approval_status(execution_id, step_id, claim_token)
    client.complete_execution(execution_id, claim_token, final_status="succeeded")

    assert http.timeouts == [RUNNER_API_TIMEOUT] * 6


def test_upload_artifact_uses_upload_specific_timeout():
    http = _RecordingHttpClient()
    client = ApiClient(
        base_url="http://api:8000",
        runner_id="test-runner",
        runner_token="test-runner-token",
        runner_version="0.1.0",
        http_client=http,  # type: ignore[arg-type]
    )

    client.upload_artifact(
        uuid4(),
        uuid4(),
        uuid4(),
        kind="stdout",
        name="stdout.txt",
        file_obj=b"hello",
        mime_type="text/plain",
        checksum_sha256="a" * 64,
    )

    assert http.timeouts == [ARTIFACT_UPLOAD_TIMEOUT]
    assert ARTIFACT_UPLOAD_TIMEOUT.read == 60.0
    assert ARTIFACT_UPLOAD_TIMEOUT.write == 60.0


def test_claim_next_retries_503_with_bounded_delays():
    attempts = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"execution": None, "poll_after_seconds": 5})

    client = make_client(
        httpx.MockTransport(handler), retry_sleep=lambda delay: sleeps.append(delay)
    )

    client.claim_next()

    assert attempts == 4
    assert sleeps == list(RETRY_DELAYS_SECONDS)


def test_claim_next_retries_transport_error():
    attempts = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json={"execution": None, "poll_after_seconds": 5})

    client = make_client(
        httpx.MockTransport(handler), retry_sleep=lambda delay: sleeps.append(delay)
    )

    client.claim_next()

    assert attempts == 2
    assert sleeps == [1.0]


def test_409_conflict_is_not_retried():
    attempts = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            409, json={"errors": [{"code": "invalid_state_transition"}]}
        )

    client = make_client(
        httpx.MockTransport(handler), retry_sleep=lambda delay: sleeps.append(delay)
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.complete_execution(uuid4(), uuid4(), final_status="succeeded")

    assert attempts == 1
    assert sleeps == []


def test_retry_wrapper_can_be_disabled():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = make_client(
        httpx.MockTransport(handler),
        api_retries_enabled=False,
        retry_sleep=lambda delay: None,
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.claim_next()

    assert attempts == 1


def test_retry_log_includes_required_context(caplog):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"execution": None, "poll_after_seconds": 5})

    client = make_client(httpx.MockTransport(handler), retry_sleep=lambda delay: None)

    with caplog.at_level(logging.WARNING, logger="runner.client"):
        client.claim_next()

    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "runner_api_request_retrying"
    )
    assert record.method == "POST"
    assert record.path == "/api/v1/internal/executions/claim-next/"
    assert record.attempt == 1
    assert record.delay_seconds == 1.0
    assert record.status_code == 503
    assert record.runner_id == "test-runner"
    assert record.request_id


def test_retry_sleep_can_be_interrupted():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = make_client(
        httpx.MockTransport(handler),
        retry_sleep=lambda delay: True,
    )

    with pytest.raises(httpx.HTTPStatusError):
        client.claim_next()

    assert attempts == 1


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


def test_claim_next_sends_runner_bearer_token():
    captured = {}
    body = {"execution": None, "poll_after_seconds": 5}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    client.claim_next()

    assert captured["authorization"] == "Bearer test-runner-token"


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


def test_update_step_running_rejected_by_schema():
    """StepUpdateRequest must not accept running — only start_step may set a step running."""
    with pytest.raises(ValidationError):
        StepUpdateRequest(
            runner_id="runner-1",
            claim_token=uuid4(),
            status="running",
        )


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
# start_step
# ---------------------------------------------------------------------------


def test_start_step_sends_correct_url_and_parses_blocked():
    captured = {}
    execution_id = uuid4()
    step_id = uuid4()
    body = {
        "execution_id": str(execution_id),
        "execution_status": "running",
        "step": {"id": str(step_id), "status": "failed"},
        "runner_action": "blocked",
        "policy_evaluation": {
            "id": str(uuid4()),
            "outcome": "block",
            "effective_outcome": "block",
            "reason": "Blocked by policy.",
        },
        "poll_after_seconds": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    claim_token = uuid4()
    client = make_client(httpx.MockTransport(handler))
    resp = client.start_step(execution_id, step_id, claim_token)

    assert captured["method"] == "POST"
    assert (
        captured["path"]
        == f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/start/"
    )
    assert captured["runner_id"] == "test-runner"
    assert captured["claim_token"] == str(claim_token)
    assert isinstance(resp, StepStartResponse)
    assert resp.runner_action == "blocked"


# ---------------------------------------------------------------------------
# get_step_approval_status
# ---------------------------------------------------------------------------


def test_get_step_approval_status_sends_correct_url_and_parses_run():
    captured = {}
    execution_id = uuid4()
    step_id = uuid4()
    body = {
        "execution_id": str(execution_id),
        "execution_status": "running",
        "step_id": str(step_id),
        "step_status": "running",
        "approval_request": None,
        "runner_action": "run",
        "poll_after_seconds": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    claim_token = uuid4()
    client = make_client(httpx.MockTransport(handler))
    resp = client.get_step_approval_status(execution_id, step_id, claim_token)

    assert captured["method"] == "POST"
    assert (
        captured["path"]
        == f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/approval-status/"
    )
    assert captured["runner_id"] == "test-runner"
    assert captured["claim_token"] == str(claim_token)
    assert isinstance(resp, ApprovalStatusResponse)
    assert resp.runner_action == "run"


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


# ---------------------------------------------------------------------------
# upload_artifact
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Request ID and Runner ID headers
# ---------------------------------------------------------------------------


def test_claim_next_sends_x_request_id():
    captured = {}
    body = {"execution": None, "poll_after_seconds": 5}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["x_request_id"] = request.headers.get("X-Request-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    client.claim_next()

    assert captured["x_request_id"] is not None
    # Must be a valid UUID
    from uuid import UUID

    UUID(captured["x_request_id"])


def test_claim_next_sends_x_runner_id():
    captured = {}
    body = {"execution": None, "poll_after_seconds": 5}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["x_runner_id"] = request.headers.get("X-Runner-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    client.claim_next()

    assert captured["x_runner_id"] == "test-runner"


def test_claim_next_logs_structured_request_context(caplog):
    captured = {}
    body = {"execution": None, "poll_after_seconds": 5}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["x_request_id"] = request.headers.get("X-Request-ID")
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    with caplog.at_level(logging.INFO, logger="runner.client"):
        client.claim_next()

    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "runner_api_request_completed"
    )
    assert record.request_id == captured["x_request_id"]
    assert record.runner_id == "test-runner"
    assert record.runner_version == "0.1.0"
    assert record.method == "POST"
    assert record.path == "/api/v1/internal/executions/claim-next/"
    assert record.status_code == 200
    assert record.duration_ms >= 0


def test_each_request_gets_unique_x_request_id():
    ids = []
    body = {"execution": None, "poll_after_seconds": 5}

    def handler(request: httpx.Request) -> httpx.Response:
        ids.append(request.headers.get("X-Request-ID"))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    client.claim_next()
    client.claim_next()

    assert len(ids) == 2
    assert ids[0] != ids[1], "Each request must carry a distinct X-Request-ID"


# ---------------------------------------------------------------------------
# upload_artifact
# ---------------------------------------------------------------------------


def test_upload_artifact_sends_multipart_shape():
    captured = {}
    execution_id = uuid4()
    step_id = uuid4()
    artifact_id = uuid4()
    body = {
        "id": str(artifact_id),
        "execution_id": str(execution_id),
        "step_id": str(step_id),
        "kind": "stdout",
        "name": "stdout.txt",
        "mime_type": "text/plain",
        "size_bytes": 11,
        "checksum_sha256": "a" * 64,
        "uploaded_by_runner_id": "test-runner",
        "uploaded_at": "2026-01-01T00:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers["content-type"]
        body_text = request.content.decode()
        captured["body"] = body_text
        return httpx.Response(
            201,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    claim_token = uuid4()
    client = make_client(httpx.MockTransport(handler))
    response = client.upload_artifact(
        execution_id,
        step_id,
        claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=b"hello world",
        mime_type="text/plain",
        checksum_sha256="a" * 64,
        metadata={"truncated": False},
    )

    assert captured["method"] == "POST"
    assert captured["path"] == (
        f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/"
    )
    assert captured["authorization"] == "Bearer test-runner-token"
    assert "multipart/form-data" in captured["content_type"]
    assert 'name="runner_id"' in captured["body"]
    assert "test-runner" in captured["body"]
    assert 'name="claim_token"' in captured["body"]
    assert str(claim_token) in captured["body"]
    assert 'name="checksum_sha256"' in captured["body"]
    assert "a" * 64 in captured["body"]
    assert 'name="metadata"' in captured["body"]
    assert '"truncated": false' in captured["body"]
    assert 'name="file"; filename="stdout.txt"' in captured["body"]
    assert "hello world" in captured["body"]
    assert response.id == artifact_id


# ---------------------------------------------------------------------------
# submit_verification_result
# ---------------------------------------------------------------------------


def test_submit_verification_result_sends_expected_payload():
    captured = {}
    change_id = uuid4()
    execution_id = uuid4()
    claim_token = uuid4()
    result_id = uuid4()
    check_id = uuid4()
    artifact_id = uuid4()
    body = {
        "result_id": str(result_id),
        "check_id": str(check_id),
        "validation_status": "accepted",
        "validation_errors": [],
        "check_status": "passed",
        "plan_status": "active",
        "change_status": "verification_pending",
        "accepted": True,
        "artifact_ids": [str(artifact_id)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("Authorization")
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    client = make_client(httpx.MockTransport(handler))
    response = client.submit_verification_result(
        change_id,
        execution_id,
        claim_token,
        check_key="runner-health-check",
        outcome="passed",
        verification_key="postdeploy.health.ok",
        step_key="health-check",
        artifact_ids=[artifact_id],
        artifact_checksums={str(artifact_id): "a" * 64},
        observed_value={"exit_code": 0},
        metadata={"source": "runner"},
    )

    assert captured["method"] == "POST"
    assert (
        captured["path"]
        == f"/api/v1/internal/changes/{change_id}/verification-results/"
    )
    assert captured["authorization"] == "Bearer test-runner-token"
    assert captured["json"]["runner_id"] == "test-runner"
    assert captured["json"]["claim_token"] == str(claim_token)
    assert captured["json"]["execution_id"] == str(execution_id)
    assert captured["json"]["check_key"] == "runner-health-check"
    assert captured["json"]["verification_key"] == "postdeploy.health.ok"
    assert captured["json"]["outcome"] == "passed"
    assert captured["json"]["step_key"] == "health-check"
    assert captured["json"]["artifact_ids"] == [str(artifact_id)]
    assert captured["json"]["artifact_checksums"][str(artifact_id)] == "a" * 64
    assert captured["json"]["observed_value"] == {"exit_code": 0}
    assert captured["json"]["metadata"] == {"source": "runner"}
    assert response.accepted is True
    assert response.validation_status == "accepted"
