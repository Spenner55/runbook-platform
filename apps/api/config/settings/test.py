from .base import *

DEBUG = False
RUNNER_REGISTRATION_TOKEN = "test-runner-token"
RUNNER_TOKENS = [RUNNER_REGISTRATION_TOKEN]
RATELIMIT_ENABLE = False

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
