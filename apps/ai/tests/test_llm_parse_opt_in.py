"""
Opt-in LLM smoke test.

This test is skipped unless AI_ENABLE_LLM_TESTS=true and OPENAI_API_KEY is set.
It makes a real OpenAI API call and may incur cost.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.mark.llm
def test_llm_parse_route_smoke():
    settings.AI_USE_LLM_PARSER = True
    settings.AI_PARSE_MODEL = settings.AI_PARSE_MODEL or "gpt-4o-mini"

    client = TestClient(app)
    response = client.post(
        "/parse/runbook",
        json={
            "request_id": "llm-smoke",
            "runbook": {
                "id": "llm-smoke",
                "title": "Health Check",
                "raw_content": "1. Check service health endpoint.",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == "llm-smoke"
    assert body["steps"]
