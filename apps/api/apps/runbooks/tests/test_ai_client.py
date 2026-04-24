"""
Tests for RunbookAiClient.

Uses httpx.MockTransport so no real network calls are made.
"""

import json

import httpx
import pytest

from apps.runbooks.ai_client import (
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
    RunbookAiClient,
    WorkflowCandidate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(handler) -> RunbookAiClient:
    """Build a RunbookAiClient backed by a MockTransport."""
    transport = httpx.MockTransport(handler)
    return RunbookAiClient(
        base_url="http://ai-test:8001",
        timeout=httpx.Timeout(5.0),
        transport=transport,
    )


def _json_response(data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(data).encode(),
    )


_VALID_RESPONSE = {
    "request_id": "req-001",
    "workflow_title": "Deploy Service",
    "steps": [
        {
            "step_key": "step-001",
            "name": "Verify prerequisites",
            "step_type": "manual_task",
            "risk_level": "low",
            "requires_approval": False,
        },
        {
            "step_key": "step-002",
            "name": "Run deployment",
            "step_type": "shell_command",
            "risk_level": "high",
            "requires_approval": True,
        },
    ],
    "warnings": [],
}


def _call(client: RunbookAiClient) -> WorkflowCandidate:
    return client.parse_runbook_to_workflow_candidate(
        request_id="req-001",
        runbook_id="deploy-service",
        runbook_title="Deploy Service",
        raw_content="Verify prerequisites\nRun deployment",
    )


# ---------------------------------------------------------------------------
# Request payload shape
# ---------------------------------------------------------------------------


def test_sends_correct_request_payload():
    """Client must send the expected JSON body to /parse/runbook."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["url"] = str(request.url)
        return _json_response(_VALID_RESPONSE)

    client = _make_client(handler)
    _call(client)

    assert captured["url"] == "http://ai-test:8001/parse/runbook"
    body = captured["body"]
    assert body["request_id"] == "req-001"
    assert body["runbook"]["id"] == "deploy-service"
    assert body["runbook"]["title"] == "Deploy Service"
    assert body["runbook"]["raw_content"] == "Verify prerequisites\nRun deployment"


# ---------------------------------------------------------------------------
# Success response mapping
# ---------------------------------------------------------------------------


def test_success_response_maps_to_candidate():
    client = _make_client(lambda _: _json_response(_VALID_RESPONSE))
    candidate = _call(client)

    assert isinstance(candidate, WorkflowCandidate)
    assert candidate.request_id == "req-001"
    assert candidate.workflow_title == "Deploy Service"
    assert len(candidate.steps) == 2


def test_step_fields_mapped_correctly():
    client = _make_client(lambda _: _json_response(_VALID_RESPONSE))
    candidate = _call(client)

    step = candidate.steps[0]
    assert step.step_key == "step-001"
    assert step.name == "Verify prerequisites"
    assert step.step_type == "manual_task"
    assert step.risk_level == "low"
    assert step.requires_approval is False


def test_warnings_included_in_candidate():
    response = {**_VALID_RESPONSE, "warnings": ["ambiguous step detected"]}
    client = _make_client(lambda _: _json_response(response))
    candidate = _call(client)
    assert candidate.warnings == ["ambiguous step detected"]


# ---------------------------------------------------------------------------
# HTTP error mapping
# ---------------------------------------------------------------------------


def test_non_200_raises_bad_response_error():
    client = _make_client(lambda _: httpx.Response(500, content=b"error"))
    with pytest.raises(AiServiceBadResponseError):
        _call(client)


def test_non_json_body_raises_bad_response_error():
    client = _make_client(
        lambda _: httpx.Response(
            200, content=b"not json", headers={"content-type": "text/plain"}
        )
    )
    with pytest.raises(AiServiceBadResponseError):
        _call(client)


def test_connect_error_raises_unavailable_error():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _make_client(handler)
    with pytest.raises(AiServiceUnavailableError):
        _call(client)


def test_read_timeout_raises_timeout_error():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = _make_client(handler)
    with pytest.raises(AiServiceTimeoutError):
        _call(client)


def test_connect_timeout_raises_timeout_error():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timeout")

    client = _make_client(handler)
    with pytest.raises(AiServiceTimeoutError):
        _call(client)


# ---------------------------------------------------------------------------
# Contract validation errors
# ---------------------------------------------------------------------------


def test_missing_workflow_title_raises_contract_error():
    response = {**_VALID_RESPONSE, "workflow_title": ""}
    client = _make_client(lambda _: _json_response(response))
    with pytest.raises(AiServiceContractError, match="workflow_title"):
        _call(client)


def test_empty_steps_list_raises_contract_error():
    response = {**_VALID_RESPONSE, "steps": []}
    client = _make_client(lambda _: _json_response(response))
    with pytest.raises(AiServiceContractError, match="steps"):
        _call(client)


def test_missing_steps_key_raises_contract_error():
    response = {"request_id": "req-001", "workflow_title": "Deploy"}
    client = _make_client(lambda _: _json_response(response))
    with pytest.raises(AiServiceContractError):
        _call(client)


def test_step_missing_name_raises_contract_error():
    bad_step = {
        "step_key": "step-001",
        "name": "",
        "step_type": "manual_task",
        "risk_level": "low",
        "requires_approval": False,
    }
    response = {**_VALID_RESPONSE, "steps": [bad_step]}
    client = _make_client(lambda _: _json_response(response))
    with pytest.raises(AiServiceContractError, match="name"):
        _call(client)


def test_duplicate_step_keys_raise_contract_error():
    dup_steps = [
        {
            "step_key": "dup",
            "name": "Step A",
            "step_type": "manual_task",
            "risk_level": "low",
            "requires_approval": False,
        },
        {
            "step_key": "dup",
            "name": "Step B",
            "step_type": "manual_task",
            "risk_level": "low",
            "requires_approval": False,
        },
    ]
    response = {**_VALID_RESPONSE, "steps": dup_steps}
    client = _make_client(lambda _: _json_response(response))
    with pytest.raises(AiServiceContractError, match="Duplicate"):
        _call(client)


def test_non_dict_response_body_raises_contract_error():
    client = _make_client(lambda _: _json_response([]))  # type: ignore[arg-type]
    with pytest.raises(AiServiceContractError):
        _call(client)
