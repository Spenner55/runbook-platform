from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403

DEBUG = False

# ──────────────────────────────────────────────────────────────────────────────
# Startup validation — fail loudly if required env vars are absent or defaulted.
# ──────────────────────────────────────────────────────────────────────────────


def _require_env(key: str) -> str:
    value = env(key, default="")  # noqa: F405 — env imported via base *
    if not value or value == "change-me":
        raise ImproperlyConfigured(
            f"Required environment variable {key!r} is not set or has default value."
        )
    return value


_require_env("DJANGO_SECRET_KEY")
_require_env("DATABASE_URL")
_require_env("RUNNER_REGISTRATION_TOKEN")
_require_env("CHANGE_DISPATCH_TOKEN_SECRET")

if not globals().get("INTEGRATION_FERNET_KEY"):
    raise ImproperlyConfigured("INTEGRATION_FERNET_KEY is required in production.")

# Fail-closed: if Prometheus metrics are enabled, a scrape token must be configured.
PROMETHEUS_METRICS_ENABLED = env.bool(  # noqa: F405
    "PROMETHEUS_METRICS_ENABLED", default=False
)
PROMETHEUS_METRICS_TOKEN = env("PROMETHEUS_METRICS_TOKEN", default="")  # noqa: F405
if PROMETHEUS_METRICS_ENABLED:
    _require_env("PROMETHEUS_METRICS_TOKEN")

# ──────────────────────────────────────────────────────────────────────────────
# Hosts and CORS — no hardcoded values; must come from environment.
# ──────────────────────────────────────────────────────────────────────────────

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")  # noqa: F405 — raises if unset
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])  # noqa: F405
CORS_ALLOW_CREDENTIALS = True

# ──────────────────────────────────────────────────────────────────────────────
# HTTPS / SSL
# ──────────────────────────────────────────────────────────────────────────────

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# ──────────────────────────────────────────────────────────────────────────────
# Cookies
# ──────────────────────────────────────────────────────────────────────────────

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# ──────────────────────────────────────────────────────────────────────────────
# Security headers
# ──────────────────────────────────────────────────────────────────────────────

X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Content Security Policy — read by csp.middleware.CSPMiddleware (registered in base.py).
# Without that middleware in MIDDLEWARE the CONTENT_SECURITY_POLICY setting is a silent no-op.
# Uses django-csp 4.x dict format (directives are lowercase strings, values are lists).
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'"],
        "style-src": [
            "'self'",
            "'unsafe-inline'",
        ],  # Vite inlines critical CSS; tighten in Phase 10.10
        "img-src": ["'self'", "data:"],
        "font-src": ["'self'"],
        "connect-src": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
}

# ──────────────────────────────────────────────────────────────────────────────
# Database connection durability
# PgBouncer (transaction mode) manages the actual pool; Django must not hold
# its own long-lived connections on top of that.
# ──────────────────────────────────────────────────────────────────────────────

DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# ──────────────────────────────────────────────────────────────────────────────
# Rate limiting (django-ratelimit)
# Applied at the view level via @ratelimit decorator on public endpoints.
# RATELIMIT_ENABLE = False in dev.py and test.py keeps local behavior unchanged.
# ──────────────────────────────────────────────────────────────────────────────

RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = "default"
AUTH_LOGIN_RATE_LIMIT = env("AUTH_LOGIN_RATE_LIMIT", default="5/m")  # noqa: F405
AUTH_REFRESH_RATE_LIMIT = env("AUTH_REFRESH_RATE_LIMIT", default="10/m")  # noqa: F405
WORKFLOW_CREATE_RATE_LIMIT = env(  # noqa: F405
    "WORKFLOW_CREATE_RATE_LIMIT", default="10/m"
)

# ──────────────────────────────────────────────────────────────────────────────
# Django admin — disabled by default in production; enable via env var only
# when needed (e.g., for a one-off data migration).
# ──────────────────────────────────────────────────────────────────────────────

DJANGO_ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=False)  # noqa: F405
