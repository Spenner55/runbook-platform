"""
AI service test configuration.

LLM tests are skipped by default. Set AI_ENABLE_LLM_TESTS=true (and
provide OPENAI_API_KEY) to opt in — doing so may incur real API costs.
"""

from __future__ import annotations

import pytest

from app.core.config import settings


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "llm" in item.keywords and not settings.AI_ENABLE_LLM_TESTS:
        pytest.skip(
            "LLM test skipped. Set AI_ENABLE_LLM_TESTS=true and OPENAI_API_KEY to run."
        )
