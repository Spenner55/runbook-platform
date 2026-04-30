import logging

import httpx
from django.conf import settings
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def _check_db() -> tuple[bool, str]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True, "ok"
    except Exception as exc:
        logger.error("health.db_check_failed", exc_info=exc)
        return False, str(exc)


def _check_ai() -> tuple[bool, str]:
    url = getattr(settings, "AI_BASE_URL", "http://ai:8001")
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        if resp.status_code == 200:
            return True, "ok"
        return False, f"status {resp.status_code}"
    except Exception as exc:
        logger.warning("health.ai_check_failed", exc_info=exc)
        return False, str(exc)


def detailed_health_view(request):
    db_ok, db_status = _check_db()
    ai_ok, ai_status = _check_ai()

    healthy = db_ok and ai_ok
    payload = {
        "healthy": healthy,
        "checks": {
            "db": db_status,
            "ai": ai_status,
        },
    }
    return JsonResponse(payload, status=200 if healthy else 503)
