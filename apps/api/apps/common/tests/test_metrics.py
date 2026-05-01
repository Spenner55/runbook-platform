from datetime import timedelta

from django.test import override_settings
from django.urls import resolve
from django.utils import timezone
from prometheus_client import REGISTRY

from apps.common import metrics as common_metrics


def test_metrics_endpoint_returns_prometheus_text(client):
    response = client.get("/metrics/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    body = response.content.decode()
    assert "# HELP" in body
    assert "# TYPE" in body


@override_settings(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN="secret")
def test_metrics_endpoint_requires_bearer_token_when_enabled(client):
    response = client.get("/metrics/")

    assert response.status_code == 403


@override_settings(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN="secret")
def test_metrics_endpoint_rejects_wrong_bearer_token(client):
    response = client.get("/metrics/", HTTP_AUTHORIZATION="Bearer wrong")

    assert response.status_code == 403


@override_settings(PROMETHEUS_METRICS_ENABLED=True, PROMETHEUS_METRICS_TOKEN="secret")
def test_metrics_endpoint_accepts_valid_bearer_token(client):
    response = client.get("/metrics/", HTTP_AUTHORIZATION="Bearer secret")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")


def test_metrics_endpoint_is_outside_v1_api_namespace():
    match = resolve("/metrics/")

    assert match.namespace != "v1"


def test_v1_api_prefix_still_resolves(client):
    response = client.get("/api/v1/")

    assert response.status_code in {401, 403, 404}


def test_blueprint_metric_aliases_are_registered_and_observable():
    requested_at = timezone.now() - timedelta(seconds=5)
    resolved_at = timezone.now()

    common_metrics.record_execution_event(event="created", status="queued")
    common_metrics.record_step_duration(
        step_type="shell_command",
        risk_level="medium",
        outcome="succeeded",
        duration_seconds=1.25,
    )
    common_metrics.record_approval_latency(
        outcome="approved",
        requested_at=requested_at,
        resolved_at=resolved_at,
    )
    common_metrics.record_integration_dispatch_duration(
        integration_type="generic_webhook",
        outcome="success",
        duration_seconds=0.15,
    )
    common_metrics.record_artifact_upload_bytes(2048)
    common_metrics.record_stuck_execution_recovery(
        reason="heartbeat_timeout",
        status="failed",
    )

    assert (
        REGISTRY.get_sample_value(
            "runbook_executions_total",
            {"event": "created", "status": "queued"},
        )
        is not None
    )
    assert (
        REGISTRY.get_sample_value(
            "runbook_step_duration_seconds_count",
            {
                "step_type": "shell_command",
                "risk_level": "medium",
                "outcome": "succeeded",
            },
        )
        is not None
    )
    assert (
        REGISTRY.get_sample_value(
            "runbook_approval_latency_seconds_count",
            {"outcome": "approved"},
        )
        is not None
    )
    assert (
        REGISTRY.get_sample_value(
            "runbook_integration_dispatch_duration_seconds_count",
            {"integration_type": "generic_webhook", "outcome": "success"},
        )
        is not None
    )
    assert REGISTRY.get_sample_value("runbook_artifact_upload_bytes_count") is not None
    assert (
        REGISTRY.get_sample_value(
            "runbook_stuck_execution_recoveries_total",
            {"reason": "heartbeat_timeout", "status": "failed"},
        )
        is not None
    )
