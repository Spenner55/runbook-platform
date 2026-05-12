"""Startup validation tests for RunnerSettings.validate_for_startup()."""

from __future__ import annotations

import os

import pytest

from runner.schemas import RunnerSettings

_SANDBOX_DEFAULTS = {
    "execution_mode": "simulated",
    "sandbox_provider": "local_process",
    "sandbox_workspace_root": "/tmp/runner-workspaces",
    "sandbox_cleanup_policy": "always",
    "sandbox_default_timeout_seconds": 300,
    "sandbox_stdout_max_bytes": 5_242_880,
    "sandbox_stderr_max_bytes": 5_242_880,
    "sandbox_artifact_max_bytes": 52_428_800,
    "sandbox_max_artifacts_per_step": 10,
    "sandbox_allowed_env_prefixes": [],
    "sandbox_allowed_env_names": [],
    "sandbox_shell_path": "/bin/sh",
    "sandbox_allow_shell": False,
}


def _valid_settings(**overrides) -> RunnerSettings:
    defaults = {
        "api_base_url": "http://api:8000",
        "runner_id": "runner-test",
        "registration_token": "secret-token",
    }
    defaults.update(overrides)
    return RunnerSettings(**defaults)


def _new_settings_raw(**attrs) -> RunnerSettings:
    """Bypass Pydantic construction to test validate_for_startup() in isolation."""
    settings = RunnerSettings.__new__(RunnerSettings)
    base = {
        "runner_version": "0.1.0",
        "poll_interval_seconds": 5,
        "heartbeat_interval_seconds": 10,
        "fake_step_delay_seconds": 1.0,
        "log_level": "INFO",
        **_SANDBOX_DEFAULTS,
    }
    base.update(attrs)
    for k, v in base.items():
        object.__setattr__(settings, k, v)
    return settings


def test_validate_for_startup_passes_with_valid_settings():
    settings = _valid_settings()
    settings.validate_for_startup()  # must not raise


def test_validate_for_startup_fails_on_empty_api_base_url():
    settings = _new_settings_raw(
        api_base_url="   ", runner_id="runner-1", registration_token="secret"
    )

    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_validate_for_startup_fails_on_empty_runner_id():
    settings = _new_settings_raw(
        api_base_url="http://api:8000", runner_id="", registration_token="secret"
    )

    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_validate_for_startup_fails_on_placeholder_token():
    settings = _new_settings_raw(
        api_base_url="http://api:8000",
        runner_id="runner-1",
        registration_token="change-me",
    )

    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_validate_for_startup_from_env_with_valid_env(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    monkeypatch.setenv("RUNNER_ID", "runner-ci")
    monkeypatch.setenv("RUNNER_REGISTRATION_TOKEN", "secure-token-abc")

    settings = RunnerSettings.from_env()
    settings.validate_for_startup()  # must not raise


def test_from_env_allows_disabling_api_retries(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    monkeypatch.setenv("RUNNER_ID", "runner-ci")
    monkeypatch.setenv("RUNNER_REGISTRATION_TOKEN", "secure-token-abc")
    monkeypatch.setenv("RUNNER_API_RETRIES_ENABLED", "false")

    settings = RunnerSettings.from_env()

    assert settings.api_retries_enabled is False


# ---------------------------------------------------------------------------
# Sandbox settings — invalid execution mode
# ---------------------------------------------------------------------------


def test_invalid_execution_mode_fails_startup():
    settings = _valid_settings(execution_mode="unknown_mode")
    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_valid_execution_modes_pass_startup():
    for mode in ("simulated", "sandboxed"):
        settings = _valid_settings(execution_mode=mode)
        settings.validate_for_startup()  # must not raise


# ---------------------------------------------------------------------------
# Sandbox settings — invalid provider
# ---------------------------------------------------------------------------


def test_invalid_sandbox_provider_fails_startup():
    settings = _valid_settings(sandbox_provider="docker")
    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_known_sandbox_provider_passes_startup():
    settings = _valid_settings(sandbox_provider="local_process")
    settings.validate_for_startup()  # must not raise


# ---------------------------------------------------------------------------
# Sandbox settings — invalid cleanup policy
# ---------------------------------------------------------------------------


def test_invalid_cleanup_policy_fails_startup():
    settings = _valid_settings(sandbox_cleanup_policy="immediately")
    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("policy", ["always", "on_success", "never"])
def test_valid_cleanup_policies_pass_startup(policy):
    settings = _valid_settings(sandbox_cleanup_policy=policy)
    settings.validate_for_startup()  # must not raise


# ---------------------------------------------------------------------------
# Sandbox settings — numeric limits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,env_var",
    [
        ("sandbox_default_timeout_seconds", "RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS"),
        ("sandbox_stdout_max_bytes", "RUNNER_SANDBOX_STDOUT_MAX_BYTES"),
        ("sandbox_stderr_max_bytes", "RUNNER_SANDBOX_STDERR_MAX_BYTES"),
        ("sandbox_artifact_max_bytes", "RUNNER_SANDBOX_ARTIFACT_MAX_BYTES"),
        ("sandbox_max_artifacts_per_step", "RUNNER_SANDBOX_MAX_ARTIFACTS_PER_STEP"),
    ],
)
def test_zero_numeric_limit_fails_startup(field, env_var):
    settings = _valid_settings(**{field: 0})
    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


@pytest.mark.parametrize(
    "field",
    [
        "sandbox_default_timeout_seconds",
        "sandbox_stdout_max_bytes",
        "sandbox_stderr_max_bytes",
        "sandbox_artifact_max_bytes",
        "sandbox_max_artifacts_per_step",
    ],
)
def test_negative_numeric_limit_fails_startup(field):
    settings = _valid_settings(**{field: -1})
    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Sandbox settings — workspace root
# ---------------------------------------------------------------------------


def test_workspace_root_created_if_missing(tmp_path):
    new_dir = tmp_path / "sandbox_ws"
    assert not new_dir.exists()
    settings = _valid_settings(sandbox_workspace_root=str(new_dir))
    settings.validate_for_startup()
    assert new_dir.exists()


@pytest.mark.skipif(os.getuid() == 0, reason="root can write to read-only dirs")
def test_workspace_root_not_writable_fails_startup(tmp_path):
    workspace = tmp_path / "sandbox_ro"
    workspace.mkdir()
    workspace.chmod(0o555)
    try:
        settings = _valid_settings(sandbox_workspace_root=str(workspace))
        with pytest.raises(SystemExit) as exc_info:
            settings.validate_for_startup()
        assert exc_info.value.code == 1
    finally:
        workspace.chmod(0o755)


# ---------------------------------------------------------------------------
# Sandbox settings — shell path
# ---------------------------------------------------------------------------


def test_missing_shell_path_with_allow_shell_fails_startup():
    settings = _valid_settings(
        sandbox_allow_shell=True,
        sandbox_shell_path="/nonexistent/runner_test_shell",
    )
    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_missing_shell_path_without_allow_shell_passes_startup():
    # shell path isn't validated when allow_shell=False
    settings = _valid_settings(
        sandbox_allow_shell=False,
        sandbox_shell_path="/nonexistent/runner_test_shell",
    )
    settings.validate_for_startup()  # must not raise


# ---------------------------------------------------------------------------
# from_env — sandbox settings
# ---------------------------------------------------------------------------


def test_from_env_reads_sandbox_settings(monkeypatch, tmp_path):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    monkeypatch.setenv("RUNNER_ID", "runner-ci")
    monkeypatch.setenv("RUNNER_REGISTRATION_TOKEN", "secure-token-abc")
    monkeypatch.setenv("RUNNER_EXECUTION_MODE", "sandboxed")
    monkeypatch.setenv("RUNNER_SANDBOX_PROVIDER", "local_process")
    monkeypatch.setenv("RUNNER_SANDBOX_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("RUNNER_SANDBOX_CLEANUP_POLICY", "on_success")
    monkeypatch.setenv("RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("RUNNER_SANDBOX_STDOUT_MAX_BYTES", "1048576")
    monkeypatch.setenv("RUNNER_SANDBOX_STDERR_MAX_BYTES", "524288")
    monkeypatch.setenv("RUNNER_SANDBOX_ARTIFACT_MAX_BYTES", "10485760")
    monkeypatch.setenv("RUNNER_SANDBOX_MAX_ARTIFACTS_PER_STEP", "5")
    monkeypatch.setenv("RUNNER_SANDBOX_ALLOWED_ENV_PREFIXES", "MY_APP_, CI_")
    monkeypatch.setenv("RUNNER_SANDBOX_ALLOWED_ENV_NAMES", "HOME,USER")
    monkeypatch.setenv("RUNNER_SANDBOX_SHELL_PATH", "/bin/bash")
    monkeypatch.setenv("RUNNER_SANDBOX_ALLOW_SHELL", "true")

    settings = RunnerSettings.from_env()

    assert settings.execution_mode == "sandboxed"
    assert settings.sandbox_provider == "local_process"
    assert settings.sandbox_workspace_root == str(workspace)
    assert settings.sandbox_cleanup_policy == "on_success"
    assert settings.sandbox_default_timeout_seconds == 120
    assert settings.sandbox_stdout_max_bytes == 1_048_576
    assert settings.sandbox_stderr_max_bytes == 524_288
    assert settings.sandbox_artifact_max_bytes == 10_485_760
    assert settings.sandbox_max_artifacts_per_step == 5
    assert settings.sandbox_allowed_env_prefixes == ["MY_APP_", "CI_"]
    assert settings.sandbox_allowed_env_names == ["HOME", "USER"]
    assert settings.sandbox_shell_path == "/bin/bash"
    assert settings.sandbox_allow_shell is True


def test_from_env_defaults_to_simulated_mode(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    monkeypatch.setenv("RUNNER_ID", "runner-ci")
    monkeypatch.setenv("RUNNER_REGISTRATION_TOKEN", "secure-token-abc")

    settings = RunnerSettings.from_env()

    assert settings.execution_mode == "simulated"
    assert settings.sandbox_allow_shell is False
    assert settings.sandbox_cleanup_policy == "always"
