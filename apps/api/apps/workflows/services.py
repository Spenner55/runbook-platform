from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.common.exceptions import ConcurrencyConflictError, InvalidStateTransitionError, InvalidWorkflowDefinitionError
from apps.runbooks.models import Runbook
from apps.workflows.internal_clients import WorkflowCandidate
from apps.workflows.models import Workflow


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def create_workflow(*, runbook: Runbook, transform_client) -> Workflow:
    """
    Create a draft Workflow from a Runbook via the transform client boundary.

    The transform call runs OUTSIDE the DB transaction so no connection is
    held open while waiting on an external dependency.
    """
    candidate = transform_client.transform_runbook(
        runbook_title=runbook.title,
        runbook_slug=runbook.slug,
        raw_content=runbook.raw_content,
    )
    _validate_candidate(candidate)
    definition = _map_candidate_to_definition(candidate)

    try:
        with transaction.atomic():
            locked_runbook = (
                Runbook.objects
                .select_for_update()
                .select_related("organization")
                .get(pk=runbook.pk)
            )
            existing_max = (
                Workflow.objects
                .filter(runbook=locked_runbook)
                .aggregate(max_version=Max("version"))["max_version"]
                or 0
            )
            return Workflow.objects.create(
                organization=locked_runbook.organization,
                runbook=locked_runbook,
                name=candidate.workflow_title,
                version=existing_max + 1,
                status=Workflow.Status.DRAFT,
                definition_schema_version="workflow.schema.v1",
                definition=definition,
            )
    except IntegrityError as exc:
        raise ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ) from exc


def create_workflow_from_runbook(*, runbook: Runbook) -> Workflow:
    """Create a draft Workflow via the AI service boundary."""
    from apps.workflows.internal_clients import HttpWorkflowTransformClient
    return create_workflow(runbook=runbook, transform_client=HttpWorkflowTransformClient.from_settings())


def publish_workflow(*, workflow: Workflow) -> Workflow:
    """Transition a draft workflow to published status, superseding any currently published sibling."""
    if workflow.status != Workflow.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot publish workflow with status '{workflow.status}', expected 'draft'.",
        )
    with transaction.atomic():
        Workflow.objects.filter(
            runbook=workflow.runbook,
            status=Workflow.Status.PUBLISHED,
        ).exclude(pk=workflow.pk).update(status=Workflow.Status.SUPERSEDED)
        workflow.status = Workflow.Status.PUBLISHED
        workflow.save(update_fields=["status", "updated_at"])
    return workflow


def archive_workflow(*, workflow: Workflow) -> Workflow:
    """Transition a draft or superseded workflow to archived status."""
    allowed = {Workflow.Status.DRAFT, Workflow.Status.SUPERSEDED}
    if workflow.status not in allowed:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot archive workflow with status '{workflow.status}'.",
        )
    workflow.status = Workflow.Status.ARCHIVED
    workflow.save(update_fields=["status", "updated_at"])
    return workflow


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_candidate(candidate: WorkflowCandidate) -> None:
    """Validate transform client output at the service boundary before persisting."""
    if not candidate.steps:
        raise InvalidWorkflowDefinitionError(
            code="invalid_workflow_definition",
            detail="Workflow transform produced no steps.",
        )
    seen_keys: set[str] = set()
    for step in candidate.steps:
        if not step.step_key:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail="A workflow step is missing step_key.",
            )
        if step.step_key in seen_keys:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Duplicate step_key in transform output: '{step.step_key}'.",
            )
        seen_keys.add(step.step_key)
        if not step.name:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step '{step.step_key}' is missing a name.",
            )


def _map_candidate_to_definition(candidate: WorkflowCandidate) -> dict:
    """Map a WorkflowCandidate to the canonical workflow definition shape."""
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
