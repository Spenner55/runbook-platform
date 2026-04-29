"""
Thin wrapper around the OpenAI SDK.

Enforces timeout, surfaces structured output via Pydantic models,
and is designed to be easily replaced with a mock in tests.
"""

from __future__ import annotations

from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_TOKENS = 4096


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = _DEFAULT_TIMEOUT,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = OpenAI(api_key=api_key, timeout=timeout)
        self._model = model
        self._timeout = timeout
        self._max_tokens = max_tokens

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=self._max_tokens,
        )
        content = response.choices[0].message.content
        if content is None:
            raise ValueError("LLM returned empty content")
        return content

    def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
    ) -> T:
        response = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=response_model,
            max_completion_tokens=self._max_tokens,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned unparseable structured output")
        return parsed
