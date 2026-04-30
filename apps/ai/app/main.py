import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.requests import Request

from app.api.routes.enrich import router as enrich_router
from app.api.routes.health import router as health_router
from app.api.routes.parse import router as parse_router
from app.api.routes.summarize import router as summarize_router

app = FastAPI(title="Runbook Platform AI Service")


AI_REQUESTS_TOTAL = Counter(
    "runbook_ai_requests_total",
    "AI service domain request count.",
    ("operation", "method", "status_code"),
)
AI_REQUEST_LATENCY_SECONDS = Histogram(
    "runbook_ai_request_latency_seconds",
    "AI service domain request latency.",
    ("operation",),
)
AI_ERRORS_TOTAL = Counter(
    "runbook_ai_errors_total",
    "AI service domain error count.",
    ("operation", "method"),
)


def _metrics_operation(path: str) -> str | None:
    if path.startswith("/parse/"):
        return "parse"
    if path.startswith("/enrich/"):
        return "enrich"
    if path.startswith("/summarize/"):
        return "summarize"
    return None


@app.middleware("http")
async def record_ai_metrics(request: Request, call_next):
    operation = _metrics_operation(request.url.path)
    if operation is None:
        return await call_next(request)

    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        AI_ERRORS_TOTAL.labels(operation=operation, method=request.method).inc()
        AI_REQUEST_LATENCY_SECONDS.labels(operation=operation).observe(
            time.monotonic() - started
        )
        raise

    status_code = str(response.status_code)
    AI_REQUESTS_TOTAL.labels(
        operation=operation,
        method=request.method,
        status_code=status_code,
    ).inc()
    AI_REQUEST_LATENCY_SECONDS.labels(operation=operation).observe(
        time.monotonic() - started
    )
    if response.status_code >= 500:
        AI_ERRORS_TOTAL.labels(operation=operation, method=request.method).inc()
    return response


app.include_router(health_router)
app.include_router(parse_router, prefix="/parse", tags=["parse"])
app.include_router(enrich_router, prefix="/enrich", tags=["enrich"])
app.include_router(summarize_router, prefix="/summarize", tags=["summarize"])

Instrumentator().instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)


@app.get("/metrics/", include_in_schema=False)
def prometheus_metrics_with_trailing_slash():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
