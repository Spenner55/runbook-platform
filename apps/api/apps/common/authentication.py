from dataclasses import dataclass
from hmac import compare_digest

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


@dataclass(frozen=True)
class RunnerPrincipal:
    """Authenticated internal runner principal, intentionally not a User."""

    token_name: str = "runner"
    is_authenticated: bool = True
    is_runner: bool = True


class RunnerBearerTokenAuthentication(BaseAuthentication):
    """Authenticate internal runner requests with a shared bearer token."""

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        configured_tokens = getattr(settings, "RUNNER_TOKENS", [])
        if not configured_tokens:
            raise AuthenticationFailed("Runner authentication is not configured.")

        if not any(compare_digest(parts[1], token) for token in configured_tokens):
            if self._is_valid_user_jwt(parts[1]):
                raise PermissionDenied(
                    "User sessions are not permitted on internal endpoints."
                )
            raise AuthenticationFailed("Invalid runner token.")

        return RunnerPrincipal(), None

    def authenticate_header(self, request):
        return self.keyword

    def _is_valid_user_jwt(self, token: str) -> bool:
        try:
            JWTAuthentication().get_validated_token(token)
        except (InvalidToken, TokenError):
            return False
        return True
