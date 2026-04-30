"""Startup validation tests for RunnerSettings.validate_for_startup()."""

from __future__ import annotations

import pytest

from runner.schemas import RunnerSettings


def _valid_settings(**overrides) -> RunnerSettings:
    defaults = {
        "api_base_url": "http://api:8000",
        "runner_id": "runner-test",
        "registration_token": "secret-token",
    }
    defaults.update(overrides)
    return RunnerSettings(**defaults)


def test_validate_for_startup_passes_with_valid_settings():
    settings = _valid_settings()
    settings.validate_for_startup()  # must not raise


def test_validate_for_startup_fails_on_empty_api_base_url():
    settings = RunnerSettings.__new__(RunnerSettings)
    object.__setattr__(settings, "api_base_url", "   ")
    object.__setattr__(settings, "runner_id", "runner-1")
    object.__setattr__(settings, "registration_token", "secret")
    object.__setattr__(settings, "runner_version", "0.1.0")
    object.__setattr__(settings, "poll_interval_seconds", 5)
    object.__setattr__(settings, "heartbeat_interval_seconds", 10)
    object.__setattr__(settings, "fake_step_delay_seconds", 1.0)
    object.__setattr__(settings, "log_level", "INFO")

    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_validate_for_startup_fails_on_empty_runner_id():
    settings = RunnerSettings.__new__(RunnerSettings)
    object.__setattr__(settings, "api_base_url", "http://api:8000")
    object.__setattr__(settings, "runner_id", "")
    object.__setattr__(settings, "registration_token", "secret")
    object.__setattr__(settings, "runner_version", "0.1.0")
    object.__setattr__(settings, "poll_interval_seconds", 5)
    object.__setattr__(settings, "heartbeat_interval_seconds", 10)
    object.__setattr__(settings, "fake_step_delay_seconds", 1.0)
    object.__setattr__(settings, "log_level", "INFO")

    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_validate_for_startup_fails_on_placeholder_token():
    settings = RunnerSettings.__new__(RunnerSettings)
    object.__setattr__(settings, "api_base_url", "http://api:8000")
    object.__setattr__(settings, "runner_id", "runner-1")
    object.__setattr__(settings, "registration_token", "change-me")
    object.__setattr__(settings, "runner_version", "0.1.0")
    object.__setattr__(settings, "poll_interval_seconds", 5)
    object.__setattr__(settings, "heartbeat_interval_seconds", 10)
    object.__setattr__(settings, "fake_step_delay_seconds", 1.0)
    object.__setattr__(settings, "log_level", "INFO")

    with pytest.raises(SystemExit) as exc_info:
        settings.validate_for_startup()
    assert exc_info.value.code == 1


def test_validate_for_startup_from_env_with_valid_env(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000")
    monkeypatch.setenv("RUNNER_ID", "runner-ci")
    monkeypatch.setenv("RUNNER_REGISTRATION_TOKEN", "secure-token-abc")

    settings = RunnerSettings.from_env()
    settings.validate_for_startup()  # must not raise
