import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    InvalidWorkflowDefinitionError,
)
from apps.executions.models import Execution, ExecutionStep
from apps.workflows.models import Workflow

# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def create_execution(*, workflow: Workflow) -> Execution:
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

            return execution
    except IntegrityError as exc:
        raise InvalidWorkflowDefinitionError(
            code="execution_step_materialization_failed",
            detail="Execution steps could not be materialized from the workflow definition.",
        ) from exc


def create_execution_from_workflow(*, workflow: Workflow) -> Execution:
    """Convenience wrapper — prefer create_execution for new call sites."""
    return create_execution(workflow=workflow)


def cancel_execution(*, execution: Execution) -> Execution:
    """Cancel a queued execution. Only queued executions may be cancelled."""
    if execution.status != Execution.Status.QUEUED:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot cancel execution with status '{execution.status}', expected 'queued'.",
        )
    execution.status = Execution.Status.CANCELLED
    execution.save(update_fields=["status", "updated_at"])
    return execution


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
        if execution is None:
            return None

        claim_token = uuid.uuid4()
        now = timezone.now()
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

        steps = list(execution.steps.order_by("position"))
        return {
            "execution": execution,
            "steps": steps,
            "claim_token": str(claim_token),
        }


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
    ExecutionStep.Status.PENDING: {ExecutionStep.Status.RUNNING, ExecutionStep.Status.FAILED},
    ExecutionStep.Status.WAITING_FOR_APPROVAL: {
        ExecutionStep.Status.RUNNING,
        ExecutionStep.Status.FAILED,
    },
    ExecutionStep.Status.RUNNING: {
        ExecutionStep.Status.SUCCEEDED,
        ExecutionStep.Status.FAILED,
    },
}


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
    _validate_runner_ownership(execution, runner_id, claim_token)

    try:
        step = execution.steps.get(pk=step_id)
    except ExecutionStep.DoesNotExist:
        raise InvalidStateTransitionError(
            code="step_not_found",
            detail=f"Step {step_id} not found on execution {execution.id}.",
        )

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

    # Transition execution CLAIMED -> RUNNING when first step starts running
    if (
        execution.status == Execution.Status.CLAIMED
        and new_status == ExecutionStep.Status.RUNNING
    ):
        execution.status = Execution.Status.RUNNING
        if not execution.started_at:
            execution.started_at = step.started_at
        execution.save(update_fields=["status", "started_at", "updated_at"])

    return step


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

    now = timezone.now()
    execution.status = outcome
    execution.finished_at = now
    if not execution.started_at:
        execution.started_at = now
    execution.save(update_fields=["status", "finished_at", "started_at", "updated_at"])
    return execution
