"""Provider registry and factory for SandboxProvider instances."""

from __future__ import annotations

from runner.sandbox.base import SandboxProvider, SandboxValidationError
from runner.sandbox.local_process import LocalProcessSandboxProvider

_REGISTRY: dict[str, type] = {
    "local_process": LocalProcessSandboxProvider,
}


def get_provider(name: str) -> SandboxProvider:
    """Return a SandboxProvider instance by name."""
    cls = _REGISTRY.get(name)
    if cls is None:
        available = sorted(_REGISTRY)
        raise SandboxValidationError(
            f"Unknown sandbox provider {name!r}. Available: {available}"
        )
    return cls()  # type: ignore[return-value]
