from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.approvals.models import ApprovalDecision
from apps.audit.models import AuditEvent
from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def claimed_approval(org):
    runbook = runbook_services.create_runbook(
        organization=org,
        title="Approval Audit",
        slug="approval-audit",
        raw_content="Deploy\nVerify",
    )
    workflow = workflow_services.publish_workflow(
        workflow=workflow_services.create_workflow(
            runbook=runbook, transform_client=StubWorkflowTransformClient()
        )
    )
    execution = execution_services.create_execution(workflow=workflow)
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])
    claimed = execution_services.claim_next_execution(runner_id="runner-1")
    claimed["step"] = step
    return claimed


@pytest.mark.django_db
def test_approval_request_and_decision_emit_audit_events(claimed_approval):
    approval_request, _ = approval_services.request_step_approval(
        execution=claimed_approval["execution"],
        step=claimed_approval["step"],
        runner_id="runner-1",
        claim_token=claimed_approval["claim_token"],
    )
    decision = approval_services.decide_approval(
        approval_request=approval_request,
        decision=ApprovalDecision.Decision.APPROVED,
        actor_label="Operator",
    )

    requested = AuditEvent.objects.get(event_type="approval.requested")
    approved = AuditEvent.objects.get(event_type="approval.approved")
    waiting = AuditEvent.objects.get(event_type="execution_step.waiting_for_approval")

    assert requested.object_id == approval_request.id
    assert requested.metadata["execution_id"] == str(claimed_approval["execution"].id)
    assert approved.object_id == decision.id
    assert approved.actor_type == AuditEvent.ActorType.UNKNOWN
    assert approved.metadata["notes_present"] is False
    assert waiting.metadata["new_status"] == "waiting_for_approval"


@pytest.mark.django_db
def test_approval_timeout_emits_audit_event(claimed_approval):
    approval_request, _ = approval_services.request_step_approval(
        execution=claimed_approval["execution"],
        step=claimed_approval["step"],
        runner_id="runner-1",
        claim_token=claimed_approval["claim_token"],
    )
    approval_request.expires_at = timezone.now() - timedelta(seconds=1)
    approval_request.save(update_fields=["expires_at", "updated_at"])

    approval_services.get_approval_status(approval_request=approval_request)

    timed_out = AuditEvent.objects.get(event_type="approval.timed_out")
    assert timed_out.actor_type == AuditEvent.ActorType.SYSTEM
    assert timed_out.metadata["decision"] == ApprovalDecision.Decision.TIMED_OUT
