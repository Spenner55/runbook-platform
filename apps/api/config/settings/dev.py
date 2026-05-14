from .base import *

DEBUG = True
RATELIMIT_ENABLE = False
RUNNER_LEGACY_TOKEN_MODE = env.bool("RUNNER_LEGACY_TOKEN_MODE", default=True)  # noqa: F405
