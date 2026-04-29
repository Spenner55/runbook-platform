"""
Unit tests for LLMClient.

All OpenAI SDK calls are mocked — no real API calls are made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.llm_client import LLMClient


class _SimpleResponse(BaseModel):
    answer: str


def _make_client() -> LLMClient:
    return LLMClient(api_key="test-key", model="gpt-4o-mini")


def _mock_completion(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_parsed_completion(parsed_obj: BaseModel) -> MagicMock:
    choice = MagicMock()
    choice.message.parsed = parsed_obj
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


def test_complete_returns_content():
    client = _make_client()
    with patch.object(
        client._client.chat.completions,
        "create",
        return_value=_mock_completion("Hello world"),
    ):
        result = client.complete("You are helpful.", "Say hello.")
    assert result == "Hello world"


def test_complete_passes_system_and_user_messages():
    client = _make_client()
    create_mock = MagicMock(return_value=_mock_completion("ok"))
    with patch.object(client._client.chat.completions, "create", create_mock):
        client.complete("system msg", "user msg")

    call_kwargs = create_mock.call_args
    messages = (
        call_kwargs.kwargs["messages"]
        if call_kwargs.kwargs
        else call_kwargs[1]["messages"]
    )
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user"]


def test_complete_raises_on_none_content():
    client = _make_client()
    with patch.object(
        client._client.chat.completions,
        "create",
        return_value=_mock_completion(None),
    ):
        with pytest.raises(ValueError, match="empty content"):
            client.complete("sys", "usr")


# ---------------------------------------------------------------------------
# complete_structured()
# ---------------------------------------------------------------------------


def test_complete_structured_returns_parsed_model():
    client = _make_client()
    expected = _SimpleResponse(answer="42")
    with patch.object(
        client._client.beta.chat.completions,
        "parse",
        return_value=_mock_parsed_completion(expected),
    ):
        result = client.complete_structured("sys", "usr", _SimpleResponse)
    assert result == expected
    assert isinstance(result, _SimpleResponse)


def test_complete_structured_raises_on_none_parsed():
    client = _make_client()
    with patch.object(
        client._client.beta.chat.completions,
        "parse",
        return_value=_mock_parsed_completion(None),
    ):
        with pytest.raises(ValueError, match="unparseable"):
            client.complete_structured("sys", "usr", _SimpleResponse)


def test_llm_client_is_instantiable_without_real_key():
    # Constructing the client must not make any network calls.
    client = LLMClient(api_key="fake", model="gpt-4o")
    assert client._model == "gpt-4o"
