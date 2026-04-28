import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.integrations.crypto import decrypt_credentials, encrypt_credentials


def test_credentials_encrypt_and_decrypt(integration_fernet_key):
    plaintext = {"url": "https://example.com/webhook", "token": "secret"}

    encrypted = encrypt_credentials(plaintext)

    assert encrypted != plaintext["url"].encode("utf-8")
    assert decrypt_credentials(encrypted) == plaintext


def test_missing_fernet_key_fails_clearly(settings):
    settings.INTEGRATION_FERNET_KEY = ""

    with pytest.raises(ImproperlyConfigured, match="INTEGRATION_FERNET_KEY"):
        encrypt_credentials({"url": "https://example.com/webhook"})


def test_encrypted_credential_value_is_not_equal_to_plaintext(integration_fernet_key):
    plaintext_url = "https://example.com/webhook"

    encrypted = encrypt_credentials({"url": plaintext_url})

    assert plaintext_url not in encrypted.decode("utf-8")
