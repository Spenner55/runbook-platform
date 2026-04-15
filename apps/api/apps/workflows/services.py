import uuid

from django.db import transaction

from apps.runbooks.models import Runbook
from apps.workflows.models import Workflow
from apps.runbooks.ai_client import (
    WorkflowCandidate,
    parse_runbook_to_workflow_candidate,
)


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
    """
    Create a new draft workflow version for the given runbook.

    Orchestration:
    1. Call the AI service *outside* the DB transaction (avoids holding the
       connection open while waiting on the network).
    2. Validate and map the candidate into the canonical definition shape.
    3. Open a transaction, assign the next version, and persist the Workflow.

    If the AI service fails, no partial Workflow row is created.
    """
    request_id = str(uuid.uuid4())

    # Step 1: call AI service (no DB transaction open here)
    candidate = parse_runbook_to_workflow_candidate(
        request_id=request_id,
        runbook_id=str(runbook.id),
        runbook_title=runbook.title,
        raw_content=runbook.raw_content,
    )

    # Step 2: map candidate to canonical definition
    definition = _map_candidate_to_definition(candidate)

    # Step 3: version assignment and persistence inside a transaction
    with transaction.atomic():
        existing_max = (
            Workflow.objects.filter(runbook=runbook)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        version = (existing_max + 1) if existing_max is not None else 1

        return Workflow.objects.create(
            organization=runbook.organization,
            runbook=runbook,
            name=candidate.workflow_title,
            version=version,
            status=Workflow.Status.DRAFT,
            definition_schema_version="workflow.schema.v1",
            definition=definition,
        )


def _map_candidate_to_definition(candidate: WorkflowCandidate) -> dict:
    """Map an AI WorkflowCandidate to the canonical workflow definition shape."""
    return {
        "name": candidate.workflow_title,
        "steps": [
            {
                "id": step.step_key,
                "name": step.name,
                "type": step.step_type,
                "risk": step.risk_level,
                "requiresApproval": step.requires_approval,
            }
            for step in candidate.steps
        ],
    }
