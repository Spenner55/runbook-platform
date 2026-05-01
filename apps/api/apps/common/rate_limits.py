from collections.abc import Callable

from django.conf import settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response


def setting_rate(setting_name: str) -> Callable[[str, Request], str | None]:
    def _rate(group: str, request: Request) -> str | None:
        return getattr(settings, setting_name, None)

    return _rate


def rate_limited_response() -> Response:
    return Response(
        {"detail": "Rate limit exceeded."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
