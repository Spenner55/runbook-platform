"""Unit tests for the deterministic workflow parser service."""

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
