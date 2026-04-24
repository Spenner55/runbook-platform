"""Tests for the deterministic StubWorkflowTransformClient."""

import pytest

from apps.workflows.internal_clients import (
    StubWorkflowTransformClient,
    WorkflowCandidate,
)


@pytest.fixture
def stub():
    return StubWorkflowTransformClient()


def _transform(stub, raw_content, *, title="My Runbook", slug="my-runbook"):
    return stub.transform_runbook(
        runbook_title=title,
        runbook_slug=slug,
        raw_content=raw_content,
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_input_produces_same_output(stub):
    content = "- Drain traffic\n- Restart service"
    r1 = _transform(stub, content)
    r2 = _transform(stub, content)
    assert r1.steps[0].step_key == r2.steps[0].step_key
    assert r1.steps[0].name == r2.steps[0].name
    assert r1.steps[1].step_key == r2.steps[1].step_key


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


def test_returns_workflow_candidate(stub):
    result = _transform(stub, "Do something")
    assert isinstance(result, WorkflowCandidate)


def test_workflow_title_matches_runbook_title(stub):
    result = _transform(stub, "Do something", title="Restart Web")
    assert result.workflow_title == "Restart Web"


def test_step_fields_are_present(stub):
    result = _transform(stub, "Drain traffic from the instance")
    step = result.steps[0]
    assert step.step_key == "step-001"
    assert step.name == "Drain traffic from the instance"
    assert step.step_type == "manual_task"
    assert step.risk_level == "medium"
    assert step.requires_approval is False


def test_step_keys_are_zero_padded(stub):
    lines = "\n".join(f"Step {i}" for i in range(1, 12))
    result = _transform(stub, lines)
    assert result.steps[0].step_key == "step-001"
    assert result.steps[9].step_key == "step-010"
    assert result.steps[10].step_key == "step-011"


# ---------------------------------------------------------------------------
# Content parsing
# ---------------------------------------------------------------------------


def test_markdown_headings_are_dropped(stub):
    content = "# Heading\n## Subheading\nDo actual work"
    result = _transform(stub, content)
    assert len(result.steps) == 1
    assert result.steps[0].name == "Do actual work"


def test_list_markers_are_stripped(stub):
    content = "- First step\n* Second step\n1. Third step\n2) Fourth step"
    result = _transform(stub, content)
    assert result.steps[0].name == "First step"
    assert result.steps[1].name == "Second step"
    assert result.steps[2].name == "Third step"
    assert result.steps[3].name == "Fourth step"


def test_blank_lines_are_ignored(stub):
    content = "Step one\n\n\nStep two\n   \nStep three"
    result = _transform(stub, content)
    assert len(result.steps) == 3


def test_run_prefix_sets_shell_command_type(stub):
    content = "run: systemctl restart web"
    result = _transform(stub, content)
    step = result.steps[0]
    assert step.step_type == "shell_command"


def test_non_run_line_sets_manual_task_type(stub):
    content = "Verify prerequisites manually"
    result = _transform(stub, content)
    assert result.steps[0].step_type == "manual_task"


def test_run_prefix_is_case_insensitive(stub):
    result = _transform(stub, "RUN: echo hello")
    assert result.steps[0].step_type == "shell_command"


def test_multiple_steps_preserve_source_order(stub):
    content = "Alpha\nBeta\nGamma"
    result = _transform(stub, content)
    assert [s.name for s in result.steps] == ["Alpha", "Beta", "Gamma"]


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


def test_blank_content_falls_back_to_title_step(stub):
    result = _transform(stub, "", title="Restart Web")
    assert len(result.steps) == 1
    assert result.steps[0].name == "Restart Web"
    assert result.steps[0].step_key == "step-001"


def test_headings_only_content_falls_back_to_title_step(stub):
    result = _transform(stub, "# Heading\n## Subheading", title="My Runbook")
    assert len(result.steps) == 1
    assert result.steps[0].name == "My Runbook"


def test_whitespace_only_content_falls_back_to_title_step(stub):
    result = _transform(stub, "   \n\t\n  ", title="Deploy DB")
    assert len(result.steps) == 1
    assert result.steps[0].name == "Deploy DB"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_repeated_lines_produce_distinct_ordered_steps(stub):
    content = "Check logs\nCheck logs\nCheck logs"
    result = _transform(stub, content)
    assert len(result.steps) == 3
    keys = [s.step_key for s in result.steps]
    assert keys == ["step-001", "step-002", "step-003"]


def test_crlf_line_endings_normalised(stub):
    content = "Step one\r\nStep two\r\nStep three"
    result = _transform(stub, content)
    assert len(result.steps) == 3


def test_single_step_workflow(stub):
    result = _transform(stub, "Only one step here")
    assert len(result.steps) == 1
