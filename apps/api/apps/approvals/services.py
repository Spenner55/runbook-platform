import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.common.exceptions import DomainConflictError, InvalidStateTransitionError
from apps.executions import services as execution_services
from apps.executions.models import Execution, ExecutionStep
from apps.integrations.services import IntegrationService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runner-facing service: create/reuse an approval request for a step
# ---------------------------------------------------------------------------


def request_step_approval(
    *,
    execution: Execution,
    step: ExecutionStep,
    runner_id: str,
    claim_token: str,
    policy_driven: bool = False,
    policy_evaluation=None,
) -> tuple[ApprovalRequest, bool]:
    """
    Atomically transition the step to waiting_for_approval and create or
    reuse the ApprovalRequest. Returns (approval_request, created).
    created=False means the request already existed (idempotent retry).
    """
    with transaction.atomic():
        execution = Execution.objects.select_for_update().get(pk=execution.pk)
        step = ExecutionStep.objects.select_for_update().get(pk=step.pk)

        _check_step_execution_invariants(execution, step)
        _check_runner_ownership(execution, runner_id, claim_token)

        # Idempotency: if already in the approval flow, return the existing request.
        if step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL:
            try:
                existing = ApprovalRequest.objects.get(step=step)
                approval_request = existing
                created = False
                return approval_request, created
            except ApprovalRequest.DoesNotExist:
                pass

        if step.status != ExecutionStep.Status.PENDING:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=(
                    f"Cannot create approval request: step status is '{step.status}',"
                    " expected 'pending'."
                ),
            )

        if not step.requires_approval and not policy_driven:
            raise InvalidStateTransitionError(
                code="approval_not_required_for_step",
                detail="This step does not require approval.",
            )

        now = timezone.now()
        previous_status = step.status
        step.status = ExecutionStep.Status.WAITING_FOR_APPROVAL
        step.save(update_fields=["status", "updated_at"])

        timeout_seconds = step.step_snapshot.get("approvalTimeoutSeconds")
        expires_at = None
        if timeout_seconds is not None:
            expires_at = now + timedelta(seconds=int(timeout_seconds))

        approval_request = ApprovalRequest.objects.create(
            organization=execution.organization,
            execution=execution,
            step=step,
            status=ApprovalRequest.Status.PENDING,
            requested_by_runner_id=runner_id,
            requested_at=now,
            timeout_seconds=timeout_seconds,
            expires_at=expires_at,
        )
        execution_services.emit_step_waiting_for_approval_audit(
            execution=execution,
            step=step,
            runner_id=runner_id,
            previous_status=previous_status,
        )
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=AuditEvent.ActorType.RUNNER,
            actor_id=runner_id,
            actor_label=runner_id,
            event_type="approval.requested",
            object_type=AuditEvent.ObjectType.APPROVAL_REQUEST,
            object_id=approval_request.id,
            metadata={
                "execution_id": str(execution.id),
                "step_id": str(step.id),
                "policy_evaluation_id": str(policy_evaluation.id)
                if policy_evaluation
                else "",
                "timeout_seconds": timeout_seconds,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        created = True

    _safe_notify_integration(
        event_type="approval.requested",
        organization=execution.organization,
        context=_approval_request_context(
            approval_request=approval_request,
            event_type="approval.requested",
        ),
    )
    return approval_request, created


# ---------------------------------------------------------------------------
# Control-plane read: resolve timeout and return current request state
# ---------------------------------------------------------------------------


def get_approval_status(*, approval_request: ApprovalRequest) -> ApprovalRequest:
    """
    Resolve expiration to timed_out exactly once if the deadline has passed.
    Returns the (possibly updated) request. Safe to call repeatedly.
    """
    if approval_request.status != ApprovalRequest.Status.PENDING:
        return approval_request

    now = timezone.now()
    if not approval_request.expires_at or approval_request.expires_at > now:
        return approval_request

    with transaction.atomic():
        locked = ApprovalRequest.objects.select_for_update().get(pk=approval_request.pk)
        if locked.status != ApprovalRequest.Status.PENDING:
            return locked

        locked.status = ApprovalRequest.Status.TIMED_OUT
        locked.resolved_at = now
        locked.save(update_fields=["status", "resolved_at", "updated_at"])

        approval_decision = ApprovalDecision.objects.create(
            approval_request=locked,
            decision=ApprovalDecision.Decision.TIMED_OUT,
            source_type=ApprovalDecision.SourceType.SYSTEM,
            decided_at=now,
            decided_by_label="system",
            decided_by_label_source="system",
        )
        _emit_approval_decision_audit(
            approval_request=locked,
            approval_decision=approval_decision,
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_id="",
            actor_label="Django system",
        )
        return locked


# ---------------------------------------------------------------------------
# Human decision: approve or reject
# ---------------------------------------------------------------------------


def decide_approval(
    *,
    approval_request: ApprovalRequest,
    decision: str,
    notes: str = "",
    actor_label: str,
) -> ApprovalDecision:
    """
    Apply a human decision to a pending approval request.
    Uses select_for_update to prevent double-decision races.
    """
    with transaction.atomic():
        locked = ApprovalRequest.objects.select_for_update().get(pk=approval_request.pk)

        # Resolve timeout before checking decidability.
        now = timezone.now()
        if (
            locked.status == ApprovalRequest.Status.PENDING
            and locked.expires_at
            and locked.expires_at <= now
        ):
            locked.status = ApprovalRequest.Status.TIMED_OUT
            locked.resolved_at = now
            locked.save(update_fields=["status", "resolved_at", "updated_at"])
            approval_decision = ApprovalDecision.objects.create(
                approval_request=locked,
                decision=ApprovalDecision.Decision.TIMED_OUT,
                source_type=ApprovalDecision.SourceType.SYSTEM,
                decided_at=now,
                decided_by_label="system",
                decided_by_label_source="system",
            )
            _emit_approval_decision_audit(
                approval_request=locked,
                approval_decision=approval_decision,
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_id="",
                actor_label="Django system",
            )
            return approval_decision

        if locked.status != ApprovalRequest.Status.PENDING:
            raise DomainConflictError(
                code="approval_request_not_pending",
                detail=f"Approval request is already in terminal state '{locked.status}'.",
            )

        locked.status = decision
        locked.resolved_at = now
        locked.save(update_fields=["status", "resolved_at", "updated_at"])

        approval_decision = ApprovalDecision.objects.create(
            approval_request=locked,
            decision=decision,
            source_type=ApprovalDecision.SourceType.HUMAN,
            decided_at=now,
            decided_by_label=actor_label,
            decided_by_label_source="unverified_pre_auth",
            notes=notes,
        )
        _emit_approval_decision_audit(
            approval_request=locked,
            approval_decision=approval_decision,
            actor_type=AuditEvent.ActorType.UNKNOWN,
            actor_id="",
            actor_label=actor_label or "Unauthenticated public API",
        )
    event_type = {
        ApprovalDecision.Decision.APPROVED: "approval.approved",
        ApprovalDecision.Decision.REJECTED: "approval.rejected",
    }[approval_decision.decision]
    _safe_notify_integration(
        event_type=event_type,
        organization=locked.organization,
        context=_approval_decision_context(
            approval_request=locked,
            approval_decision=approval_decision,
            event_type=event_type,
        ),
    )
    return approval_decision


# ---------------------------------------------------------------------------
# Inbox query
# ---------------------------------------------------------------------------


def list_approvals(*, organization, status=None, execution_id=None):
    """Return approval requests filtered by organization, optionally by status/execution."""
    qs = (
        ApprovalRequest.objects.filter(organization=organization)
        .select_related("step", "execution")
        .prefetch_related("decision")
    )

    if status and status != "all":
        qs = qs.filter(status=status)
    elif not status:
        qs = qs.filter(status=ApprovalRequest.Status.PENDING)

    if execution_id:
        qs = qs.filter(execution_id=execution_id)

    return qs


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _check_step_execution_invariants(execution: Execution, step: ExecutionStep) -> None:
    if str(step.execution_id) != str(execution.id):
        raise InvalidStateTransitionError(
            code="step_execution_mismatch",
            detail="Step does not belong to the given execution.",
        )
    if str(step.execution.organization_id) != str(execution.organization_id):
        raise InvalidStateTransitionError(
            code="organization_mismatch",
            detail="Step execution organization does not match.",
        )


def _check_runner_ownership(
    execution: Execution, runner_id: str, claim_token: str
) -> None:
    if execution.claimed_by_runner_id != runner_id:
        raise InvalidStateTransitionError(
            code="runner_ownership_mismatch",
            detail="Runner ID does not match execution owner.",
        )
    if str(execution.claim_token) != claim_token:
        raise InvalidStateTransitionError(
            code="claim_token_mismatch",
            detail="Claim token is invalid.",
        )


def _emit_approval_decision_audit(
    *,
    approval_request: ApprovalRequest,
    approval_decision: ApprovalDecision,
    actor_type: str,
    actor_id: str,
    actor_label: str,
) -> None:
    event_type = {
        ApprovalDecision.Decision.APPROVED: "approval.approved",
        ApprovalDecision.Decision.REJECTED: "approval.rejected",
        ApprovalDecision.Decision.TIMED_OUT: "approval.timed_out",
    }[approval_decision.decision]
    AuditService.emit(
        organization_id=approval_request.organization_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.APPROVAL_DECISION,
        object_id=approval_decision.id,
        metadata={
            "approval_request_id": str(approval_request.id),
            "execution_id": str(approval_request.execution_id),
            "step_id": str(approval_request.step_id),
            "decision": approval_decision.decision,
            "notes_present": bool(approval_decision.notes),
        },
    )


def _safe_notify_integration(*, event_type: str, organization, context: dict) -> None:
    try:
        IntegrationService.notify(
            event_type=event_type,
            organization=organization,
            context=context,
        )
    except Exception:
        logger.exception("Integration notify failed for %s.", event_type)


def _approval_request_context(
    *, approval_request: ApprovalRequest, event_type: str
) -> dict:
    return {
        "event_type": event_type,
        "organization_id": str(approval_request.organization_id),
        "approval_request_id": str(approval_request.id),
        "execution_id": str(approval_request.execution_id),
        "step_id": str(approval_request.step_id),
        "approval_status": approval_request.status,
        "timeout_seconds": approval_request.timeout_seconds,
        "expires_at": approval_request.expires_at.isoformat()
        if approval_request.expires_at
        else None,
    }


def _approval_decision_context(
    *,
    approval_request: ApprovalRequest,
    approval_decision: ApprovalDecision,
    event_type: str,
) -> dict:
    return {
        "event_type": event_type,
        "organization_id": str(approval_request.organization_id),
        "approval_request_id": str(approval_request.id),
        "approval_decision_id": str(approval_decision.id),
        "execution_id": str(approval_request.execution_id),
        "step_id": str(approval_request.step_id),
        "approval_status": approval_request.status,
        "decision": approval_decision.decision,
        "source_type": approval_decision.source_type,
        "decided_at": approval_decision.decided_at.isoformat()
        if approval_decision.decided_at
        else None,
        "notes_present": bool(approval_decision.notes),
    }
