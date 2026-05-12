"""
Schema validation tests for workflow.v2.schema.json.

These are pure JSON-schema tests — no database access required.
The schema is loaded from packages/workflow-schema/workflow.v2.schema.json.
"""

import json
from pathlib import Path

import jsonschema
import pytest


def _load_v2_schema() -> dict:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "workflow-schema" / "workflow.v2.schema.json"
        if candidate.is_file():
            return json.loads(candidate.read_text())
    # Fallback for container paths
    container = Path("/packages/workflow-schema/workflow.v2.schema.json")
    if container.is_file():
        return json.loads(container.read_text())
    raise RuntimeError("Could not locate workflow.v2.schema.json")


def _load_example(filename: str) -> dict:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "workflow-schema" / "examples" / filename
        if candidate.is_file():
            return json.loads(candidate.read_text())
    raise RuntimeError(f"Could not locate example: {filename}")


@pytest.fixture(scope="module")
def v2_schema():
    return _load_v2_schema()


@pytest.fixture(scope="module")
def validator(v2_schema):
    return jsonschema.Draft7Validator(v2_schema)


# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_valid_shell_command_workflow(validator):
    doc = _load_example("valid_shell_command_v2.json")
    errors = list(validator.iter_errors(doc))
    assert errors == [], [e.message for e in errors]


def test_valid_http_request_workflow(validator):
    doc = _load_example("valid_http_request_v2.json")
    errors = list(validator.iter_errors(doc))
    assert errors == [], [e.message for e in errors]


def test_valid_mixed_workflow(validator):
    doc = _load_example("valid_mixed_v2.json")
    errors = list(validator.iter_errors(doc))
    assert errors == [], [e.message for e in errors]


def test_valid_manual_task_minimal(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Minimal Manual Workflow",
        "steps": [
            {
                "id": "s1",
                "name": "Do the thing",
                "type": "manual_task",
                "risk": "low",
                "action": {"type": "manual_task"},
            }
        ],
    }
    assert list(validator.iter_errors(doc)) == []


def test_valid_approval_gate(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Approval Gate Workflow",
        "steps": [
            {
                "id": "gate",
                "name": "Wait for approval",
                "type": "approval_gate",
                "risk": "high",
                "action": {
                    "type": "approval_gate",
                    "params": {"message": "Please confirm.", "timeout_seconds": 3600},
                },
            }
        ],
    }
    assert list(validator.iter_errors(doc)) == []


def test_valid_artifact_assertion_exists(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Artifact Check",
        "steps": [
            {
                "id": "check",
                "name": "Assert log exists",
                "type": "artifact_assertion",
                "risk": "low",
                "action": {
                    "type": "artifact_assertion",
                    "params": {"artifact_key": "build_log", "assertion": "exists"},
                },
            }
        ],
    }
    assert list(validator.iter_errors(doc)) == []


def test_valid_artifact_assertion_content_matches_with_pattern(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Artifact Content Check",
        "steps": [
            {
                "id": "check",
                "name": "Assert log contains SUCCESS",
                "type": "artifact_assertion",
                "risk": "low",
                "action": {
                    "type": "artifact_assertion",
                    "params": {
                        "artifact_key": "build_log",
                        "assertion": "content_matches",
                        "pattern": "SUCCESS",
                    },
                },
            }
        ],
    }
    assert list(validator.iter_errors(doc)) == []


# ---------------------------------------------------------------------------
# Invalid cases
# ---------------------------------------------------------------------------


def test_invalid_missing_schema_version(validator):
    doc = _load_example("invalid_missing_schema_version.json")
    errors = list(validator.iter_errors(doc))
    assert errors, "Expected validation errors for missing schemaVersion"
    messages = " ".join(e.message for e in errors)
    assert "schemaVersion" in messages


def test_invalid_missing_action(validator):
    doc = _load_example("invalid_missing_action.json")
    errors = list(validator.iter_errors(doc))
    assert errors, "Expected validation errors for missing action"
    messages = " ".join(e.message for e in errors)
    assert "action" in messages


def test_invalid_unknown_action_type(validator):
    doc = _load_example("invalid_unknown_action_type.json")
    errors = list(validator.iter_errors(doc))
    assert errors, "Expected validation errors for unknown action type"


def test_invalid_type_action_mismatch(validator):
    doc = _load_example("invalid_type_action_mismatch.json")
    errors = list(validator.iter_errors(doc))
    assert errors, "Expected validation errors for step.type / action.type mismatch"


def test_invalid_wrong_schema_version(validator):
    doc = {
        "schemaVersion": "1",
        "name": "Old version",
        "steps": [
            {
                "id": "s1",
                "name": "Step",
                "type": "manual_task",
                "risk": "low",
                "action": {"type": "manual_task"},
            }
        ],
    }
    errors = list(validator.iter_errors(doc))
    assert errors, "schemaVersion '1' should fail v2 schema"


def test_invalid_empty_steps(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Empty steps",
        "steps": [],
    }
    errors = list(validator.iter_errors(doc))
    assert errors, "Empty steps array should fail validation"


def test_invalid_shell_command_missing_command(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Bad shell step",
        "steps": [
            {
                "id": "s1",
                "name": "Run nothing",
                "type": "shell_command",
                "risk": "low",
                "action": {
                    "type": "shell_command",
                    "params": {},
                },
            }
        ],
    }
    errors = list(validator.iter_errors(doc))
    assert errors, "shell_command action missing 'command' should fail"


def test_invalid_http_request_missing_url(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Bad HTTP step",
        "steps": [
            {
                "id": "s1",
                "name": "Call nothing",
                "type": "http_request",
                "risk": "low",
                "action": {
                    "type": "http_request",
                    "params": {"method": "GET"},
                },
            }
        ],
    }
    errors = list(validator.iter_errors(doc))
    assert errors, "http_request action missing 'url' should fail"


def test_invalid_artifact_assertion_content_matches_without_pattern(validator):
    doc = {
        "schemaVersion": "2",
        "name": "Bad artifact assertion",
        "steps": [
            {
                "id": "check",
                "name": "Assert without pattern",
                "type": "artifact_assertion",
                "risk": "low",
                "action": {
                    "type": "artifact_assertion",
                    "params": {
                        "artifact_key": "build_log",
                        "assertion": "content_matches",
                    },
                },
            }
        ],
    }
    errors = list(validator.iter_errors(doc))
    assert errors, "content_matches assertion without pattern should fail"
