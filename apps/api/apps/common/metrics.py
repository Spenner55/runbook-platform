import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from hmac import compare_digest
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django_prometheus.exports import ExportToDjangoView
from prometheus_client import Counter, Histogram

EXECUTION_LIFECYCLE_EVENTS_TOTAL = Counter(
    "runbook_execution_lifecycle_events_total",
    "Execution lifecycle events emitted by the Django control plane.",
    ("event", "status"),
)

EXECUTION_SERVICE_OPERATION_SECONDS = Histogram(
    "runbook_execution_service_operation_seconds",
    "Latency for key execution service operations.",
    ("operation",),
)

EXECUTION_STEP_TRANSITIONS_TOTAL = Counter(
    "runbook_execution_step_transitions_total",
    "Execution step status transitions emitted by the Django control plane.",
    ("status",),
)

RUNBOOK_EXECUTIONS_TOTAL = Counter(
    "runbook_executions_total",
    "Blueprint-compatible execution lifecycle event count.",
    ("event", "status"),
)

RUNBOOK_STEP_DURATION_SECONDS = Histogram(
    "runbook_step_duration_seconds",
    "Blueprint-compatible execution step runtime.",
    ("step_type", "risk_level", "outcome"),
)

RUNBOOK_APPROVAL_LATENCY_SECONDS = Histogram(
    "runbook_approval_latency_seconds",
    "Blueprint-compatible approval request resolution latency.",
    ("outcome",),
)

RUNBOOK_INTEGRATION_DISPATCH_DURATION_SECONDS = Histogram(
    "runbook_integration_dispatch_duration_seconds",
    "Blueprint-compatible integration dispatch duration.",
    ("integration_type", "outcome"),
)

RUNBOOK_ARTIFACT_UPLOAD_BYTES = Histogram(
    "runbook_artifact_upload_bytes",
    "Blueprint-compatible artifact upload size.",
    buckets=(
        1_024,
        10_240,
        102_400,
        1_048_576,
        10_485_760,
        52_428_800,
        262_144_000,
        float("inf"),
    ),
)

RUNBOOK_STUCK_EXECUTION_RECOVERIES_TOTAL = Counter(
    "runbook_stuck_execution_recoveries_total",
    "Blueprint-compatible stuck execution recovery count.",
    ("reason", "status"),
)


def record_execution_event(*, event: str, status: str) -> None:
    EXECUTION_LIFECYCLE_EVENTS_TOTAL.labels(event=event, status=status).inc()
    RUNBOOK_EXECUTIONS_TOTAL.labels(event=event, status=status).inc()


def record_step_transition(*, status: str) -> None:
    EXECUTION_STEP_TRANSITIONS_TOTAL.labels(status=status).inc()


def record_step_duration(
    *, step_type: str, risk_level: str, outcome: str, duration_seconds: float | None
) -> None:
    if duration_seconds is None:
        return
    RUNBOOK_STEP_DURATION_SECONDS.labels(
        step_type=step_type or "unknown",
        risk_level=risk_level or "unknown",
        outcome=outcome,
    ).observe(max(0.0, duration_seconds))


def record_approval_latency(*, outcome: str, requested_at, resolved_at) -> None:
    if not requested_at or not resolved_at:
        return
    RUNBOOK_APPROVAL_LATENCY_SECONDS.labels(outcome=outcome).observe(
        max(0.0, (resolved_at - requested_at).total_seconds())
    )


def record_integration_dispatch_duration(
    *, integration_type: str, outcome: str, duration_seconds: float
) -> None:
    RUNBOOK_INTEGRATION_DISPATCH_DURATION_SECONDS.labels(
        integration_type=integration_type or "unknown",
        outcome=outcome,
    ).observe(max(0.0, duration_seconds))


def record_artifact_upload_bytes(size_bytes: int) -> None:
    RUNBOOK_ARTIFACT_UPLOAD_BYTES.observe(max(0, size_bytes))


def record_stuck_execution_recovery(*, reason: str, status: str) -> None:
    RUNBOOK_STUCK_EXECUTION_RECOVERIES_TOTAL.labels(
        reason=reason,
        status=status,
    ).inc()


@contextmanager
def time_execution_operation(operation: str):
    started = time.monotonic()
    try:
        yield
    finally:
        EXECUTION_SERVICE_OPERATION_SECONDS.labels(operation=operation).observe(
            time.monotonic() - started
        )


def timed_execution_operation(operation: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            with time_execution_operation(operation):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def metrics_view(request: HttpRequest) -> HttpResponse:
    if not getattr(settings, "PROMETHEUS_METRICS_ENABLED", False):
        return ExportToDjangoView(request)

    expected_token = getattr(settings, "PROMETHEUS_METRICS_TOKEN", "")
    auth_header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if (
        not expected_token
        or not auth_header.startswith(prefix)
        or not compare_digest(auth_header[len(prefix) :], expected_token)
    ):
        return HttpResponseForbidden("Forbidden")

    return ExportToDjangoView(request)
