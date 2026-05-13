import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.audit.models import AuditEvent
from apps.audit.services import (
    AuditActor,
    AuditService,
    actor_from_runner,
    system_actor,
)
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)
from apps.common.metrics import record_approval_latency
from apps.executions import services as execution_services
from apps.executions.models import Execution, ExecutionStep
from apps.integrations.services import IntegrationService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Change-level approval request creation
# ---------------------------------------------------------------------------


def create_change_approval_request(
    *,
    change_record,
    organization,
    ttl_seconds=None,
    actor=None,
) -> "ApprovalRequest":
    """Create an ApprovalRequest for a change record (not execution-step-scoped)."""
    from apps.audit.services import AuditActor  # noqa: F401

    if organization.id != change_record.organization_id:
        raise DomainValidationError(
            code="approval_change_organization_mismatch",
            detail="Approval request organization must match the change organization.",
        )

    now = timezone.now()
    expires_at = None
    if ttl_seconds is not None:
        expires_at = now + timedelta(seconds=int(ttl_seconds))

    approval_request = ApprovalRequest.objects.create(
        organization=organization,
        subject_type=ApprovalRequest.SubjectType.CHANGE_RECORD,
        subject_id=change_record.id,
        execution=None,
        step=None,
        status=ApprovalRequest.Status.PENDING,
        requested_by_runner_id="",
        requested_at=now,
        timeout_seconds=ttl_seconds,
        expires_at=expires_at,
    )
    audit_actor = actor or system_actor()
    AuditService.emit(
        organization_id=approval_request.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type="approval.requested",
        object_type=AuditEvent.ObjectType.APPROVAL_REQUEST,
        object_id=approval_request.id,
        metadata={
            "approval_request_id": str(approval_request.id),
            "subject_type": approval_request.subject_type,
            "subject_id": str(approval_request.subject_id),
            "change_record_id": str(change_record.id),
            "timeout_seconds": ttl_seconds,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    _safe_notify_integration(
        event_type="approval.requested",
        organization=organization,
        context=_approval_request_context(
            approval_request=approval_request,
            event_type="approval.requested",
        ),
    )
    return approval_request


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
            subject_type=ApprovalRequest.SubjectType.EXECUTION_STEP,
            subject_id=step.id,
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
        audit_actor = actor_from_runner(runner_id)
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
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

    execution_services.emit_step_status_changed_event(execution=execution, step=step)
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

        approval_decision, created = ApprovalDecision.objects.get_or_create(
            approval_request=locked,
            defaults={
                "decision": ApprovalDecision.Decision.TIMED_OUT,
                "source_type": ApprovalDecision.SourceType.SYSTEM,
                "decided_at": now,
                "decided_by_label": "system",
                "decided_by_label_source": "system",
            },
        )
        if created:
            _emit_approval_decision_audit(
                approval_request=locked,
                approval_decision=approval_decision,
                actor=system_actor(),
            )
        record_approval_latency(
            outcome=locked.status,
            requested_at=locked.requested_at,
            resolved_at=locked.resolved_at,
        )

        if locked.subject_type == ApprovalRequest.SubjectType.CHANGE_RECORD:
            _handle_change_approval_decision(
                approval_request=locked,
                decision=ApprovalDecision.Decision.TIMED_OUT,
                actor=system_actor(),
            )

        return locked


def recover_expired_approvals(*, now=None, batch_size: int = 100) -> list[str]:
    """
    Resolve expired pending approvals and fail their blocked executions.

    The watchdog owns this bulk path. It preserves the existing timeout decision
    audit while adding explicit watchdog recovery events for operational triage.
    Returns approval request IDs recovered by this call.
    """
    now = now or timezone.now()
    if batch_size < 1:
        return []

    candidate_ids = list(
        ApprovalRequest.objects.filter(
            status=ApprovalRequest.Status.PENDING,
            expires_at__isnull=False,
            expires_at__lte=now,
        )
        .order_by("expires_at", "id")
        .values_list("id", flat=True)[:batch_size]
    )

    recovered: list[str] = []
    for approval_id in candidate_ids:
        recovered_id = _recover_expired_approval(approval_id=approval_id, now=now)
        if recovered_id:
            recovered.append(recovered_id)
    return recovered


def _recover_expired_approval(*, approval_id, now) -> str | None:
    with transaction.atomic():
        locked = (
            ApprovalRequest.objects.select_for_update(skip_locked=True)
            .select_related("organization")
            .filter(
                pk=approval_id,
                status=ApprovalRequest.Status.PENDING,
                expires_at__isnull=False,
                expires_at__lte=now,
            )
            .first()
        )
        if locked is None:
            return None

        updated = ApprovalRequest.objects.filter(
            pk=locked.pk,
            status=ApprovalRequest.Status.PENDING,
        ).update(
            status=ApprovalRequest.Status.TIMED_OUT,
            resolved_at=now,
            updated_at=now,
        )
        if updated != 1:
            return None

        locked.status = ApprovalRequest.Status.TIMED_OUT
        locked.resolved_at = now
        locked.updated_at = now

        approval_decision, created = ApprovalDecision.objects.get_or_create(
            approval_request=locked,
            defaults={
                "decision": ApprovalDecision.Decision.TIMED_OUT,
                "source_type": ApprovalDecision.SourceType.SYSTEM,
                "decided_at": now,
                "decided_by_label": "system",
                "decided_by_label_source": "system",
            },
        )
        if not created:
            return None

        audit_actor = system_actor()
        _emit_approval_decision_audit(
            approval_request=locked,
            approval_decision=approval_decision,
            actor=audit_actor,
        )
        timeout_meta: dict = {
            "approval_request_id": str(locked.id),
            "subject_type": locked.subject_type,
            "expires_at": locked.expires_at.isoformat() if locked.expires_at else None,
            "resolved_at": locked.resolved_at.isoformat()
            if locked.resolved_at
            else None,
            "reason": "watchdog_approval_timeout",
            "recovery_source": "watchdog",
        }
        if locked.execution_id:
            timeout_meta["execution_id"] = str(locked.execution_id)
        if locked.step_id:
            timeout_meta["step_id"] = str(locked.step_id)
        if locked.subject_id:
            timeout_meta["subject_id"] = str(locked.subject_id)

        AuditService.emit(
            organization_id=locked.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="approval.timeout",
            object_type=AuditEvent.ObjectType.APPROVAL_REQUEST,
            object_id=locked.id,
            metadata=timeout_meta,
        )

        execution_failed = False
        if locked.subject_type == ApprovalRequest.SubjectType.CHANGE_RECORD:
            _handle_change_approval_decision(
                approval_request=locked,
                decision="timed_out",
                actor=audit_actor,
            )
        elif locked.execution_id and locked.step_id:
            execution_failed = execution_services.fail_execution_for_approval_timeout(
                execution=locked.execution,
                step=locked.step,
                approval_request=locked,
                now=now,
            )

        logger.warning(
            "watchdog recovered expired approval",
            extra={
                "approval_id": str(locked.id),
                "subject_type": locked.subject_type,
                "expires_at": locked.expires_at.isoformat()
                if locked.expires_at
                else None,
                "execution_failed": execution_failed,
            },
        )
        record_approval_latency(
            outcome=locked.status,
            requested_at=locked.requested_at,
            resolved_at=locked.resolved_at,
        )

    if locked.subject_type != ApprovalRequest.SubjectType.CHANGE_RECORD:
        _safe_notify_integration(
            event_type="approval.timeout",
            organization=locked.organization,
            context=_approval_decision_context(
                approval_request=locked,
                approval_decision=approval_decision,
                event_type="approval.timeout",
            ),
        )
    return str(locked.id)


# ---------------------------------------------------------------------------
# Human decision: approve or reject
# ---------------------------------------------------------------------------


def decide_approval(
    *,
    approval_request: ApprovalRequest,
    decision: str,
    notes: str = "",
    actor: AuditActor | None = None,
    actor_label: str = "",
    actor_user=None,
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
                actor=system_actor(),
            )
            record_approval_latency(
                outcome=locked.status,
                requested_at=locked.requested_at,
                resolved_at=locked.resolved_at,
            )
            if locked.subject_type == ApprovalRequest.SubjectType.CHANGE_RECORD:
                _handle_change_approval_decision(
                    approval_request=locked,
                    decision=ApprovalDecision.Decision.TIMED_OUT,
                    actor=system_actor(),
                )
            return approval_decision

        if locked.status != ApprovalRequest.Status.PENDING:
            raise DomainConflictError(
                code="approval_request_not_pending",
                detail=f"Approval request is already in terminal state '{locked.status}'.",
            )

        audit_actor = actor or AuditActor(
            actor_type=AuditEvent.ActorType.UNKNOWN,
            actor_label=actor_label or "Unauthenticated public API",
        )

        if locked.subject_type == ApprovalRequest.SubjectType.CHANGE_EXCEPTION:
            from apps.changes import services as change_services

            change_services.apply_exception_approval_decision(
                approval_request=locked,
                decision=decision,
                actor=audit_actor,
                actor_user=actor_user,
            )

        locked.status = decision
        locked.resolved_at = now
        locked.save(update_fields=["status", "resolved_at", "updated_at"])

        approval_decision = ApprovalDecision.objects.create(
            approval_request=locked,
            decision=decision,
            source_type=ApprovalDecision.SourceType.HUMAN,
            decided_at=now,
            decided_by_user_id=audit_actor.actor_id
            if audit_actor.actor_type == AuditEvent.ActorType.USER
            else None,
            decided_by_label=audit_actor.actor_label,
            decided_by_label_source="authenticated_user"
            if audit_actor.actor_type == AuditEvent.ActorType.USER
            else "unverified_pre_auth",
            notes=notes,
        )
        _emit_approval_decision_audit(
            approval_request=locked,
            approval_decision=approval_decision,
            actor=audit_actor,
        )
        record_approval_latency(
            outcome=locked.status,
            requested_at=locked.requested_at,
            resolved_at=locked.resolved_at,
        )

        if locked.subject_type == ApprovalRequest.SubjectType.CHANGE_RECORD:
            _handle_change_approval_decision(
                approval_request=locked,
                decision=decision,
                actor=audit_actor,
            )

    if locked.subject_type == ApprovalRequest.SubjectType.CHANGE_RECORD:
        return approval_decision

    event_type = "approval.decided"
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
    actor: AuditActor,
) -> None:
    event_type = {
        ApprovalDecision.Decision.APPROVED: "approval.approved",
        ApprovalDecision.Decision.REJECTED: "approval.rejected",
        ApprovalDecision.Decision.TIMED_OUT: "approval.timed_out",
    }[approval_decision.decision]
    metadata = {
        "approval_request_id": str(approval_request.id),
        "subject_type": approval_request.subject_type,
        "decision": approval_decision.decision,
        "notes_present": bool(approval_decision.notes),
    }
    if approval_request.execution_id:
        metadata["execution_id"] = str(approval_request.execution_id)
    if approval_request.step_id:
        metadata["step_id"] = str(approval_request.step_id)
    if approval_request.subject_id:
        metadata["subject_id"] = str(approval_request.subject_id)
    AuditService.emit(
        organization_id=approval_request.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.APPROVAL_DECISION,
        object_id=approval_decision.id,
        metadata=metadata,
    )


def _handle_change_approval_decision(
    *,
    approval_request: ApprovalRequest,
    decision: str,
    actor: AuditActor,
) -> None:
    """Callback for change-record approval decisions. Must be called inside the same transaction."""
    from apps.changes import services as change_services  # avoid circular

    change_services.handle_change_approval_decision(
        approval_request_id=approval_request.id,
        decision=decision,
        actor=actor,
    )


def _safe_notify_integration(*, event_type: str, organization, context: dict) -> None:
    def notify() -> None:
        try:
            IntegrationService.notify(
                event_type=event_type,
                organization=organization,
                context=dict(context),
            )
        except Exception:
            logger.exception("Integration notify failed for %s.", event_type)

    transaction.on_commit(notify)


def _approval_request_context(
    *, approval_request: ApprovalRequest, event_type: str
) -> dict:
    ctx: dict = {
        "event_type": event_type,
        "organization_id": str(approval_request.organization_id),
        "approval_request_id": str(approval_request.id),
        "subject_type": approval_request.subject_type,
        "approval_status": approval_request.status,
        "timeout_seconds": approval_request.timeout_seconds,
        "expires_at": approval_request.expires_at.isoformat()
        if approval_request.expires_at
        else None,
    }
    if approval_request.execution_id:
        ctx["execution_id"] = str(approval_request.execution_id)
    if approval_request.step_id and approval_request.step:
        ctx["step_id"] = str(approval_request.step_id)
        ctx["step_name"] = approval_request.step.name
        ctx["step_position"] = approval_request.step.position
        ctx["workflow_id"] = str(approval_request.execution.workflow_id)
        ctx["workflow_name"] = _workflow_name(approval_request.execution)
    if approval_request.subject_id:
        ctx["subject_id"] = str(approval_request.subject_id)
    return ctx


def _approval_decision_context(
    *,
    approval_request: ApprovalRequest,
    approval_decision: ApprovalDecision,
    event_type: str,
) -> dict:
    ctx: dict = {
        "event_type": event_type,
        "organization_id": str(approval_request.organization_id),
        "approval_request_id": str(approval_request.id),
        "approval_decision_id": str(approval_decision.id),
        "subject_type": approval_request.subject_type,
        "approval_status": approval_request.status,
        "decision": approval_decision.decision,
        "source_type": approval_decision.source_type,
        "decided_at": approval_decision.decided_at.isoformat()
        if approval_decision.decided_at
        else None,
        "notes_present": bool(approval_decision.notes),
    }
    if approval_request.execution_id:
        ctx["execution_id"] = str(approval_request.execution_id)
    if approval_request.step_id and approval_request.step:
        ctx["step_id"] = str(approval_request.step_id)
        ctx["step_name"] = approval_request.step.name
        ctx["step_position"] = approval_request.step.position
        ctx["workflow_id"] = str(approval_request.execution.workflow_id)
        ctx["workflow_name"] = _workflow_name(approval_request.execution)
    if approval_request.subject_id:
        ctx["subject_id"] = str(approval_request.subject_id)
    return ctx


def _workflow_name(execution: Execution) -> str:
    name = execution.workflow_snapshot.get("name")
    return name if isinstance(name, str) and name else ""
