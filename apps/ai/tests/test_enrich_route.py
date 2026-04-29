"""
FastAPI contract tests for POST /enrich/workflow.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_VALID_PAYLOAD = {
    "request_id": "enrich-001",
    "workflow_title": "Deploy Service",
    "steps": [
        {
            "step_key": "step-1",
            "name": "Verify prerequisites",
            "step_type": "manual_task",
            "risk_level": "low",
            "requires_approval": False,
            "command": None,
        },
        {
            "step_key": "step-2",
            "name": "Run deployment script",
            "step_type": "shell_command",
            "risk_level": "medium",
            "requires_approval": False,
            "command": "./deploy.sh",
        },
    ],
}


def test_enrich_workflow_returns_200():
    response = client.post("/enrich/workflow", json=_VALID_PAYLOAD)
    assert response.status_code == 200


def test_enrich_workflow_response_has_required_fields():
    response = client.post("/enrich/workflow", json=_VALID_PAYLOAD)
    body = response.json()
    assert "request_id" in body
    assert "steps" in body
    assert "warnings" in body


def test_enrich_workflow_echoes_request_id():
    response = client.post("/enrich/workflow", json=_VALID_PAYLOAD)
    assert response.json()["request_id"] == "enrich-001"


def test_enrich_workflow_returns_same_number_of_steps():
    response = client.post("/enrich/workflow", json=_VALID_PAYLOAD)
    assert len(response.json()["steps"]) == len(_VALID_PAYLOAD["steps"])


def test_enrich_workflow_step_has_command_field():
    response = client.post("/enrich/workflow", json=_VALID_PAYLOAD)
    steps = response.json()["steps"]
    for step in steps:
        assert "command" in step


def test_enrich_workflow_with_optional_raw_content():
    payload = {**_VALID_PAYLOAD, "raw_content": "Some runbook text"}
    response = client.post("/enrich/workflow", json=payload)
    assert response.status_code == 200


def test_enrich_workflow_missing_request_id_returns_422():
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "request_id"}
    response = client.post("/enrich/workflow", json=payload)
    assert response.status_code == 422


def test_enrich_workflow_missing_steps_returns_422():
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "steps"}
    response = client.post("/enrich/workflow", json=payload)
    assert response.status_code == 422


def test_enrich_workflow_invalid_step_missing_name_returns_422():
    payload = {
        **_VALID_PAYLOAD,
        "steps": [
            {
                "step_key": "step-1",
                "step_type": "manual_task",
                "risk_level": "low",
                "requires_approval": False,
            }
        ],
    }
    response = client.post("/enrich/workflow", json=payload)
    assert response.status_code == 422
