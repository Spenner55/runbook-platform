"""Unit tests for the secrets package."""

from __future__ import annotations

import pytest

from runner.secrets.base import SecretUnavailableError
from runner.secrets.null_provider import NullProvider
from runner.secrets.redaction import censor_values, safe_key_list


class TestNullProvider:
    def test_no_secrets_required_returns_empty(self):
        provider = NullProvider()
        result = provider.resolve([])
        assert result == {}

    def test_single_secret_required_fails_closed(self):
        provider = NullProvider()
        with pytest.raises(SecretUnavailableError) as exc_info:
            provider.resolve(["MY_SECRET"])
        assert "MY_SECRET" in str(exc_info.value)
        assert "no credential broker" in str(exc_info.value)

    def test_multiple_secrets_required_fails_closed(self):
        provider = NullProvider()
        with pytest.raises(SecretUnavailableError) as exc_info:
            provider.resolve(["KEY_A", "KEY_B"])
        assert "KEY_A" in str(exc_info.value)
        assert "KEY_B" in str(exc_info.value)

    def test_error_message_does_not_contain_values(self):
        provider = NullProvider()
        with pytest.raises(SecretUnavailableError) as exc_info:
            provider.resolve(["SECRET_TOKEN"])
        # The error only names the key, there are no values to leak
        assert "SECRET_TOKEN" in str(exc_info.value)


class TestSecretRedaction:
    def test_censor_values_replaces_secret_keys(self):
        mapping = {"A": "value_a", "B": "value_b", "C": "value_c"}
        result = censor_values(mapping, ["A", "C"])
        assert result["A"] == "[REDACTED]"
        assert result["B"] == "value_b"
        assert result["C"] == "[REDACTED]"

    def test_censor_values_leaves_non_secret_keys(self):
        mapping = {"X": "foo", "Y": "bar"}
        result = censor_values(mapping, ["Z"])
        assert result == {"X": "foo", "Y": "bar"}

    def test_censor_values_empty_secret_keys(self):
        mapping = {"K": "v"}
        result = censor_values(mapping, [])
        assert result == {"K": "v"}

    def test_safe_key_list_sorts_output(self):
        result = safe_key_list(["C", "A", "B"])
        assert result == "A, B, C"

    def test_safe_key_list_empty(self):
        assert safe_key_list([]) == ""
