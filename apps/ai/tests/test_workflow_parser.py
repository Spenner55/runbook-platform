"""Unit tests for the deterministic workflow parser service."""

from types import SimpleNamespace

from app.core.config import settings
from app.schemas.workflow_parse import ParseRunbookRequest, RunbookInput
from app.services.workflow_parser import parse_runbook_to_candidate


def _make_request(raw_content: str, title: str = "Test Runbook") -> ParseRunbookRequest:
    return ParseRunbookRequest(
        request_id="req-test",
        runbook=RunbookInput(id="test-rb", title=title, raw_content=raw_content),
    )


def test_numbered_steps_are_extracted():
    req = _make_request("1. First step\n2. Second step\n3. Third step")
    resp = parse_runbook_to_candidate(req)
    assert len(resp.steps) == 3


def test_step_names_are_extracted():
    req = _make_request("1. Verify prerequisites\n2. Run migration")
    resp = parse_runbook_to_candidate(req)
    assert resp.steps[0].name == "Verify prerequisites"
    assert resp.steps[1].name == "Run migration"


def test_step_keys_are_sequential():
    req = _make_request("1. Step A\n2. Step B")
    resp = parse_runbook_to_candidate(req)
    assert resp.steps[0].step_key == "step-1"
    assert resp.steps[1].step_key == "step-2"


def test_workflow_title_from_runbook_title():
    req = _make_request("1. Do something", title="My Workflow")
    resp = parse_runbook_to_candidate(req)
    assert resp.workflow_title == "My Workflow"


def test_request_id_echoed():
    req = _make_request("1. Step")
    resp = parse_runbook_to_candidate(req)
    assert resp.request_id == "req-test"


def test_empty_content_produces_fallback_steps():
    req = _make_request("")
    resp = parse_runbook_to_candidate(req)
    assert len(resp.steps) > 0


def test_empty_content_includes_warning():
    req = _make_request("")
    resp = parse_runbook_to_candidate(req)
    assert len(resp.warnings) > 0


def test_default_risk_level_is_medium():
    req = _make_request("1. Check logs")
    resp = parse_runbook_to_candidate(req)
    assert resp.steps[0].risk_level == "medium"


def test_default_requires_approval_is_false():
    req = _make_request("1. Check logs")
    resp = parse_runbook_to_candidate(req)
    assert resp.steps[0].requires_approval is False


def test_same_input_same_output():
    req = _make_request("1. Alpha\n2. Beta")
    r1 = parse_runbook_to_candidate(req)
    r2 = parse_runbook_to_candidate(req)
    assert [(s.step_key, s.name) for s in r1.steps] == [
        (s.step_key, s.name) for s in r2.steps
    ]


def test_llm_empty_steps_falls_back_to_deterministic_extraction(monkeypatch):
    class FakeLLMClient:
        def __init__(self, **_kwargs):
            pass

        def complete_structured(self, *_args):
            return SimpleNamespace(
                workflow_title="LLM Title",
                steps=[],
                warnings=["empty model output"],
            )

    monkeypatch.setattr("app.services.llm_client.LLMClient", FakeLLMClient)
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "test-key"

    req = _make_request("1. Verify health\n2. Restart service")
    resp = parse_runbook_to_candidate(req)

    assert resp.workflow_title == "LLM Title"
    assert [step.name for step in resp.steps] == ["Verify health", "Restart service"]
    assert "empty model output" in resp.warnings
    assert (
        "LLM parser returned no steps; using deterministic step extraction."
        in resp.warnings
    )


def test_llm_empty_steps_falls_back_to_default_steps(monkeypatch):
    class FakeLLMClient:
        def __init__(self, **_kwargs):
            pass

        def complete_structured(self, *_args):
            return SimpleNamespace(workflow_title="", steps=[], warnings=[])

    monkeypatch.setattr("app.services.llm_client.LLMClient", FakeLLMClient)
    settings.AI_USE_LLM_PARSER = True
    settings.OPENAI_API_KEY = "test-key"

    req = _make_request("", title="Unstructured Runbook")
    resp = parse_runbook_to_candidate(req)

    assert resp.workflow_title == "Unstructured Runbook"
    assert len(resp.steps) == 2
    assert resp.steps[0].name == "Verify prerequisites"
    assert (
        "LLM parser returned no steps; using deterministic step extraction."
        in resp.warnings
    )
    assert (
        "No numbered steps detected in content; using default step structure."
        in resp.warnings
    )
