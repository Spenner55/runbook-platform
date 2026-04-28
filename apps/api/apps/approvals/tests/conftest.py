import pytest

from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Approval Test Runbook",
        slug="approval-test",
        raw_content="Deploy service\nVerify health",
    )


@pytest.fixture
def approval_workflow(runbook, org):
    """Workflow whose first step requires approval."""
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    published = workflow_services.publish_workflow(workflow=wf)
    # Patch the first step's snapshot to require approval.
    execution = execution_services.create_execution(workflow=published)
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.step_snapshot = {**step.step_snapshot, "requiresApproval": True}
    step.save(update_fields=["requires_approval", "step_snapshot", "updated_at"])
    return published, execution


@pytest.fixture
def claimed_approval_execution(approval_workflow):
    _, execution = approval_workflow
    result = execution_services.claim_next_execution(runner_id="runner-1")
    return result


@pytest.fixture
def queued_execution_no_approval(org, runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    published = workflow_services.publish_workflow(workflow=wf)
    return execution_services.create_execution(workflow=published)
