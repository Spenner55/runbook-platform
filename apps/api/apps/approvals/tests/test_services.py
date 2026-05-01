"""
Service-level tests for the approvals app.

Covers: request creation, idempotency, decision recording, timeout resolution,
and double-decision concurrency guard.
"""

import threading
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connections
from django.utils import timezone
from prometheus_client import REGISTRY

from apps.approvals import services
from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.audit.models import AuditEvent
from apps.common.exceptions import DomainConflictError, InvalidStateTransitionError
from apps.executions.models import Execution, ExecutionStep

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
def test_request_step_approval_emits_waiting_step_status_changed(
    claimed_approval_execution,
):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    with patch("apps.executions.services._emit_on_commit") as mock_emit:
        services.request_step_approval(
            execution=execution,
            step=step,
            runner_id="runner-1",
            claim_token=claim_token,
        )

    mock_emit.assert_called_once()
    execution_id, event = mock_emit.call_args[0]
    assert execution_id == str(execution.id)
    assert event.event_type == "step.status_changed"
    assert event.data["execution_id"] == str(execution.id)
    assert event.data["step_id"] == str(step.id)
    assert event.data["status"] == ExecutionStep.Status.WAITING_FOR_APPROVAL


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
def test_request_step_approval_rejects_step_from_different_execution(
    claimed_approval_execution, org
):
    """Step belonging to a different execution is rejected before any state change."""
    from apps.executions import services as execution_services
    from apps.runbooks import services as runbook_services
    from apps.workflows import services as workflow_services
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]

    # Build a second execution and grab one of its steps.
    rb = runbook_services.create_runbook(
        organization=org, title="Other", slug="other-inv", raw_content="Step A"
    )
    wf = workflow_services.publish_workflow(
        workflow=workflow_services.create_workflow(
            runbook=rb, transform_client=StubWorkflowTransformClient()
        )
    )
    other_execution = execution_services.create_execution(workflow=wf)
    other_step = other_execution.steps.order_by("position").first()
    other_step.requires_approval = True
    other_step.save(update_fields=["requires_approval", "updated_at"])

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.request_step_approval(
            execution=execution,
            step=other_step,
            runner_id="runner-1",
            claim_token=claim_token,
        )

    assert exc_info.value.code == "step_execution_mismatch"


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
    before = (
        REGISTRY.get_sample_value(
            "runbook_approval_latency_seconds_count",
            {"outcome": ApprovalRequest.Status.APPROVED},
        )
        or 0
    )

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
    after = REGISTRY.get_sample_value(
        "runbook_approval_latency_seconds_count",
        {"outcome": ApprovalRequest.Status.APPROVED},
    )
    assert after > before


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
    assert (
        ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1
    )


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

    assert (
        ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1
    )


@pytest.mark.django_db
def test_get_approval_status_no_timeout_when_not_expired(pending_approval):
    pending_approval.expires_at = timezone.now() + timedelta(seconds=3600)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    resolved = services.get_approval_status(approval_request=pending_approval)
    assert resolved.status == ApprovalRequest.Status.PENDING


# ---------------------------------------------------------------------------
# recover_expired_approvals — watchdog timeout recovery
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_recover_expired_approvals_fails_blocked_execution(pending_approval):
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    recovered = services.recover_expired_approvals()

    assert recovered == [str(pending_approval.id)]
    pending_approval.refresh_from_db()
    pending_approval.execution.refresh_from_db()
    pending_approval.step.refresh_from_db()
    assert pending_approval.status == ApprovalRequest.Status.TIMED_OUT
    assert pending_approval.execution.status == Execution.Status.FAILED
    assert pending_approval.step.status == ExecutionStep.Status.FAILED
    assert "approval timeout" in pending_approval.step.error_message


@pytest.mark.django_db(transaction=True)
def test_recover_expired_approvals_emits_audit_events(pending_approval):
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    services.recover_expired_approvals()

    event_types = set(
        AuditEvent.objects.filter(
            organization_id=pending_approval.organization_id,
        ).values_list("event_type", flat=True)
    )
    assert "approval.timed_out" in event_types
    assert "approval.timeout" in event_types
    assert "execution.failed" in event_types
    assert "execution.approval_timeout" in event_types

    approval_timeout = AuditEvent.objects.get(event_type="approval.timeout")
    assert approval_timeout.metadata["approval_request_id"] == str(pending_approval.id)
    assert approval_timeout.metadata["recovery_source"] == "watchdog"


@pytest.mark.django_db(transaction=True)
def test_recover_expired_approvals_is_idempotent(pending_approval):
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    first = services.recover_expired_approvals()
    second = services.recover_expired_approvals()

    assert first == [str(pending_approval.id)]
    assert second == []
    assert (
        ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1
    )
    assert (
        AuditEvent.objects.filter(event_type="execution.approval_timeout").count() == 1
    )


@pytest.mark.django_db(transaction=True)
def test_recover_expired_approvals_leaves_non_expired_pending(pending_approval):
    pending_approval.expires_at = timezone.now() + timedelta(seconds=3600)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    recovered = services.recover_expired_approvals()

    assert recovered == []
    pending_approval.refresh_from_db()
    assert pending_approval.status == ApprovalRequest.Status.PENDING
    assert pending_approval.execution.status != Execution.Status.FAILED


@pytest.mark.django_db(transaction=True)
def test_recover_expired_approvals_leaves_decided_request(pending_approval):
    services.decide_approval(
        approval_request=pending_approval,
        decision=ApprovalDecision.Decision.APPROVED,
        actor_label="Operator",
    )
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    recovered = services.recover_expired_approvals()

    assert recovered == []
    pending_approval.refresh_from_db()
    assert pending_approval.status == ApprovalRequest.Status.APPROVED
    assert (
        ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_expired_approval_recovery_runs_once(pending_approval):
    pending_approval.expires_at = timezone.now() - timedelta(seconds=1)
    pending_approval.save(update_fields=["expires_at", "updated_at"])

    results: list[list[str]] = [[], []]
    barrier = threading.Barrier(2)

    def run(index: int) -> None:
        barrier.wait()
        try:
            results[index] = services.recover_expired_approvals()
        finally:
            connections.close_all()

    t1 = threading.Thread(target=run, args=(0,))
    t2 = threading.Thread(target=run, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    all_recovered = results[0] + results[1]
    assert all_recovered.count(str(pending_approval.id)) == 1
    assert (
        ApprovalDecision.objects.filter(approval_request=pending_approval).count() == 1
    )
    assert (
        AuditEvent.objects.filter(event_type="execution.approval_timeout").count() == 1
    )


# ---------------------------------------------------------------------------
# Integration notifications
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approval_requested_triggers_notify(
    claimed_approval_execution, django_capture_on_commit_callbacks
):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    with patch("apps.approvals.services.IntegrationService.notify") as notify:
        with django_capture_on_commit_callbacks(execute=True):
            approval_request, created = services.request_step_approval(
                execution=execution,
                step=step,
                runner_id="runner-1",
                claim_token=claim_token,
            )

    assert created is True
    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["event_type"] == "approval.requested"
    assert kwargs["organization"] == execution.organization
    assert kwargs["context"]["event_type"] == "approval.requested"
    assert kwargs["context"]["approval_request_id"] == str(approval_request.id)
    assert kwargs["context"]["execution_id"] == str(execution.id)
    assert kwargs["context"]["step_id"] == str(step.id)
    assert kwargs["context"]["step_name"] == step.name
    assert kwargs["context"]["step_position"] == step.position
    assert kwargs["context"]["workflow_name"] == execution.workflow_snapshot["name"]


@pytest.mark.django_db
def test_approval_decision_triggers_notify_and_excludes_notes(
    pending_approval, django_capture_on_commit_callbacks
):
    with patch("apps.approvals.services.IntegrationService.notify") as notify:
        with django_capture_on_commit_callbacks(execute=True):
            decision = services.decide_approval(
                approval_request=pending_approval,
                decision="rejected",
                notes="secret incident details",
                actor_label="Test Operator",
            )

    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["event_type"] == "approval.decided"
    assert kwargs["context"]["event_type"] == "approval.decided"
    assert kwargs["context"]["approval_request_id"] == str(pending_approval.id)
    assert kwargs["context"]["approval_decision_id"] == str(decision.id)
    assert kwargs["context"]["execution_id"] == str(pending_approval.execution_id)
    assert kwargs["context"]["decision"] == "rejected"
    assert kwargs["context"]["step_name"] == pending_approval.step.name
    assert kwargs["context"]["step_position"] == pending_approval.step.position
    assert kwargs["context"]["notes_present"] is True
    assert "secret incident details" not in str(kwargs["context"])


@pytest.mark.django_db
def test_notify_failure_does_not_fail_approval_action(
    claimed_approval_execution, django_capture_on_commit_callbacks
):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    with patch(
        "apps.approvals.services.IntegrationService.notify",
        side_effect=RuntimeError("dispatch unavailable"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            approval_request, created = services.request_step_approval(
                execution=execution,
                step=step,
                runner_id="runner-1",
                claim_token=claim_token,
            )

    assert created is True
    approval_request.refresh_from_db()
    assert approval_request.status == ApprovalRequest.Status.PENDING


# ---------------------------------------------------------------------------
# Concurrency guard: double-decision tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_double_decision_serial_only_one_wins(claimed_approval_execution):
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

    services.decide_approval(
        approval_request=ar, decision="approved", actor_label="Op A"
    )

    with pytest.raises(DomainConflictError):
        services.decide_approval(
            approval_request=ar, decision="rejected", actor_label="Op B"
        )

    assert ApprovalDecision.objects.filter(approval_request=ar).count() == 1
    ar.refresh_from_db()
    assert ar.status == ApprovalRequest.Status.APPROVED


@pytest.mark.django_db(transaction=True)
def test_double_decision_concurrent_exactly_one_wins(claimed_approval_execution):
    """Two threads race to decide the same approval; exactly one must succeed."""
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

    barrier = threading.Barrier(2)
    winners = []
    losers = []

    def try_decide(decision, actor):
        barrier.wait()
        try:
            services.decide_approval(
                approval_request=ar, decision=decision, actor_label=actor
            )
            winners.append(decision)
        except DomainConflictError:
            losers.append(decision)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=try_decide, args=("approved", "Op A"))
    t2 = threading.Thread(target=try_decide, args=("rejected", "Op B"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert len(winners) == 1, f"Expected exactly one winner, got: {winners}"
    assert len(losers) == 1, f"Expected exactly one loser, got: {losers}"
    assert ApprovalDecision.objects.filter(approval_request=ar).count() == 1
    ar.refresh_from_db()
    assert ar.status in {
        ApprovalRequest.Status.APPROVED,
        ApprovalRequest.Status.REJECTED,
    }
