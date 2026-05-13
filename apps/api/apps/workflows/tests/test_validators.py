"""
Tests for apps/api/apps/workflows/validators.py

Covers all acceptance-criteria validation failures from the Pilot Phase B blueprint:
  - Unknown schema version fails closed
  - v1 path unchanged
  - v2 JSON schema violations
  - v2 semantic violations:
      duplicate step IDs, action type mismatch, unknown catalog version,
      unknown action type, unknown secret refs, duplicate secret keys,
      secret requiredBy unknown step, duplicate artifact keys,
      unsafe artifact paths (absolute, traversal, empty, tilde/double-slash),
      retry without idempotency, keyed idempotency without key,
      raw secrets in shell_command environment,
      raw secrets in http_request headers,
      absolute / traversal working_directory for shell_command,
      non-absolute URL for http_request,
      invalid dry-run strategy.
"""

import pytest

from apps.common.exceptions import InvalidWorkflowDefinitionError
from apps.workflows.tests.fixtures.workflow_v2 import invalid_secret_ref_workflow
from apps.workflows.validators import validate_workflow_definition

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _minimal_v2(*, steps=None, **overrides) -> dict:
    """Return a minimal valid v2 workflow definition."""
    doc = {
        "schemaVersion": "2",
        "name": "Test Workflow",
        "steps": steps
        or [
            {
                "id": "s1",
                "name": "Do something",
                "type": "manual_task",
                "risk": "low",
                "action": {"type": "manual_task"},
            }
        ],
    }
    doc.update(overrides)
    return doc


def _shell_step(step_id="run", **overrides) -> dict:
    step = {
        "id": step_id,
        "name": "Run command",
        "type": "shell_command",
        "risk": "low",
        "action": {
            "type": "shell_command",
            "params": {"command": "echo hello"},
        },
    }
    step.update(overrides)
    return step


def _http_step(step_id="call", **overrides) -> dict:
    step = {
        "id": step_id,
        "name": "HTTP call",
        "type": "http_request",
        "risk": "low",
        "action": {
            "type": "http_request",
            "params": {"method": "GET", "url": "https://example.com/api"},
        },
    }
    step.update(overrides)
    return step


def _validate_v2(definition: dict) -> None:
    validate_workflow_definition(definition, "workflow.schema.v2")


def _validate_v1(definition: dict) -> None:
    validate_workflow_definition(definition, "workflow.schema.v1")


# ---------------------------------------------------------------------------
# Unknown schema version
# ---------------------------------------------------------------------------


def test_unknown_schema_version_fails_closed():
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        validate_workflow_definition({}, "workflow.schema.v99")
    assert exc_info.value.code == "unsupported_schema_version"


def test_garbage_schema_version_fails_closed():
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        validate_workflow_definition({}, "completely_wrong")
    assert exc_info.value.code == "unsupported_schema_version"


# ---------------------------------------------------------------------------
# v1 path unchanged
# ---------------------------------------------------------------------------


def test_v1_valid_definition_passes():
    definition = {
        "name": "Simple",
        "steps": [
            {
                "id": "s1",
                "name": "Manual step",
                "type": "manual_task",
                "risk": "low",
                "requiresApproval": False,
            }
        ],
    }
    _validate_v1(definition)  # must not raise


def test_v1_missing_steps_raises():
    with pytest.raises(InvalidWorkflowDefinitionError):
        _validate_v1({"name": "Bad"})


def test_v1_unknown_step_type_raises():
    definition = {
        "name": "Bad",
        "steps": [
            {
                "id": "s1",
                "name": "Step",
                "type": "kubernetes_rollout",
                "risk": "low",
            }
        ],
    }
    with pytest.raises(InvalidWorkflowDefinitionError):
        _validate_v1(definition)


# ---------------------------------------------------------------------------
# v2 JSON schema violations
# ---------------------------------------------------------------------------


def test_v2_valid_minimal_workflow_passes():
    _validate_v2(_minimal_v2())


def test_v2_valid_shell_command_passes():
    _validate_v2(_minimal_v2(steps=[_shell_step()]))


def test_v2_valid_http_request_passes():
    _validate_v2(_minimal_v2(steps=[_http_step()]))


def test_v2_missing_schema_version_fails():
    doc = {
        "name": "Missing schema version",
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
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "workflow_schema_violation"


def test_v2_wrong_schema_version_value_fails():
    doc = _minimal_v2()
    doc["schemaVersion"] = "1"
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "workflow_schema_violation"


def test_v2_missing_action_fails():
    doc = {
        "schemaVersion": "2",
        "name": "No action",
        "steps": [
            {"id": "s1", "name": "Step", "type": "manual_task", "risk": "low"}
        ],
    }
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "workflow_schema_violation"


def test_v2_empty_steps_fails():
    doc = {"schemaVersion": "2", "name": "Empty", "steps": []}
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "workflow_schema_violation"


def test_v2_shell_command_missing_command_fails():
    step = _shell_step()
    step["action"]["params"] = {}  # missing required 'command'
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "workflow_schema_violation"


def test_v2_http_request_missing_url_fails():
    step = _http_step()
    step["action"]["params"] = {"method": "GET"}  # missing required 'url'
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "workflow_schema_violation"


# ---------------------------------------------------------------------------
# v2 semantic: duplicate step IDs
# ---------------------------------------------------------------------------


def test_v2_duplicate_step_ids_rejected():
    steps = [
        {
            "id": "dup",
            "name": "First",
            "type": "manual_task",
            "risk": "low",
            "action": {"type": "manual_task"},
        },
        {
            "id": "dup",
            "name": "Second",
            "type": "manual_task",
            "risk": "low",
            "action": {"type": "manual_task"},
        },
    ]
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=steps))
    assert exc_info.value.code == "duplicate_step_id"
    assert "dup" in exc_info.value.detail


# ---------------------------------------------------------------------------
# v2 semantic: action type mismatch
# ---------------------------------------------------------------------------


def test_v2_action_type_mismatch_semantic_code():
    # Call the semantic layer directly so we bypass JSON-schema and confirm the
    # semantic check raises action_type_mismatch with the expected code.
    from apps.workflows.validators import _v2_semantics

    definition = {
        "schemaVersion": "2",
        "name": "Mismatch Test",
        "steps": [
            {
                "id": "s1",
                "name": "Step",
                "type": "manual_task",
                "risk": "low",
                "action": {"type": "approval_gate"},
            }
        ],
    }
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _v2_semantics(definition)
    assert exc_info.value.code == "action_type_mismatch"


def test_v2_action_type_mismatch_rejected():
    # The JSON schema allOf enforces step.type == action.type, so it is caught
    # as a schema violation before the semantic check runs.  Any
    # InvalidWorkflowDefinitionError is the correct outcome.
    step = {
        "id": "s1",
        "name": "Step",
        "type": "manual_task",
        "risk": "low",
        "action": {"type": "approval_gate"},  # mismatch
    }
    with pytest.raises(InvalidWorkflowDefinitionError):
        _validate_v2(_minimal_v2(steps=[step]))


# ---------------------------------------------------------------------------
# v2 semantic: catalogVersion
# ---------------------------------------------------------------------------


def test_v2_unsupported_catalog_version_rejected():
    doc = _minimal_v2(catalogVersion="future.v99")
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "unsupported_catalog_version"


def test_v2_pilot_v1_catalog_version_accepted():
    doc = _minimal_v2(catalogVersion="pilot.v1")
    _validate_v2(doc)  # must not raise


def test_v2_omitted_catalog_version_defaults_to_pilot_v1():
    doc = _minimal_v2()
    assert "catalogVersion" not in doc
    _validate_v2(doc)  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: unknown action type
# ---------------------------------------------------------------------------


def test_v2_unknown_action_type_fails_closed():
    step = {
        "id": "s1",
        "name": "Step",
        "type": "kubernetes_rollout",
        "risk": "low",
        "action": {"type": "kubernetes_rollout"},
    }
    # Schema will reject unknown type first (enum constraint), but if schema
    # somehow passed we need the semantic check too; here we test via the full path.
    with pytest.raises(InvalidWorkflowDefinitionError):
        _validate_v2(_minimal_v2(steps=[step]))


# ---------------------------------------------------------------------------
# v2 semantic: secret declarations and references
# ---------------------------------------------------------------------------


def test_v2_step_refs_undeclared_secret_rejected():
    step = {
        "id": "s1",
        "name": "Step",
        "type": "manual_task",
        "risk": "low",
        "action": {"type": "manual_task"},
        "secrets": ["my_api_token"],  # not declared at top level
    }
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "unknown_secret_reference"
    assert "my_api_token" in exc_info.value.detail


def test_shared_invalid_secret_ref_fixture_rejected():
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(invalid_secret_ref_workflow())
    assert exc_info.value.code == "unknown_secret_reference"


def test_v2_step_refs_declared_secret_passes():
    step = {
        "id": "s1",
        "name": "Step",
        "type": "manual_task",
        "risk": "low",
        "action": {"type": "manual_task"},
        "secrets": ["my_api_token"],
    }
    doc = _minimal_v2(
        steps=[step],
        secrets=[{"key": "my_api_token", "ref": "vault://platform/my-token"}],
    )
    _validate_v2(doc)  # must not raise


def test_v2_duplicate_secret_keys_rejected():
    doc = _minimal_v2(
        secrets=[
            {"key": "tok", "ref": "vault://a"},
            {"key": "tok", "ref": "vault://b"},
        ]
    )
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "duplicate_secret_key"
    assert "tok" in exc_info.value.detail


def test_v2_secret_required_by_unknown_step_rejected():
    step = {
        "id": "real_step",
        "name": "Step",
        "type": "manual_task",
        "risk": "low",
        "action": {"type": "manual_task"},
    }
    doc = _minimal_v2(
        steps=[step],
        secrets=[{"key": "tok", "ref": "vault://a", "requiredBy": ["ghost_step"]}],
    )
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(doc)
    assert exc_info.value.code == "unknown_step_reference"
    assert "ghost_step" in exc_info.value.detail


def test_v2_secret_required_by_existing_step_passes():
    step = {
        "id": "real_step",
        "name": "Step",
        "type": "manual_task",
        "risk": "low",
        "action": {"type": "manual_task"},
        "secrets": ["tok"],
    }
    doc = _minimal_v2(
        steps=[step],
        secrets=[{"key": "tok", "ref": "vault://a", "requiredBy": ["real_step"]}],
    )
    _validate_v2(doc)  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: artifact declarations
# ---------------------------------------------------------------------------


def test_v2_duplicate_artifact_keys_rejected():
    step1 = _shell_step("s1")
    step1["artifacts"] = [
        {"key": "output", "kind": "file", "path": "artifacts/output.txt"}
    ]
    step2 = _shell_step("s2")
    step2["action"]["params"]["command"] = "echo world"
    step2["artifacts"] = [
        {"key": "output", "kind": "file", "path": "artifacts/output2.txt"}  # same key
    ]
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step1, step2]))
    assert exc_info.value.code == "duplicate_artifact_key"
    assert "output" in exc_info.value.detail


def test_v2_artifact_absolute_path_rejected():
    step = _shell_step()
    step["artifacts"] = [{"key": "log", "kind": "file", "path": "/etc/passwd"}]
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_artifact_path"
    assert "absolute" in exc_info.value.detail.lower()


def test_v2_artifact_traversal_path_rejected():
    step = _shell_step()
    step["artifacts"] = [
        {"key": "log", "kind": "file", "path": "artifacts/../../../etc/shadow"}
    ]
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_artifact_path"
    assert ".." in exc_info.value.detail


def test_v2_artifact_tilde_path_rejected():
    step = _shell_step()
    step["artifacts"] = [{"key": "log", "kind": "file", "path": "~/.ssh/id_rsa"}]
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_artifact_path"


def test_v2_artifact_empty_path_for_file_kind_rejected():
    step = _shell_step()
    step["artifacts"] = [{"key": "log", "kind": "file", "path": ""}]
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_artifact_path"


def test_v2_artifact_safe_relative_path_passes():
    step = _shell_step()
    step["artifacts"] = [
        {"key": "log", "kind": "file", "path": "artifacts/run.log"}
    ]
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_artifact_stdout_without_path_passes():
    step = _shell_step()
    step["artifacts"] = [{"key": "stdout_capture", "kind": "stdout"}]
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: retry + idempotency
# ---------------------------------------------------------------------------


def test_v2_retry_max_attempts_gt1_without_idempotency_rejected():
    step = _shell_step()
    step["retry"] = {"maxAttempts": 3}
    # No idempotency declared — must fail
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "retry_requires_idempotency"
    assert "3" in exc_info.value.detail


def test_v2_retry_max_attempts_gt1_with_none_idempotency_rejected():
    step = _shell_step()
    step["retry"] = {"maxAttempts": 2}
    step["idempotency"] = {"mode": "none"}
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "retry_requires_idempotency"


def test_v2_retry_max_attempts_gt1_with_natural_idempotency_passes():
    step = _shell_step()
    step["retry"] = {"maxAttempts": 3}
    step["idempotency"] = {"mode": "natural"}
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_retry_max_attempts_gt1_with_keyed_idempotency_passes():
    step = _shell_step()
    step["retry"] = {"maxAttempts": 2}
    step["idempotency"] = {"mode": "keyed", "key": "deploy-run-42"}
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_retry_max_attempts_1_without_idempotency_passes():
    step = _shell_step()
    step["retry"] = {"maxAttempts": 1}
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_keyed_idempotency_without_key_rejected():
    step = _shell_step()
    step["idempotency"] = {"mode": "keyed"}  # key missing
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "keyed_idempotency_requires_key"


def test_v2_keyed_idempotency_with_key_passes():
    step = _shell_step()
    step["idempotency"] = {"mode": "keyed", "key": "deploy-run-42"}
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_natural_idempotency_without_key_passes():
    step = _shell_step()
    step["idempotency"] = {"mode": "natural"}
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: dry-run
# ---------------------------------------------------------------------------


def test_v2_invalid_dry_run_strategy_rejected():
    step = _shell_step()
    step["dryRun"] = {"supported": True, "strategy": "magic_mode"}
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_dry_run_strategy"
    assert "magic_mode" in exc_info.value.detail


@pytest.mark.parametrize("strategy", ["native", "validate_only", "mock", "unsupported"])
def test_v2_valid_dry_run_strategies_pass(strategy):
    step = _shell_step()
    step["dryRun"] = {"supported": True, "strategy": strategy}
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: shell_command pilot restrictions
# ---------------------------------------------------------------------------


def test_v2_shell_command_raw_bearer_token_in_env_rejected():
    step = _shell_step()
    step["action"]["params"]["environment"] = {
        "API_KEY": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    }
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "raw_secret_in_environment"
    assert "API_KEY" in exc_info.value.detail


def test_v2_shell_command_github_pat_in_env_rejected():
    step = _shell_step()
    step["action"]["params"]["environment"] = {
        "GH_TOKEN": "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGH12"
    }
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "raw_secret_in_environment"


def test_v2_shell_command_safe_env_value_passes():
    step = _shell_step()
    step["action"]["params"]["environment"] = {
        "TARGET_ENV": "staging",
        "REPLICAS": "3",
    }
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_shell_command_absolute_working_directory_rejected():
    step = _shell_step()
    step["action"]["params"]["working_directory"] = "/app"
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_working_directory"
    assert "relative" in exc_info.value.detail.lower()


def test_v2_shell_command_traversal_working_directory_rejected():
    step = _shell_step()
    step["action"]["params"]["working_directory"] = "src/../../etc"
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_working_directory"
    assert ".." in exc_info.value.detail


def test_v2_shell_command_relative_working_directory_passes():
    step = _shell_step()
    step["action"]["params"]["working_directory"] = "src/scripts"
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: http_request pilot restrictions
# ---------------------------------------------------------------------------


def test_v2_http_request_raw_bearer_token_in_header_rejected():
    step = _http_step()
    step["action"]["params"]["headers"] = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    }
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "raw_secret_in_header"
    assert "Authorization" in exc_info.value.detail


def test_v2_http_request_safe_header_passes():
    step = _http_step()
    step["action"]["params"]["headers"] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_http_request_non_absolute_url_rejected():
    step = _http_step()
    step["action"]["params"]["url"] = "example.com/api"  # not absolute
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        _validate_v2(_minimal_v2(steps=[step]))
    assert exc_info.value.code == "invalid_request_url"


def test_v2_http_request_https_url_passes():
    step = _http_step()
    step["action"]["params"]["url"] = "https://api.example.com/status"
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_http_request_http_url_passes():
    step = _http_step()
    step["action"]["params"]["url"] = "http://localhost:8080/health"
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


# ---------------------------------------------------------------------------
# v2 semantic: action.version catalog lookup
# ---------------------------------------------------------------------------


def test_v2_explicit_known_action_version_passes():
    step = _shell_step()
    step["action"]["version"] = "pilot.v1"
    _validate_v2(_minimal_v2(steps=[step]))  # must not raise


def test_v2_explicit_unknown_action_version_rejected():
    step = _shell_step()
    step["action"]["version"] = "future.v99"
    with pytest.raises(InvalidWorkflowDefinitionError):
        _validate_v2(_minimal_v2(steps=[step]))


# ---------------------------------------------------------------------------
# v2 integration: complex valid workflow
# ---------------------------------------------------------------------------


def test_v2_complex_valid_workflow_passes():
    """Smoke-test a rich workflow with multiple step types, secrets, artifacts, retry."""
    steps = [
        {
            "id": "backup",
            "name": "Backup database",
            "type": "shell_command",
            "risk": "medium",
            "action": {
                "type": "shell_command",
                "params": {"command": "pg_dump $DATABASE_URL > /tmp/backup.sql"},
            },
            "idempotency": {"mode": "natural"},
            "retry": {"maxAttempts": 2},
            "artifacts": [{"key": "backup_log", "kind": "stdout"}],
        },
        {
            "id": "approve",
            "name": "Approve migration",
            "type": "approval_gate",
            "risk": "high",
            "requiresApproval": True,
            "action": {
                "type": "approval_gate",
                "params": {"message": "Proceed with migration?"},
            },
        },
        {
            "id": "health",
            "name": "Check health",
            "type": "http_request",
            "risk": "low",
            "action": {
                "type": "http_request",
                "params": {"method": "GET", "url": "https://api.example.com/health"},
            },
        },
        {
            "id": "verify",
            "name": "Check artifact",
            "type": "artifact_assertion",
            "risk": "low",
            "action": {
                "type": "artifact_assertion",
                "params": {"artifact_key": "backup_log", "assertion": "exists"},
            },
        },
    ]
    doc = {
        "schemaVersion": "2",
        "name": "Migration Runbook",
        "catalogVersion": "pilot.v1",
        "secrets": [],
        "steps": steps,
    }
    _validate_v2(doc)  # must not raise
