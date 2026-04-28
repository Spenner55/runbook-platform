from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.audit.models import AuditEvent
from apps.executions import services as execution_services
from apps.executions.models import Execution, ExecutionStep
from apps.policies import services as policy_services
from apps.policies.models import PolicyEvaluation
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def published_workflow(org):
    runbook = runbook_services.create_runbook(
        organization=org,
        title="Rollback Test",
        slug="rollback-test",
        raw_content="Deploy\nVerify",
    )
    workflow = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=workflow)


@pytest.mark.django_db
def test_execution_cancel_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.executions.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            execution_services.cancel_execution(execution=execution)

    execution.refresh_from_db()
    assert execution.status == Execution.Status.QUEUED
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_approval_decision_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])
    claimed = execution_services.claim_next_execution(runner_id="runner-1")
    approval_request, _ = approval_services.request_step_approval(
        execution=claimed["execution"],
        step=step,
        runner_id="runner-1",
        claim_token=claimed["claim_token"],
    )
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.approvals.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            approval_services.decide_approval(
                approval_request=approval_request,
                decision="approved",
                actor_label="Operator",
            )

    approval_request.refresh_from_db()
    assert approval_request.status == ApprovalRequest.Status.PENDING
    assert (
        ApprovalDecision.objects.filter(approval_request=approval_request).count() == 0
    )
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_policy_evaluation_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    step = execution.steps.order_by("position").first()

    with patch(
        "apps.policies.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            policy_services.evaluate_step_policy(execution=execution, step=step)

    assert PolicyEvaluation.objects.count() == 0


@pytest.mark.django_db
def test_execution_creation_rolls_back_if_audit_emit_fails(published_workflow):
    execution_count = Execution.objects.count()
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.executions.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            execution_services.create_execution(workflow=published_workflow)

    assert Execution.objects.count() == execution_count
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_runner_claim_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.executions.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            execution_services.claim_next_execution(runner_id="runner-1")

    execution.refresh_from_db()
    assert execution.status == Execution.Status.QUEUED
    assert not execution.claimed_by_runner_id
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_step_transition_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    claimed = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]
    step = execution.steps.order_by("position").first()
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.executions.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            execution_services.update_execution_step(
                execution=execution,
                step_id=str(step.id),
                runner_id="runner-1",
                claim_token=claimed["claim_token"],
                new_status=ExecutionStep.Status.RUNNING,
            )

    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.PENDING
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_approval_request_creation_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])
    claimed = execution_services.claim_next_execution(runner_id="runner-1")
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.approvals.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            approval_services.request_step_approval(
                execution=claimed["execution"],
                step=step,
                runner_id="runner-1",
                claim_token=claimed["claim_token"],
            )

    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.PENDING
    assert ApprovalRequest.objects.filter(step=step).count() == 0
    assert AuditEvent.objects.count() == audit_count


@pytest.mark.django_db
def test_approval_timeout_rolls_back_if_audit_emit_fails(published_workflow):
    execution = execution_services.create_execution(workflow=published_workflow)
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])
    claimed = execution_services.claim_next_execution(runner_id="runner-1")

    approval_request, _ = approval_services.request_step_approval(
        execution=claimed["execution"],
        step=step,
        runner_id="runner-1",
        claim_token=claimed["claim_token"],
    )
    # Force the timeout deadline to be in the past.
    approval_request.expires_at = timezone.now() - timedelta(seconds=1)
    approval_request.save(update_fields=["expires_at", "updated_at"])
    audit_count = AuditEvent.objects.count()

    with patch(
        "apps.approvals.services.AuditService.emit",
        side_effect=RuntimeError("audit unavailable"),
    ):
        with pytest.raises(RuntimeError):
            approval_services.get_approval_status(approval_request=approval_request)

    approval_request.refresh_from_db()
    assert approval_request.status == ApprovalRequest.Status.PENDING
    assert (
        ApprovalDecision.objects.filter(approval_request=approval_request).count() == 0
    )
    assert AuditEvent.objects.count() == audit_count
