"""
FastAPI contract tests for POST /parse/runbook.

Uses TestClient so no real network is needed.
"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import workflow_parser

client = TestClient(app)

_VALID_PAYLOAD = {
    "request_id": "req-001",
    "runbook": {
        "id": "deploy-service",
        "title": "Deploy Service",
        "raw_content": "1. Verify prerequisites\n2. Run deployment script\n3. Validate health check",
    },
}


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


def test_parse_runbook_returns_200():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    assert response.status_code == 200


def test_parse_runbook_response_has_required_fields():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    body = response.json()
    assert "request_id" in body
    assert "workflow_title" in body
    assert "steps" in body
    assert "warnings" in body


def test_parse_runbook_echoes_request_id():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    assert response.json()["request_id"] == "req-001"


def test_parse_runbook_uses_runbook_title_as_workflow_title():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    assert response.json()["workflow_title"] == "Deploy Service"


def test_parse_runbook_returns_steps():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    steps = response.json()["steps"]
    assert isinstance(steps, list)
    assert len(steps) > 0


def test_each_step_has_required_fields():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    for step in response.json()["steps"]:
        assert "step_key" in step
        assert "name" in step
        assert "step_type" in step
        assert "risk_level" in step
        assert "requires_approval" in step


# ---------------------------------------------------------------------------
# Deterministic behaviour
# ---------------------------------------------------------------------------


def test_numbered_steps_produce_one_step_per_line():
    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    steps = response.json()["steps"]
    assert len(steps) == 3


def test_same_input_produces_same_output():
    r1 = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    r2 = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    assert r1.json()["steps"] == r2.json()["steps"]


def test_normal_tests_force_deterministic_mode(monkeypatch):
    def fail_if_llm_called(_request):
        raise AssertionError("LLM parser must not run in normal tests")

    monkeypatch.setattr(workflow_parser, "_llm_parse", fail_if_llm_called)
    assert settings.AI_USE_LLM_PARSER is False

    response = client.post("/parse/runbook", json=_VALID_PAYLOAD)
    assert response.status_code == 200
    assert len(response.json()["steps"]) == 3


# ---------------------------------------------------------------------------
# Fallback for empty content
# ---------------------------------------------------------------------------


def test_empty_content_returns_fallback_steps():
    payload = {
        "request_id": "req-002",
        "runbook": {
            "id": "empty-rb",
            "title": "Empty Runbook",
            "raw_content": "",
        },
    }
    response = client.post("/parse/runbook", json=payload)
    assert response.status_code == 200
    steps = response.json()["steps"]
    assert len(steps) > 0


def test_empty_content_includes_warning():
    payload = {
        "request_id": "req-003",
        "runbook": {
            "id": "empty-rb",
            "title": "Empty Runbook",
            "raw_content": "",
        },
    }
    response = client.post("/parse/runbook", json=payload)
    assert len(response.json()["warnings"]) > 0


# ---------------------------------------------------------------------------
# Validation — missing required fields
# ---------------------------------------------------------------------------


def test_missing_request_id_returns_422():
    payload = {
        "runbook": {
            "id": "rb",
            "title": "T",
            "raw_content": "Step one",
        }
    }
    response = client.post("/parse/runbook", json=payload)
    assert response.status_code == 422


def test_missing_runbook_returns_422():
    response = client.post("/parse/runbook", json={"request_id": "req-x"})
    assert response.status_code == 422


def test_missing_raw_content_returns_422():
    payload = {
        "request_id": "req-y",
        "runbook": {"id": "rb", "title": "Title"},
    }
    response = client.post("/parse/runbook", json=payload)
    assert response.status_code == 422
