"""Unit tests for SandboxProvider factory."""

import pytest

from runner.sandbox.base import SandboxValidationError
from runner.sandbox.factory import get_provider


def test_get_local_process_returns_provider():
    p = get_provider("local_process")
    assert p.name == "local_process"


def test_invalid_provider_raises_validation_error():
    with pytest.raises(SandboxValidationError, match="Unknown sandbox provider"):
        get_provider("nonexistent_provider")


def test_invalid_provider_error_lists_available():
    with pytest.raises(SandboxValidationError, match="local_process"):
        get_provider("bad_name")


def test_local_process_validate_not_implemented():
    p = get_provider("local_process")
    with pytest.raises(NotImplementedError):
        p.validate(None)


def test_local_process_execute_not_implemented():
    p = get_provider("local_process")
    with pytest.raises(NotImplementedError):
        p.execute(None, None)


def test_local_process_cleanup_not_implemented():
    p = get_provider("local_process")
    with pytest.raises(NotImplementedError):
        p.cleanup(None, None)
