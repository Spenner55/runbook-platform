from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()

OpenAIHealthCheck = dict[str, str]

_openai_health_cache: tuple[float, OpenAIHealthCheck] | None = None


def _clear_openai_health_cache() -> None:
    global _openai_health_cache
    _openai_health_cache = None


def _openai_check_from_cache(now: float) -> OpenAIHealthCheck | None:
    if _openai_health_cache is None:
        return None

    cached_at, cached_check = _openai_health_cache
    if now - cached_at <= settings.AI_HEALTH_OPENAI_CACHE_SECONDS:
        return cached_check
    return None


def _cache_openai_check(now: float, check: OpenAIHealthCheck) -> OpenAIHealthCheck:
    global _openai_health_cache
    _openai_health_cache = (now, check)
    return check


def _build_openai_client() -> Any:
    from openai import OpenAI

    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.AI_HEALTH_OPENAI_TIMEOUT_SECONDS,
    )


def _openai_health_check() -> OpenAIHealthCheck:
    if not settings.AI_USE_LLM_PARSER:
        return {
            "status": "disabled",
            "mode": "disabled",
            "detail": "LLM parsing is disabled.",
        }

    missing_config = []
    if not settings.OPENAI_API_KEY:
        missing_config.append("OPENAI_API_KEY")
    if not settings.AI_PARSE_MODEL:
        missing_config.append("AI_PARSE_MODEL")

    if missing_config:
        return {
            "status": "not_configured",
            "mode": "configured",
            "detail": f"Missing required configuration: {', '.join(missing_config)}.",
        }

    now = time.monotonic()
    cached_check = _openai_check_from_cache(now)
    if cached_check is not None:
        return cached_check

    try:
        client = _build_openai_client()
        client.models.list()
    except Exception as exc:
        return _cache_openai_check(
            now,
            {
                "status": "degraded",
                "mode": "connectivity_checked",
                "detail": f"OpenAI connectivity check failed: {type(exc).__name__}.",
            },
        )

    return _cache_openai_check(
        now,
        {
            "status": "ok",
            "mode": "connectivity_checked",
            "detail": "OpenAI models endpoint reachable.",
        },
    )


@router.get("/health")
def health() -> dict[str, Any]:
    openai_check = _openai_health_check()
    status = "ok" if openai_check["status"] in {"ok", "disabled"} else "degraded"
    return {
        "status": status,
        "service": "ai",
        "checks": {
            "openai": openai_check,
        },
    }
