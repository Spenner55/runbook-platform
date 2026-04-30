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
