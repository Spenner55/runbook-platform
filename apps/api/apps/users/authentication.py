from django.conf import settings
from django.core.cache import cache
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.settings import api_settings


class CachedJWTAuthentication(JWTAuthentication):
    """Cache valid JWT user lookups briefly to reduce hot-path DB reads."""

    def get_user(self, validated_token):
        cache_seconds = getattr(settings, "JWT_USER_CACHE_SECONDS", 0)
        if cache_seconds <= 0:
            return super().get_user(validated_token)

        user_id = validated_token.get(api_settings.USER_ID_CLAIM)
        cache_key = f"auth:jwt-user:v1:{user_id}"
        cached_user = cache.get(cache_key)
        if cached_user is not None:
            return cached_user

        user = super().get_user(validated_token)
        cache.set(cache_key, user, timeout=cache_seconds)
        return user
