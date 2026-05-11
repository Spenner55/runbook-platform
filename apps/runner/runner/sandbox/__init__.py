"""SandboxProvider abstraction for the runner execution substrate."""

from runner.sandbox.base import (
    ArtifactSpec,
    CapturedStream,
    CollectedArtifact,
    SandboxError,
    SandboxExecutionSpec,
    SandboxLimits,
    SandboxProvider,
    SandboxResult,
    SandboxRuntimeError,
    SandboxSetupError,
    SandboxValidationError,
)
from runner.sandbox.factory import get_provider

__all__ = [
    "ArtifactSpec",
    "CapturedStream",
    "CollectedArtifact",
    "SandboxError",
    "SandboxExecutionSpec",
    "SandboxLimits",
    "SandboxProvider",
    "SandboxResult",
    "SandboxRuntimeError",
    "SandboxSetupError",
    "SandboxValidationError",
    "get_provider",
]
