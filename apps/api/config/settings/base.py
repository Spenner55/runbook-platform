from pathlib import Path
import os
import environ

BASE_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BASE_DIR

env = environ.Env(
    DEBUG=(bool, False),
)

environ.Env.read_env(os.path.join(REPO_ROOT, '.env'))

SECRET_KEY = env('DJANGO_SECRET_KEY', default='django-insecure-change-me')
DEBUG = env('DJANGO_DEBUG', default=False)

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    # Domain apps
    'apps.common.apps.CommonConfig',
    'apps.organizations.apps.OrganizationsConfig',
    'apps.runbooks.apps.RunbooksConfig',
    'apps.workflows.apps.WorkflowsConfig',
    'apps.executions.apps.ExecutionsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': env.db(
        'DATABASE_URL',
        default='postgresql://postgres:postgres@localhost:5432/runbook_platform'
    )
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.NamespaceVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ('v1',),
    'EXCEPTION_HANDLER': 'apps.common.api_errors.custom_exception_handler',
}

# AI service settings
AI_BASE_URL = env('AI_BASE_URL', default='http://ai:8001')
AI_CONNECT_TIMEOUT_SECONDS = env.float('AI_CONNECT_TIMEOUT_SECONDS', default=1.0)
AI_READ_TIMEOUT_SECONDS = env.float('AI_READ_TIMEOUT_SECONDS', default=20.0)
AI_WRITE_TIMEOUT_SECONDS = env.float('AI_WRITE_TIMEOUT_SECONDS', default=5.0)
AI_POOL_TIMEOUT_SECONDS = env.float('AI_POOL_TIMEOUT_SECONDS', default=1.0)
