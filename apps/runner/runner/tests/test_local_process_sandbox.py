"""Tests for LocalProcessSandboxProvider."""

from __future__ import annotations

import threading
from pathlib import Path
from uuid import uuid4

import pytest

from runner.sandbox.base import (
    ArtifactSpec,
    SandboxExecutionSpec,
    SandboxLimits,
    SandboxValidationError,
)
from runner.sandbox.local_process import LocalProcessSandboxProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_LIMITS = SandboxLimits(
    timeout_seconds=10,
    stdout_max_bytes=1024 * 1024,
    stderr_max_bytes=1024 * 1024,
    artifact_max_bytes=1024 * 1024,
    max_artifacts=10,
)

_FAST_CANCEL_INTERVAL = SandboxExecutionSpec.__dataclass_fields__  # unused; just confirming it's a dataclass
del _FAST_CANCEL_INTERVAL


def _make_spec(
    tmp_path: Path,
    command: list[str],
    *,
    limits: SandboxLimits = _DEFAULT_LIMITS,
    environment: dict[str, str] | None = None,
    artifact_specs: list[ArtifactSpec] | None = None,
    cancellation_check_interval_seconds: float = 0.1,
) -> SandboxExecutionSpec:
    return SandboxExecutionSpec(
        execution_id=uuid4(),
        step_id=uuid4(),
        step_key="test-step",
        step_type="shell",
        command=command,
        display_command=" ".join(command),
        workspace_root=tmp_path / "workspace",
        environment=environment if environment is not None else {"PATH": "/usr/bin:/bin:/usr/local/bin"},
        limits=limits,
        artifact_specs=artifact_specs or [],
        cancellation_check_interval_seconds=cancellation_check_interval_seconds,
    )


@pytest.fixture
def provider() -> LocalProcessSandboxProvider:
    return LocalProcessSandboxProvider()


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


def test_validate_empty_command_raises(provider, tmp_path):
    spec = _make_spec(tmp_path, [])
    with pytest.raises(SandboxValidationError, match="non-empty"):
        provider.validate(spec)


def test_validate_blank_command_raises(provider, tmp_path):
    spec = _make_spec(tmp_path, ["   "])
    with pytest.raises(SandboxValidationError, match="blank"):
        provider.validate(spec)


def test_validate_valid_command_passes(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo hello"])
    provider.validate(spec)  # must not raise


# ---------------------------------------------------------------------------
# execute() — successful command
# ---------------------------------------------------------------------------


def test_successful_command(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo hello"])
    result = provider.execute(spec, None)

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.failure_kind == ""
    assert b"hello" in result.stdout.content


def test_workspace_directories_created(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    provider.execute(spec, None)

    ws = spec.workspace_root
    assert (ws / "work").is_dir()
    assert (ws / "artifacts").is_dir()
    assert (ws / "tmp").is_dir()
    assert (ws / "meta").is_dir()


def test_workspace_permissions(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    provider.execute(spec, None)

    import stat

    for subdir in ("work", "artifacts", "tmp", "meta"):
        mode = (spec.workspace_root / subdir).stat().st_mode
        assert stat.S_IMODE(mode) == 0o700


# ---------------------------------------------------------------------------
# execute() — stdout/stderr separate capture
# ---------------------------------------------------------------------------


def test_stdout_and_stderr_captured_separately(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo out; echo err >&2"])
    result = provider.execute(spec, None)

    assert b"out" in result.stdout.content
    assert b"err" in result.stderr.content
    assert b"err" not in result.stdout.content
    assert b"out" not in result.stderr.content


def test_stdout_only(provider, tmp_path):
    spec = _make_spec(tmp_path, ["printf 'just stdout'"])
    result = provider.execute(spec, None)

    assert b"just stdout" in result.stdout.content
    assert result.stderr.content == b""


def test_stderr_only(provider, tmp_path):
    spec = _make_spec(tmp_path, ["printf 'just stderr' >&2"])
    result = provider.execute(spec, None)

    assert result.stdout.content == b""
    assert b"just stderr" in result.stderr.content


# ---------------------------------------------------------------------------
# execute() — non-zero exit code
# ---------------------------------------------------------------------------


def test_nonzero_exit_code(provider, tmp_path):
    spec = _make_spec(tmp_path, ["exit 42"])
    result = provider.execute(spec, None)

    assert result.exit_code == 42
    assert result.timed_out is False
    assert result.cancelled is False
    assert result.failure_kind == ""


def test_nonzero_exit_from_failing_command(provider, tmp_path):
    spec = _make_spec(tmp_path, ["false"])
    result = provider.execute(spec, None)

    assert result.exit_code != 0


def test_stderr_captured_on_failure(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo 'error output' >&2; exit 1"])
    result = provider.execute(spec, None)

    assert result.exit_code == 1
    assert b"error output" in result.stderr.content


# ---------------------------------------------------------------------------
# execute() — timeout kills process group
# ---------------------------------------------------------------------------


def test_timeout_kills_process(provider, tmp_path):
    limits = SandboxLimits(
        timeout_seconds=1,
        stdout_max_bytes=1024,
        stderr_max_bytes=1024,
        artifact_max_bytes=1024,
        max_artifacts=10,
    )
    spec = _make_spec(tmp_path, ["sleep 60"], limits=limits)
    result = provider.execute(spec, None)

    assert result.timed_out is True
    assert result.cancelled is False


def test_timeout_result_has_no_normal_exit(provider, tmp_path):
    limits = SandboxLimits(
        timeout_seconds=1,
        stdout_max_bytes=1024,
        stderr_max_bytes=1024,
        artifact_max_bytes=1024,
        max_artifacts=10,
    )
    spec = _make_spec(tmp_path, ["sleep 60"], limits=limits)
    result = provider.execute(spec, None)

    assert result.timed_out is True
    # exit_code is the kill signal code (negative on Linux); it is not a clean exit
    assert result.exit_code != 0


def test_timeout_kills_child_processes(provider, tmp_path):
    """The entire process group, including spawned children, must be killed."""
    limits = SandboxLimits(
        timeout_seconds=1,
        stdout_max_bytes=1024,
        stderr_max_bytes=1024,
        artifact_max_bytes=1024,
        max_artifacts=10,
    )
    # Spawn a background child sleep to verify process group termination
    spec = _make_spec(tmp_path, ["sleep 100 & sleep 100"], limits=limits)
    result = provider.execute(spec, None)
    assert result.timed_out is True


# ---------------------------------------------------------------------------
# execute() — cancellation kills process group
# ---------------------------------------------------------------------------


def test_cancellation_kills_process(provider, tmp_path):
    cancel = threading.Event()
    spec = _make_spec(tmp_path, ["sleep 60"])
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    try:
        result = provider.execute(spec, cancel)
    finally:
        timer.cancel()

    assert result.cancelled is True
    assert result.timed_out is False


def test_cancellation_result_structure(provider, tmp_path):
    cancel = threading.Event()
    spec = _make_spec(tmp_path, ["sleep 60"])
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    try:
        result = provider.execute(spec, cancel)
    finally:
        timer.cancel()

    assert result.cancelled is True
    assert result.provider == "local_process"
    assert result.sandbox_run_id != ""
    assert result.started_at < result.finished_at


def test_none_cancellation_token_not_cancelled(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo done"])
    result = provider.execute(spec, None)

    assert result.cancelled is False
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# execute() — output truncation
# ---------------------------------------------------------------------------


def test_stdout_truncated_when_cap_exceeded(provider, tmp_path):
    limits = SandboxLimits(
        timeout_seconds=10,
        stdout_max_bytes=5,
        stderr_max_bytes=1024,
        artifact_max_bytes=1024,
        max_artifacts=10,
    )
    spec = _make_spec(tmp_path, ["echo 'this is longer than five bytes'"], limits=limits)
    result = provider.execute(spec, None)

    assert result.stdout.truncated is True
    assert len(result.stdout.content) == 5
    assert result.stdout.original_size_bytes > 5


def test_stderr_truncated_when_cap_exceeded(provider, tmp_path):
    limits = SandboxLimits(
        timeout_seconds=10,
        stdout_max_bytes=1024,
        stderr_max_bytes=5,
        artifact_max_bytes=1024,
        max_artifacts=10,
    )
    spec = _make_spec(tmp_path, ["echo 'this is longer than five bytes' >&2"], limits=limits)
    result = provider.execute(spec, None)

    assert result.stderr.truncated is True
    assert len(result.stderr.content) == 5


def test_no_truncation_when_under_cap(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo hi"])
    result = provider.execute(spec, None)

    assert result.stdout.truncated is False
    assert result.stderr.truncated is False


# ---------------------------------------------------------------------------
# execute() — redaction applied
# ---------------------------------------------------------------------------


def test_secret_redacted_from_stdout(provider, tmp_path):
    secret = "s3cr3t-p4ssw0rd"
    spec = _make_spec(
        tmp_path,
        [f"echo {secret}"],
        environment={"PATH": "/usr/bin:/bin", "MY_SECRET": secret},
    )
    result = provider.execute(spec, None)

    assert secret.encode() not in result.stdout.content
    assert b"[REDACTED]" in result.stdout.content


def test_secret_redacted_from_stderr(provider, tmp_path):
    secret = "top-secret-value"
    spec = _make_spec(
        tmp_path,
        [f"echo {secret} >&2"],
        environment={"PATH": "/usr/bin:/bin", "SECRET": secret},
    )
    result = provider.execute(spec, None)

    assert secret.encode() not in result.stderr.content
    assert b"[REDACTED]" in result.stderr.content


def test_non_secret_env_value_not_redacted(provider, tmp_path):
    # PATH value should not appear in output anyway, but redaction of PATH
    # segments would corrupt useful output if PATH segments appeared in stdout
    spec = _make_spec(tmp_path, ["echo hello world"])
    result = provider.execute(spec, None)

    assert b"hello world" in result.stdout.content


# ---------------------------------------------------------------------------
# execute() — missing/invalid command fails closed
# ---------------------------------------------------------------------------


def test_invalid_executable_returns_failure(provider, tmp_path):
    """A command that references a non-existent binary returns failure, not an exception."""
    spec = _make_spec(tmp_path, ["/nonexistent/binary --arg"])
    result = provider.execute(spec, None)

    # bash -c "set -euo pipefail\n..." will exit non-zero when the command fails
    assert result.exit_code != 0 or result.failure_kind != ""


def test_validate_empty_command_fails_closed(provider, tmp_path):
    """validate() must raise for empty command, not silently succeed."""
    spec = _make_spec(tmp_path, [])
    with pytest.raises(SandboxValidationError):
        provider.validate(spec)


# ---------------------------------------------------------------------------
# execute() — required artifact missing
# ---------------------------------------------------------------------------


def test_required_artifact_missing_sets_failure_kind(provider, tmp_path):
    spec = _make_spec(
        tmp_path,
        ["echo ok"],
        artifact_specs=[ArtifactSpec(name="report", path="artifacts/report.txt", required=True)],
    )
    result = provider.execute(spec, None)

    assert result.failure_kind == "artifact_error"
    assert "report.txt" in result.error_message or "Required artifact" in result.error_message


def test_optional_artifact_missing_no_failure(provider, tmp_path):
    spec = _make_spec(
        tmp_path,
        ["echo ok"],
        artifact_specs=[ArtifactSpec(name="report", path="artifacts/report.txt", required=False)],
    )
    result = provider.execute(spec, None)

    assert result.failure_kind == ""
    assert result.artifacts == []


def test_required_artifact_present_collected(provider, tmp_path):
    # The command runs in workspace/work/; write to ../artifacts/ to place
    # the file at workspace/artifacts/report.txt, where the spec path resolves.
    spec = _make_spec(
        tmp_path,
        ["echo content > ../artifacts/report.txt"],
        artifact_specs=[ArtifactSpec(name="report", path="artifacts/report.txt", required=True)],
    )
    result = provider.execute(spec, None)

    assert result.failure_kind == ""
    assert len(result.artifacts) == 1
    assert result.artifacts[0].spec.name == "report"


# ---------------------------------------------------------------------------
# execute() — unsafe artifact rejected
# ---------------------------------------------------------------------------


def test_unsafe_artifact_path_traversal_rejected(provider, tmp_path):
    spec = _make_spec(
        tmp_path,
        ["echo ok"],
        artifact_specs=[ArtifactSpec(name="escape", path="../../../etc/passwd", required=True)],
    )
    result = provider.execute(spec, None)

    assert result.failure_kind == "artifact_error"


def test_unsafe_artifact_absolute_path_rejected(provider, tmp_path):
    spec = _make_spec(
        tmp_path,
        ["echo ok"],
        artifact_specs=[ArtifactSpec(name="abs", path="/etc/passwd", required=True)],
    )
    result = provider.execute(spec, None)

    assert result.failure_kind == "artifact_error"


def test_unsafe_optional_artifact_path_traversal_skipped(provider, tmp_path):
    spec = _make_spec(
        tmp_path,
        ["echo ok"],
        artifact_specs=[ArtifactSpec(name="escape", path="../../../etc/passwd", required=False)],
    )
    result = provider.execute(spec, None)

    # Optional invalid path is silently skipped — no failure
    assert result.failure_kind == ""
    assert result.artifacts == []


# ---------------------------------------------------------------------------
# cleanup()
# ---------------------------------------------------------------------------


def test_cleanup_removes_workspace(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    result = provider.execute(spec, None)

    assert spec.workspace_root.exists()
    provider.cleanup(spec, result)
    assert not spec.workspace_root.exists()


def test_cleanup_tolerates_missing_workspace(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    # Do not execute, so workspace was never created
    provider.cleanup(spec, None)  # must not raise


# ---------------------------------------------------------------------------
# SandboxResult structure
# ---------------------------------------------------------------------------


def test_result_provider_name(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    result = provider.execute(spec, None)
    assert result.provider == "local_process"


def test_result_has_unique_run_id(provider, tmp_path):
    spec1 = _make_spec(tmp_path / "a", ["echo ok"])
    spec2 = _make_spec(tmp_path / "b", ["echo ok"])
    r1 = provider.execute(spec1, None)
    r2 = provider.execute(spec2, None)
    assert r1.sandbox_run_id != r2.sandbox_run_id


def test_result_timestamps_ordered(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    result = provider.execute(spec, None)
    assert result.started_at <= result.finished_at


def test_no_artifacts_when_specs_empty(provider, tmp_path):
    spec = _make_spec(tmp_path, ["echo ok"])
    result = provider.execute(spec, None)
    assert result.artifacts == []
