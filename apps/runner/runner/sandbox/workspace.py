"""Workspace path construction, validation, and artifact collection."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from runner.sandbox.base import (
    ArtifactSpec,
    CollectedArtifact,
    SandboxExecutionSpec,
    SandboxLimits,
    SandboxSetupError,
    SandboxValidationError,
)


@dataclass
class Workspace:
    root: Path
    work: Path
    artifacts: Path
    tmp: Path
    meta: Path


class WorkspaceManager:
    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root.resolve()

    def build_workspace_path(
        self,
        execution_id: UUID,
        step_position: int,
        step_key: str,
        step_id: UUID,
    ) -> Path:
        """Construct and validate the workspace path (does not create it)."""
        safe_key = step_key.replace(os.sep, "_").replace("..", "__")
        step_dir = f"{step_position}-{safe_key}-{step_id}"
        candidate = (self._root / str(execution_id) / step_dir).resolve()
        root_str = str(self._root)
        if not (
            str(candidate).startswith(root_str + os.sep) or str(candidate) == root_str
        ):
            raise SandboxValidationError(
                f"Workspace path {candidate} escapes configured root {self._root}"
            )
        return candidate

    def create_workspace(
        self, spec: SandboxExecutionSpec, position: int = 0
    ) -> Workspace:
        """Create workspace directories for a step."""
        root = self.build_workspace_path(
            spec.execution_id, position, spec.step_key, spec.step_id
        )
        try:
            for subdir in ("work", "artifacts", "tmp", "meta"):
                (root / subdir).mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise SandboxSetupError(
                f"Failed to create workspace {root}: {exc}"
            ) from exc
        return Workspace(
            root=root,
            work=root / "work",
            artifacts=root / "artifacts",
            tmp=root / "tmp",
            meta=root / "meta",
        )

    def resolve_workspace_path(self, workspace: Workspace, relative_path: str) -> Path:
        return validate_artifact_path(workspace.root, relative_path)

    def collect_artifacts(
        self,
        workspace: Workspace,
        artifact_specs: list[ArtifactSpec],
        limits: SandboxLimits,
    ) -> list[CollectedArtifact]:
        """Validate and collect declared artifacts from the workspace."""
        collected: list[CollectedArtifact] = []
        for spec in artifact_specs:
            try:
                abs_path = validate_artifact_path(workspace.root, spec.path)
            except SandboxValidationError:
                if spec.required:
                    raise
                continue

            if not abs_path.exists():
                if spec.required:
                    raise SandboxValidationError(
                        f"Required artifact {spec.path!r} not found"
                    )
                continue

            _reject_special_file(abs_path)

            size = abs_path.stat().st_size
            if size > limits.artifact_max_bytes:
                raise SandboxValidationError(
                    f"Artifact {spec.path!r} is {size} bytes, "
                    f"exceeds limit {limits.artifact_max_bytes}"
                )
            if len(collected) >= limits.max_artifacts:
                raise SandboxValidationError(
                    f"Artifact count exceeds limit of {limits.max_artifacts}"
                )

            data = abs_path.read_bytes()
            checksum = hashlib.sha256(data).hexdigest()
            collected.append(
                CollectedArtifact(
                    spec=spec,
                    absolute_path=abs_path,
                    size_bytes=size,
                    checksum_sha256=checksum,
                )
            )
        return collected

    def cleanup_workspace(self, workspace: Workspace) -> None:
        if workspace.root.exists():
            shutil.rmtree(workspace.root, ignore_errors=True)


def validate_artifact_path(workspace_root: Path, relative_path: str) -> Path:
    """
    Validate and resolve a relative artifact path against the workspace root.

    Raises SandboxValidationError for:
    - absolute paths
    - paths containing '..'
    - paths that resolve (following symlinks) outside the workspace root
    """
    if os.path.isabs(relative_path):
        raise SandboxValidationError(
            f"Artifact path must be relative, got absolute: {relative_path!r}"
        )
    if ".." in Path(relative_path).parts:
        raise SandboxValidationError(f"Artifact path contains '..': {relative_path!r}")

    resolved_root = workspace_root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    root_str = str(resolved_root)

    if not (str(candidate).startswith(root_str + os.sep) or str(candidate) == root_str):
        raise SandboxValidationError(
            f"Artifact path {relative_path!r} resolves outside workspace root "
            f"(possible symlink escape or traversal)"
        )

    return candidate


def _reject_special_file(path: Path) -> None:
    """Raise SandboxValidationError for device, socket, or FIFO files."""
    mode = path.stat().st_mode
    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
        raise SandboxValidationError(f"Artifact path is a device file: {path}")
    if stat.S_ISSOCK(mode):
        raise SandboxValidationError(f"Artifact path is a socket: {path}")
    if stat.S_ISFIFO(mode):
        raise SandboxValidationError(f"Artifact path is a FIFO: {path}")
