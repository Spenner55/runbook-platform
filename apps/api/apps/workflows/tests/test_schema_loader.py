"""
Tests for schema_loader and action_catalog.

Pure unit tests — no database access required.
"""


import pytest

from apps.common.exceptions import DomainValidationError
from apps.workflows import action_catalog as catalog_mod
from apps.workflows import schema_loader

# ---------------------------------------------------------------------------
# schema_loader: workflow schemas
# ---------------------------------------------------------------------------


def test_load_v1_workflow_schema_returns_dict():
    schema = schema_loader.load_workflow_schema("1")
    assert isinstance(schema, dict)
    assert "properties" in schema


def test_load_v2_workflow_schema_returns_dict():
    schema = schema_loader.load_workflow_schema("2")
    assert isinstance(schema, dict)
    assert schema.get("title") == "WorkflowDefinitionV2"


def test_load_v2_schema_requires_schema_version_field():
    schema = schema_loader.load_workflow_schema("2")
    required = schema.get("required", [])
    assert "schemaVersion" in required


def test_load_unknown_workflow_schema_version_raises():
    with pytest.raises(ValueError, match="Unknown workflow schema version"):
        schema_loader.load_workflow_schema("99")


# ---------------------------------------------------------------------------
# schema_loader: action schemas
# ---------------------------------------------------------------------------


def test_load_known_action_schema_returns_dict():
    schema = schema_loader.load_action_schema("shell_command", "pilot.v1")
    assert isinstance(schema, dict)
    assert schema.get("title") == "ShellCommandAction"


def test_load_action_schema_all_known_types():
    known_types = [
        "manual_task",
        "approval_gate",
        "shell_command",
        "http_request",
        "artifact_assertion",
    ]
    for action_type in known_types:
        schema = schema_loader.load_action_schema(action_type, "pilot.v1")
        assert isinstance(schema, dict), f"Expected dict for {action_type}"


def test_load_missing_action_schema_file_raises_loudly():
    # A nonexistent action type must fail with FileNotFoundError, never silently.
    with pytest.raises(FileNotFoundError):
        schema_loader.load_action_schema("nonexistent_action_xyz", "pilot.v1")


def test_load_corrupt_action_schema_raises_loudly(tmp_path, monkeypatch):
    # A malformed JSON file must raise json.JSONDecodeError, never silently succeed.
    import json as _json

    actions_dir = tmp_path / "actions"
    actions_dir.mkdir()
    corrupt = actions_dir / "bad_action.pilot.v1.schema.json"
    corrupt.write_text("{ not valid json }", encoding="utf-8")

    schema_loader._find_schema_dir.cache_clear()
    schema_loader.load_action_schema.cache_clear()
    monkeypatch.setattr(schema_loader, "_find_schema_dir", lambda: tmp_path)

    try:
        with pytest.raises(_json.JSONDecodeError):
            schema_loader.load_action_schema("bad_action", "pilot.v1")
    finally:
        monkeypatch.undo()  # restore lru_cache version before calling cache_clear
        schema_loader._find_schema_dir.cache_clear()
        schema_loader.load_action_schema.cache_clear()


# ---------------------------------------------------------------------------
# action_catalog: catalog loading
# ---------------------------------------------------------------------------


def test_pilot_catalog_loads():
    # Verifies the catalog file exists and parses cleanly.
    catalog = catalog_mod._load_catalog("pilot.v1")
    assert isinstance(catalog, dict)
    assert catalog.get("version") == "pilot.v1"
    assert isinstance(catalog.get("actions"), list)
    assert len(catalog["actions"]) > 0


def test_unknown_catalog_version_raises():
    with pytest.raises(ValueError, match="Unknown action catalog version"):
        catalog_mod._load_catalog("unknown.v99")


# ---------------------------------------------------------------------------
# action_catalog: lookup_action_contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_type",
    ["manual_task", "approval_gate", "shell_command", "http_request", "artifact_assertion"],
)
def test_known_action_contracts_resolve(action_type):
    contract = catalog_mod.lookup_action_contract(action_type, "pilot.v1")
    assert contract["type"] == action_type
    assert "schema" in contract
    assert "requiresRunner" in contract


def test_shell_command_requires_runner():
    contract = catalog_mod.lookup_action_contract("shell_command", "pilot.v1")
    assert contract["requiresRunner"] is True


def test_manual_task_does_not_require_runner():
    contract = catalog_mod.lookup_action_contract("manual_task", "pilot.v1")
    assert contract["requiresRunner"] is False


def test_unknown_action_type_raises_domain_validation_error():
    with pytest.raises(DomainValidationError) as exc_info:
        catalog_mod.lookup_action_contract("totally_fake_action", "pilot.v1")
    assert exc_info.value.code == "unknown_action_type"


def test_unknown_action_version_raises_domain_validation_error():
    with pytest.raises(DomainValidationError) as exc_info:
        catalog_mod.lookup_action_contract("shell_command", "unknown.v99")
    assert exc_info.value.code == "unknown_action_catalog_version"


def test_domain_error_is_stable_type():
    # Ensure both failure modes raise DomainValidationError, not a raw exception.
    with pytest.raises(DomainValidationError):
        catalog_mod.lookup_action_contract("bad_type", "pilot.v1")
    with pytest.raises(DomainValidationError):
        catalog_mod.lookup_action_contract("shell_command", "bad.version")
