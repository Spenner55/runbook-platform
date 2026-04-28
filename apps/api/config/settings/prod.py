from django.core.exceptions import ImproperlyConfigured

from .base import *

DEBUG = False

if not globals().get("INTEGRATION_FERNET_KEY"):
    raise ImproperlyConfigured("INTEGRATION_FERNET_KEY is required in production.")
