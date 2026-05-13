"""
Tests: v2 action facts appear in audit metadata (Phase B.5).

Covers:
- execution.created audit includes schema_version, catalog_version, dry_run_mode
- execution_step.started audit includes action_type, action_version, retry, idempotency,
  declared_artifact_keys, declared_secret_key_names
- audit metadata never includes raw secret values
- v1 step audit metadata has safe empty defaults (behaviour unchanged)
"""

import pytest

from apps.audit.models import AuditEvent
from apps.executions import services as exec_services
from apps.executions.models import Execution
from apps.runbooks import services as runbook_services
from apps.workflows import services as wf_services
from apps.workflows.internal_clients import StubWorkflowTransformClient

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Audit Meta Test",
        slug="audit-meta",
        raw_content="step one",
    )


@pytest.fixture
def published_v1_workflow(runbook):
    wf = wf_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return wf_services.publish_workflow(workflow=wf)


def _publish_v2(runbook, definition):
    wf = wf_services.create_workflow_v2_draft(runbook=runbook, definition=definition)
    return wf_services.publish_workflow(workflow=wf)


def _v2_step(**overrides) -> dict:
    """Return a schema-valid v2 shell_command step definition."""
    step = {
        "id": "s1",
        "name": "Shell step",
        "type": "shell_command",
        "risk": "medium",
        "action": {
            "type": "shell_command",
            "params": {"command": "echo ok"},
        },
        "retry": {"maxAttempts": 2},
        "idempotency": {"mode": "natural"},
        "dryRun": {"supported": True, "strategy": "native"},
        "secrets": ["DB_PASS", "VAULT_TOKEN"],
        "artifacts": [
            {"key": "log_file", "kind": "file", "path": "log.txt", "required": True},
        ],
    }
    step.update(overrides)
    return step


def _v2_def(step=None) -> dict:
    s = step or _v2_step()
    secret_keys = s.get("secrets", [])
    return {
        "schemaVersion": "2",
        "catalogVersion": "pilot.v1",
        "name": "Audit Test Workflow",
        "secrets": [{"key": k} for k in secret_keys],
        "steps": [s],
    }


def _claim_v2(runbook, runner_id="runner-audit"):
    wf = _publish_v2(runbook, _v2_def())
    exec_services.create_execution(workflow=wf)
    return exec_services.claim_next_execution(runner_id=runner_id)


def _claim_v1(published_v1_workflow, runner_id="runner-v1"):
    exec_services.create_execution(workflow=published_v1_workflow)
    return exec_services.claim_next_execution(runner_id=runner_id)


# ---------------------------------------------------------------------------
# execution.created audit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_created_audit_includes_schema_version(org, runbook):
    wf = _publish_v2(runbook, _v2_def())
    execution = exec_services.create_execution(workflow=wf)

    event = AuditEvent.objects.filter(
        object_id=execution.id,
        event_type="execution.created",
    ).first()
    assert event is not None
    assert event.metadata["schema_version"] == "2"


@pytest.mark.django_db
def test_execution_created_audit_includes_catalog_version(org, runbook):
    wf = _publish_v2(runbook, _v2_def())
    execution = exec_services.create_execution(workflow=wf)

    event = AuditEvent.objects.get(object_id=execution.id, event_type="execution.created")
    assert event.metadata["catalog_version"] == "pilot.v1"


@pytest.mark.django_db
def test_execution_created_audit_dry_run_mode_false_for_live(org, runbook):
    wf = _publish_v2(runbook, _v2_def())
    execution = exec_services.create_execution(workflow=wf, mode=Execution.ExecutionMode.LIVE)

    event = AuditEvent.objects.get(object_id=execution.id, event_type="execution.created")
    assert event.metadata["dry_run_mode"] is False


@pytest.mark.django_db
def test_execution_created_audit_dry_run_mode_true_for_dry_run(org, runbook):
    step = _v2_step()  # dryRun.supported=True, strategy=native
    wf = _publish_v2(runbook, _v2_def(step=step))
    execution = exec_services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)

    event = AuditEvent.objects.get(object_id=execution.id, event_type="execution.created")
    assert event.metadata["dry_run_mode"] is True


@pytest.mark.django_db
def test_execution_created_audit_schema_version_empty_for_v1(org, published_v1_workflow):
    execution = exec_services.create_execution(workflow=published_v1_workflow)

    event = AuditEvent.objects.get(object_id=execution.id, event_type="execution.created")
    assert event.metadata["schema_version"] == ""


# ---------------------------------------------------------------------------
# execution_step.started audit — v2 enrichment
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_started_audit_includes_action_type(org, runbook):
    result = _claim_v2(runbook)
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-audit",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    assert event is not None
    assert event.metadata["action_type"] == "shell_command"


@pytest.mark.django_db
def test_step_started_audit_includes_action_version_empty_when_unset(org, runbook):
    # No version set on the action in _v2_step; expect empty string.
    result = _claim_v2(runbook, runner_id="runner-av")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-av",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    assert event.metadata["action_version"] == ""


@pytest.mark.django_db
def test_step_started_audit_includes_retry_max_attempts(org, runbook):
    result = _claim_v2(runbook, runner_id="runner-retry")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-retry",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    assert event.metadata["retry_max_attempts"] == 2


@pytest.mark.django_db
def test_step_started_audit_includes_idempotency_mode(org, runbook):
    result = _claim_v2(runbook, runner_id="runner-idem")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-idem",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    assert event.metadata["idempotency_mode"] == "natural"


@pytest.mark.django_db
def test_step_started_audit_includes_declared_artifact_keys(org, runbook):
    result = _claim_v2(runbook, runner_id="runner-art")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-art",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    assert event.metadata["declared_artifact_keys"] == ["log_file"]


@pytest.mark.django_db
def test_step_started_audit_includes_declared_secret_key_names(org, runbook):
    result = _claim_v2(runbook, runner_id="runner-sec")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-sec",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    # key names are present; actual values are never stored
    assert event.metadata["declared_secret_key_names"] == ["DB_PASS", "VAULT_TOKEN"]


@pytest.mark.django_db
def test_step_started_audit_does_not_include_raw_secret_values(org, runbook):
    """Secret values must never appear in audit metadata — only key names."""
    result = _claim_v2(runbook, runner_id="runner-sec-val")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-sec-val",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    # The FORBIDDEN key "secrets" must not appear in stored metadata
    assert "secrets" not in event.metadata
    assert "secret" not in event.metadata


# ---------------------------------------------------------------------------
# v1 step audit — safe defaults, existing fields present
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_v1_step_audit_has_empty_action_type(org, published_v1_workflow):
    exec_services.create_execution(workflow=published_v1_workflow)
    result = exec_services.claim_next_execution(runner_id="runner-v1-audit")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-v1-audit",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    assert event is not None
    assert event.metadata["action_type"] == ""
    assert event.metadata["declared_artifact_keys"] == []
    assert event.metadata["declared_secret_key_names"] == []


@pytest.mark.django_db
def test_v1_step_audit_still_has_existing_fields(org, published_v1_workflow):
    exec_services.create_execution(workflow=published_v1_workflow)
    result = exec_services.claim_next_execution(runner_id="runner-v1-existing")
    execution = result["execution"]
    step = execution.steps.first()
    claim_token = result["claim_token"]

    exec_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-v1-existing",
        claim_token=claim_token,
        new_status="running",
        _allow_running=True,
    )

    event = AuditEvent.objects.filter(
        object_id=step.id, event_type="execution_step.started"
    ).first()
    # All original fields still present
    assert "step_key" in event.metadata
    assert "risk_level" in event.metadata
    assert "step_type" in event.metadata
    assert "previous_status" in event.metadata
    assert "new_status" in event.metadata
