"""NullProvider: fail-closed secret provider for environments without a credential broker."""

from __future__ import annotations

from runner.secrets.base import SecretUnavailableError


class NullProvider:
    """Returns an empty mapping when no secrets are declared.

    If any secret key is requested, raises SecretUnavailableError because no
    credential broker is configured.  This is the correct fail-closed behavior:
    a step that declares secrets but has no broker must not run.
    """

    def resolve(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        raise SecretUnavailableError(
            f"Secrets required but no credential broker is configured: {sorted(keys)}"
        )
