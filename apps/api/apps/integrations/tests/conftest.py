import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def integration_fernet_key(settings):
    key = Fernet.generate_key().decode("utf-8")
    settings.INTEGRATION_FERNET_KEY = key
    return key
