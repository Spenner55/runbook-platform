from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.common.exceptions import DomainConflictError, InvalidStateTransitionError
from apps.executions.models import Execution, ExecutionStep


# ---------------------------------------------------------------------------
# Runner-facing service: create/reuse an approval request for a step
# ---------------------------------------------------------------------------


def request_step_approval(
    *,
    execution: Execution,
    step: ExecutionStep,
    runner_id: str,
    claim_token: str,
) -> tuple[ApprovalRequest, bool]:
    """
    Atomically transition the step to waiting_for_approval and create or
    reuse the ApprovalRequest. Returns (approval_request, created).
    created=False means the request already existed (idempotent retry).
    """
    with transaction.atomic():
        execution = Execution.objects.select_for_update().get(pk=execution.pk)
        step = ExecutionStep.objects.select_for_update().get(pk=step.pk)

        _check_runner_ownership(execution, runner_id, claim_token)

        # Idempotency: if already in the approval flow, return the existing request.
        if step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL:
            try:
                existing = ApprovalRequest.objects.get(step=step)
                return existing, False
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

        if not step.requires_approval:
            raise InvalidStateTransitionError(
                code="approval_not_required_for_step",
                detail="This step does not require approval.",
            )

        now = timezone.now()
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
        return approval_request, True


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

        ApprovalDecision.objects.create(
            approval_request=locked,
            decision=ApprovalDecision.Decision.TIMED_OUT,
            source_type=ApprovalDecision.SourceType.SYSTEM,
            decided_at=now,
            decided_by_label="system",
            decided_by_label_source="system",
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
        if locked.status == ApprovalRequest.Status.PENDING and locked.expires_at and locked.expires_at <= now:
            locked.status = ApprovalRequest.Status.TIMED_OUT
            locked.resolved_at = now
            locked.save(update_fields=["status", "resolved_at", "updated_at"])
            ApprovalDecision.objects.create(
                approval_request=locked,
                decision=ApprovalDecision.Decision.TIMED_OUT,
                source_type=ApprovalDecision.SourceType.SYSTEM,
                decided_at=now,
                decided_by_label="system",
                decided_by_label_source="system",
            )

        if locked.status != ApprovalRequest.Status.PENDING:
            raise DomainConflictError(
                code="approval_request_not_pending",
                detail=f"Approval request is already in terminal state '{locked.status}'.",
            )

        locked.status = decision
        locked.resolved_at = now
        locked.save(update_fields=["status", "resolved_at", "updated_at"])

        return ApprovalDecision.objects.create(
            approval_request=locked,
            decision=decision,
            source_type=ApprovalDecision.SourceType.HUMAN,
            decided_at=now,
            decided_by_label=actor_label,
            decided_by_label_source="unverified_pre_auth",
            notes=notes,
        )


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


def _check_runner_ownership(execution: Execution, runner_id: str, claim_token: str) -> None:
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
