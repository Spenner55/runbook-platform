from django.db import transaction

from apps.runbooks.models import Runbook
from apps.workflows.models import Workflow


def publish_workflow(*, workflow: Workflow) -> Workflow:
    """Transition a draft workflow to published status."""
    if workflow.status != Workflow.Status.DRAFT:
        raise ValueError(
            f"Cannot publish workflow with status '{workflow.status}', expected 'draft'."
        )
    workflow.status = Workflow.Status.PUBLISHED
    workflow.save(update_fields=["status", "updated_at"])
    return workflow


def create_workflow_from_runbook(*, runbook: Runbook) -> Workflow:
    """Create a new draft workflow version for the given runbook."""
    with transaction.atomic():
        existing_max = (
            Workflow.objects.filter(runbook=runbook)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        version = (existing_max + 1) if existing_max is not None else 1

        definition = {
            "name": runbook.title,
            "steps": [
                {
                    "id": "step-1",
                    "name": "Verify prerequisites",
                    "type": "manual",
                    "risk": "low",
                },
                {
                    "id": "step-2",
                    "name": "Execute main task",
                    "type": "manual",
                    "risk": "medium",
                },
            ],
        }

        return Workflow.objects.create(
            organization=runbook.organization,
            runbook=runbook,
            name=runbook.title,
            version=version,
            status=Workflow.Status.DRAFT,
            definition_schema_version="workflow.schema.v1",
            definition=definition,
        )
