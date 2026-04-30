from django.urls import resolve


def test_metrics_endpoint_returns_prometheus_text(client):
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert "# HELP" in body
    assert "# TYPE" in body


def test_metrics_endpoint_is_outside_v1_api_namespace():
    match = resolve("/metrics/")

    assert match.namespace != "v1"


def test_v1_api_prefix_still_resolves(client):
    response = client.get("/api/v1/")

    assert response.status_code in {401, 403, 404}
