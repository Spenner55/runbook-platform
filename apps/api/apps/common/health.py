import logging
import time

import httpx
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def _healthy_check(latency_ms: float | None = None) -> dict[str, object]:
    check: dict[str, object] = {"status": "healthy"}
    if latency_ms is not None:
        check["latency_ms"] = round(latency_ms, 2)
    return check


def _unhealthy_check(detail: str) -> dict[str, object]:
    return {"status": "unhealthy", "detail": detail}


def _check_db() -> dict[str, object]:
    started = time.perf_counter()
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return _healthy_check((time.perf_counter() - started) * 1000)
    except Exception as exc:
        logger.error("health.db_check_failed", exc_info=True)
        return _unhealthy_check(str(exc))


def _check_migrations() -> dict[str, object]:
    try:
        call_command("migrate", "--check", verbosity=0)
        return _healthy_check()
    except Exception as exc:
        logger.error("health.migration_check_failed", exc_info=True)
        return _unhealthy_check(str(exc))


def _check_ai() -> dict[str, object]:
    started = time.perf_counter()
    url = getattr(settings, "AI_BASE_URL", "http://ai:8001")
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        if resp.status_code == 200:
            return _healthy_check((time.perf_counter() - started) * 1000)
        return _unhealthy_check(f"status {resp.status_code}")
    except Exception as exc:
        logger.warning("health.ai_check_failed", exc_info=True)
        return _unhealthy_check(str(exc))


def _is_healthy(check: dict[str, object]) -> bool:
    return check.get("status") == "healthy"


def live_view(request):
    return JsonResponse({"status": "live", "service": "api"}, status=200)


def readiness_view(request):
    database = _check_db()
    migrations = _check_migrations()

    ready = _is_healthy(database) and _is_healthy(migrations)
    payload = {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": database,
            "migrations": migrations,
        },
    }
    return JsonResponse(payload, status=200 if ready else 503)


def detailed_health_view(request):
    database = _check_db()
    ai_service = _check_ai()

    healthy = _is_healthy(database) and _is_healthy(ai_service)
    payload = {
        "status": "healthy" if healthy else "unhealthy",
        "checks": {
            "database": database,
            "ai_service": ai_service,
        },
    }
    return JsonResponse(payload, status=200 if healthy else 503)
