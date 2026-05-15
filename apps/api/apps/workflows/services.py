import hashlib
import json
from functools import lru_cache
from pathlib import Path

import jsonschema
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.common.exceptions import (
    ConcurrencyConflictError,
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
    InvalidWorkflowDefinitionError,
)
from apps.runbooks.models import Runbook
from apps.workflows.internal_clients import WorkflowCandidate
from apps.workflows.models import Workflow

SUPPORTED_STEP_TYPES = {"manual_task", "shell_command", "approval"}
SUPPORTED_RISK_LEVELS = {"low", "medium", "high", "critical"}

# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def create_workflow(
    *,
    runbook: Runbook,
    transform_client,
    requires_review: bool = False,
    parse_source: str = Workflow.ParseSource.MANUAL,
    actor: AuditActor | None = None,
    request_id: str | None = None,
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
        request_id=request_id,
    )
    _validate_candidate(candidate)
    definition = _map_candidate_to_definition(candidate)
    _validate_workflow_definition(definition)

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
            workflow = Workflow.objects.create(
                organization=locked_runbook.organization,
                runbook=locked_runbook,
                name=candidate.workflow_title,
                version=existing_max + 1,
                status=Workflow.Status.DRAFT,
                definition_schema_version="workflow.schema.v1",
                definition=definition,
                definition_hash_sha256=compute_definition_hash(definition),
                validation_status=Workflow.ValidationStatus.NOT_APPLICABLE,
                validation_report={},
                requires_review=requires_review,
                parse_source=parse_source,
            )
            _emit_workflow_audit(
                workflow=workflow,
                event_type="workflow.created",
                actor=actor,
                metadata={
                    "runbook_id": str(locked_runbook.id),
                    "version": workflow.version,
                    "status": workflow.status,
                    "requires_review": workflow.requires_review,
                    "parse_source": workflow.parse_source,
                },
            )
            return workflow
    except IntegrityError as exc:
        raise ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ) from exc


def create_workflow_from_runbook(
    *, runbook: Runbook, actor: AuditActor | None = None, request_id: str | None = None
) -> Workflow:
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
        actor=actor,
        request_id=request_id,
    )


def accept_review(*, workflow: Workflow, actor: AuditActor | None = None) -> Workflow:
    """Clear the requires_review flag on a workflow, allowing it to be published."""
    with transaction.atomic():
        workflow = Workflow.objects.select_for_update().get(pk=workflow.pk)
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
        _emit_workflow_audit(
            workflow=workflow,
            event_type="workflow.review_accepted",
            actor=actor,
            metadata={"runbook_id": str(workflow.runbook_id)},
        )
    return workflow


def reject_review(*, workflow: Workflow, actor: AuditActor | None = None) -> Workflow:
    """Archive an AI-parsed workflow that failed human review."""
    with transaction.atomic():
        workflow = Workflow.objects.select_for_update().get(pk=workflow.pk)
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
        _emit_workflow_audit(
            workflow=workflow,
            event_type="workflow.review_rejected",
            actor=actor,
            metadata={
                "runbook_id": str(workflow.runbook_id),
                "new_status": workflow.status,
            },
        )
    return workflow


def publish_workflow(
    *, workflow: Workflow, actor: AuditActor | None = None
) -> Workflow:
    """Transition a draft workflow to published status, superseding any currently published sibling."""
    with transaction.atomic():
        workflow = Workflow.objects.select_for_update().get(pk=workflow.pk)
        if workflow.requires_review:
            raise DomainConflictError(
                code="workflow_requires_review",
                detail="Workflow requires human review before it can be published.",
            )
        if workflow.status != Workflow.Status.DRAFT:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Cannot publish workflow with status '{workflow.status}', expected 'draft'.",
            )
        if (
            workflow.definition_schema_version == "workflow.schema.v2"
            and workflow.validation_status != Workflow.ValidationStatus.VALID
        ):
            raise DomainConflictError(
                code="workflow_invalid_definition",
                detail=(
                    "Cannot publish a v2 workflow with an invalid or unvalidated "
                    f"definition (validation_status='{workflow.validation_status}')."
                ),
            )
        Workflow.objects.filter(
            runbook=workflow.runbook,
            status=Workflow.Status.PUBLISHED,
        ).exclude(pk=workflow.pk).update(status=Workflow.Status.SUPERSEDED)
        previous_status = workflow.status
        workflow.status = Workflow.Status.PUBLISHED
        workflow.save(update_fields=["status", "updated_at"])
        _emit_workflow_audit(
            workflow=workflow,
            event_type="workflow.published",
            actor=actor,
            metadata={
                "runbook_id": str(workflow.runbook_id),
                "previous_status": previous_status,
                "new_status": workflow.status,
                "version": workflow.version,
            },
        )
    return workflow


def archive_workflow(
    *, workflow: Workflow, actor: AuditActor | None = None
) -> Workflow:
    """Transition a draft or superseded workflow to archived status."""
    with transaction.atomic():
        workflow = Workflow.objects.select_for_update().get(pk=workflow.pk)
        allowed = {Workflow.Status.DRAFT, Workflow.Status.SUPERSEDED}
        if workflow.status not in allowed:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Cannot archive workflow with status '{workflow.status}'.",
            )
        previous_status = workflow.status
        workflow.status = Workflow.Status.ARCHIVED
        workflow.save(update_fields=["status", "updated_at"])
        _emit_workflow_audit(
            workflow=workflow,
            event_type="workflow.archived",
            actor=actor,
            metadata={
                "runbook_id": str(workflow.runbook_id),
                "previous_status": previous_status,
                "new_status": workflow.status,
            },
        )
    return workflow


def create_workflow_v2_draft(
    *,
    runbook: Runbook,
    definition: dict,
    actor: AuditActor | None = None,
) -> Workflow:
    """
    Create a draft Workflow from a v2 definition supplied directly.

    Invalid definitions are allowed as drafts — validation_status records the
    outcome.  Publish will reject invalid v2 workflows.
    """
    schema_version = "workflow.schema.v2"
    report = _build_validation_report(definition, schema_version)
    validation_status = (
        Workflow.ValidationStatus.VALID
        if report["valid"]
        else Workflow.ValidationStatus.INVALID
    )
    catalog_version = definition.get("catalogVersion", "pilot.v1")

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
            workflow = Workflow.objects.create(
                organization=locked_runbook.organization,
                runbook=locked_runbook,
                name=definition.get("name", locked_runbook.title),
                version=existing_max + 1,
                status=Workflow.Status.DRAFT,
                definition_schema_version=schema_version,
                definition=definition,
                definition_hash_sha256=compute_definition_hash(definition),
                catalog_version=catalog_version,
                validation_status=validation_status,
                validation_report=report,
                requires_review=False,
                parse_source=Workflow.ParseSource.MANUAL,
            )
            _emit_workflow_audit(
                workflow=workflow,
                event_type="workflow.created",
                actor=actor,
                metadata={
                    "runbook_id": str(locked_runbook.id),
                    "version": workflow.version,
                    "status": workflow.status,
                    "definition_schema_version": schema_version,
                    "validation_status": validation_status,
                },
            )
            return workflow
    except IntegrityError as exc:
        raise ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ) from exc


def create_v2_draft_from_v1(
    *,
    workflow: Workflow,
    actor: AuditActor | None = None,
) -> Workflow:
    """
    Lift a v1 workflow (any status) to a new v2 draft on the same runbook.

    The source workflow row is never mutated. The result is always a new draft.
    Raises DomainValidationError when the source schema is not workflow.schema.v1.
    """
    if workflow.definition_schema_version != "workflow.schema.v1":
        raise DomainValidationError(
            code="unsupported_source_schema",
            detail=(
                f"Cannot migrate workflow with schema version "
                f"'{workflow.definition_schema_version}'; "
                "only 'workflow.schema.v1' is supported."
            ),
        )

    v1_def = workflow.definition
    v2_steps, shell_introduced = _lift_v1_steps(v1_def.get("steps", []))

    v2_def: dict = {
        "schemaVersion": "2",
        "name": v1_def.get("name", workflow.name),
        "catalogVersion": "pilot.v1",
        "steps": v2_steps,
        "secrets": [],
    }

    schema_version = "workflow.schema.v2"
    report = _build_validation_report(v2_def, schema_version)
    validation_status = (
        Workflow.ValidationStatus.VALID
        if report["valid"]
        else Workflow.ValidationStatus.INVALID
    )

    requires_review = (
        workflow.parse_source == Workflow.ParseSource.AI_PARSE or shell_introduced
    )

    try:
        with transaction.atomic():
            locked_runbook = (
                Runbook.objects.select_for_update()
                .select_related("organization")
                .get(pk=workflow.runbook_id)
            )
            existing_max = (
                Workflow.objects.filter(runbook=locked_runbook).aggregate(
                    max_version=Max("version")
                )["max_version"]
                or 0
            )
            new_workflow = Workflow.objects.create(
                organization=locked_runbook.organization,
                runbook=locked_runbook,
                name=v2_def["name"],
                version=existing_max + 1,
                status=Workflow.Status.DRAFT,
                definition_schema_version=schema_version,
                definition=v2_def,
                definition_hash_sha256=compute_definition_hash(v2_def),
                catalog_version="pilot.v1",
                validation_status=validation_status,
                validation_report=report,
                requires_review=requires_review,
                parse_source=workflow.parse_source,
            )
            _emit_workflow_audit(
                workflow=new_workflow,
                event_type="workflow.created",
                actor=actor,
                metadata={
                    "runbook_id": str(locked_runbook.id),
                    "version": new_workflow.version,
                    "status": new_workflow.status,
                    "definition_schema_version": schema_version,
                    "migrated_from_version": workflow.version,
                    "migrated_from_schema": workflow.definition_schema_version,
                    "validation_status": validation_status,
                },
            )
            return new_workflow
    except IntegrityError as exc:
        raise ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ) from exc


def validate_definition_report(definition: dict, schema_version: str) -> dict:
    """Return a validation report dict without persisting anything."""
    return _build_validation_report(definition, schema_version)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def compute_definition_hash(definition: dict) -> str:
    """Return a deterministic SHA-256 hex digest of the canonical JSON form of *definition*."""
    canonical = json.dumps(
        definition, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_validation_report(definition: dict, schema_version: str) -> dict:
    """Run validation and return a report dict; never raises."""
    from apps.workflows.validators import validate_workflow_definition

    try:
        validate_workflow_definition(definition, schema_version)
        return {"valid": True, "errors": [], "warnings": []}
    except InvalidWorkflowDefinitionError as exc:
        return {
            "valid": False,
            "errors": [{"code": exc.code, "detail": exc.detail}],
            "warnings": [],
        }


def _emit_workflow_audit(
    *, workflow: Workflow, event_type: str, actor: AuditActor | None, metadata: dict
) -> None:
    audit_actor = actor or system_actor("Workflow service")
    AuditService.emit(
        organization_id=workflow.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.WORKFLOW,
        object_id=workflow.id,
        metadata=metadata,
    )


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
        jsonschema.Draft7Validator(_workflow_schema()).validate(definition)
    except jsonschema.ValidationError as exc:
        raise InvalidWorkflowDefinitionError(
            code="workflow_schema_violation",
            detail=f"Workflow definition does not conform to schema: {exc.message}",
        ) from exc


def _validate_definition_semantics(definition: dict) -> None:
    """Validate workflow domain invariants not expressible in the v1 JSON schema."""
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        raise InvalidWorkflowDefinitionError(
            code="invalid_workflow_definition",
            detail="Workflow definition must contain at least one step.",
        )

    seen_ids: set[str] = set()
    for position, step in enumerate(steps, start=1):
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step at position {position} is missing a stable id.",
            )
        if step_id in seen_ids:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Duplicate step id '{step_id}' in workflow definition.",
            )
        seen_ids.add(step_id)

        step_type = step.get("type")
        if step_type not in SUPPORTED_STEP_TYPES:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step '{step_id}' has unsupported type '{step_type}'.",
            )

        risk = step.get("risk")
        if risk not in SUPPORTED_RISK_LEVELS:
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step '{step_id}' has unsupported risk level '{risk}'.",
            )

        requires_approval = step.get("requiresApproval")
        if "requiresApproval" in step and not isinstance(requires_approval, bool):
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step '{step_id}' field 'requiresApproval' must be a boolean.",
            )

        command = step.get("command")
        if "command" in step and not isinstance(command, str):
            raise InvalidWorkflowDefinitionError(
                code="invalid_workflow_definition",
                detail=f"Step '{step_id}' field 'command' must be a string.",
            )


def _validate_workflow_definition(definition: dict) -> None:
    _validate_definition_schema(definition)
    _validate_definition_semantics(definition)


@lru_cache(maxsize=1)
def _workflow_schema() -> dict:
    schema_path = _workflow_schema_path()
    with schema_path.open("r", encoding="utf-8") as schema_file:
        return json.load(schema_file)


def _workflow_schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "workflow-schema" / "workflow.schema.json"
        if candidate.is_file():
            return candidate
    container_candidate = Path("/packages/workflow-schema/workflow.schema.json")
    if container_candidate.is_file():
        return container_candidate
    raise RuntimeError("Could not locate packages/workflow-schema/workflow.schema.json")


def _lift_v1_steps(steps: list[dict]) -> tuple[list[dict], bool]:
    """
    Convert a v1 step list to v2 format.

    Returns (v2_steps, shell_introduced) where shell_introduced is True when at
    least one shell_command step was lifted (runner risk introduced).

    Lift rules:
      manual_task  -> manual_task action
      approval     -> approval_gate step + approval_gate action
      shell_command with command -> shell_command action with params.command
    """
    shell_introduced = False
    v2_steps: list[dict] = []

    for step in steps:
        step_type = step.get("type", "")
        v2_step: dict = {
            "id": step.get("id", ""),
            "name": step.get("name", ""),
            "risk": step.get("risk", "low"),
            "retry": {"maxAttempts": 1},
            "idempotency": {"mode": "none"},
            "artifacts": [],
            "secrets": [],
        }

        if "requiresApproval" in step:
            v2_step["requiresApproval"] = step["requiresApproval"]
        if "approvalTimeoutSeconds" in step:
            v2_step["approvalTimeoutSeconds"] = step["approvalTimeoutSeconds"]

        if step_type == "manual_task":
            v2_step["type"] = "manual_task"
            v2_step["action"] = {"type": "manual_task"}
        elif step_type == "approval":
            v2_step["type"] = "approval_gate"
            action: dict = {"type": "approval_gate"}
            if "approvalTimeoutSeconds" in step:
                action["params"] = {"timeout_seconds": step["approvalTimeoutSeconds"]}
            v2_step["action"] = action
        elif step_type in ("shell_command", "command"):
            v2_step["type"] = "shell_command"
            v2_step["action"] = {
                "type": "shell_command",
                "params": {"command": step.get("command", "")},
            }
            shell_introduced = True
        else:
            # Unknown v1 type: carry through; validation report will flag it.
            v2_step["type"] = step_type
            v2_step["action"] = {"type": step_type}

        v2_steps.append(v2_step)

    return v2_steps, shell_introduced


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
