"""
AI service test configuration.

LLM tests are skipped by default. Set AI_ENABLE_LLM_TESTS=true (and
provide OPENAI_API_KEY) to opt in — doing so may incur real API costs.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import settings


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "llm" not in item.keywords:
        settings.AI_USE_LLM_PARSER = False
        settings.AI_ENABLE_LLM_TESTS = False
        settings.OPENAI_API_KEY = ""
        return

    llm_enabled = os.environ.get("AI_ENABLE_LLM_TESTS", "").lower() == "true"
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not llm_enabled or not api_key:
        pytest.skip(
            "LLM test skipped. Set AI_ENABLE_LLM_TESTS=true and OPENAI_API_KEY to run."
        )
    settings.AI_ENABLE_LLM_TESTS = True
    settings.OPENAI_API_KEY = api_key
