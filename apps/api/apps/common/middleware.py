import time
import uuid

import structlog

logger = structlog.get_logger(__name__)


class RequestIDMiddleware:
    """Ensures every request carries a unique X-Request-ID header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        structlog.contextvars.clear_contextvars()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        method = request.method
        path = request.path
        request.request_id = request_id
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=method,
            path=path,
        )

        started = time.monotonic()
        status_code = 500
        try:
            response = self.get_response(request)
            status_code = response.status_code
            response["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            logger.info(
                "request_completed",
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()
