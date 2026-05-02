import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

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
    InvalidWorkflowDefinitionError,
)
from apps.common.metrics import (
    record_execution_event,
    record_step_duration,
    record_step_transition,
    record_stuck_execution_recovery,
    timed_execution_operation,
)
from apps.executions.event_bus import StreamEvent, execution_event_bus
from apps.executions.models import Execution, ExecutionStep
from apps.integrations.services import IntegrationService
from apps.workflows.models import Workflow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


@timed_execution_operation("create_execution")
def create_execution(
    *,
    workflow: Workflow,
    actor: AuditActor | None = None,
    _from_change_service: bool = False,
) -> Execution:
    """
    Create an immutable execution snapshot from a published workflow,
    expanding workflow steps into ExecutionStep rows atomically.

    The definition is validated outside the transaction so no partial state
    can be committed on a structurally invalid workflow.
    """
    if workflow.status != Workflow.Status.PUBLISHED:
        raise DomainValidationError(
            code="workflow_not_published",
            detail=(
                f"Cannot create execution: workflow has status '{workflow.status}', "
                f"expected 'published'."
            ),
        )

    if workflow.requires_review:
        raise DomainValidationError(
            code="workflow_requires_review",
            detail="Workflow requires human review before it can be executed.",
        )

    if not _from_change_service:
        from apps.changes.models import OperationProfile  # avoid circular
        if OperationProfile.objects.filter(is_active=True, allowed_workflows=workflow).exists():
            raise DomainConflictError(
                code="workflow_requires_change_record",
                detail=(
                    "This workflow is managed by an active operation profile "
                    "and must be executed through a change record."
                ),
            )

    definition = workflow.definition
    _validate_workflow_definition(definition)

    try:
        with transaction.atomic():
            execution = Execution.objects.create(
                organization=workflow.organization,
                workflow=workflow,
                workflow_version=workflow.version,
                workflow_snapshot=definition,
                status=Execution.Status.QUEUED,
            )

            step_rows = [
                ExecutionStep(
                    execution=execution,
                    position=position,
                    step_key=step["id"],
                    name=step["name"],
                    step_type=step.get("type", ""),
                    risk_level=step.get("risk", ""),
                    command=step.get("command", ""),
                    requires_approval=step.get("requiresApproval", False),
                    step_snapshot=step,
                    status=ExecutionStep.Status.PENDING,
                )
                for position, step in enumerate(definition["steps"], start=1)
            ]
            ExecutionStep.objects.bulk_create(step_rows)
            AuditService.emit(
                organization_id=execution.organization_id,
                actor_type=(actor or system_actor()).actor_type,
                actor_id=(actor or system_actor()).actor_id,
                actor_label=(actor or system_actor()).actor_label,
                event_type="execution.created",
                object_type=AuditEvent.ObjectType.EXECUTION,
                object_id=execution.id,
                metadata={
                    "workflow_id": str(workflow.id),
                    "workflow_version": workflow.version,
                    "initial_status": execution.status,
                },
            )

        _safe_notify_integration(
            event_type="execution.created",
            organization=execution.organization,
            context=_execution_context(
                execution=execution,
                event_type="execution.created",
                previous_status="",
            ),
        )
        record_execution_event(event="created", status=execution.status)
        return execution
    except IntegrityError as exc:
        raise InvalidWorkflowDefinitionError(
            code="execution_step_materialization_failed",
            detail="Execution steps could not be materialized from the workflow definition.",
        ) from exc


def create_execution_from_workflow(*, workflow: Workflow) -> Execution:
    """Convenience wrapper — prefer create_execution for new call sites."""
    return create_execution(workflow=workflow)


@timed_execution_operation("cancel_execution")
def cancel_execution(
    *, execution: Execution, actor: AuditActor | None = None
) -> Execution:
    """Cancel a queued execution. Only queued executions may be cancelled."""
    with transaction.atomic():
        execution = Execution.objects.select_for_update().get(pk=execution.pk)
        if execution.status != Execution.Status.QUEUED:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Cannot cancel execution with status '{execution.status}', expected 'queued'.",
            )
        previous_status = execution.status
        execution.status = Execution.Status.CANCELLED
        execution.save(update_fields=["status", "updated_at"])
        audit_actor = actor or system_actor()
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="execution.cancelled",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=execution.id,
            metadata={
                "previous_status": previous_status,
                "new_status": execution.status,
            },
        )
    _ts = execution.updated_at.isoformat()
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="execution.status_changed",
            data={
                "execution_id": str(execution.id),
                "status": execution.status,
                "timestamp": _ts,
                "started_at": None,
                "finished_at": None,
            },
        ),
    )
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="stream.closed",
            data={
                "execution_id": str(execution.id),
                "final_status": execution.status,
                "timestamp": _ts,
                "reason": "terminal_state",
            },
        ),
    )
    _safe_notify_integration(
        event_type="execution.cancelled",
        organization=execution.organization,
        context=_execution_context(
            execution=execution,
            event_type="execution.cancelled",
            previous_status=previous_status,
        ),
    )
    record_execution_event(event="cancelled", status=execution.status)
    return execution


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@timed_execution_operation("recover_stuck_executions")
def recover_stuck_executions(*, stuck_threshold_seconds: int = 300) -> list[str]:
    """
    Sweep for executions in claimed/running whose last_heartbeat_at is older
    than stuck_threshold_seconds. For each, transition the execution to failed,
    fail any running steps, and emit an audit event.

    Uses select_for_update(skip_locked=True) per execution so concurrent
    invocations skip rows already being processed without double-failing them.
    Returns a list of recovered execution IDs.
    """
    stale_before = timezone.now() - timedelta(seconds=stuck_threshold_seconds)
    stuck_statuses = (Execution.Status.CLAIMED, Execution.Status.RUNNING)

    candidate_ids = list(
        Execution.objects.filter(
            status__in=stuck_statuses,
            last_heartbeat_at__lt=stale_before,
        ).values_list("id", flat=True)
    )

    recovered: list[str] = []
    for exec_id in candidate_ids:
        with transaction.atomic():
            execution = (
                Execution.objects.select_for_update(skip_locked=True)
                .filter(
                    id=exec_id,
                    status__in=stuck_statuses,
                    last_heartbeat_at__lt=stale_before,
                )
                .first()
            )
            if execution is None:
                continue

            now = timezone.now()
            previous_status = execution.status
            execution.status = Execution.Status.FAILED
            execution.finished_at = now
            if not execution.started_at:
                execution.started_at = now
            execution.save(
                update_fields=["status", "finished_at", "started_at", "updated_at"]
            )

            running_steps = list(
                ExecutionStep.objects.select_for_update().filter(
                    execution=execution,
                    status=ExecutionStep.Status.RUNNING,
                )
            )
            for step in running_steps:
                step.status = ExecutionStep.Status.FAILED
                step.finished_at = now
                step.error_message = "Step marked failed by watchdog: heartbeat timeout"
                step.save(
                    update_fields=[
                        "status",
                        "finished_at",
                        "error_message",
                        "updated_at",
                    ]
                )

            logger.warning(
                "watchdog recovered stuck execution %s (was %s, %d running step(s) failed)",
                execution.id,
                previous_status,
                len(running_steps),
            )

            AuditService.emit(
                organization_id=execution.organization_id,
                actor_type=system_actor().actor_type,
                actor_id=system_actor().actor_id,
                actor_label=system_actor().actor_label,
                event_type="execution.failed",
                object_type=AuditEvent.ObjectType.EXECUTION,
                object_id=execution.id,
                metadata={
                    "previous_status": previous_status,
                    "new_status": execution.status,
                    "reason": "watchdog_heartbeat_timeout",
                    "stuck_threshold_seconds": stuck_threshold_seconds,
                    "running_steps_failed": len(running_steps),
                },
            )

            recovered.append(str(execution.id))
            record_execution_event(event="watchdog_recovered", status=execution.status)
            record_stuck_execution_recovery(
                reason="heartbeat_timeout",
                status=execution.status,
            )
            for _step in running_steps:
                record_step_transition(status=_step.status)
                _record_step_duration_if_available(_step)

    return recovered


@timed_execution_operation("fail_execution_for_approval_timeout")
def fail_execution_for_approval_timeout(
    *,
    execution: Execution,
    step: ExecutionStep,
    approval_request,
    now=None,
) -> bool:
    """
    Fail an execution blocked on an expired approval request.

    Returns True when this call performed the execution failure. Returns False
    when the execution was already terminal or no longer in the approval wait
    state, which keeps watchdog retries idempotent.
    """
    now = now or timezone.now()

    with transaction.atomic():
        execution = Execution.objects.select_for_update().get(pk=execution.pk)
        step = ExecutionStep.objects.select_for_update().get(
            pk=step.pk,
            execution=execution,
        )

        active_execution_statuses = (
            Execution.Status.CLAIMED,
            Execution.Status.RUNNING,
        )
        if execution.status not in active_execution_statuses:
            return False

        if step.status != ExecutionStep.Status.WAITING_FOR_APPROVAL:
            return False

        previous_execution_status = execution.status
        previous_step_status = step.status

        step.status = ExecutionStep.Status.FAILED
        step.finished_at = now
        step.error_message = "Step marked failed by watchdog: approval timeout"
        step.save(
            update_fields=[
                "status",
                "finished_at",
                "error_message",
                "updated_at",
            ]
        )

        execution.status = Execution.Status.FAILED
        execution.finished_at = now
        if not execution.started_at:
            execution.started_at = now
        execution.save(
            update_fields=["status", "finished_at", "started_at", "updated_at"]
        )

        audit_actor = system_actor()
        common_metadata = {
            "approval_request_id": str(approval_request.id),
            "execution_id": str(execution.id),
            "step_id": str(step.id),
            "expires_at": approval_request.expires_at.isoformat()
            if approval_request.expires_at
            else None,
            "reason": "watchdog_approval_timeout",
            "recovery_source": "watchdog",
        }
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="execution_step.failed",
            object_type=AuditEvent.ObjectType.EXECUTION_STEP,
            object_id=step.id,
            metadata={
                **common_metadata,
                "step_key": step.step_key,
                "position": step.position,
                "previous_status": previous_step_status,
                "new_status": step.status,
                "error_message": step.error_message,
            },
        )
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="execution.failed",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=execution.id,
            metadata={
                **common_metadata,
                "previous_status": previous_execution_status,
                "new_status": execution.status,
            },
        )
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="execution.approval_timeout",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=execution.id,
            metadata={
                **common_metadata,
                "previous_status": previous_execution_status,
                "new_status": execution.status,
            },
        )

    _emit_step_status_changed_event(execution=execution, step=step)
    _ts = (
        execution.finished_at.isoformat() if execution.finished_at else now.isoformat()
    )
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="execution.status_changed",
            data={
                "execution_id": str(execution.id),
                "status": execution.status,
                "timestamp": _ts,
                "started_at": execution.started_at.isoformat()
                if execution.started_at
                else None,
                "finished_at": execution.finished_at.isoformat()
                if execution.finished_at
                else None,
            },
        ),
    )
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="stream.closed",
            data={
                "execution_id": str(execution.id),
                "final_status": execution.status,
                "timestamp": _ts,
                "reason": "approval_timeout",
            },
        ),
    )
    _safe_notify_integration(
        event_type="execution_step.failed",
        organization=execution.organization,
        context=_step_context(
            execution=execution,
            step=step,
            event_type="execution_step.failed",
            previous_status=previous_step_status,
            new_status=step.status,
        ),
    )
    _safe_notify_integration(
        event_type="execution.failed",
        organization=execution.organization,
        context=_execution_context(
            execution=execution,
            event_type="execution.failed",
            previous_status=previous_execution_status,
        ),
    )
    record_step_transition(status=step.status)
    record_execution_event(event="approval_timeout", status=execution.status)
    return True


def _validate_workflow_definition(definition: dict) -> None:
    """Validate that a workflow definition can be expanded into execution steps."""
    if not isinstance(definition, dict):
        raise InvalidWorkflowDefinitionError(
            code="invalid_workflow_definition",
            detail="Workflow definition is not a valid object.",
        )
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        raise InvalidWorkflowDefinitionError(
            code="workflow_has_no_steps",
            detail="Workflow definition must contain at least one step.",
        )
    seen_ids: set[str] = set()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step at position {i + 1} is not a valid object.",
            )
        step_id = step.get("id")
        if not step_id:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step at position {i + 1} is missing 'id'.",
            )
        if step_id in seen_ids:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Duplicate step id '{step_id}' in workflow definition.",
            )
        seen_ids.add(step_id)


# ---------------------------------------------------------------------------
# Internal runner service functions
# ---------------------------------------------------------------------------


@timed_execution_operation("claim_next_execution")
def claim_next_execution(*, runner_id: str) -> dict | None:
    """
    Atomically claim the oldest queued execution for the given runner.

    Returns a dict with 'execution', 'steps', and 'claim_token' if work was
    found, or None if the queue is empty.
    """
    with transaction.atomic():
        execution = (
            Execution.objects.select_for_update(skip_locked=True)
            .filter(status=Execution.Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        reclaimed = False
        if execution is None:
            stale_before = timezone.now() - timedelta(
                seconds=settings.RUNNER_STALE_HEARTBEAT_SECONDS
            )
            waiting_step = ExecutionStep.objects.filter(
                execution_id=OuterRef("pk"),
                status=ExecutionStep.Status.WAITING_FOR_APPROVAL,
            )
            running_step = ExecutionStep.objects.filter(
                execution_id=OuterRef("pk"),
                status=ExecutionStep.Status.RUNNING,
            )
            execution = (
                Execution.objects.select_for_update(skip_locked=True)
                .annotate(
                    has_waiting_step=Exists(waiting_step),
                    has_running_step=Exists(running_step),
                )
                .filter(
                    status__in=(Execution.Status.CLAIMED, Execution.Status.RUNNING),
                    last_heartbeat_at__lt=stale_before,
                    has_waiting_step=True,
                    has_running_step=False,
                )
                .order_by("last_heartbeat_at", "created_at")
                .first()
            )
            reclaimed = execution is not None
        if execution is None:
            return None

        claim_token = uuid.uuid4()
        now = timezone.now()
        previous_status = execution.status
        if execution.status != Execution.Status.RUNNING:
            execution.status = Execution.Status.CLAIMED
        execution.claimed_by_runner_id = runner_id
        execution.claim_token = claim_token
        execution.claimed_at = now
        execution.last_heartbeat_at = now
        execution.save(
            update_fields=[
                "status",
                "claimed_by_runner_id",
                "claim_token",
                "claimed_at",
                "last_heartbeat_at",
                "updated_at",
            ]
        )
        audit_actor = actor_from_runner(runner_id)
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="execution.claimed",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=execution.id,
            metadata={
                "previous_status": previous_status,
                "new_status": execution.status,
                "claimed_at": now.isoformat(),
                "reclaimed": reclaimed,
            },
        )

        steps = list(execution.steps.order_by("position"))
        result = {
            "execution": execution,
            "steps": steps,
            "claim_token": str(claim_token),
        }

    if previous_status != execution.status:
        _emit_on_commit(
            str(execution.id),
            StreamEvent(
                event_type="execution.status_changed",
                data={
                    "execution_id": str(execution.id),
                    "status": execution.status,
                    "timestamp": execution.claimed_at.isoformat(),
                    "started_at": execution.started_at.isoformat()
                    if execution.started_at
                    else None,
                    "finished_at": execution.finished_at.isoformat()
                    if execution.finished_at
                    else None,
                },
            ),
        )
    record_execution_event(event="claimed", status=execution.status)
    return result


def _validate_runner_ownership(
    execution: Execution, runner_id: str, claim_token: str
) -> None:
    """Raise InvalidStateTransitionError if the given runner_id/claim_token doesn't own this execution."""
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


@timed_execution_operation("heartbeat_execution")
def heartbeat_execution(
    *,
    execution: Execution,
    runner_id: str,
    claim_token: str,
) -> Execution:
    """Update last_heartbeat_at for an active execution owned by the runner."""
    if execution.status not in (Execution.Status.CLAIMED, Execution.Status.RUNNING):
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot heartbeat execution with status '{execution.status}'.",
        )
    _validate_runner_ownership(execution, runner_id, claim_token)
    execution.last_heartbeat_at = timezone.now()
    execution.save(update_fields=["last_heartbeat_at", "updated_at"])
    return execution


_VALID_STEP_TRANSITIONS: dict[str, set[str]] = {
    ExecutionStep.Status.PENDING: {
        ExecutionStep.Status.RUNNING,
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.WAITING_FOR_APPROVAL: {
        ExecutionStep.Status.RUNNING,
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.RUNNING: {
        ExecutionStep.Status.SUCCEEDED,
        ExecutionStep.Status.FAILED,
    },
}


@timed_execution_operation("update_execution_step")
def update_execution_step(
    *,
    execution: Execution,
    step_id: str,
    runner_id: str,
    claim_token: str,
    new_status: str,
    started_at=None,
    finished_at=None,
    exit_code=None,
    error_message: str = "",
) -> ExecutionStep:
    """
    Apply a narrow status transition to one step on an execution.

    Allowed transitions:
      pending  -> running
      running  -> succeeded | failed

    Also transitions the parent execution from CLAIMED -> RUNNING when the
    first step starts.
    """
    execution_started = False
    with transaction.atomic():
        execution = Execution.objects.select_for_update().get(pk=execution.pk)
        _validate_runner_ownership(execution, runner_id, claim_token)

        try:
            step = ExecutionStep.objects.select_for_update().get(
                pk=step_id, execution=execution
            )
        except ExecutionStep.DoesNotExist:
            raise InvalidStateTransitionError(
                code="step_not_found",
                detail=f"Step {step_id} not found on execution {execution.id}.",
            )

        previous_status = step.status
        allowed = _VALID_STEP_TRANSITIONS.get(step.status, set())
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Invalid step transition: '{step.status}' -> '{new_status}'.",
            )

        now = timezone.now()
        update_fields = ["status", "updated_at"]
        step.status = new_status

        if new_status == ExecutionStep.Status.RUNNING:
            step.started_at = started_at or now
            update_fields.append("started_at")

        if new_status in (ExecutionStep.Status.SUCCEEDED, ExecutionStep.Status.FAILED):
            step.finished_at = finished_at or now
            update_fields.append("finished_at")
            if exit_code is not None:
                step.exit_code = exit_code
                update_fields.append("exit_code")
            if error_message:
                step.error_message = error_message
                update_fields.append("error_message")

        step.save(update_fields=update_fields)

        # Transition execution CLAIMED -> RUNNING when first step starts running.
        if (
            execution.status == Execution.Status.CLAIMED
            and new_status == ExecutionStep.Status.RUNNING
        ):
            execution_started = True
            execution.status = Execution.Status.RUNNING
            if not execution.started_at:
                execution.started_at = step.started_at
            execution.save(update_fields=["status", "started_at", "updated_at"])

        _emit_step_transition_audit(
            execution=execution,
            step=step,
            runner_id=runner_id,
            previous_status=previous_status,
            new_status=new_status,
            error_message=error_message,
        )
    _ts = timezone.now().isoformat()
    _emit_step_status_changed_event(execution=execution, step=step)
    if execution_started:
        _emit_on_commit(
            str(execution.id),
            StreamEvent(
                event_type="execution.status_changed",
                data={
                    "execution_id": str(execution.id),
                    "status": execution.status,
                    "timestamp": execution.started_at.isoformat()
                    if execution.started_at
                    else _ts,
                    "started_at": execution.started_at.isoformat()
                    if execution.started_at
                    else None,
                    "finished_at": None,
                },
            ),
        )
        record_execution_event(event="started", status=execution.status)
    if execution_started:
        _safe_notify_integration(
            event_type="execution.started",
            organization=execution.organization,
            context=_execution_context(
                execution=execution,
                event_type="execution.started",
                previous_status=Execution.Status.CLAIMED,
            ),
        )
    if new_status in (
        ExecutionStep.Status.WAITING_FOR_APPROVAL,
        ExecutionStep.Status.RUNNING,
        ExecutionStep.Status.FAILED,
    ):
        event_type = {
            ExecutionStep.Status.WAITING_FOR_APPROVAL: "execution_step.waiting_for_approval",
            ExecutionStep.Status.RUNNING: "execution_step.started",
            ExecutionStep.Status.FAILED: "execution_step.failed",
        }[new_status]
        _safe_notify_integration(
            event_type=event_type,
            organization=execution.organization,
            context=_step_context(
                execution=execution,
                step=step,
                event_type=event_type,
                previous_status=previous_status,
                new_status=new_status,
            ),
        )
    record_step_transition(status=step.status)
    if new_status in (ExecutionStep.Status.SUCCEEDED, ExecutionStep.Status.FAILED):
        _record_step_duration_if_available(step)
    return step


@timed_execution_operation("complete_execution")
def complete_execution(
    *,
    execution: Execution,
    runner_id: str,
    claim_token: str,
    outcome: str,
) -> Execution:
    """
    Mark an execution as succeeded or failed.

    outcome must be one of: 'succeeded', 'failed'.
    """
    with transaction.atomic():
        execution = Execution.objects.select_for_update().get(pk=execution.pk)
        _validate_runner_ownership(execution, runner_id, claim_token)

        if execution.status not in (Execution.Status.CLAIMED, Execution.Status.RUNNING):
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Cannot complete execution with status '{execution.status}'.",
            )

        valid_outcomes = {Execution.Status.SUCCEEDED, Execution.Status.FAILED}
        if outcome not in valid_outcomes:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Invalid completion outcome: '{outcome}'.",
            )

        previous_status = execution.status
        now = timezone.now()
        execution.status = outcome
        execution.finished_at = now
        if not execution.started_at:
            execution.started_at = now
        execution.save(
            update_fields=["status", "finished_at", "started_at", "updated_at"]
        )
        audit_actor = actor_from_runner(runner_id)
        AuditService.emit(
            organization_id=execution.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="execution.completed"
            if outcome == Execution.Status.SUCCEEDED
            else "execution.failed",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=execution.id,
            metadata={
                "previous_status": previous_status,
                "new_status": execution.status,
                "started_at": execution.started_at.isoformat()
                if execution.started_at
                else None,
                "finished_at": execution.finished_at.isoformat()
                if execution.finished_at
                else None,
            },
        )
    _ts = (
        execution.finished_at.isoformat()
        if execution.finished_at
        else timezone.now().isoformat()
    )
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="execution.status_changed",
            data={
                "execution_id": str(execution.id),
                "status": execution.status,
                "timestamp": _ts,
                "started_at": execution.started_at.isoformat()
                if execution.started_at
                else None,
                "finished_at": execution.finished_at.isoformat()
                if execution.finished_at
                else None,
            },
        ),
    )
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="stream.closed",
            data={
                "execution_id": str(execution.id),
                "final_status": execution.status,
                "timestamp": _ts,
                "reason": "terminal_state",
            },
        ),
    )
    event_type = (
        "execution.completed"
        if outcome == Execution.Status.SUCCEEDED
        else "execution.failed"
    )
    _safe_notify_integration(
        event_type=event_type,
        organization=execution.organization,
        context=_execution_context(
            execution=execution,
            event_type=event_type,
            previous_status=previous_status,
        ),
    )
    record_execution_event(event=event_type, status=execution.status)

    # Update change lifecycle if this execution is change-bound
    try:
        from apps.changes import services as change_services  # avoid circular
        change_services.handle_bound_execution_completed(execution=execution)
    except Exception:
        logger.exception(
            "handle_bound_execution_completed failed for execution %s", execution.id
        )

    return execution


def emit_step_waiting_for_approval_audit(
    *,
    execution: Execution,
    step: ExecutionStep,
    runner_id: str,
    previous_status: str,
) -> None:
    _emit_step_transition_audit(
        execution=execution,
        step=step,
        runner_id=runner_id,
        previous_status=previous_status,
        new_status=ExecutionStep.Status.WAITING_FOR_APPROVAL,
    )


def emit_step_status_changed_event(
    *, execution: Execution, step: ExecutionStep
) -> None:
    """Emit a stream event for a persisted execution step status transition."""
    _emit_step_status_changed_event(execution=execution, step=step)


def _emit_on_commit(execution_id: str, event: StreamEvent) -> None:
    """Emit a stream event after the current transaction commits.

    When called outside any atomic block, Django fires on_commit immediately.
    When called inside a nested atomic (savepoint), the emit is deferred until
    the outermost transaction commits, guaranteeing emit-after-commit.
    """
    transaction.on_commit(lambda: execution_event_bus.emit(execution_id, event))


def _emit_step_status_changed_event(
    *, execution: Execution, step: ExecutionStep
) -> None:
    _ts = timezone.now().isoformat()
    _emit_on_commit(
        str(execution.id),
        StreamEvent(
            event_type="step.status_changed",
            data={
                "execution_id": str(execution.id),
                "step_id": str(step.id),
                "position": step.position,
                "status": step.status,
                "timestamp": _ts,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "finished_at": step.finished_at.isoformat()
                if step.finished_at
                else None,
                "exit_code": step.exit_code,
                "error_message": step.error_message,
            },
        ),
    )


def _emit_step_transition_audit(
    *,
    execution: Execution,
    step: ExecutionStep,
    runner_id: str,
    previous_status: str,
    new_status: str,
    error_message: str = "",
) -> None:
    event_type_by_status = {
        ExecutionStep.Status.WAITING_FOR_APPROVAL: "execution_step.waiting_for_approval",
        ExecutionStep.Status.RUNNING: "execution_step.started",
        ExecutionStep.Status.SUCCEEDED: "execution_step.succeeded",
        ExecutionStep.Status.FAILED: "execution_step.failed",
    }
    event_type = event_type_by_status.get(new_status)
    if not event_type:
        return

    safe_error = (
        (error_message or "")[:500] if new_status == ExecutionStep.Status.FAILED else ""
    )
    metadata = {
        "execution_id": str(execution.id),
        "step_id": str(step.id),
        "step_key": step.step_key,
        "position": step.position,
        "step_type": step.step_type,
        "risk_level": step.risk_level,
        "previous_status": previous_status,
        "new_status": new_status,
        "exit_code": step.exit_code,
        "error_message": safe_error,
    }
    audit_actor = actor_from_runner(runner_id)
    AuditService.emit(
        organization_id=execution.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.EXECUTION_STEP,
        object_id=step.id,
        metadata=metadata,
    )


def _record_step_duration_if_available(step: ExecutionStep) -> None:
    if not step.started_at or not step.finished_at:
        return
    record_step_duration(
        step_type=step.step_type,
        risk_level=step.risk_level,
        outcome=step.status,
        duration_seconds=(step.finished_at - step.started_at).total_seconds(),
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


def _execution_context(
    *, execution: Execution, event_type: str, previous_status: str = ""
) -> dict:
    context = {
        "event_type": event_type,
        "organization_id": str(execution.organization_id),
        "execution_id": str(execution.id),
        "workflow_id": str(execution.workflow_id),
        "workflow_name": _workflow_name(execution),
        "workflow_version": execution.workflow_version,
        "execution_status": execution.status,
        "previous_status": previous_status,
        "started_at": execution.started_at.isoformat()
        if execution.started_at
        else None,
        "finished_at": execution.finished_at.isoformat()
        if execution.finished_at
        else None,
    }
    if event_type == "execution.failed":
        failed_step = (
            execution.steps.filter(status=ExecutionStep.Status.FAILED)
            .order_by("position")
            .first()
        )
        if failed_step:
            context["failed_step_id"] = str(failed_step.id)
            context["failed_step_key"] = failed_step.step_key
            context["failed_step_name"] = failed_step.name
            context["failed_step_position"] = failed_step.position
    return context


def _step_context(
    *,
    execution: Execution,
    step: ExecutionStep,
    event_type: str,
    previous_status: str,
    new_status: str,
) -> dict:
    return {
        "event_type": event_type,
        "organization_id": str(execution.organization_id),
        "execution_id": str(execution.id),
        "workflow_id": str(execution.workflow_id),
        "step_id": str(step.id),
        "step_key": step.step_key,
        "step_name": step.name,
        "step_position": step.position,
        "step_type": step.step_type,
        "risk_level": step.risk_level,
        "previous_status": previous_status,
        "new_status": new_status,
        "exit_code": step.exit_code,
    }


def _workflow_name(execution: Execution) -> str:
    name = execution.workflow_snapshot.get("name")
    return name if isinstance(name, str) and name else ""
