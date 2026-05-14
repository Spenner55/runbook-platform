from .base import *

DEBUG = False
RUNNER_REGISTRATION_TOKEN = "test-runner-token"
RUNNER_TOKENS = [RUNNER_REGISTRATION_TOKEN]
RUNNER_LEGACY_TOKEN_MODE = True
CHANGE_DISPATCH_TOKEN_SECRET = "test-dispatch-secret-for-tests-only-a8k3mq9x"
RATELIMIT_ENABLE = False
EXECUTION_LIST_CACHE_SECONDS = 0
EXECUTION_LIST_CACHE_STALE_SECONDS = 0
JWT_USER_CACHE_SECONDS = 0

# Use a plain logging config in tests so pytest caplog can capture records.
# The structlog ProcessorFormatter with propagate=False breaks caplog because
# records never reach the root logger where caplog's handler is installed.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
}
