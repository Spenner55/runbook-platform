"""
FastAPI contract tests for POST /summarize/execution.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_VALID_PAYLOAD = {
    "request_id": "sum-001",
    "execution_id": "exec-abc-123",
    "workflow_title": "Deploy Service",
    "status": "succeeded",
    "steps": [
        {
            "step_id": "step-1",
            "name": "Verify prerequisites",
            "status": "succeeded",
            "output": "All checks passed.",
        },
        {
            "step_id": "step-2",
            "name": "Run deployment script",
            "status": "succeeded",
            "output": None,
        },
    ],
}


def test_summarize_execution_returns_200():
    response = client.post("/summarize/execution", json=_VALID_PAYLOAD)
    assert response.status_code == 200


def test_summarize_execution_response_has_required_fields():
    response = client.post("/summarize/execution", json=_VALID_PAYLOAD)
    body = response.json()
    assert "request_id" in body
    assert "summary" in body
    assert "key_outcomes" in body


def test_summarize_execution_echoes_request_id():
    response = client.post("/summarize/execution", json=_VALID_PAYLOAD)
    assert response.json()["request_id"] == "sum-001"


def test_summarize_execution_summary_is_string():
    response = client.post("/summarize/execution", json=_VALID_PAYLOAD)
    assert isinstance(response.json()["summary"], str)
    assert len(response.json()["summary"]) > 0


def test_summarize_execution_key_outcomes_is_list():
    response = client.post("/summarize/execution", json=_VALID_PAYLOAD)
    assert isinstance(response.json()["key_outcomes"], list)


def test_summarize_execution_with_failed_status():
    payload = {**_VALID_PAYLOAD, "status": "failed"}
    response = client.post("/summarize/execution", json=payload)
    assert response.status_code == 200


def test_summarize_execution_missing_request_id_returns_422():
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "request_id"}
    response = client.post("/summarize/execution", json=payload)
    assert response.status_code == 422


def test_summarize_execution_missing_execution_id_returns_422():
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "execution_id"}
    response = client.post("/summarize/execution", json=payload)
    assert response.status_code == 422


def test_summarize_execution_step_output_is_optional():
    payload = {
        **_VALID_PAYLOAD,
        "steps": [{"step_id": "s1", "name": "Step One", "status": "succeeded"}],
    }
    response = client.post("/summarize/execution", json=payload)
    assert response.status_code == 200
