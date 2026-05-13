"""Secret provider protocol and error types."""

from __future__ import annotations

from typing import Protocol


class SecretUnavailableError(Exception):
    """Raised by a SecretProvider when any requested secret cannot be resolved."""


class SecretProvider(Protocol):
    def resolve(self, keys: list[str]) -> dict[str, str]:
        """Return key→value mapping for all requested keys.

        If keys is empty, return {}.
        If any key cannot be resolved, raise SecretUnavailableError.
        Raw values must never be logged or persisted outside the execution environment.
        """
        ...
