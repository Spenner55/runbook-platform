"""Utilities to prevent accidental exposure of secret values in logs and metadata."""

from __future__ import annotations

_REDACTED = "[REDACTED]"


def censor_values(mapping: dict[str, str], secret_keys: list[str]) -> dict[str, str]:
    """Return a copy of mapping with values for secret_keys replaced by [REDACTED]."""
    key_set = set(secret_keys)
    return {k: (_REDACTED if k in key_set else v) for k, v in mapping.items()}


def safe_key_list(keys: list[str]) -> str:
    """Format a list of secret key names for safe logging (key names only, no values)."""
    return ", ".join(sorted(keys))
