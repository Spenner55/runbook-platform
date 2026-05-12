"""LocalProcessSandboxProvider: run shell commands in an isolated subprocess."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from datetime import UTC, datetime
from uuid import uuid4

from runner.sandbox.base import (
    CapturedStream,
    CollectedArtifact,
    SandboxExecutionSpec,
    SandboxLimits,
    SandboxResult,
    SandboxSetupError,
    SandboxValidationError,
)
from runner.sandbox.redaction import SecretRedactor
from runner.sandbox.streams import StreamCapture
from runner.sandbox.workspace import Workspace, WorkspaceManager

try:
    import resource as _resource

    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False

logger = logging.getLogger(__name__)

_SIGTERM_GRACE_SECONDS = 5.0


def _empty_stream() -> CapturedStream:
    return CapturedStream(
        content=b"",
        truncated=False,
        original_size_bytes=0,
        captured_size_bytes=0,
    )


def _is_cancelled(token: object) -> bool:
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        return is_set()
    return False


def _drain(pipe, capture: StreamCapture) -> None:
    try:
        for chunk in iter(lambda: pipe.read(4096), b""):
            capture.write(chunk)
    except OSError:
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _kill_process_group(
    proc: subprocess.Popen, grace_seconds: float = _SIGTERM_GRACE_SECONDS
) -> None:
    """Send SIGTERM to the process group, then SIGKILL after grace_seconds."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass

    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass


def _apply_resource_limits(limits: SandboxLimits) -> None:
    if not _HAS_RESOURCE:
        return
    pairs = [
        ("cpu_seconds", _resource.RLIMIT_CPU),
        ("memory_bytes", _resource.RLIMIT_AS),
        ("file_size_bytes", _resource.RLIMIT_FSIZE),
    ]
    for attr, rlimit in pairs:
        val = getattr(limits, attr, None)
        if val is not None:
            try:
                _resource.setrlimit(rlimit, (val, val))
            except (ValueError, OSError):
                pass
    if limits.process_limit is not None:
        nproc = getattr(_resource, "RLIMIT_NPROC", None)
        if nproc is not None:
            try:
                _resource.setrlimit(nproc, (limits.process_limit, limits.process_limit))
            except (ValueError, OSError):
                pass


class LocalProcessSandboxProvider:
    name = "local_process"

    def validate(self, spec: SandboxExecutionSpec) -> None:
        """Raise SandboxValidationError if the spec is invalid for local process execution."""
        if not spec.command:
            raise SandboxValidationError("command must be non-empty")
        script = " ".join(spec.command)
        if not script.strip():
            raise SandboxValidationError("command script is blank after joining")

    def execute(
        self, spec: SandboxExecutionSpec, cancellation_token: object
    ) -> SandboxResult:
        """Execute spec in a sandboxed subprocess. Never raises for non-zero exit codes."""
        started_at = datetime.now(tz=UTC)
        sandbox_run_id = str(uuid4())

        ws_root = spec.workspace_root
        try:
            for subdir in ("work", "artifacts", "tmp", "meta"):
                (ws_root / subdir).mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError as exc:
            raise SandboxSetupError(
                f"Failed to create workspace directories under {ws_root}: {exc}"
            ) from exc

        work_dir = ws_root / "work"
        limits = spec.limits
        script = " ".join(spec.command)
        cmd = ["/bin/bash", "-c", f"set -euo pipefail\n{script}"]
        redactor = SecretRedactor([v for v in spec.environment.values() if v])

        def _preexec() -> None:
            _apply_resource_limits(limits)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(work_dir),
                env=dict(spec.environment),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                preexec_fn=_preexec,
            )
        except (OSError, ValueError) as exc:
            return SandboxResult(
                provider=self.name,
                sandbox_run_id=sandbox_run_id,
                started_at=started_at,
                finished_at=datetime.now(tz=UTC),
                exit_code=None,
                timed_out=False,
                cancelled=False,
                failure_kind="spawn_error",
                error_message=str(exc),
                stdout=_empty_stream(),
                stderr=_empty_stream(),
                artifacts=[],
                metadata={},
            )

        stdout_cap = StreamCapture(limits.stdout_max_bytes)
        stderr_cap = StreamCapture(limits.stderr_max_bytes)
        stdout_thread = threading.Thread(
            target=_drain, args=(proc.stdout, stdout_cap), daemon=True
        )
        stderr_thread = threading.Thread(
            target=_drain, args=(proc.stderr, stderr_cap), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()

        deadline = time.monotonic() + limits.timeout_seconds
        timed_out = False
        cancelled = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break

            wait_interval = min(spec.cancellation_check_interval_seconds, remaining)
            try:
                proc.wait(timeout=wait_interval)
                break
            except subprocess.TimeoutExpired:
                pass

            if _is_cancelled(cancellation_token):
                cancelled = True
                break

        if timed_out or cancelled:
            _kill_process_group(proc)
        elif proc.returncode is None:
            # Ensure returncode is set if we somehow exited the loop early
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

        stdout_thread.join(timeout=10.0)
        stderr_thread.join(timeout=10.0)

        raw_stdout = stdout_cap.to_captured_stream()
        raw_stderr = stderr_cap.to_captured_stream()

        final_stdout = CapturedStream(
            content=redactor.redact(raw_stdout.content),
            truncated=raw_stdout.truncated,
            original_size_bytes=raw_stdout.original_size_bytes,
            captured_size_bytes=raw_stdout.captured_size_bytes,
        )
        final_stderr = CapturedStream(
            content=redactor.redact(raw_stderr.content),
            truncated=raw_stderr.truncated,
            original_size_bytes=raw_stderr.original_size_bytes,
            captured_size_bytes=raw_stderr.captured_size_bytes,
        )

        finished_at = datetime.now(tz=UTC)
        exit_code = proc.returncode

        artifacts: list[CollectedArtifact] = []
        failure_kind = ""
        error_message = ""

        if not timed_out and not cancelled and spec.artifact_specs:
            workspace = Workspace(
                root=ws_root,
                work=work_dir,
                artifacts=ws_root / "artifacts",
                tmp=ws_root / "tmp",
                meta=ws_root / "meta",
            )
            mgr = WorkspaceManager(ws_root)
            try:
                artifacts = mgr.collect_artifacts(
                    workspace, spec.artifact_specs, limits
                )
            except SandboxValidationError as exc:
                failure_kind = "artifact_error"
                error_message = str(exc)

        return SandboxResult(
            provider=self.name,
            sandbox_run_id=sandbox_run_id,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            timed_out=timed_out,
            cancelled=cancelled,
            failure_kind=failure_kind,
            error_message=error_message,
            stdout=final_stdout,
            stderr=final_stderr,
            artifacts=artifacts,
            metadata={},
        )

    def cleanup(self, spec: SandboxExecutionSpec, result: SandboxResult | None) -> None:
        """Remove the workspace directory. Never raises."""
        try:
            if spec.workspace_root.exists():
                shutil.rmtree(spec.workspace_root, ignore_errors=True)
        except Exception as exc:
            logger.warning(
                "cleanup failed for workspace %s: %s", spec.workspace_root, exc
            )
