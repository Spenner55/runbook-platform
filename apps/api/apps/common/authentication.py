import hashlib
from dataclasses import dataclass, field

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
    runner_id: str | None = None
    pool_id: str | None = None
    organization_id: str | None = None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RunnerBearerTokenAuthentication(BaseAuthentication):
    """Authenticate internal runner requests with a bearer token.

    Resolves against the Runner model first (per-runner tokens). Falls back to
    the legacy RUNNER_TOKENS list when RUNNER_LEGACY_TOKEN_MODE is True.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            return None

        token = parts[1]

        # Try DB-based per-runner token first.
        result = self._authenticate_runner_token(token)
        if result is not None:
            return result  # already (principal, None)

        # Fall back to legacy shared token list.
        if getattr(settings, "RUNNER_LEGACY_TOKEN_MODE", True):
            return self._authenticate_legacy_token(token)

        if self._is_valid_user_jwt(token):
            raise PermissionDenied(
                "User sessions are not permitted on internal endpoints."
            )
        raise AuthenticationFailed("Invalid runner token.")

    def authenticate_header(self, request):
        return self.keyword

    def _authenticate_runner_token(self, token: str):
        """Try to match against Runner.token_hash. Returns (principal, None) or None."""
        try:
            from apps.runners.models import Runner  # avoid circular at module level
        except ImportError:
            return None

        token_hash = _hash_token(token)
        try:
            runner = Runner.objects.select_related("pool", "organization").get(
                token_hash=token_hash
            )
        except Runner.DoesNotExist:
            return None

        if runner.status in (Runner.Status.REVOKED, Runner.Status.DISABLED):
            raise AuthenticationFailed(
                f"Runner is {runner.status} and cannot authenticate."
            )

        principal = RunnerPrincipal(
            runner_id=str(runner.id),
            pool_id=str(runner.pool_id),
            organization_id=str(runner.organization_id),
        )
        return principal, None

    def _authenticate_legacy_token(self, token: str):
        from hmac import compare_digest

        configured_tokens = getattr(settings, "RUNNER_TOKENS", [])
        if not configured_tokens:
            raise AuthenticationFailed("Runner authentication is not configured.")

        if not any(compare_digest(token, t) for t in configured_tokens):
            if self._is_valid_user_jwt(token):
                raise PermissionDenied(
                    "User sessions are not permitted on internal endpoints."
                )
            raise AuthenticationFailed("Invalid runner token.")

        return RunnerPrincipal(), None

    def _is_valid_user_jwt(self, token: str) -> bool:
        try:
            JWTAuthentication().get_validated_token(token)
        except (InvalidToken, TokenError):
            return False
        return True
