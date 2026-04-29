from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max

import jsonschema

from apps.common.exceptions import (
    ConcurrencyConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
    InvalidWorkflowDefinitionError,
)
from apps.runbooks.models import Runbook
from apps.workflows.internal_clients import WorkflowCandidate
from apps.workflows.models import Workflow

# Canonical workflow schema — must stay in sync with workflow.schema.json.
_WORKFLOW_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "WorkflowDefinition",
    "type": "object",
    "required": ["name", "steps"],
    "properties": {
        "name": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "type", "risk"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "risk": {"type": "string"},
                    "command": {"type": "string"},
                    "requiresApproval": {"type": "boolean"},
                    "approvalTimeoutSeconds": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def create_workflow(
    *,
    runbook: Runbook,
    transform_client,
    requires_review: bool = False,
    parse_source: str = Workflow.ParseSource.MANUAL,
) -> Workflow:
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
    _validate_definition_schema(definition)

    try:
        with transaction.atomic():
            locked_runbook = (
                Runbook.objects.select_for_update()
                .select_related("organization")
                .get(pk=runbook.pk)
            )
            existing_max = (
                Workflow.objects.filter(runbook=locked_runbook).aggregate(
                    max_version=Max("version")
                )["max_version"]
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
                requires_review=requires_review,
                parse_source=parse_source,
            )
    except IntegrityError as exc:
        raise ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ) from exc


def create_workflow_from_runbook(*, runbook: Runbook) -> Workflow:
    """Create a draft Workflow via the AI service boundary with input guard."""
    from apps.workflows.internal_clients import HttpWorkflowTransformClient

    max_chars = getattr(settings, "AI_MAX_INPUT_CHARS", 100000)
    if len(runbook.raw_content) > max_chars:
        raise DomainValidationError(
            code="ai_input_too_large",
            detail=(
                f"Runbook content exceeds the maximum allowed input size "
                f"({max_chars} characters)."
            ),
        )

    return create_workflow(
        runbook=runbook,
        transform_client=HttpWorkflowTransformClient.from_settings(),
        requires_review=True,
        parse_source=Workflow.ParseSource.AI_PARSE,
    )


def accept_review(*, workflow: Workflow) -> Workflow:
    """Clear the requires_review flag on a workflow, allowing it to be published."""
    if not workflow.requires_review:
        raise InvalidStateTransitionError(
            code="workflow_not_pending_review",
            detail="Workflow is not pending review.",
        )
    if workflow.status != Workflow.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot accept review for workflow with status '{workflow.status}', expected 'draft'.",
        )
    workflow.requires_review = False
    workflow.save(update_fields=["requires_review", "updated_at"])
    return workflow


def reject_review(*, workflow: Workflow) -> Workflow:
    """Archive an AI-parsed workflow that failed human review."""
    if not workflow.requires_review:
        raise InvalidStateTransitionError(
            code="workflow_not_pending_review",
            detail="Workflow is not pending review.",
        )
    if workflow.status != Workflow.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot reject review for workflow with status '{workflow.status}', expected 'draft'.",
        )
    workflow.status = Workflow.Status.ARCHIVED
    workflow.requires_review = False
    workflow.save(update_fields=["status", "requires_review", "updated_at"])
    return workflow


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


def _validate_definition_schema(definition: dict) -> None:
    """Validate the mapped definition against the canonical workflow JSON schema."""
    try:
        jsonschema.validate(instance=definition, schema=_WORKFLOW_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise InvalidWorkflowDefinitionError(
            code="workflow_schema_violation",
            detail=f"Workflow definition does not conform to schema: {exc.message}",
        ) from exc


def _map_candidate_to_definition(candidate: WorkflowCandidate) -> dict:
    """Map a WorkflowCandidate to the canonical workflow definition shape."""
    steps = []
    for step in candidate.steps:
        entry: dict = {
            "id": step.step_key,
            "name": step.name,
            "type": step.step_type,
            "risk": step.risk_level,
            "requiresApproval": step.requires_approval,
        }
        if step.command is not None:
            entry["command"] = step.command
        steps.append(entry)
    return {"name": candidate.workflow_title, "steps": steps}
