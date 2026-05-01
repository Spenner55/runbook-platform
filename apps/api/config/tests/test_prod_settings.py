"""
Tests for production settings: startup validation and security header configuration.

_require_env logic is tested as a pure function (no Django import needed).
CSP headers are verified by applying the prod-equivalent settings via override_settings
and making a request through the test client (which runs the full middleware stack).
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from config.urls import build_urlpatterns

# ──────────────────────────────────────────────────────────────────────────────
# _require_env validation logic
# ──────────────────────────────────────────────────────────────────────────────


def _require_env_logic(value: str, key: str) -> str:
    """Mirror of prod.py's _require_env for pure unit testing (no Django deps)."""
    if not value or value == "change-me":
        raise ImproperlyConfigured(
            f"Required environment variable {key!r} is not set or has default value."
        )
    return value


def _validate_prometheus_settings_logic(*, enabled: bool, token: str) -> None:
    if enabled:
        _require_env_logic(token, "PROMETHEUS_METRICS_TOKEN")


class TestRequireEnvLogic:
    def test_raises_for_empty_string(self):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _require_env_logic("", "DJANGO_SECRET_KEY")

    def test_raises_for_change_me_sentinel(self):
        with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
            _require_env_logic("change-me", "DJANGO_SECRET_KEY")

    def test_raises_for_none_coerced_to_falsy(self):
        with pytest.raises(ImproperlyConfigured):
            _require_env_logic(None, "SOME_KEY")

    def test_returns_value_for_valid_input(self):
        result = _require_env_logic("a-real-secret-value", "DJANGO_SECRET_KEY")
        assert result == "a-real-secret-value"

    @pytest.mark.parametrize(
        "key",
        [
            "DJANGO_SECRET_KEY",
            "DATABASE_URL",
            "RUNNER_REGISTRATION_TOKEN",
        ],
    )
    def test_required_production_keys_fail_when_empty(self, key):
        """Each key required in prod.py raises ImproperlyConfigured when empty."""
        with pytest.raises(ImproperlyConfigured):
            _require_env_logic("", key)


def test_prometheus_metrics_startup_validation_fails_when_enabled_without_token():
    with pytest.raises(ImproperlyConfigured, match="PROMETHEUS_METRICS_TOKEN"):
        _validate_prometheus_settings_logic(enabled=True, token="")


def test_prometheus_metrics_startup_validation_allows_disabled_without_token():
    _validate_prometheus_settings_logic(enabled=False, token="")


def _route_strings(patterns) -> set[str]:
    return {str(pattern.pattern) for pattern in patterns}


def test_admin_url_is_absent_when_disabled():
    routes = _route_strings(build_urlpatterns(admin_enabled=False))

    assert "admin/" not in routes


def test_admin_url_is_present_when_enabled():
    routes = _route_strings(build_urlpatterns(admin_enabled=True))

    assert "admin/" in routes


# ──────────────────────────────────────────────────────────────────────────────
# CSP and security header settings (django-csp 4.x CONTENT_SECURITY_POLICY dict)
# ──────────────────────────────────────────────────────────────────────────────

# Mirrors the CONTENT_SECURITY_POLICY value in prod.py.
PROD_CSP = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": ["'self'", "'unsafe-inline'"],
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
}


@override_settings(CONTENT_SECURITY_POLICY=PROD_CSP)
def test_csp_middleware_emits_header(client):
    """CSP middleware emits Content-Security-Policy when CONTENT_SECURITY_POLICY is configured."""
    response = client.get("/health/")
    assert "Content-Security-Policy" in response, (
        "CSP middleware did not emit the Content-Security-Policy header. "
        "Ensure csp.middleware.CSPMiddleware is registered in MIDDLEWARE (base.py)."
    )


@override_settings(CONTENT_SECURITY_POLICY=PROD_CSP)
def test_csp_header_contains_default_self(client):
    response = client.get("/health/")
    csp = response.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp


@override_settings(CONTENT_SECURITY_POLICY=PROD_CSP)
def test_csp_header_denies_frame_ancestors(client):
    response = client.get("/health/")
    csp = response.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp


@override_settings(CONTENT_SECURITY_POLICY=PROD_CSP)
def test_csp_header_allows_data_uri_images(client):
    response = client.get("/health/")
    csp = response.get("Content-Security-Policy", "")
    assert "img-src 'self' data:" in csp
