import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError

FERNET_KEY_SETTING = "INTEGRATION_FERNET_KEY"


def encrypt_credentials(plaintext: dict) -> bytes:
    if not isinstance(plaintext, dict):
        raise ValidationError("Integration credentials must be a JSON object.")

    encoded = json.dumps(plaintext, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return _get_fernet().encrypt(encoded)


def decrypt_credentials(ciphertext: bytes) -> dict:
    if not ciphertext:
        return {}

    try:
        decrypted = _get_fernet().decrypt(bytes(ciphertext))
        value = json.loads(decrypted.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "Integration credentials could not be decrypted."
        ) from exc

    if not isinstance(value, dict):
        raise ValidationError("Integration credentials must decrypt to a JSON object.")
    return value


def _get_fernet() -> Fernet:
    key = getattr(settings, FERNET_KEY_SETTING, "")
    if not key:
        raise ImproperlyConfigured(
            f"{FERNET_KEY_SETTING} is required to encrypt integration credentials."
        )

    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured(
            f"{FERNET_KEY_SETTING} must be a valid Fernet key."
        ) from exc
