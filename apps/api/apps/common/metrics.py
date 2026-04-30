import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import wraps
from typing import Any

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


def record_execution_event(*, event: str, status: str) -> None:
    EXECUTION_LIFECYCLE_EVENTS_TOTAL.labels(event=event, status=status).inc()


def record_step_transition(*, status: str) -> None:
    EXECUTION_STEP_TRANSITIONS_TOTAL.labels(status=status).inc()


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
