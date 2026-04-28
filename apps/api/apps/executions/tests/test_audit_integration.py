import pytest

from apps.audit.models import AuditEvent
from apps.executions import services as execution_services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def published_workflow(org):
    runbook = runbook_services.create_runbook(
        organization=org,
        title="Execution Audit",
        slug="execution-audit",
        raw_content="Deploy\nVerify",
    )
    workflow = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=workflow)


@pytest.mark.django_db
def test_execution_lifecycle_emits_audit_events(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    claimed = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()

    execution_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-1",
        claim_token=claim_token,
        new_status=ExecutionStep.Status.RUNNING,
    )
    execution_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-1",
        claim_token=claim_token,
        new_status=ExecutionStep.Status.SUCCEEDED,
        exit_code=0,
    )
    execution_services.complete_execution(
        execution=execution,
        runner_id="runner-1",
        claim_token=claim_token,
        outcome=Execution.Status.SUCCEEDED,
    )

    event_types = set(
        AuditEvent.objects.filter(
            organization_id=execution.organization_id
        ).values_list("event_type", flat=True)
    )
    assert {
        "execution.created",
        "execution.claimed",
        "execution_step.started",
        "execution_step.succeeded",
        "execution.completed",
    }.issubset(event_types)


@pytest.mark.django_db
def test_step_failure_audit_metadata_excludes_command(published_workflow):
    execution_services.create_execution(workflow=published_workflow)
    claimed = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]
    step = execution.steps.order_by("position").first()

    execution_services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-1",
        claim_token=claimed["claim_token"],
        new_status=ExecutionStep.Status.FAILED,
        error_message="process failed",
    )

    event = AuditEvent.objects.get(event_type="execution_step.failed")
    assert event.metadata["error_message"] == "process failed"
    assert "command" not in event.metadata
    assert "claim_token" not in event.metadata
