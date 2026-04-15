from django.db import transaction

from apps.executions.models import Execution, ExecutionStep
from apps.workflows.models import Workflow


def cancel_execution(*, execution: Execution) -> Execution:
    """Cancel a queued execution. Only queued executions may be cancelled."""
    if execution.status != Execution.Status.QUEUED:
        raise ValueError(
            f"Cannot cancel execution with status '{execution.status}', expected 'queued'."
        )
    execution.status = Execution.Status.CANCELLED
    execution.save(update_fields=["status", "updated_at"])
    return execution


def create_execution_from_workflow(*, workflow: Workflow) -> Execution:
    """Create a queued execution from a published workflow, materializing all steps."""
    if workflow.status != Workflow.Status.PUBLISHED:
        raise ValueError(
            f"Cannot create execution: workflow {workflow.id} has status "
            f"'{workflow.status}', expected 'published'."
        )

    with transaction.atomic():
        execution = Execution.objects.create(
            organization=workflow.organization,
            workflow=workflow,
            workflow_version=workflow.version,
            workflow_snapshot=workflow.definition,
            status=Execution.Status.QUEUED,
        )

        steps = workflow.definition.get("steps", [])
        for position, step in enumerate(steps, start=1):
            ExecutionStep.objects.create(
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

        return execution
