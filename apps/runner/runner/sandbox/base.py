"""Core dataclasses, exceptions, and protocol for the SandboxProvider abstraction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SandboxError(Exception):
    """Base for all sandbox errors."""


class SandboxValidationError(SandboxError):
    """Raised when a spec or path fails pre-execution validation."""


class SandboxSetupError(SandboxError):
    """Raised when workspace or provider setup fails."""


class SandboxRuntimeError(SandboxError):
    """Raised when subprocess infrastructure itself fails (not a non-zero exit code)."""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: int
    stdout_max_bytes: int
    stderr_max_bytes: int
    artifact_max_bytes: int
    max_artifacts: int
    cpu_seconds: int | None = None
    memory_bytes: int | None = None
    file_size_bytes: int | None = None
    process_limit: int | None = None


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    path: str  # relative to workspace root
    kind: str = "file"
    mime_type: str = ""
    required: bool = False
    declaration_key: str = ""  # original declaration key, empty for ad-hoc specs


@dataclass(frozen=True)
class SandboxExecutionSpec:
    execution_id: UUID
    step_id: UUID
    step_key: str
    step_type: str
    command: list[str]
    display_command: str
    workspace_root: Path
    environment: Mapping[str, str]
    limits: SandboxLimits
    artifact_specs: list[ArtifactSpec] = field(default_factory=list)
    cancellation_check_interval_seconds: float = 1.0


@dataclass(frozen=True)
class CapturedStream:
    content: bytes
    truncated: bool
    original_size_bytes: int
    captured_size_bytes: int


@dataclass(frozen=True)
class CollectedArtifact:
    spec: ArtifactSpec
    absolute_path: Path
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True)
class SandboxResult:
    provider: str
    sandbox_run_id: str
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    failure_kind: str  # empty string means no infrastructure failure
    error_message: str
    stdout: CapturedStream
    stderr: CapturedStream
    artifacts: list[CollectedArtifact]
    metadata: dict


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SandboxProvider(Protocol):
    name: str

    def validate(self, spec: SandboxExecutionSpec) -> None:
        """Raise SandboxValidationError if the spec is invalid for this provider."""
        ...

    def execute(
        self, spec: SandboxExecutionSpec, cancellation_token: object
    ) -> SandboxResult:
        """Execute the spec and return a result. Must not raise for non-zero exit codes."""
        ...

    def cleanup(self, spec: SandboxExecutionSpec, result: SandboxResult | None) -> None:
        """Clean up resources. Must not raise — log and record failures in metadata."""
        ...
