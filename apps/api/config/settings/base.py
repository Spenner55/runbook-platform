import os
from datetime import timedelta
from pathlib import Path

import environ
import structlog
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR

env = environ.Env(
    DEBUG=(bool, False),
)

environ.Env.read_env(os.path.join(REPO_ROOT, ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-change-me")
DEBUG = env("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

AUTH_USER_MODEL = "users.User"

INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # Domain apps
    "apps.users.apps.UsersConfig",
    "apps.common.apps.CommonConfig",
    "apps.organizations.apps.OrganizationsConfig",
    "apps.runbooks.apps.RunbooksConfig",
    "apps.workflows.apps.WorkflowsConfig",
    "apps.executions.apps.ExecutionsConfig",
    "apps.approvals.apps.ApprovalsConfig",
    "apps.policies.apps.PoliciesConfig",
    "apps.audit.apps.AuditConfig",
    "apps.artifacts.apps.ArtifactsConfig",
    "apps.integrations.apps.IntegrationsConfig",
    "apps.changes.apps.ChangesConfig",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "apps.common.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://postgres:postgres@localhost:5432/runbook_platform",
    )
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.users.authentication.CachedJWTAuthentication",
    ],
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ("v1",),
    "EXCEPTION_HANDLER": "apps.common.api_errors.custom_exception_handler",
}

DJANGO_LOG_LEVEL = env("DJANGO_LOG_LEVEL", default="INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain_console": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processors": [
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain_console",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": DJANGO_LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": DJANGO_LOG_LEVEL,
            "propagate": False,
        },
    },
}

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-organization-id",
    "x-request-id",
]
CORS_EXPOSE_HEADERS = ["x-request-id"]

# AI service settings
AI_BASE_URL = env("AI_BASE_URL", default="http://ai:8001")
# Model selection is a human decision — no default. Must be set explicitly when LLM parsing is enabled.
AI_PARSE_MODEL = env("AI_PARSE_MODEL", default="")

# Integration settings
INTEGRATION_FERNET_KEY = env("INTEGRATION_FERNET_KEY", default="")
INTEGRATION_DISPATCH_TIMEOUT_SECONDS = env.float(
    "INTEGRATION_DISPATCH_TIMEOUT_SECONDS", default=3.0
)
INTEGRATION_DISPATCH_BUDGET_SECONDS = env.float(
    "INTEGRATION_DISPATCH_BUDGET_SECONDS", default=10.0
)
INTEGRATION_MAX_PER_TRIGGER = env.int("INTEGRATION_MAX_PER_TRIGGER", default=25)

# Change dispatch token settings
CHANGE_DISPATCH_TOKEN_SECRET = env(
    "CHANGE_DISPATCH_TOKEN_SECRET", default="change-dispatch-insecure-change-me"
)

# Artifact storage settings
RUNNER_REGISTRATION_TOKEN = env("RUNNER_REGISTRATION_TOKEN", default="")
RUNNER_TOKENS = [
    token
    for token in env.list("RUNNER_TOKENS", default=[])
    or ([RUNNER_REGISTRATION_TOKEN] if RUNNER_REGISTRATION_TOKEN else [])
    if token
]
RUNNER_STALE_HEARTBEAT_SECONDS = env.int("RUNNER_STALE_HEARTBEAT_SECONDS", default=60)
ARTIFACT_STORAGE_BACKEND = env("ARTIFACT_STORAGE_BACKEND", default="local")
ARTIFACT_MEDIA_ROOT = env(
    "ARTIFACT_MEDIA_ROOT", default=str(BASE_DIR / "media" / "artifacts")
)
ARTIFACT_S3_BUCKET = env("ARTIFACT_S3_BUCKET", default="")
ARTIFACT_S3_REGION = env("ARTIFACT_S3_REGION", default="")
ARTIFACT_S3_PREFIX = env("ARTIFACT_S3_PREFIX", default="artifacts/")
ARTIFACT_ALLOWED_MIME_TYPES = env.list("ARTIFACT_ALLOWED_MIME_TYPES", default=[])
ARTIFACT_REQUIRE_CHECKSUM = env.bool("ARTIFACT_REQUIRE_CHECKSUM", default=True)
ARTIFACT_MAX_UPLOAD_BYTES = env.int(
    "ARTIFACT_MAX_UPLOAD_BYTES", default=52428800
)  # 50 MB
ARTIFACT_MAX_ARTIFACTS_PER_STEP = env.int("ARTIFACT_MAX_ARTIFACTS_PER_STEP", default=10)
ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION = env.int(
    "ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION", default=262144000
)  # 250 MB
ARTIFACT_DAILY_BYTES_PER_RUNNER = env.int(
    "ARTIFACT_DAILY_BYTES_PER_RUNNER", default=1073741824
)  # 1 GB
ARTIFACT_DOWNLOAD_URL_TTL_SECONDS = env.int(
    "ARTIFACT_DOWNLOAD_URL_TTL_SECONDS", default=300
)
ARTIFACT_MAX_METADATA_BYTES = env.int("ARTIFACT_MAX_METADATA_BYTES", default=8192)
ARTIFACT_STDOUT_STDERR_MAX_BYTES = env.int(
    "ARTIFACT_STDOUT_STDERR_MAX_BYTES", default=5242880
)  # 5 MB
WATCHDOG_STUCK_THRESHOLD_SECONDS = env.int(
    "WATCHDOG_STUCK_THRESHOLD_SECONDS", default=300
)
EXECUTION_LIST_CACHE_SECONDS = env.int("EXECUTION_LIST_CACHE_SECONDS", default=5)
EXECUTION_LIST_CACHE_STALE_SECONDS = env.int(
    "EXECUTION_LIST_CACHE_STALE_SECONDS", default=60
)
JWT_USER_CACHE_SECONDS = env.int("JWT_USER_CACHE_SECONDS", default=60)
PROMETHEUS_METRICS_ENABLED = env.bool("PROMETHEUS_METRICS_ENABLED", default=False)
PROMETHEUS_METRICS_TOKEN = env("PROMETHEUS_METRICS_TOKEN", default="")
DJANGO_ADMIN_ENABLED = env.bool("DJANGO_ADMIN_ENABLED", default=True)
AUTH_LOGIN_RATE_LIMIT = env("AUTH_LOGIN_RATE_LIMIT", default="5/m")
AUTH_REFRESH_RATE_LIMIT = env("AUTH_REFRESH_RATE_LIMIT", default="10/m")
WORKFLOW_CREATE_RATE_LIMIT = env("WORKFLOW_CREATE_RATE_LIMIT", default="10/m")
if ARTIFACT_STORAGE_BACKEND not in {"local", "s3"}:
    raise ImproperlyConfigured(
        "ARTIFACT_STORAGE_BACKEND must be either 'local' or 's3'."
    )
if ARTIFACT_STORAGE_BACKEND == "s3" and (
    not ARTIFACT_S3_BUCKET or not ARTIFACT_S3_REGION
):
    raise ImproperlyConfigured(
        "ARTIFACT_S3_BUCKET and ARTIFACT_S3_REGION are required when "
        "ARTIFACT_STORAGE_BACKEND=s3."
    )
AI_CONNECT_TIMEOUT_SECONDS = env.float("AI_CONNECT_TIMEOUT_SECONDS", default=1.0)
AI_READ_TIMEOUT_SECONDS = env.float("AI_READ_TIMEOUT_SECONDS", default=60.0)
AI_WRITE_TIMEOUT_SECONDS = env.float("AI_WRITE_TIMEOUT_SECONDS", default=5.0)
AI_POOL_TIMEOUT_SECONDS = env.float("AI_POOL_TIMEOUT_SECONDS", default=1.0)
AI_MAX_INPUT_CHARS = env.int("AI_MAX_INPUT_CHARS", default=100000)
