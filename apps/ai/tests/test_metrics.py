import json
import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_metrics_endpoint_returns_prometheus_text():
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "# HELP" in body
    assert "# TYPE" in body


def test_parse_request_updates_ai_metrics():
    payload = {
        "request_id": "metrics-req-001",
        "runbook": {
            "id": "deploy-service",
            "title": "Deploy Service",
            "raw_content": "1. Verify prerequisites\n2. Deploy\n3. Validate",
        },
    }

    response = client.post("/parse/runbook", json=payload)
    assert response.status_code == 200

    metrics = client.get("/metrics/")
    assert metrics.status_code == 200
    assert "runbook_ai_requests_total" in metrics.text
    assert 'operation="parse"' in metrics.text
    assert "runbook_ai_request_latency_seconds" in metrics.text
    assert "ai_parse_request_duration_seconds" in metrics.text


def test_blueprint_ai_duration_metrics_are_exposed_for_domain_routes():
    enrich_payload = {
        "request_id": "metrics-enrich-001",
        "workflow_title": "Deploy Service",
        "steps": [
            {
                "step_key": "step-1",
                "name": "Verify prerequisites",
                "step_type": "manual_task",
                "risk_level": "low",
                "requires_approval": False,
                "command": None,
            }
        ],
    }
    summarize_payload = {
        "request_id": "metrics-summary-001",
        "execution_id": "exec-1",
        "workflow_title": "Deploy Service",
        "status": "succeeded",
        "steps": [
            {
                "step_id": "step-1",
                "name": "Verify prerequisites",
                "status": "succeeded",
                "output": "ok",
            }
        ],
    }

    assert client.post("/enrich/workflow", json=enrich_payload).status_code == 200
    assert (
        client.post("/summarize/execution", json=summarize_payload).status_code == 200
    )

    metrics = client.get("/metrics/")
    assert "ai_enrich_request_duration_seconds" in metrics.text
    assert "ai_summarize_request_duration_seconds" in metrics.text


def test_ai_response_echoes_inbound_request_id_and_logs_completion(caplog):
    request_id = "ai-req-001"

    with caplog.at_level("INFO", logger="app.request"):
        response = client.get("/health", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if "request_completed" in record.getMessage()
    ]
    record = next(item for item in records if item["request_id"] == request_id)
    assert record["event"] == "request_completed"
    assert record["method"] == "GET"
    assert record["path"] == "/health"
    assert record["status_code"] == 200
    assert record["duration_ms"] >= 0


def test_ai_response_generates_request_id_when_absent():
    response = client.get("/health")

    assert response.status_code == 200
    uuid.UUID(response.headers["X-Request-ID"])
