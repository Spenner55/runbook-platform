import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR

env = environ.Env(
    DEBUG=(bool, False),
)

environ.Env.read_env(os.path.join(REPO_ROOT, ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-change-me")
DEBUG = env("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    # Domain apps
    "apps.common.apps.CommonConfig",
    "apps.organizations.apps.OrganizationsConfig",
    "apps.runbooks.apps.RunbooksConfig",
    "apps.workflows.apps.WorkflowsConfig",
    "apps.executions.apps.ExecutionsConfig",
    "apps.approvals.apps.ApprovalsConfig",
    "apps.policies.apps.PoliciesConfig",
    "apps.audit.apps.AuditConfig",
    "apps.artifacts.apps.ArtifactsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ("v1",),
    "EXCEPTION_HANDLER": "apps.common.api_errors.custom_exception_handler",
}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
]

# AI service settings
AI_BASE_URL = env("AI_BASE_URL", default="http://ai:8001")

# Artifact storage settings
ARTIFACT_MEDIA_ROOT = env("ARTIFACT_MEDIA_ROOT", default=str(BASE_DIR / "media" / "artifacts"))
ARTIFACT_MAX_UPLOAD_BYTES = env.int("ARTIFACT_MAX_UPLOAD_BYTES", default=52428800)  # 50 MB
ARTIFACT_MAX_ARTIFACTS_PER_STEP = env.int("ARTIFACT_MAX_ARTIFACTS_PER_STEP", default=10)
ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION = env.int(
    "ARTIFACT_MAX_TOTAL_BYTES_PER_EXECUTION", default=262144000
)  # 250 MB
ARTIFACT_DAILY_BYTES_PER_RUNNER = env.int(
    "ARTIFACT_DAILY_BYTES_PER_RUNNER", default=1073741824
)  # 1 GB
ARTIFACT_DOWNLOAD_URL_TTL_SECONDS = env.int("ARTIFACT_DOWNLOAD_URL_TTL_SECONDS", default=300)
ARTIFACT_STDOUT_STDERR_MAX_BYTES = env.int(
    "ARTIFACT_STDOUT_STDERR_MAX_BYTES", default=5242880
)  # 5 MB
AI_CONNECT_TIMEOUT_SECONDS = env.float("AI_CONNECT_TIMEOUT_SECONDS", default=1.0)
AI_READ_TIMEOUT_SECONDS = env.float("AI_READ_TIMEOUT_SECONDS", default=20.0)
AI_WRITE_TIMEOUT_SECONDS = env.float("AI_WRITE_TIMEOUT_SECONDS", default=5.0)
AI_POOL_TIMEOUT_SECONDS = env.float("AI_POOL_TIMEOUT_SECONDS", default=1.0)
