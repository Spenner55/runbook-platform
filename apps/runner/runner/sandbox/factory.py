"""Provider registry and factory for SandboxProvider instances."""

from __future__ import annotations

from runner.sandbox.base import SandboxProvider, SandboxValidationError


class _LocalProcessStub:
    """Placeholder for LocalProcessSandboxProvider — subprocess execution is Phase A step 5+."""

    name = "local_process"

    def validate(self, spec) -> None:
        raise NotImplementedError(
            "LocalProcessSandboxProvider.validate is not yet implemented"
        )

    def execute(self, spec, cancellation_token) -> None:
        raise NotImplementedError(
            "LocalProcessSandboxProvider.execute is not yet implemented"
        )

    def cleanup(self, spec, result) -> None:
        raise NotImplementedError(
            "LocalProcessSandboxProvider.cleanup is not yet implemented"
        )


_REGISTRY: dict[str, type] = {
    "local_process": _LocalProcessStub,
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
