"""
Service-level tests for the approvals app.

Covers: request creation, idempotency, decision recording, timeout resolution,
and double-decision concurrency guard.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.approvals import services
from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.common.exceptions import DomainConflictError, InvalidStateTransitionError
from apps.executions.models import ExecutionStep


# ---------------------------------------------------------------------------
# request_step_approval
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_step_approval_creates_request(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    ar, created = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )

    assert created is True
    assert ar.status == ApprovalRequest.Status.PENDING
    assert ar.execution_id == execution.id
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL


@pytest.mark.django_db
def test_request_step_approval_is_idempotent(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    ar1, created1 = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )
    ar2, created2 = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )

    assert created1 is True
    assert created2 is False
    assert ar1.id == ar2.id
    assert ApprovalRequest.objects.filter(step=step).count() == 1


@pytest.mark.django_db
def test_request_step_approval_rejects_wrong_runner(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.request_step_approval(
            execution=execution,
            step=step,
            runner_id="wrong-runner",
            claim_token=claim_token,
        )

    assert exc_info.value.code == "runner_ownership_mismatch"


@pytest.mark.django_db
def test_request_step_approval_rejects_non_approval_step(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    # Second step does not require approval.
    step = execution.steps.order_by("position").last()
    assert not step.requires_approval

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.request_step_approval(
            execution=execution,
            step=step,
            runner_id="runner-1",
            claim_token=claim_token,
        )

    assert exc_info.value.code == "approval_not_required_for_step"


@pytest.mark.django_db
def test_request_step_approval_snapshots_timeout(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()
    step.step_snapshot = {**step.step_snapshot, "approvalTimeoutSeconds": 600}
    step.save()

    ar, _ = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )

    assert ar.timeout_seconds == 600
    assert ar.expires_at is not None


# ---------------------------------------------------------------------------
# decide_approval
# ---------------------------------------------------------------------------


@pytest.fixture
def pending_approval(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()
    ar, _ = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )
    return ar


@pytest.mark.django_db
def test_decide_approval_approved(pending_approval):
    decision = services.decide_approval(
        approval_request=pending_approval,
        decision="approved",
        actor_label="Test Operator",
    )

    assert decision.decision == ApprovalDecision.Decision.APPROVED
    assert decision.source_type == ApprovalDecision.SourceType.HUMAN
    assert decision.decided_by_label == "Test Operator"
    assert decision.decided_by_label_source == "unverified_pre_auth"

    pending_approval.refresh_from_db()
    assert pending_approval.status == ApprovalRequest.Status.APPROVED
    assert pending_approval.resolved_at is not None


@pytest.mark.django_db
def test_decide_approval_rejected(pending_approval):
    decision = services.decide_approval(
        approval_request=pending_approval,
        decision="rejected",
        notes="Not the right time.",
        actor_label="Test Operator",
    )

    assert decision.decision == ApprovalDecision.Decision.REJECTED
    assert decision.notes == "Not the right time."

    pending_approval.refresh_from_db()
    assert pending_approval.status == ApprovalRequest.Status.REJECTED


@pytest.mark.django_db
def test_decide_approval_second_decision_raises_conflict(pending_approval):
    services.decide_approval(
        approval_request=pending_approval,
        decision="approved",
        actor_label="Operator A",
    )

    with pytest.raises(DomainConflictError) as exc_info:
        services.decide_approval(
            approval_request=pending_approval,
            decision="rejected",
            actor_label="Operator B",
        )

    assert exc_info.value.code == "approval_request_not_pending"
    assert ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1


# ---------------------------------------------------------------------------
# get_approval_status — timeout resolution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_approval_status_resolves_expired_request(pending_approval):
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    resolved = services.get_approval_status(approval_request=pending_approval)

    assert resolved.status == ApprovalRequest.Status.TIMED_OUT
    assert resolved.resolved_at is not None
    assert ApprovalDecision.objects.filter(
        approval_request=resolved,
        decision=ApprovalDecision.Decision.TIMED_OUT,
        source_type=ApprovalDecision.SourceType.SYSTEM,
    ).exists()


@pytest.mark.django_db
def test_get_approval_status_does_not_double_timeout(pending_approval):
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    services.get_approval_status(approval_request=pending_approval)
    services.get_approval_status(approval_request=pending_approval)

    assert ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1


@pytest.mark.django_db
def test_get_approval_status_no_timeout_when_not_expired(pending_approval):
    pending_approval.expires_at = timezone.now() + timedelta(seconds=3600)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    resolved = services.get_approval_status(approval_request=pending_approval)
    assert resolved.status == ApprovalRequest.Status.PENDING


# ---------------------------------------------------------------------------
# Concurrency guard: double-decision serial test
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_double_decision_only_one_wins(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    ar, _ = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )

    services.decide_approval(approval_request=ar, decision="approved", actor_label="Op A")

    with pytest.raises(DomainConflictError):
        services.decide_approval(approval_request=ar, decision="rejected", actor_label="Op B")

    assert ApprovalDecision.objects.filter(approval_request=ar).count() == 1
    ar.refresh_from_db()
    assert ar.status == ApprovalRequest.Status.APPROVED
