"""
Approval integration tests for Phase 10.2.

Covers: policy_driven=True bypass, floor case, no duplicate approval requests.
"""

import pytest

from apps.approvals import services as approval_services
from apps.approvals.models import ApprovalRequest
from apps.common.exceptions import InvalidStateTransitionError
from apps.executions import services as exec_services
from apps.executions.models import ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as wf_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Approval Policy Test Runbook",
        slug="approval-policy-test",
        raw_content="Deploy\nVerify",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = wf_services.create_workflow(runbook=runbook, transform_client=StubWorkflowTransformClient())
    return wf_services.publish_workflow(workflow=wf)


@pytest.fixture
def claimed(published_workflow):
    exec_services.create_execution(workflow=published_workflow)
    return exec_services.claim_next_execution(runner_id="runner-1")


@pytest.mark.django_db
def test_policy_driven_creates_approval_request_on_non_requires_approval_step(claimed):
    """policy_driven=True bypasses the requires_approval guard."""
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    assert step.requires_approval is False

    ar, created = approval_services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
        policy_driven=True,
    )

    assert created is True
    assert ar.status == ApprovalRequest.Status.PENDING
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL


@pytest.mark.django_db
def test_non_policy_driven_still_rejects_non_requires_approval_step(claimed):
    """Default behavior (policy_driven=False) still rejects steps without requires_approval."""
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    assert step.requires_approval is False

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        approval_services.request_step_approval(
            execution=execution,
            step=step,
            runner_id="runner-1",
            claim_token=claim_token,
        )
    assert exc_info.value.code == "approval_not_required_for_step"


@pytest.mark.django_db
def test_policy_driven_idempotent_no_duplicate_request(claimed):
    """Second call with policy_driven=True returns existing request, doesn't create duplicate."""
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()

    ar1, created1 = approval_services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
        policy_driven=True,
    )
    ar2, created2 = approval_services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
        policy_driven=True,
    )

    assert created1 is True
    assert created2 is False
    assert ar1.id == ar2.id
    assert ApprovalRequest.objects.filter(step=step).count() == 1
