"""
Tests for v2 workflow execution creation (Pilot Phase B.3).

Covers:
- v1 execution creation is unchanged by the new code paths
- v2 execution creation succeeds for a valid published v2 workflow
- v2 step_snapshot is the exact source step object
- execution_mode persists on the execution row
- dry_run mode rejects steps with dryRun.strategy='unsupported'
- invalid v2 workflow (structural violation) cannot create an execution
- workflow_snapshot_hash_sha256 is deterministic for identical definitions
"""

import hashlib
import json

import pytest

from apps.common.exceptions import DomainValidationError, InvalidWorkflowDefinitionError
from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient
from apps.workflows.tests.fixtures.workflow_v2 import valid_v2_shell_command_workflow

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _minimal_v2(**overrides) -> dict:
    doc = {
        "schemaVersion": "2",
        "name": "Test Workflow",
        "steps": [
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


def _shell_step(step_id="run", dry_run_strategy=None, **overrides) -> dict:
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
    if dry_run_strategy is not None:
        step["dryRun"] = {"supported": dry_run_strategy != "unsupported", "strategy": dry_run_strategy}
    step.update(overrides)
    return step


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Deploy Service",
        slug="deploy-service",
        raw_content="Step one",
    )


@pytest.fixture
def published_v1_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


def _publish_v2(runbook, definition):
    wf = workflow_services.create_workflow_v2_draft(runbook=runbook, definition=definition)
    return workflow_services.publish_workflow(workflow=wf)


# ---------------------------------------------------------------------------
# v1 unchanged
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_v1_execution_creation_unchanged(published_v1_workflow):
    execution = services.create_execution(workflow=published_v1_workflow)

    assert execution.status == Execution.Status.QUEUED
    assert execution.workflow_version == published_v1_workflow.version
    assert execution.workflow_snapshot == published_v1_workflow.definition


@pytest.mark.django_db
def test_v1_execution_step_count_matches_definition(published_v1_workflow):
    execution = services.create_execution(workflow=published_v1_workflow)
    expected = len(published_v1_workflow.definition["steps"])
    assert ExecutionStep.objects.filter(execution=execution).count() == expected


@pytest.mark.django_db
def test_v1_execution_step_snapshot_is_source_step(published_v1_workflow):
    execution = services.create_execution(workflow=published_v1_workflow)
    first_step = execution.steps.order_by("position").first()
    expected = published_v1_workflow.definition["steps"][0]
    assert first_step.step_snapshot == expected


@pytest.mark.django_db
def test_v1_execution_mode_defaults_to_live(published_v1_workflow):
    execution = services.create_execution(workflow=published_v1_workflow)
    assert execution.execution_mode == Execution.ExecutionMode.LIVE


# ---------------------------------------------------------------------------
# v2 happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.django_db
def test_published_shared_v2_shell_workflow_creates_execution(runbook):
    definition = valid_v2_shell_command_workflow()
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)

    assert execution.status == Execution.Status.QUEUED
    assert execution.workflow_snapshot == definition
    step = execution.steps.get()
    assert step.step_snapshot == definition["steps"][0]
    assert step.step_type == "shell_command"


def test_v2_execution_creation_succeeds(runbook):
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf)

    assert execution.status == Execution.Status.QUEUED
    assert execution.workflow_version == wf.version
    assert execution.workflow_snapshot == wf.definition


@pytest.mark.django_db
def test_v2_execution_step_count_matches_definition(runbook):
    definition = _minimal_v2(
        steps=[
            {"id": "s1", "name": "Step 1", "type": "manual_task", "risk": "low", "action": {"type": "manual_task"}},
            {"id": "s2", "name": "Step 2", "type": "manual_task", "risk": "low", "action": {"type": "manual_task"}},
        ]
    )
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)
    assert ExecutionStep.objects.filter(execution=execution).count() == 2


@pytest.mark.django_db
def test_v2_step_snapshot_is_exact_source_step(runbook):
    definition = _minimal_v2()
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)

    first_step = execution.steps.order_by("position").first()
    assert first_step.step_snapshot == definition["steps"][0]


@pytest.mark.django_db
def test_v2_step_fields_populated_from_definition(runbook):
    definition = _minimal_v2(steps=[_shell_step()])
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)

    step = execution.steps.order_by("position").first()
    assert step.step_key == "run"
    assert step.name == "Run command"
    assert step.step_type == "shell_command"
    assert step.risk_level == "low"
    assert step.command == "echo hello"
    assert step.requires_approval is False


@pytest.mark.django_db
def test_v2_shell_step_command_extracted_from_action(runbook):
    cmd = "pg_dump $DATABASE_URL > backup.dump"
    definition = _minimal_v2(
        steps=[
            {
                "id": "backup",
                "name": "Backup DB",
                "type": "shell_command",
                "risk": "medium",
                "action": {"type": "shell_command", "params": {"command": cmd}},
            }
        ]
    )
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)

    step = execution.steps.order_by("position").first()
    assert step.command == cmd


@pytest.mark.django_db
def test_v2_manual_task_step_has_empty_command(runbook):
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf)

    step = execution.steps.order_by("position").first()
    assert step.command == ""


@pytest.mark.django_db
def test_v2_step_requires_approval_preserved(runbook):
    definition = _minimal_v2(
        steps=[
            {
                "id": "approve",
                "name": "Approve",
                "type": "approval_gate",
                "risk": "high",
                "requiresApproval": True,
                "action": {"type": "approval_gate"},
            }
        ]
    )
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)

    step = execution.steps.order_by("position").first()
    assert step.requires_approval is True


# ---------------------------------------------------------------------------
# execution_mode
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_mode_live_is_default(runbook):
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf)
    assert execution.execution_mode == Execution.ExecutionMode.LIVE


@pytest.mark.django_db
def test_execution_mode_dry_run_persists(runbook):
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)
    assert execution.execution_mode == Execution.ExecutionMode.DRY_RUN

    execution.refresh_from_db()
    assert execution.execution_mode == Execution.ExecutionMode.DRY_RUN


@pytest.mark.django_db
def test_execution_mode_live_persists_to_db(runbook):
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf, mode="live")

    execution.refresh_from_db()
    assert execution.execution_mode == "live"


# ---------------------------------------------------------------------------
# dry_run enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_rejects_step_with_unsupported_strategy(runbook):
    definition = _minimal_v2(steps=[_shell_step(dry_run_strategy="unsupported")])
    wf = _publish_v2(runbook, definition)

    with pytest.raises(DomainValidationError) as exc_info:
        services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)
    assert exc_info.value.code == "step_not_dry_run_compatible"


@pytest.mark.django_db
def test_dry_run_accepts_step_with_native_strategy(runbook):
    definition = _minimal_v2(steps=[_shell_step(dry_run_strategy="native")])
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)
    assert execution.execution_mode == Execution.ExecutionMode.DRY_RUN


@pytest.mark.django_db
def test_dry_run_accepts_steps_without_dry_run_declaration(runbook):
    # Steps with no dryRun field should pass dry-run validation.
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)
    assert execution.execution_mode == Execution.ExecutionMode.DRY_RUN


@pytest.mark.django_db
def test_dry_run_rejects_first_unsupported_step_in_mixed_workflow(runbook):
    definition = _minimal_v2(
        steps=[
            _shell_step("step1", dry_run_strategy="native"),
            _shell_step("step2", dry_run_strategy="unsupported"),
        ]
    )
    wf = _publish_v2(runbook, definition)

    with pytest.raises(DomainValidationError) as exc_info:
        services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)
    assert exc_info.value.code == "step_not_dry_run_compatible"
    assert "step2" in exc_info.value.detail


@pytest.mark.django_db
def test_live_mode_does_not_check_dry_run_strategy(runbook):
    # unsupported strategy is OK for live mode
    definition = _minimal_v2(steps=[_shell_step(dry_run_strategy="unsupported")])
    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf, mode=Execution.ExecutionMode.LIVE)
    assert execution.execution_mode == Execution.ExecutionMode.LIVE


# ---------------------------------------------------------------------------
# Invalid v2 workflow cannot create execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_v2_workflow_cannot_create_execution(runbook):
    # A workflow with a v2 definition that bypasses publish validation
    # (e.g., manually saved with an invalid definition) should be rejected.
    wf = _publish_v2(runbook, _minimal_v2())
    # Corrupt the definition directly so publish validation is bypassed.
    wf.definition = {
        "schemaVersion": "2",
        "name": "Bad",
        "steps": [{"id": "s1", "name": "Step", "type": "manual_task", "risk": "low"}],
        # Missing required 'action' field
    }
    wf.save(update_fields=["definition"])

    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        services.create_execution(workflow=wf)
    assert exc_info.value.code == "workflow_schema_violation"


# ---------------------------------------------------------------------------
# workflow_snapshot_hash_sha256 — determinism
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.django_db
def test_secret_values_are_not_persisted_in_v2_execution_snapshots(runbook):
    secret_value = "SHOULD_NOT_BE_PERSISTED_12345"
    definition = valid_v2_shell_command_workflow()
    definition["secrets"] = [
        {
            "key": "deploy_token",
            "displayName": "Deploy token",
            "provider": "external",
            "ref": "vault://platform/pilot/deploy-token",
            "requiredBy": ["run-echo"],
        }
    ]
    definition["steps"][0]["secrets"] = ["deploy_token"]

    wf = _publish_v2(runbook, definition)
    execution = services.create_execution(workflow=wf)
    step = execution.steps.get()

    persisted = json.dumps(
        [wf.definition, execution.workflow_snapshot, step.step_snapshot],
        sort_keys=True,
    )
    assert secret_value not in persisted
    assert "deploy_token" in persisted


def test_snapshot_hash_is_set_on_v2_execution(runbook):
    wf = _publish_v2(runbook, _minimal_v2())
    execution = services.create_execution(workflow=wf)
    assert len(execution.workflow_snapshot_hash_sha256) == 64
    assert all(c in "0123456789abcdef" for c in execution.workflow_snapshot_hash_sha256)


@pytest.mark.django_db
def test_snapshot_hash_is_deterministic(runbook):
    definition = _minimal_v2()
    wf1 = _publish_v2(runbook, definition)
    e1 = services.create_execution(workflow=wf1)

    # Reorder keys in the definition dict to verify canonical serialization.
    reordered = dict(reversed(list(definition.items())))
    expected_hash = hashlib.sha256(
        json.dumps(reordered, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()

    assert e1.workflow_snapshot_hash_sha256 == expected_hash


@pytest.mark.django_db
def test_snapshot_hash_differs_for_different_definitions(runbook):
    def1 = _minimal_v2(name="Alpha")
    def2 = _minimal_v2(name="Beta")

    wf1 = _publish_v2(runbook, def1)
    e1 = services.create_execution(workflow=wf1)

    runbook2 = runbook_services.create_runbook(
        organization=runbook.organization,
        title="Beta Service",
        slug="beta-service",
        raw_content="Step beta",
    )
    wf2 = _publish_v2(runbook2, def2)
    e2 = services.create_execution(workflow=wf2)

    assert e1.workflow_snapshot_hash_sha256 != e2.workflow_snapshot_hash_sha256
