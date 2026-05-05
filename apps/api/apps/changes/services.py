"""Change record lifecycle services."""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.changes.models import (
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    ChangeWindow,
    DispatchEligibilityCheck,
    FreezeRule,
    OperationProfile,
    TargetLock,
)
from apps.changes.transitions import transition_change  # noqa: F401 – re-exported
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)
from apps.executions.models import Execution
from apps.workflows.models import Workflow

logger = logging.getLogger(__name__)


_TARGET_METADATA_FORBIDDEN_KEYS = {
    "api_key",
    "api_token",
    "apikey",
    "apitoken",
    "auth",
    "auth_header",
    "authorization",
    "bearer",
    "bearer_token",
    # Phase 11.1 change-lifecycle secrets
    "change_dispatch_token",
    "claim_token",
    "cookie",
    "dispatch_token",
    "dispatch_token_hash",
    "password",
    "private_key",
    "requested_inputs",
    "secret",
    "session",
    "session_token",
    "token",
    "webhook_url",
    "x_api_key",
}


# ---------------------------------------------------------------------------
# Canonical hashing helpers
# ---------------------------------------------------------------------------


def canonical_json_bytes(value) -> bytes:
    """Produce canonical UTF-8 JSON bytes with sorted keys and compact separators."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_canonical_json(value) -> str:
    """Return hex SHA-256 of canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_request_snapshot(
    change_record: ChangeRecord,
    targets: list,
    submitted_at=None,
    *,
    profile: OperationProfile | None = None,
    workflow=None,
) -> dict:
    """Build the immutable request snapshot dict for a change record.

    ``profile`` and ``workflow`` should be passed at submit time so the
    snapshot captures the full approved dossier.  During re-hash verification
    the caller must NOT recompute this — instead hash the stored
    ``request_snapshot`` field directly.
    """
    target_list = [
        {
            "position": t.position,
            "target_type": t.target_type,
            "target_identifier": t.target_identifier,
            "normalized_identifier": t.normalized_identifier,
            "display_name": t.display_name,
            "environment": t.environment,
            "metadata": t.metadata or {},
        }
        for t in sorted(targets, key=lambda t: t.position)
    ]
    requested_inputs = change_record.requested_inputs or {}

    profile_snapshot: dict = {}
    if profile is not None:
        profile_snapshot = {
            "id": str(profile.id),
            "key": profile.key,
            "name": profile.name,
            "risk_level": profile.risk_level,
            "requires_approval": profile.requires_approval,
            "verification_required": profile.verification_required,
        }

    workflow_snapshot: dict = {}
    if workflow is not None:
        workflow_snapshot = {
            "id": str(workflow.id),
            "name": workflow.name,
            "version": workflow.version,
            "status": workflow.status,
            "definition_sha256": sha256_canonical_json(workflow.definition or {}),
        }

    return {
        "change_record_id": str(change_record.id),
        "title": change_record.title,
        "summary": change_record.summary,
        "justification": change_record.justification,
        "operation_profile_id": str(change_record.operation_profile_id),
        "operation_profile_key": change_record.operation_profile_key_snapshot
        or (profile.key if profile else None),
        "operation_profile_snapshot": profile_snapshot,
        "workflow_id": str(change_record.workflow_id),
        "workflow_version": change_record.workflow_version_snapshot
        or (workflow.version if workflow else None),
        "workflow_snapshot": workflow_snapshot,
        "requested_inputs_sha256": sha256_canonical_json(requested_inputs),
        "requested_input_keys": sorted(str(key) for key in requested_inputs.keys()),
        "requested_inputs_representation": "sha256_and_keys_only",
        "scheduled_for": change_record.scheduled_for.isoformat()
        if change_record.scheduled_for
        else None,
        "targets": target_list,
        "submitted_at": (submitted_at or timezone.now()).isoformat(),
    }


def hash_dispatch_token(token: str) -> str:
    """SHA-256 hash of the clear dispatch token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_INSECURE_SECRET_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "change-dispatch-insecure-change-me",
        "insecure-change-me",
        "insecure",
        "changeme",
        "change-me",
    }
)


def generate_dispatch_token(binding: ChangeExecutionBinding) -> str:
    """Regenerate the clear dispatch token from stored nonce + server secret."""
    secret = getattr(settings, "CHANGE_DISPATCH_TOKEN_SECRET", "")
    if not secret or secret.lower() in _INSECURE_SECRET_PLACEHOLDERS:
        raise DomainValidationError(
            code="dispatch_token_secret_missing",
            detail="CHANGE_DISPATCH_TOKEN_SECRET is not configured.",
        )
    message = (
        f"{binding.change_record_id}:{binding.execution_id}:"
        f"{binding.dispatch_token_nonce}:{binding.requested_inputs_sha256}"
    )
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_dispatch_token(binding: ChangeExecutionBinding, token: str) -> bool:
    """Verify submitted token and persisted hash using constant-time comparisons."""
    if not token:
        return False
    expected_token = generate_dispatch_token(binding)
    expected_hash = hash_dispatch_token(expected_token)
    submitted_hash = hash_dispatch_token(token)
    stored_hash = binding.dispatch_token_hash or ""
    return hmac.compare_digest(stored_hash, expected_hash) and hmac.compare_digest(
        stored_hash, submitted_hash
    )


# ---------------------------------------------------------------------------
# Immutability guard
# ---------------------------------------------------------------------------


def assert_change_request_mutable(change: ChangeRecord) -> None:
    if change.status != ChangeRecord.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="change_request_immutable",
            detail=(
                f"Change request content is immutable after submit "
                f"(current status: '{change.status}')."
            ),
        )


def validate_operation_profile_workflows(
    profile: OperationProfile, workflow_ids=None
) -> None:
    """Ensure an operation profile only allowlists workflows in its own organization."""
    qs = profile.allowed_workflows.all()
    if workflow_ids is not None:
        qs = Workflow.objects.filter(pk__in=workflow_ids)
    if qs.exclude(organization_id=profile.organization_id).exists():
        raise DomainValidationError(
            code="operation_profile_workflow_org_mismatch",
            detail="Operation profile workflows must belong to the same organization.",
        )


def emit_operation_profile_audit(
    *,
    profile: OperationProfile,
    event_type: str,
    actor: AuditActor | None = None,
    metadata: dict | None = None,
) -> None:
    audit_actor = actor or system_actor("Change service")
    AuditService.emit(
        organization_id=profile.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.OPERATION_PROFILE,
        object_id=profile.id,
        metadata={
            "operation_profile_key": profile.key,
            "is_active": profile.is_active,
            "risk_level": profile.risk_level,
            **(metadata or {}),
        },
    )


# ---------------------------------------------------------------------------
# OperationProfile governance service functions
# ---------------------------------------------------------------------------

# Sentinel for optional fields that distinguish None from "not provided".
_UNSET = object()


def create_operation_profile(
    *,
    organization,
    key: str,
    name: str,
    description: str = "",
    risk_level: str,
    requires_approval: bool = True,
    verification_required: bool = True,
    approval_ttl_seconds: int | None = None,
    dispatch_ttl_seconds: int = 900,
    allowed_target_types: list | None = None,
    requested_inputs_schema: dict | None = None,
    target_schema: dict | None = None,
    workflow_ids: list | None = None,
    actor: AuditActor | None = None,
) -> OperationProfile:
    """Create a new OperationProfile with same-org workflow validation and audit."""
    if risk_level not in ("high", "critical"):
        raise DomainValidationError(
            code="invalid_risk_level",
            detail="Operation profile risk level must be 'high' or 'critical'.",
        )
    audit_actor = actor or system_actor("Change service")
    profile = OperationProfile(
        organization=organization,
        key=key,
        name=name,
        description=description,
        risk_level=risk_level,
        requires_approval=requires_approval,
        verification_required=verification_required,
        approval_ttl_seconds=approval_ttl_seconds,
        dispatch_ttl_seconds=dispatch_ttl_seconds,
        allowed_target_types=allowed_target_types or [],
        requested_inputs_schema=requested_inputs_schema or {},
        target_schema=target_schema or {},
        created_by_id=audit_actor.actor_id
        if audit_actor.actor_type == AuditEvent.ActorType.USER
        else None,
        updated_by_id=audit_actor.actor_id
        if audit_actor.actor_type == AuditEvent.ActorType.USER
        else None,
    )
    profile._audit_actor = audit_actor
    profile.save()

    if workflow_ids:
        validate_operation_profile_workflows(profile, workflow_ids)
        workflows = list(
            Workflow.objects.filter(pk__in=workflow_ids, organization=organization)
        )
        profile._audit_actor = audit_actor
        profile.allowed_workflows.set(workflows)

    return profile


def update_operation_profile(
    *,
    profile: OperationProfile,
    actor: AuditActor | None = None,
    name: str | None = None,
    description: str | None = None,
    risk_level: str | None = None,
    requires_approval: bool | None = None,
    verification_required: bool | None = None,
    approval_ttl_seconds: int | None = _UNSET,  # type: ignore[assignment]
    dispatch_ttl_seconds: int | None = None,
    allowed_target_types: list | None = None,
    requested_inputs_schema: dict | None = None,
    target_schema: dict | None = None,
    workflow_ids: list | None = None,
) -> OperationProfile:
    """Update mutable OperationProfile fields with audit and same-org enforcement."""
    if risk_level is not None and risk_level not in ("high", "critical"):
        raise DomainValidationError(
            code="invalid_risk_level",
            detail="Operation profile risk level must be 'high' or 'critical'.",
        )
    audit_actor = actor or system_actor("Change service")
    update_fields: list[str] = ["updated_at"]

    if name is not None:
        profile.name = name
        update_fields.append("name")
    if description is not None:
        profile.description = description
        update_fields.append("description")
    if risk_level is not None:
        profile.risk_level = risk_level
        update_fields.append("risk_level")
    if requires_approval is not None:
        profile.requires_approval = requires_approval
        update_fields.append("requires_approval")
    if verification_required is not None:
        profile.verification_required = verification_required
        update_fields.append("verification_required")
    if approval_ttl_seconds is not _UNSET:
        profile.approval_ttl_seconds = approval_ttl_seconds
        update_fields.append("approval_ttl_seconds")
    if dispatch_ttl_seconds is not None:
        profile.dispatch_ttl_seconds = dispatch_ttl_seconds
        update_fields.append("dispatch_ttl_seconds")
    if allowed_target_types is not None:
        profile.allowed_target_types = allowed_target_types
        update_fields.append("allowed_target_types")
    if requested_inputs_schema is not None:
        profile.requested_inputs_schema = requested_inputs_schema
        update_fields.append("requested_inputs_schema")
    if target_schema is not None:
        profile.target_schema = target_schema
        update_fields.append("target_schema")
    if audit_actor.actor_type == AuditEvent.ActorType.USER:
        profile.updated_by_id = audit_actor.actor_id
        if "updated_by" not in update_fields:
            update_fields.append("updated_by")

    profile._audit_actor = audit_actor
    profile.save(update_fields=update_fields)

    if workflow_ids is not None:
        validate_operation_profile_workflows(profile, workflow_ids)
        workflows = list(
            Workflow.objects.filter(
                pk__in=workflow_ids, organization=profile.organization
            )
        )
        profile._audit_actor = audit_actor
        profile.allowed_workflows.set(workflows)

    return profile


def deactivate_operation_profile(
    *,
    profile: OperationProfile,
    actor: AuditActor | None = None,
) -> OperationProfile:
    """Deactivate an OperationProfile with audit. Idempotent when already inactive."""
    if not profile.is_active:
        return profile
    audit_actor = actor or system_actor("Change service")
    update_fields = ["is_active", "updated_at"]
    profile.is_active = False
    if audit_actor.actor_type == AuditEvent.ActorType.USER:
        profile.updated_by_id = audit_actor.actor_id
        update_fields.append("updated_by")
    profile._audit_actor = audit_actor
    profile.save(update_fields=update_fields)
    return profile


def validate_request_integrity(change: ChangeRecord) -> None:
    """Verify frozen request hashes and reject post-submit dossier drift.

    Three independent checks are performed:

    1. Re-hash ``requested_inputs`` and compare to ``requested_inputs_sha256``.
       This catches any mutation of the live ``requested_inputs`` JSON field.

    2. Re-hash the stored ``request_snapshot`` and compare to
       ``request_snapshot_sha256``.  This catches tampering with the full
       frozen dossier without needing to rebuild it from live relational data.

    3. Rebuild the submitted dossier from current ChangeRecord request fields
       and current ordered ChangeTarget rows, then compare that live dossier
       to both the frozen ``request_snapshot`` and ``request_snapshot_sha256``.
       This catches bulk ORM or direct database drift that bypasses model
       ``save()``/``delete()`` immutability hooks.

    All checks must pass. Any mismatch raises ``InvalidStateTransitionError`` with
    code ``change_request_integrity_mismatch``, failing closed.
    """
    live_change = _load_live_change_for_integrity(change)
    if live_change.status == ChangeRecord.Status.DRAFT:
        return
    if (
        not live_change.submitted_at
        or not live_change.requested_inputs_sha256
        or not live_change.request_snapshot_sha256
    ):
        raise InvalidStateTransitionError(
            code="change_request_integrity_missing",
            detail="Submitted change is missing frozen request hashes.",
        )

    inputs_hash = sha256_canonical_json(live_change.requested_inputs or {})
    if not hmac.compare_digest(inputs_hash, live_change.requested_inputs_sha256):
        raise InvalidStateTransitionError(
            code="change_request_integrity_mismatch",
            detail="Requested inputs no longer match the submitted hash.",
        )

    # Hash the stored snapshot directly — do not recompute from live data.
    # This proves request_snapshot itself has not been tampered with since submit.
    snapshot_hash = sha256_canonical_json(live_change.request_snapshot)
    if not hmac.compare_digest(snapshot_hash, live_change.request_snapshot_sha256):
        raise InvalidStateTransitionError(
            code="change_request_integrity_mismatch",
            detail="Request snapshot no longer matches the submitted hash.",
        )

    live_snapshot = build_live_submitted_request_snapshot(live_change)
    live_snapshot_hash = sha256_canonical_json(live_snapshot)
    if live_snapshot != live_change.request_snapshot or not hmac.compare_digest(
        live_snapshot_hash, live_change.request_snapshot_sha256
    ):
        raise InvalidStateTransitionError(
            code="change_request_integrity_mismatch",
            detail="Submitted change dossier no longer matches the frozen request snapshot.",
        )


def _load_live_change_for_integrity(change: ChangeRecord) -> ChangeRecord:
    if change.pk is None:
        return change
    return ChangeRecord.objects.select_related("operation_profile", "workflow").get(
        pk=change.pk
    )


def build_live_submitted_request_snapshot(change: ChangeRecord) -> dict:
    """Rebuild the submitted dossier from live request fields and target rows."""
    if not change.submitted_at:
        raise InvalidStateTransitionError(
            code="change_request_integrity_missing",
            detail="Submitted change is missing submitted_at.",
        )
    targets = list(
        ChangeTarget.objects.filter(change_record=change).order_by("position")
    )
    profile = getattr(change, "operation_profile", None)
    workflow = getattr(change, "workflow", None)
    snapshot = build_request_snapshot(
        change,
        targets,
        submitted_at=change.submitted_at,
        profile=profile,
        workflow=workflow,
    )
    snapshot["operation_profile_key"] = change.operation_profile_key_snapshot
    snapshot["workflow_version"] = change.workflow_version_snapshot
    return snapshot


def assert_execution_change_binding_ready(
    execution, runner_id: str, claim_token: str | None = None
) -> None:
    """Require a change-bound execution to be bound by the current runner.

    Checks (in order):
    - Binding exists (non-change executions pass through immediately).
    - binding.bound_at is set and change.status is 'running'.
    - The requesting runner_id matches binding.bound_by_runner_id.
    - execution.claimed_by_runner_id still matches binding.bound_by_runner_id
      (cross-validates that the execution has not been reclaimed by a different
      runner since the binding was confirmed).
    - When claim_token is provided, it matches the execution's current claim token.

    Providing claim_token strengthens the guard so a stale runner that still
    knows the bound runner_id but no longer holds the execution claim cannot
    proceed.  All internal view callers should pass claim_token.
    """
    try:
        binding = ChangeExecutionBinding.objects.select_related("change_record").get(
            execution=execution
        )
    except ChangeExecutionBinding.DoesNotExist:
        return

    if (
        binding.bound_at is None
        or binding.change_record.status != ChangeRecord.Status.RUNNING
    ):
        raise InvalidStateTransitionError(
            code="change_binding_not_confirmed",
            detail=(
                "Execution is change-bound but the dispatch token has not been "
                "verified yet. The runner must call bind-execution first."
            ),
        )

    # The requesting runner must be the one that bound the change.
    if binding.bound_by_runner_id != runner_id:
        raise InvalidStateTransitionError(
            code="change_binding_runner_mismatch",
            detail="Execution is change-bound by a different runner.",
        )

    # Cross-validate: the execution's current ownership must still match the binding.
    # This catches reclaims (legitimate or otherwise) before reaching service-layer
    # ownership checks, providing defense-in-depth for the change lifecycle gate.
    if execution.claimed_by_runner_id != binding.bound_by_runner_id:
        raise InvalidStateTransitionError(
            code="change_binding_runner_mismatch",
            detail="Execution ownership no longer matches the change binding.",
        )

    # Validate the current claim token when provided — prevents a stale runner that
    # knows the bound runner_id but holds an old claim_token from proceeding.
    if claim_token is not None and str(execution.claim_token) != claim_token:
        raise InvalidStateTransitionError(
            code="claim_token_mismatch",
            detail="Claim token is invalid.",
        )

    validate_request_integrity(binding.change_record)


# ---------------------------------------------------------------------------
# Target normalization
# ---------------------------------------------------------------------------


def normalize_target_identifier(identifier: str) -> str:
    return identifier.strip().lower()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_change_record(
    *,
    organization,
    operation_profile_key: str,
    workflow_id: str,
    title: str,
    summary: str = "",
    justification: str = "",
    requested_inputs: dict | None = None,
    scheduled_for=None,
    targets: list[dict] | None = None,
    actor: AuditActor | None = None,
) -> ChangeRecord:
    """Create a draft change record from an active operation profile."""
    requested_inputs = requested_inputs or {}
    targets = targets or []

    profile = (
        OperationProfile.objects.filter(
            organization=organization,
            key=operation_profile_key,
        )
        .prefetch_related("allowed_workflows")
        .first()
    )
    if profile is None:
        raise DomainValidationError(
            code="invalid_operation_profile",
            detail=f"Operation profile '{operation_profile_key}' not found.",
        )
    if not profile.is_active:
        raise DomainConflictError(
            code="change_profile_inactive",
            detail=f"Operation profile '{operation_profile_key}' is inactive.",
        )
    if profile.risk_level not in ("high", "critical"):
        raise DomainValidationError(
            code="invalid_operation_profile",
            detail="Operation profile risk level must be 'high' or 'critical'.",
        )

    try:
        workflow = Workflow.objects.get(pk=workflow_id, organization=organization)
    except Workflow.DoesNotExist:
        raise DomainValidationError(
            code="workflow_not_found",
            detail=f"Workflow '{workflow_id}' not found.",
        )

    if workflow not in profile.allowed_workflows.all():
        raise DomainValidationError(
            code="workflow_not_allowlisted_for_profile",
            detail=f"Workflow '{workflow_id}' is not allowlisted for profile '{operation_profile_key}'.",
        )

    if workflow.status != Workflow.Status.PUBLISHED:
        raise DomainValidationError(
            code="workflow_not_published",
            detail=f"Workflow must be published (current status: '{workflow.status}').",
        )

    _validate_requested_inputs(requested_inputs, profile)
    _validate_targets(targets, profile)

    with transaction.atomic():
        change = ChangeRecord.objects.create(
            organization=organization,
            operation_profile=profile,
            workflow=workflow,
            requested_by_id=actor.actor_id
            if actor and actor.actor_type == AuditEvent.ActorType.USER
            else None,
            title=title,
            summary=summary,
            justification=justification,
            status=ChangeRecord.Status.DRAFT,
            requested_inputs=requested_inputs,
            scheduled_for=scheduled_for,
        )
        for position, target_data in enumerate(targets, start=1):
            normalized = normalize_target_identifier(target_data["target_identifier"])
            ChangeTarget.objects.create(
                change_record=change,
                organization=organization,
                position=position,
                target_type=target_data["target_type"],
                target_identifier=target_data["target_identifier"],
                normalized_identifier=normalized,
                display_name=target_data.get("display_name", ""),
                environment=target_data["environment"],
                metadata=target_data.get("metadata", {}),
            )
        _emit(
            change=change,
            event_type="change.created",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=actor or system_actor("Change service"),
            metadata={
                "operation_profile_key": profile.key,
                "workflow_id": str(workflow.id),
                "target_count": len(targets),
            },
        )
    return change


def _validate_targets(targets: list[dict], profile: OperationProfile) -> None:
    allow_empty = profile.target_schema.get("allow_empty_targets", False)
    if not targets and not allow_empty:
        raise DomainValidationError(
            code="change_requires_targets",
            detail="At least one production target is required.",
        )

    seen: set[tuple[str, str]] = set()
    for i, t in enumerate(targets):
        env = t.get("environment", "")
        if env != "production":
            raise DomainValidationError(
                code="non_production_target",
                detail=f"Target at position {i + 1} must have environment='production' (got '{env}').",
            )
        ttype = t.get("target_type", "")
        if (
            not profile.allowed_target_types
            or ttype not in profile.allowed_target_types
        ):
            raise DomainValidationError(
                code="target_type_not_allowed",
                detail=f"Target type '{ttype}' is not allowed by profile.",
            )
        normalized = normalize_target_identifier(t.get("target_identifier", ""))
        if not normalized:
            raise DomainValidationError(
                code="target_identifier_required",
                detail=f"Target at position {i + 1} requires a target_identifier.",
            )
        metadata = t.get("metadata", {})
        _validate_target_metadata(metadata, position=i + 1)
        key = (ttype, normalized)
        if key in seen:
            raise DomainValidationError(
                code="duplicate_change_target",
                detail=f"Duplicate target: type='{ttype}', identifier='{t.get('target_identifier')}'.",
            )
        seen.add(key)


def _validate_target_metadata(metadata, *, position: int) -> None:
    if metadata is None:
        return
    if not isinstance(metadata, dict):
        raise DomainValidationError(
            code="target_metadata_invalid",
            detail=f"Target metadata at position {position} must be a JSON object.",
        )
    _reject_sensitive_keys(
        metadata,
        code="target_metadata_forbidden_key",
        detail_prefix=f"Target metadata at position {position}",
    )


def _reject_sensitive_keys(value, *, code: str, detail_prefix: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in _TARGET_METADATA_FORBIDDEN_KEYS:
                raise DomainValidationError(
                    code=code,
                    detail=f"{detail_prefix} contains forbidden sensitive key '{key_text}'.",
                )
            _reject_sensitive_keys(child, code=code, detail_prefix=detail_prefix)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_keys(child, code=code, detail_prefix=detail_prefix)


def _validate_requested_inputs(
    requested_inputs: dict, profile: OperationProfile
) -> None:
    if not isinstance(requested_inputs, dict):
        raise DomainValidationError(
            code="requested_inputs_invalid",
            detail="Requested inputs must be a JSON object.",
        )
    schema = profile.requested_inputs_schema or {}
    if not schema:
        return
    if not isinstance(schema, dict):
        raise DomainValidationError(
            code="requested_inputs_schema_invalid",
            detail="Operation profile requested_inputs_schema must be a JSON object.",
        )

    required = schema.get("required", [])
    if not isinstance(required, list):
        raise DomainValidationError(
            code="requested_inputs_schema_invalid",
            detail="requested_inputs_schema.required must be a list.",
        )
    for key in required:
        if key not in requested_inputs:
            raise DomainValidationError(
                code="requested_inputs_invalid",
                detail=f"Missing required requested input '{key}'.",
            )

    properties = schema.get("properties", {})
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise DomainValidationError(
            code="requested_inputs_schema_invalid",
            detail="requested_inputs_schema.properties must be a JSON object.",
        )

    if schema.get("additionalProperties") is False:
        extra_keys = set(requested_inputs) - set(properties)
        if extra_keys:
            raise DomainValidationError(
                code="requested_inputs_invalid",
                detail=f"Unexpected requested input '{sorted(extra_keys)[0]}'.",
            )

    for key, rules in properties.items():
        if key not in requested_inputs or not isinstance(rules, dict):
            continue
        expected_type = rules.get("type")
        if expected_type and not _json_type_matches(
            requested_inputs[key], expected_type
        ):
            raise DomainValidationError(
                code="requested_inputs_invalid",
                detail=f"Requested input '{key}' must be of type '{expected_type}'.",
            )


def _json_type_matches(value, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "null":
        return value is None
    return True


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def submit_change_record(
    *,
    change: ChangeRecord,
    actor: AuditActor | None = None,
) -> ChangeRecord:
    """Submit a draft change for approval."""
    with transaction.atomic():
        change = ChangeRecord.objects.select_for_update().get(pk=change.pk)
        if change.status != ChangeRecord.Status.DRAFT:
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Cannot submit change with status '{change.status}', expected 'draft'.",
            )

        profile = OperationProfile.objects.prefetch_related("allowed_workflows").get(
            pk=change.operation_profile_id
        )
        if not profile.is_active:
            raise DomainConflictError(
                code="change_profile_inactive",
                detail=f"Operation profile '{profile.key}' is no longer active.",
            )

        workflow = Workflow.objects.get(pk=change.workflow_id)
        if workflow.organization_id != change.organization_id:
            raise DomainValidationError(
                code="workflow_organization_mismatch",
                detail="Workflow organization does not match the change organization.",
            )
        if profile.organization_id != change.organization_id:
            raise DomainValidationError(
                code="operation_profile_organization_mismatch",
                detail="Operation profile organization does not match the change organization.",
            )
        if workflow not in profile.allowed_workflows.all():
            raise DomainValidationError(
                code="workflow_not_allowlisted_for_profile",
                detail="Workflow is no longer allowlisted for this profile.",
            )
        if workflow.status != Workflow.Status.PUBLISHED:
            raise DomainValidationError(
                code="workflow_not_published",
                detail=f"Workflow must be published (current: '{workflow.status}').",
            )

        if not change.justification.strip():
            raise DomainValidationError(
                code="change_requires_justification",
                detail="Justification is required to submit a change.",
            )

        targets = list(change.targets.order_by("position"))
        _validate_requested_inputs(change.requested_inputs or {}, profile)
        _validate_targets(
            [
                {
                    "environment": t.environment,
                    "target_type": t.target_type,
                    "target_identifier": t.target_identifier,
                    "metadata": t.metadata,
                }
                for t in targets
            ],
            profile,
        )

        now = timezone.now()
        inputs_hash = sha256_canonical_json(change.requested_inputs)
        snapshot = build_request_snapshot(
            change, targets, submitted_at=now, profile=profile, workflow=workflow
        )
        snapshot_hash = sha256_canonical_json(snapshot)

        change.requested_inputs_sha256 = inputs_hash
        change.request_snapshot = snapshot
        change.request_snapshot_sha256 = snapshot_hash
        change.operation_profile_key_snapshot = profile.key
        change.workflow_version_snapshot = workflow.version
        change.workflow_definition_sha256 = sha256_canonical_json(
            workflow.definition or {}
        )
        change.submitted_at = now
        if actor and actor.actor_type == AuditEvent.ActorType.USER:
            change.submitted_by_id = actor.actor_id

        _emit(
            change=change,
            event_type="change.submitted",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=actor or system_actor("Change service"),
            metadata={
                "operation_profile_key": profile.key,
                "workflow_id": str(workflow.id),
                "workflow_version": workflow.version,
                "requested_inputs_sha256": inputs_hash,
                "request_snapshot_sha256": snapshot_hash,
                "target_count": len(targets),
            },
        )

        if profile.requires_approval:
            from apps.approvals import services as approval_services  # avoid circular

            approval_request = approval_services.create_change_approval_request(
                change_record=change,
                organization=change.organization,
                ttl_seconds=profile.approval_ttl_seconds,
                actor=actor,
            )
            change.approval_request = approval_request
            transition_change(
                change=change,
                new_status=ChangeRecord.Status.PENDING_APPROVAL,
                actor=actor,
                save=False,
            )
            change.save(
                update_fields=[
                    "requested_inputs_sha256",
                    "request_snapshot",
                    "request_snapshot_sha256",
                    "operation_profile_key_snapshot",
                    "workflow_version_snapshot",
                    "workflow_definition_sha256",
                    "submitted_at",
                    "submitted_by",
                    "approval_request",
                    "status",
                    "updated_at",
                ]
            )
            _emit(
                change=change,
                event_type="change.approval_bound",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                actor=actor or system_actor("Change service"),
                metadata={
                    "approval_request_id": str(approval_request.id),
                },
            )
        else:
            transition_change(
                change=change,
                new_status=ChangeRecord.Status.APPROVED,
                actor=actor,
                now=now,
                save=False,
            )
            change.save(
                update_fields=[
                    "requested_inputs_sha256",
                    "request_snapshot",
                    "request_snapshot_sha256",
                    "operation_profile_key_snapshot",
                    "workflow_version_snapshot",
                    "workflow_definition_sha256",
                    "submitted_at",
                    "submitted_by",
                    "status",
                    "approved_at",
                    "updated_at",
                ]
            )
            schedule_or_make_dispatchable(change=change, actor=actor)

    return change


# ---------------------------------------------------------------------------
# Approval callback
# ---------------------------------------------------------------------------


def handle_change_approval_decision(
    *,
    approval_request_id,
    decision: str,
    actor: AuditActor | None = None,
) -> None:
    """
    Called from approvals.services.decide_approval (same transaction) when
    the approval request subject is a change_record.
    """
    change = (
        ChangeRecord.objects.select_for_update()
        .filter(approval_request_id=approval_request_id)
        .first()
    )
    if change is None:
        raise DomainValidationError(
            code="change_approval_decision_orphaned",
            detail=(
                f"No ChangeRecord found for approval_request_id={approval_request_id} "
                f"(decision={decision}). Approval decision rolled back to preserve consistency."
            ),
        )

    if change.status != ChangeRecord.Status.PENDING_APPROVAL:
        raise InvalidStateTransitionError(
            code="change_approval_state_conflict",
            detail=(
                f"ChangeRecord {change.id} is in status '{change.status}', expected "
                f"'pending_approval' (decision={decision}). "
                "Approval decision rolled back to prevent approval/change divergence."
            ),
        )

    now = timezone.now()
    validate_request_integrity(change)

    if decision == "approved":
        transition_change(
            change=change,
            new_status=ChangeRecord.Status.APPROVED,
            actor=actor,
            now=now,
        )
        schedule_or_make_dispatchable(change=change, actor=actor)

    elif decision == "rejected":
        transition_change(
            change=change,
            new_status=ChangeRecord.Status.REJECTED,
            actor=actor,
            now=now,
            terminal_reason="approval_rejected",
        )

    elif decision == "timed_out":
        transition_change(
            change=change,
            new_status=ChangeRecord.Status.EXPIRED,
            actor=actor,
            now=now,
            terminal_reason="approval_timed_out",
        )


# ---------------------------------------------------------------------------
# Schedule or dispatch
# ---------------------------------------------------------------------------


def schedule_or_make_dispatchable(
    *,
    change: ChangeRecord,
    actor: AuditActor | None = None,
) -> None:
    """Transition approved change to scheduled or dispatchable."""
    if change.status != ChangeRecord.Status.APPROVED:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot schedule or dispatch change with status '{change.status}'.",
        )
    validate_request_integrity(change)
    now = timezone.now()
    if change.scheduled_for and change.scheduled_for > now:
        transition_change(
            change=change,
            new_status=ChangeRecord.Status.SCHEDULED,
            actor=actor,
            audit_metadata={
                "scheduled_for": change.scheduled_for.isoformat(),
            },
        )
    else:
        make_dispatchable(change=change, actor=actor)


def _get_fresh_passed_preflight(
    change: ChangeRecord, now
) -> DispatchEligibilityCheck | None:
    """Return the latest PASSED, non-expired preflight check for change, or None."""
    return (
        DispatchEligibilityCheck.objects.filter(
            change_record=change,
            result=DispatchEligibilityCheck.Result.PASSED,
            expires_at__gt=now,
        )
        .order_by("-checked_at")
        .first()
    )


def _acquire_target_locks_for_dispatch(
    *,
    change: ChangeRecord,
    execution: "Execution",
    now,
    actor: AuditActor,
) -> list[TargetLock]:
    """Create ACTIVE TargetLock rows for every change target inside an open transaction.

    Raises DomainConflictError(code='target_lock_conflict') if any target is already
    locked by another change. The IntegrityError from the DB unique constraint is caught
    via a savepoint so the outer transaction remains usable.
    """
    targets = list(change.targets.order_by("position"))
    if not targets:
        return []

    locks: list[TargetLock] = []
    for target in targets:
        try:
            with transaction.atomic():
                lock = TargetLock.objects.create(
                    organization=change.organization,
                    change_record=change,
                    execution=execution,
                    change_target=target,
                    target_type=target.target_type,
                    target_identifier=target.target_identifier,
                    normalized_identifier=target.normalized_identifier,
                    status=TargetLock.Status.ACTIVE,
                    acquired_at=now,
                )
                locks.append(lock)
        except IntegrityError:
            raise DomainConflictError(
                code="target_lock_conflict",
                detail=(
                    f"Dispatch blocked: active target lock exists for "
                    f"{target.target_type}:{target.target_identifier}."
                ),
            )

    for lock in locks:
        _emit(
            change=change,
            event_type="change.target_lock_acquired",
            object_type=AuditEvent.ObjectType.TARGET_LOCK,
            actor=actor,
            metadata={
                "target_type": lock.target_type,
                "target_identifier": lock.target_identifier,
                "execution_id": str(execution.id),
            },
            object_id=lock.id,
        )

    return locks


def make_dispatchable(
    *,
    change: ChangeRecord,
    actor: AuditActor | None = None,
) -> None:
    """Reserve an execution and create the ChangeExecutionBinding."""
    from apps.executions import services as execution_services  # avoid circular

    effective_actor = actor or system_actor("Change service")

    with transaction.atomic():
        change = ChangeRecord.objects.select_for_update().get(pk=change.pk)
        if change.status not in (
            ChangeRecord.Status.APPROVED,
            ChangeRecord.Status.SCHEDULED,
        ):
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail=f"Cannot dispatch change with status '{change.status}'.",
            )
        now = timezone.now()
        if (
            change.status == ChangeRecord.Status.SCHEDULED
            and change.scheduled_for
            and change.scheduled_for > now
        ):
            raise InvalidStateTransitionError(
                code="invalid_state_transition",
                detail="Cannot dispatch scheduled change before scheduled_for.",
            )
        validate_request_integrity(change)

        # Phase 11.2: gate on a fresh PASSED preflight eligibility check.
        fresh_check = _get_fresh_passed_preflight(change, now)
        if fresh_check is None:
            fresh_check = run_dispatch_preflight(change=change, actor=effective_actor)
        if fresh_check.result != DispatchEligibilityCheck.Result.PASSED:
            conflict_count = len(fresh_check.conflicts)
            raise DomainConflictError(
                code="dispatch_preflight_failed",
                detail=(
                    f"Dispatch blocked: preflight failed with {conflict_count} conflict(s)."
                    if conflict_count
                    else "Dispatch blocked: preflight check failed."
                ),
            )

        profile = OperationProfile.objects.get(pk=change.operation_profile_id)
        workflow = Workflow.objects.get(pk=change.workflow_id)
        if profile.organization_id != change.organization_id:
            raise DomainValidationError(
                code="operation_profile_organization_mismatch",
                detail="Operation profile organization does not match the change organization.",
            )
        if workflow.organization_id != change.organization_id:
            raise DomainValidationError(
                code="workflow_organization_mismatch",
                detail="Workflow organization does not match the change organization.",
            )

        execution = execution_services.create_execution(
            workflow=workflow,
            actor=effective_actor,
            _from_change_service=True,
        )

        _acquire_target_locks_for_dispatch(
            change=change,
            execution=execution,
            now=now,
            actor=effective_actor,
        )

        nonce = secrets.token_hex(32)
        ttl_seconds = profile.dispatch_ttl_seconds
        expires_at = now + timedelta(seconds=ttl_seconds)

        inputs_hash = change.requested_inputs_sha256 or sha256_canonical_json(
            change.requested_inputs
        )

        binding = ChangeExecutionBinding.objects.create(
            change_record=change,
            execution=execution,
            organization=change.organization,
            operation_profile_key=profile.key,
            requested_inputs_sha256=inputs_hash,
            dispatch_token_nonce=nonce,
            dispatch_token_hash="",
            dispatch_token_expires_at=expires_at,
            reserved_at=now,
        )
        clear_token = generate_dispatch_token(binding)
        binding.dispatch_token_hash = hash_dispatch_token(clear_token)
        binding.runner_payload_snapshot = {
            "change_record_id": str(change.id),
            "execution_id": str(execution.id),
            "operation_profile_key": profile.key,
            "requested_inputs_sha256": inputs_hash,
            "dispatch_token_expires_at": expires_at.isoformat(),
        }
        binding.save(
            update_fields=[
                "dispatch_token_hash",
                "runner_payload_snapshot",
                "updated_at",
            ]
        )

        transition_change(
            change=change,
            new_status=ChangeRecord.Status.DISPATCHABLE,
            actor=actor,
            now=now,
        )

        _emit(
            change=change,
            event_type="change.execution_binding_reserved",
            object_type=AuditEvent.ObjectType.CHANGE_EXECUTION_BINDING,
            actor=effective_actor,
            metadata={
                "change_record_id": str(change.id),
                "execution_id": str(execution.id),
                "operation_profile_key": profile.key,
                "requested_inputs_sha256": inputs_hash,
            },
            object_id=binding.id,
        )


def promote_due_scheduled_changes() -> list[str]:
    """Move due scheduled changes to dispatchable."""
    now = timezone.now()
    due_ids = list(
        ChangeRecord.objects.filter(
            status=ChangeRecord.Status.SCHEDULED,
            scheduled_for__lte=now,
        ).values_list("id", flat=True)[:50]
    )
    promoted = []
    for change_id in due_ids:
        try:
            with transaction.atomic():
                change = (
                    ChangeRecord.objects.select_for_update(skip_locked=True)
                    .filter(
                        pk=change_id,
                        status=ChangeRecord.Status.SCHEDULED,
                        scheduled_for__lte=now,
                    )
                    .first()
                )
                if change is None:
                    continue
                make_dispatchable(change=change)
                promoted.append(str(change_id))
        except Exception:
            logger.exception("Failed to promote scheduled change %s", change_id)
    return promoted


# ---------------------------------------------------------------------------
# Bind execution (called by runner internal endpoint)
# ---------------------------------------------------------------------------


def expire_dispatchable_change(
    *,
    change: ChangeRecord,
    now=None,
    actor: AuditActor | None = None,
    terminal_reason: str = "dispatch_token_expired",
) -> None:
    """Transition a dispatchable change to expired due to dispatch token expiry."""
    if change.status != ChangeRecord.Status.DISPATCHABLE:
        return
    transition_change(
        change=change,
        new_status=ChangeRecord.Status.EXPIRED,
        actor=actor or system_actor("Change service"),
        now=now or timezone.now(),
        terminal_reason=terminal_reason,
    )


def expire_unbound_dispatch_for_execution(*, execution, now=None) -> bool:
    """
    Expire an unbound change dispatch tied to a queued/claimed execution.

    Returns True when the execution should be skipped by runner claim.
    """
    now = now or timezone.now()
    try:
        binding = (
            ChangeExecutionBinding.objects.select_for_update()
            .select_related("change_record")
            .get(execution=execution)
        )
    except ChangeExecutionBinding.DoesNotExist:
        return False

    if binding.bound_at is not None or binding.dispatch_token_expires_at > now:
        return False

    change = binding.change_record
    if change.status == ChangeRecord.Status.DISPATCHABLE:
        expire_dispatchable_change(
            change=change,
            now=now,
            actor=system_actor("Change service"),
            terminal_reason="dispatch_token_expired",
        )

    if execution.status in (Execution.Status.QUEUED, Execution.Status.CLAIMED):
        previous_status = execution.status
        execution.status = Execution.Status.CANCELLED
        execution.finished_at = now
        if not execution.started_at:
            execution.started_at = now
        execution.save(
            update_fields=["status", "finished_at", "started_at", "updated_at"]
        )
        audit_actor = system_actor("Change service")
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
                "reason": "change_dispatch_token_expired",
                "change_record_id": str(change.id),
            },
        )
    return True


def bind_execution(
    *,
    change_id: str,
    runner_id: str,
    claim_token: str,
    execution_id: str,
    dispatch_token: str,
    requested_inputs_sha256: str,
    operation_profile_key: str,
) -> dict:
    """Validate runner possession of dispatch token and activate the binding."""
    from apps.executions.models import Execution  # avoid circular

    # _dispatch_token_expired is set when we detect expiry inside the transaction
    # so we can perform the lifecycle transition in its own atomic after the
    # read-only validation transaction exits (raising would roll back any saves).
    _dispatch_token_expired = False
    _request_integrity_failed = False

    try:
        with transaction.atomic():
            try:
                change = ChangeRecord.objects.select_for_update().get(pk=change_id)
            except ChangeRecord.DoesNotExist:
                raise DomainValidationError(
                    code="change_not_found",
                    detail="Change record not found.",
                )

            # Fetch binding and check idempotency BEFORE the status check so that a
            # runner retry after a successful bind (change is now 'running') succeeds.
            try:
                binding = ChangeExecutionBinding.objects.select_for_update().get(
                    change_record=change
                )
            except ChangeExecutionBinding.DoesNotExist:
                raise DomainValidationError(
                    code="execution_binding_not_found",
                    detail="No execution binding found for this change.",
                )

            if str(binding.execution_id) != str(execution_id):
                raise InvalidStateTransitionError(
                    code="execution_binding_conflict",
                    detail="Execution ID does not match binding.",
                )

            try:
                execution = Execution.objects.select_for_update().get(pk=execution_id)
            except Execution.DoesNotExist:
                raise DomainValidationError(
                    code="execution_not_found",
                    detail="Execution not found.",
                )

            if execution.claimed_by_runner_id != runner_id:
                raise InvalidStateTransitionError(
                    code="runner_ownership_mismatch",
                    detail="Runner does not own this execution.",
                )
            if str(execution.claim_token) != str(claim_token):
                raise InvalidStateTransitionError(
                    code="claim_token_mismatch",
                    detail="Claim token is invalid.",
                )

            now = timezone.now()

            # Idempotency: same runner/execution/payload already bound — revalidate and return success.
            if binding.bound_at is not None:
                if binding.bound_by_runner_id != runner_id:
                    raise InvalidStateTransitionError(
                        code="execution_binding_conflict",
                        detail="Binding already claimed by a different runner.",
                    )
                if binding.dispatch_token_expires_at <= now:
                    raise InvalidStateTransitionError(
                        code="dispatch_token_expired",
                        detail="Dispatch token has expired.",
                    )
                # Revalidate payload to prove this is the same dispatch, not a stale retry.
                if binding.operation_profile_key != operation_profile_key:
                    raise DomainValidationError(
                        code="operation_profile_key_mismatch",
                        detail="Operation profile key does not match binding on idempotent retry.",
                    )
                if binding.requested_inputs_sha256 != requested_inputs_sha256:
                    raise DomainValidationError(
                        code="requested_inputs_hash_mismatch",
                        detail="Requested inputs hash does not match binding on idempotent retry.",
                    )
                if not verify_dispatch_token(binding, dispatch_token):
                    raise DomainValidationError(
                        code="dispatch_token_invalid",
                        detail="Dispatch token is invalid on idempotent retry.",
                    )
                return {
                    "change_record_id": str(change.id),
                    "execution_id": str(execution.id),
                    "binding_id": str(binding.id),
                    "status": change.status,
                    "bound_at": binding.bound_at,
                }

            # Status check comes after idempotency so retries never fail here.
            if change.status != ChangeRecord.Status.DISPATCHABLE:
                raise InvalidStateTransitionError(
                    code="change_not_dispatchable",
                    detail=f"Change is not dispatchable (status: '{change.status}').",
                )
            try:
                validate_request_integrity(change)
            except InvalidStateTransitionError:
                _request_integrity_failed = True
                raise

            if binding.operation_profile_key != operation_profile_key:
                raise DomainValidationError(
                    code="operation_profile_key_mismatch",
                    detail="Operation profile key does not match binding.",
                )
            if binding.requested_inputs_sha256 != requested_inputs_sha256:
                raise DomainValidationError(
                    code="requested_inputs_hash_mismatch",
                    detail="Requested inputs hash does not match binding.",
                )

            if binding.dispatch_token_expires_at <= now:
                # Signal expiry for post-transaction lifecycle handling.
                _dispatch_token_expired = True
                raise InvalidStateTransitionError(
                    code="dispatch_token_expired",
                    detail="Dispatch token has expired.",
                )

            if not verify_dispatch_token(binding, dispatch_token):
                raise DomainValidationError(
                    code="dispatch_token_invalid",
                    detail="Dispatch token is invalid.",
                )

            binding.bound_at = now
            binding.bound_by_runner_id = runner_id
            binding.save(update_fields=["bound_at", "bound_by_runner_id", "updated_at"])

            transition_change(
                change=change,
                new_status=ChangeRecord.Status.RUNNING,
                actor=_runner_actor(runner_id),
                now=now,
            )

            _emit(
                change=change,
                event_type="change.execution_bound",
                object_type=AuditEvent.ObjectType.CHANGE_EXECUTION_BINDING,
                actor=_runner_actor(runner_id),
                metadata={
                    "change_record_id": str(change.id),
                    "execution_id": str(execution.id),
                    "runner_id": runner_id,
                },
                object_id=binding.id,
            )
    except InvalidStateTransitionError:
        if _dispatch_token_expired or _request_integrity_failed:
            # Perform the expiry lifecycle transition in its own transaction so
            # it commits even though the outer transaction was rolled back.
            try:
                change_for_expiry = ChangeRecord.objects.get(pk=change_id)
                expire_dispatchable_change(
                    change=change_for_expiry,
                    now=timezone.now(),
                    terminal_reason=(
                        "request_integrity_mismatch"
                        if _request_integrity_failed
                        else "dispatch_token_expired"
                    ),
                )
            except Exception:
                logger.exception(
                    "Failed to expire dispatchable change %s after bind rejection",
                    change_id,
                )
        raise

    return {
        "change_record_id": str(change.id),
        "execution_id": str(execution.id),
        "binding_id": str(binding.id),
        "status": change.status,
        "bound_at": binding.bound_at,
    }


# ---------------------------------------------------------------------------
# Policy evaluation linkage
# ---------------------------------------------------------------------------


def link_policy_evaluation(
    *,
    execution,
    policy_evaluation,
) -> None:
    """Link the first policy evaluation to the associated change record."""
    try:
        binding = ChangeExecutionBinding.objects.select_related("change_record").get(
            execution=execution
        )
    except ChangeExecutionBinding.DoesNotExist:
        return

    change = ChangeRecord.objects.select_for_update().get(pk=binding.change_record_id)
    if change.policy_evaluation_id is not None:
        return

    change.policy_evaluation = policy_evaluation
    change.policy_decision_snapshot = {
        "policy_evaluation_id": str(policy_evaluation.id),
        "policy_id": str(policy_evaluation.policy_id)
        if policy_evaluation.policy_id
        else None,
        "policy_rule_id": str(policy_evaluation.rule_id)
        if policy_evaluation.rule_id
        else None,
        "outcome": policy_evaluation.outcome,
        "effective_outcome": policy_evaluation.effective_outcome,
        "decision_source": policy_evaluation.decision_source,
        "reason": policy_evaluation.reason,
        "evaluated_at": policy_evaluation.created_at.isoformat()
        if policy_evaluation.created_at
        else None,
    }
    change.save(
        update_fields=["policy_evaluation", "policy_decision_snapshot", "updated_at"]
    )
    _emit(
        change=change,
        event_type="change.policy_bound",
        object_type=AuditEvent.ObjectType.CHANGE_RECORD,
        actor=system_actor("Change service"),
        metadata={
            "policy_evaluation_id": str(policy_evaluation.id),
            "outcome": policy_evaluation.outcome,
            "effective_outcome": policy_evaluation.effective_outcome,
        },
    )


# ---------------------------------------------------------------------------
# Runner timing callbacks (accepted / started / finished)
# ---------------------------------------------------------------------------


def _resolve_bound_binding(
    *, change_id: str, runner_id: str, execution_id: str
) -> tuple["ChangeRecord", "ChangeExecutionBinding"]:
    """Fetch and validate a bound ChangeExecutionBinding inside a transaction.

    Raises DomainValidationError / InvalidStateTransitionError on mismatch.
    Caller must be inside transaction.atomic() and should pass select_for_update
    locks already acquired before calling this.
    """
    try:
        change = ChangeRecord.objects.select_for_update().get(pk=change_id)
    except ChangeRecord.DoesNotExist:
        raise DomainValidationError(
            code="change_not_found",
            detail="Change record not found.",
        )
    try:
        binding = ChangeExecutionBinding.objects.select_for_update().get(
            change_record=change
        )
    except ChangeExecutionBinding.DoesNotExist:
        raise DomainValidationError(
            code="binding_not_found",
            detail="No execution binding found for this change.",
        )
    if str(binding.execution_id) != str(execution_id):
        raise DomainValidationError(
            code="execution_id_mismatch",
            detail="Execution ID does not match binding.",
        )
    if not binding.bound_at:
        raise InvalidStateTransitionError(
            code="execution_not_bound",
            detail="Execution has not been bound yet.",
        )
    if binding.bound_by_runner_id != runner_id:
        raise InvalidStateTransitionError(
            code="runner_ownership_mismatch",
            detail="Runner does not own this execution.",
        )
    return change, binding


def record_execution_accepted(
    *,
    change_id: str,
    runner_id: str,
    execution_id: str,
    observed_at=None,
) -> dict:
    """Record that the runner has accepted the change execution dispatch.

    Stores a runner-observed timestamp on the binding. Idempotent: if
    execution_accepted_at is already set the call succeeds without overwriting.
    """
    now = observed_at or timezone.now()

    with transaction.atomic():
        change, binding = _resolve_bound_binding(
            change_id=change_id,
            runner_id=runner_id,
            execution_id=execution_id,
        )

        if binding.execution_accepted_at is None:
            binding.execution_accepted_at = now
            binding.save(update_fields=["execution_accepted_at", "updated_at"])

        _emit(
            change=change,
            event_type="change.execution_accepted",
            object_type=AuditEvent.ObjectType.CHANGE_EXECUTION_BINDING,
            actor=_runner_actor(runner_id),
            metadata={
                "execution_id": str(execution_id),
                "runner_id": runner_id,
                "observed_at": now.isoformat(),
            },
            object_id=binding.id,
        )

    return {
        "change_record_id": str(change.id),
        "binding_id": str(binding.id),
        "execution_id": str(execution_id),
        "execution_accepted_at": binding.execution_accepted_at,
    }


def record_execution_started(
    *,
    change_id: str,
    runner_id: str,
    execution_id: str,
    observed_at=None,
) -> dict:
    """Record that the runner has started executing the change.

    Stores a runner-observed timestamp on the binding. Idempotent: if
    execution_started_at is already set the call succeeds without overwriting.
    """
    now = observed_at or timezone.now()

    with transaction.atomic():
        change, binding = _resolve_bound_binding(
            change_id=change_id,
            runner_id=runner_id,
            execution_id=execution_id,
        )

        if binding.execution_started_at is None:
            binding.execution_started_at = now
            binding.save(update_fields=["execution_started_at", "updated_at"])

        _emit(
            change=change,
            event_type="change.execution_started",
            object_type=AuditEvent.ObjectType.CHANGE_EXECUTION_BINDING,
            actor=_runner_actor(runner_id),
            metadata={
                "execution_id": str(execution_id),
                "runner_id": runner_id,
                "observed_at": now.isoformat(),
            },
            object_id=binding.id,
        )

    return {
        "change_record_id": str(change.id),
        "binding_id": str(binding.id),
        "execution_id": str(execution_id),
        "execution_started_at": binding.execution_started_at,
    }


def _release_active_target_locks(
    *, change: ChangeRecord, now, runner_id: str
) -> int:
    """Release all ACTIVE target locks for the change. Returns count released."""
    locks = list(
        TargetLock.objects.select_for_update().filter(
            change_record=change, status=TargetLock.Status.ACTIVE
        )
    )
    for lock in locks:
        lock.status = TargetLock.Status.RELEASED
        lock.released_at = now
        lock.release_reason = "execution_finished"
        lock.save(update_fields=["status", "released_at", "release_reason", "updated_at"])
        AuditService.emit(
            organization_id=change.organization_id,
            actor_type=AuditEvent.ActorType.RUNNER,
            actor_id=runner_id,
            actor_label=runner_id,
            event_type="target_lock.released",
            object_type=AuditEvent.ObjectType.TARGET_LOCK,
            object_id=lock.id,
            metadata={
                "change_record_id": str(change.id),
                "target_type": lock.target_type,
                "target_identifier": lock.target_identifier,
                "release_reason": "execution_finished",
            },
        )
    return len(locks)


def _finalize_window_on_execution_finished(
    *, change: ChangeRecord, now, runner_id: str
) -> str | None:
    """Update the change window status when execution finishes.

    Returns the new window status, or None if no window exists or it was
    already in a final state.
    """
    try:
        window = ChangeWindow.objects.select_for_update().get(change_record=change)
    except ChangeWindow.DoesNotExist:
        return None

    if window.status in (ChangeWindow.Status.CLOSED, ChangeWindow.Status.OVERRUN):
        return window.status

    if now > window.ends_at:
        new_status = ChangeWindow.Status.OVERRUN
        window.status = new_status
        window.overrun_at = now
        window.save(update_fields=["status", "overrun_at", "updated_at"])
        event_type = "change.window_overrun"
    else:
        new_status = ChangeWindow.Status.CLOSED
        window.status = new_status
        window.closed_at = now
        window.save(update_fields=["status", "closed_at", "updated_at"])
        event_type = "change.window_closed"

    AuditService.emit(
        organization_id=change.organization_id,
        actor_type=AuditEvent.ActorType.RUNNER,
        actor_id=runner_id,
        actor_label=runner_id,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.CHANGE_WINDOW,
        object_id=window.id,
        metadata={
            "change_record_id": str(change.id),
            "window_ends_at": window.ends_at.isoformat(),
            "observed_finished_at": now.isoformat(),
        },
    )
    return new_status


def record_execution_finished(
    *,
    change_id: str,
    runner_id: str,
    execution_id: str,
    observed_at=None,
) -> dict:
    """Record that the runner has finished executing the change.

    Stores a runner-observed timestamp, releases all active target locks, and
    finalizes the change window status (CLOSED or OVERRUN). Idempotent: if
    execution_finished_at is already set the locks and window are still
    re-evaluated (both are no-ops when already in terminal state).
    """
    now = observed_at or timezone.now()

    with transaction.atomic():
        change, binding = _resolve_bound_binding(
            change_id=change_id,
            runner_id=runner_id,
            execution_id=execution_id,
        )

        if binding.execution_finished_at is None:
            binding.execution_finished_at = now
            binding.save(update_fields=["execution_finished_at", "updated_at"])

        locks_released = _release_active_target_locks(
            change=change, now=now, runner_id=runner_id
        )
        window_status = _finalize_window_on_execution_finished(
            change=change, now=now, runner_id=runner_id
        )

        _emit(
            change=change,
            event_type="change.execution_finished",
            object_type=AuditEvent.ObjectType.CHANGE_EXECUTION_BINDING,
            actor=_runner_actor(runner_id),
            metadata={
                "execution_id": str(execution_id),
                "runner_id": runner_id,
                "observed_at": now.isoformat(),
                "locks_released": locks_released,
                "window_status": window_status,
            },
            object_id=binding.id,
        )

    return {
        "change_record_id": str(change.id),
        "binding_id": str(binding.id),
        "execution_id": str(execution_id),
        "execution_finished_at": binding.execution_finished_at,
        "locks_released": locks_released,
        "window_status": window_status,
    }


# ---------------------------------------------------------------------------
# Execution completion hook
# ---------------------------------------------------------------------------


def handle_bound_execution_completed(*, execution) -> None:
    """Update change lifecycle after bound execution completes."""
    try:
        binding = ChangeExecutionBinding.objects.select_related("change_record").get(
            execution=execution
        )
    except ChangeExecutionBinding.DoesNotExist:
        return

    with transaction.atomic():
        change = ChangeRecord.objects.select_for_update().get(
            pk=binding.change_record_id
        )
        # Execution completed before binding was confirmed — the runner executed
        # without calling bind-execution (e.g. expired token at claim time).
        # Expire the change so it does not remain stranded in dispatchable.
        if change.status == ChangeRecord.Status.DISPATCHABLE:
            expire_dispatchable_change(
                change=change,
                now=timezone.now(),
                terminal_reason="execution_failed_before_binding",
            )
            return
        if change.status != ChangeRecord.Status.RUNNING:
            return
        try:
            validate_request_integrity(change)
        except InvalidStateTransitionError:
            transition_change(
                change=change,
                new_status=ChangeRecord.Status.CLOSED,
                actor=system_actor("Change service"),
                now=timezone.now(),
                terminal_reason="request_integrity_mismatch",
                audit_metadata={"execution_status": execution.status},
            )
            return

        profile = OperationProfile.objects.get(pk=change.operation_profile_id)
        now = timezone.now()

        if execution.status == Execution.Status.SUCCEEDED:
            if profile.verification_required:
                transition_change(
                    change=change,
                    new_status=ChangeRecord.Status.VERIFICATION_PENDING,
                    actor=system_actor("Change service"),
                    now=now,
                    audit_metadata={
                        "execution_status": execution.status,
                        "verification_required": profile.verification_required,
                    },
                )
            else:
                transition_change(
                    change=change,
                    new_status=ChangeRecord.Status.CLOSED,
                    actor=system_actor("Change service"),
                    now=now,
                    terminal_reason="execution_succeeded",
                    audit_metadata={
                        "execution_status": execution.status,
                        "verification_required": profile.verification_required,
                    },
                )
        else:
            terminal_reason = (
                "execution_cancelled"
                if execution.status == Execution.Status.CANCELLED
                else "execution_failed"
            )
            transition_change(
                change=change,
                new_status=ChangeRecord.Status.CLOSED,
                actor=system_actor("Change service"),
                now=now,
                terminal_reason=terminal_reason,
                audit_metadata={
                    "execution_status": execution.status,
                    "verification_required": profile.verification_required,
                },
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _emit(
    *,
    change: ChangeRecord,
    event_type: str,
    object_type: str,
    actor: AuditActor,
    metadata: dict,
    object_id=None,
) -> None:
    AuditService.emit(
        organization_id=change.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id if object_id is not None else change.id,
        metadata=metadata,
    )


def _runner_actor(runner_id: str) -> AuditActor:
    return AuditActor(
        actor_type=AuditEvent.ActorType.RUNNER,
        actor_id=runner_id,
        actor_label=runner_id,
    )


# ---------------------------------------------------------------------------
# Change window service
# ---------------------------------------------------------------------------

# Statuses that allow window creation / update.
_WINDOW_ALLOWED_STATUSES = frozenset(
    [
        ChangeRecord.Status.DRAFT,
        ChangeRecord.Status.PENDING_APPROVAL,
        ChangeRecord.Status.APPROVED,
        ChangeRecord.Status.SCHEDULED,
    ]
)

# Statuses where a window update must invalidate the existing approval.
_WINDOW_INVALIDATION_STATUSES = frozenset(
    [
        ChangeRecord.Status.APPROVED,
        ChangeRecord.Status.SCHEDULED,
    ]
)

# Terminal ChangeRecord statuses that map the window to CLOSED.
_CHANGE_TERMINAL_STATUSES = frozenset(
    [
        ChangeRecord.Status.CLOSED,
        ChangeRecord.Status.VERIFIED,
        ChangeRecord.Status.REJECTED,
        ChangeRecord.Status.CANCELED,
        ChangeRecord.Status.EXPIRED,
    ]
)

# ChangeRecord statuses considered "running" for overrun detection.
_CHANGE_RUNNING_STATUSES = frozenset(
    [
        ChangeRecord.Status.RUNNING,
        ChangeRecord.Status.VERIFICATION_PENDING,
    ]
)


def _window_status_from_time(starts_at, ends_at, now) -> str:
    """Compute window status from time boundaries only."""
    if now < starts_at:
        return ChangeWindow.Status.SCHEDULED
    if now <= ends_at:
        return ChangeWindow.Status.OPEN
    return ChangeWindow.Status.EXPIRED


def recompute_window_status(window: ChangeWindow, now=None) -> str:
    """Compute window status from starts_at, ends_at, change execution status, and current time."""
    now = now or timezone.now()
    change_status = window.change_record.status

    if change_status in _CHANGE_TERMINAL_STATUSES:
        return ChangeWindow.Status.CLOSED

    if change_status in _CHANGE_RUNNING_STATUSES and now > window.ends_at:
        return ChangeWindow.Status.OVERRUN

    return _window_status_from_time(window.starts_at, window.ends_at, now)


def _invalidate_change_approval(
    *, change: ChangeRecord, actor: AuditActor, now
) -> None:
    """Reset an approved/scheduled change to pending_approval, voiding the approval.

    This bypasses the transition table intentionally: approval invalidation is a
    reverse transition that exists only in this context (window update after approval).
    The caller is responsible for holding a select_for_update lock on `change`.
    """
    previous_status = change.status
    change.status = ChangeRecord.Status.PENDING_APPROVAL
    change.approved_at = None
    change.save(update_fields=["status", "approved_at", "updated_at"])
    AuditService.emit(
        organization_id=change.organization_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        event_type="change.approval_invalidated",
        object_type=AuditEvent.ObjectType.CHANGE_RECORD,
        object_id=change.id,
        metadata={
            "previous_status": previous_status,
            "reason": "window_updated",
        },
    )


def create_or_update_change_window(
    *,
    change: ChangeRecord,
    starts_at,
    ends_at,
    timezone_name: str = "",
    reason: str = "",
    actor: AuditActor | None = None,
) -> ChangeWindow:
    """Create or replace the ChangeWindow for a change record.

    Allowed while the change is draft, pending_approval, approved, or scheduled.
    Updating the window for an approved/scheduled change with requires_approval=True
    invalidates the approval and resets the change to pending_approval.
    """
    if change.status not in _WINDOW_ALLOWED_STATUSES:
        raise InvalidStateTransitionError(
            code="window_update_not_allowed",
            detail=(
                f"Cannot update window for change with status '{change.status}'. "
                "Window updates are only allowed before dispatch."
            ),
        )

    if ends_at <= starts_at:
        raise DomainValidationError(
            code="window_ends_before_starts",
            detail="ends_at must be after starts_at.",
        )

    audit_actor = actor or system_actor("Change service")
    now = timezone.now()
    approval_invalidated = False

    with transaction.atomic():
        change = ChangeRecord.objects.select_for_update().get(pk=change.pk)

        if change.status not in _WINDOW_ALLOWED_STATUSES:
            raise InvalidStateTransitionError(
                code="window_update_not_allowed",
                detail=(
                    f"Cannot update window for change with status '{change.status}'."
                ),
            )

        if change.status in _WINDOW_INVALIDATION_STATUSES:
            profile = OperationProfile.objects.get(pk=change.operation_profile_id)
            if profile.requires_approval:
                _invalidate_change_approval(change=change, actor=audit_actor, now=now)
                approval_invalidated = True

        computed_status = _window_status_from_time(starts_at, ends_at, now)
        updated_by_id = (
            audit_actor.actor_id
            if audit_actor.actor_type == AuditEvent.ActorType.USER
            else None
        )

        try:
            window = ChangeWindow.objects.select_for_update().get(change_record=change)
            window.starts_at = starts_at
            window.ends_at = ends_at
            window.timezone = timezone_name
            window.reason = reason
            window.status = computed_status
            window.updated_by_id = updated_by_id
            window.save(
                update_fields=[
                    "starts_at",
                    "ends_at",
                    "timezone",
                    "reason",
                    "status",
                    "updated_by",
                    "updated_at",
                ]
            )
        except ChangeWindow.DoesNotExist:
            window = ChangeWindow.objects.create(
                change_record=change,
                organization=change.organization,
                starts_at=starts_at,
                ends_at=ends_at,
                timezone=timezone_name,
                reason=reason,
                status=computed_status,
                updated_by_id=updated_by_id,
            )

        AuditService.emit(
            organization_id=change.organization_id,
            actor_type=audit_actor.actor_type,
            actor_id=audit_actor.actor_id,
            actor_label=audit_actor.actor_label,
            event_type="change.window_updated",
            object_type=AuditEvent.ObjectType.CHANGE_WINDOW,
            object_id=window.id,
            metadata={
                "change_record_id": str(change.id),
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "window_status": window.status,
                "approval_invalidated": approval_invalidated,
            },
        )

    return window


# ---------------------------------------------------------------------------
# FreezeRule governance service functions
# ---------------------------------------------------------------------------


def emit_freeze_rule_audit(
    *,
    rule: FreezeRule,
    event_type: str,
    actor: AuditActor | None = None,
    metadata: dict | None = None,
) -> None:
    audit_actor = actor or system_actor("Change service")
    AuditService.emit(
        organization_id=rule.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.FREEZE_RULE,
        object_id=rule.id,
        metadata={
            "name": rule.name,
            "behavior": rule.behavior,
            "scope_type": rule.scope_type,
            "is_active": rule.is_active,
            **(metadata or {}),
        },
    )


def create_freeze_rule(
    *,
    organization,
    name: str,
    behavior: str,
    starts_at,
    ends_at,
    scope_type: str,
    description: str = "",
    target_type: str = "",
    target_identifier: str = "",
    requires_exception_reference: bool = False,
    actor: AuditActor | None = None,
) -> FreezeRule:
    """Create a new FreezeRule with org scoping, validation, and audit."""
    if behavior not in (FreezeRule.Behavior.BLOCK, FreezeRule.Behavior.ALLOW_WITH_EXCEPTION):
        raise DomainValidationError(
            code="invalid_behavior",
            detail="behavior must be 'block' or 'allow_with_exception'.",
        )
    if scope_type not in (
        FreezeRule.ScopeType.ALL_PRODUCTION,
        FreezeRule.ScopeType.TARGET_TYPE,
        FreezeRule.ScopeType.TARGET_IDENTIFIER,
    ):
        raise DomainValidationError(
            code="invalid_scope_type",
            detail="scope_type must be 'all_production', 'target_type', or 'target_identifier'.",
        )
    if ends_at <= starts_at:
        raise DomainValidationError(
            code="invalid_time_range",
            detail="ends_at must be after starts_at.",
        )
    if (
        behavior == FreezeRule.Behavior.ALLOW_WITH_EXCEPTION
        and not requires_exception_reference
    ):
        raise DomainValidationError(
            code="exception_behavior_requires_ref",
            detail="allow_with_exception behavior requires requires_exception_reference=True.",
        )
    if scope_type == FreezeRule.ScopeType.TARGET_TYPE and not target_type:
        raise DomainValidationError(
            code="target_type_required",
            detail="target_type is required when scope_type is 'target_type'.",
        )
    if scope_type == FreezeRule.ScopeType.TARGET_IDENTIFIER and not target_identifier:
        raise DomainValidationError(
            code="target_identifier_required",
            detail="target_identifier is required when scope_type is 'target_identifier'.",
        )

    audit_actor = actor or system_actor("Change service")
    normalized = (
        normalize_target_identifier(target_identifier)
        if target_identifier
        else ""
    )
    rule = FreezeRule(
        organization=organization,
        name=name,
        description=description,
        behavior=behavior,
        starts_at=starts_at,
        ends_at=ends_at,
        scope_type=scope_type,
        target_type=target_type,
        target_identifier=target_identifier,
        normalized_identifier=normalized,
        requires_exception_reference=requires_exception_reference,
        is_active=True,
        created_by_id=audit_actor.actor_id
        if audit_actor.actor_type == AuditEvent.ActorType.USER
        else None,
        updated_by_id=audit_actor.actor_id
        if audit_actor.actor_type == AuditEvent.ActorType.USER
        else None,
    )
    rule.save()
    emit_freeze_rule_audit(rule=rule, event_type="freeze_rule.created", actor=audit_actor)
    return rule


def update_freeze_rule(
    *,
    rule: FreezeRule,
    actor: AuditActor | None = None,
    name: str | None = None,
    description: str | None = None,
    behavior: str | None = None,
    starts_at=None,
    ends_at=None,
    scope_type: str | None = None,
    target_type: str | None = None,
    target_identifier: str | None = None,
    requires_exception_reference: bool | None = None,
) -> FreezeRule:
    """Update mutable FreezeRule fields with validation and audit."""
    if not rule.is_active:
        raise DomainValidationError(
            code="freeze_rule_inactive",
            detail="Cannot update an inactive freeze rule.",
        )

    new_behavior = behavior if behavior is not None else rule.behavior
    new_starts_at = starts_at if starts_at is not None else rule.starts_at
    new_ends_at = ends_at if ends_at is not None else rule.ends_at
    new_scope_type = scope_type if scope_type is not None else rule.scope_type
    new_target_type = target_type if target_type is not None else rule.target_type
    new_target_identifier = (
        target_identifier if target_identifier is not None else rule.target_identifier
    )
    new_req_ref = (
        requires_exception_reference
        if requires_exception_reference is not None
        else rule.requires_exception_reference
    )

    if new_behavior not in (FreezeRule.Behavior.BLOCK, FreezeRule.Behavior.ALLOW_WITH_EXCEPTION):
        raise DomainValidationError(
            code="invalid_behavior",
            detail="behavior must be 'block' or 'allow_with_exception'.",
        )
    if new_ends_at <= new_starts_at:
        raise DomainValidationError(
            code="invalid_time_range",
            detail="ends_at must be after starts_at.",
        )
    if (
        new_behavior == FreezeRule.Behavior.ALLOW_WITH_EXCEPTION
        and not new_req_ref
    ):
        raise DomainValidationError(
            code="exception_behavior_requires_ref",
            detail="allow_with_exception behavior requires requires_exception_reference=True.",
        )
    if new_scope_type == FreezeRule.ScopeType.TARGET_TYPE and not new_target_type:
        raise DomainValidationError(
            code="target_type_required",
            detail="target_type is required when scope_type is 'target_type'.",
        )
    if new_scope_type == FreezeRule.ScopeType.TARGET_IDENTIFIER and not new_target_identifier:
        raise DomainValidationError(
            code="target_identifier_required",
            detail="target_identifier is required when scope_type is 'target_identifier'.",
        )

    audit_actor = actor or system_actor("Change service")
    update_fields: list[str] = ["updated_at"]

    if name is not None:
        rule.name = name
        update_fields.append("name")
    if description is not None:
        rule.description = description
        update_fields.append("description")
    if behavior is not None:
        rule.behavior = behavior
        update_fields.append("behavior")
    if starts_at is not None:
        rule.starts_at = starts_at
        update_fields.append("starts_at")
    if ends_at is not None:
        rule.ends_at = ends_at
        update_fields.append("ends_at")
    if scope_type is not None:
        rule.scope_type = scope_type
        update_fields.append("scope_type")
    if target_type is not None:
        rule.target_type = target_type
        update_fields.append("target_type")
    if target_identifier is not None:
        rule.target_identifier = target_identifier
        rule.normalized_identifier = normalize_target_identifier(target_identifier)
        update_fields.extend(["target_identifier", "normalized_identifier"])
    if requires_exception_reference is not None:
        rule.requires_exception_reference = requires_exception_reference
        update_fields.append("requires_exception_reference")
    if audit_actor.actor_type == AuditEvent.ActorType.USER:
        rule.updated_by_id = audit_actor.actor_id
        if "updated_by" not in update_fields:
            update_fields.append("updated_by")

    rule.save(update_fields=update_fields)
    emit_freeze_rule_audit(rule=rule, event_type="freeze_rule.updated", actor=audit_actor)
    return rule


def deactivate_freeze_rule(
    *,
    rule: FreezeRule,
    actor: AuditActor | None = None,
) -> FreezeRule:
    """Deactivate a FreezeRule. Idempotent when already inactive."""
    if not rule.is_active:
        return rule
    audit_actor = actor or system_actor("Change service")
    update_fields = ["is_active", "updated_at"]
    rule.is_active = False
    if audit_actor.actor_type == AuditEvent.ActorType.USER:
        rule.updated_by_id = audit_actor.actor_id
        update_fields.append("updated_by")
    rule.save(update_fields=update_fields)
    emit_freeze_rule_audit(rule=rule, event_type="freeze_rule.deactivated", actor=audit_actor)
    return rule


def get_active_matching_freeze_rules(
    *,
    organization,
    target_type: str = "",
    target_identifier: str = "",
    at=None,
) -> models.QuerySet:
    """Return active FreezeRule objects that match the given target at the given time.

    Used as a helper for dispatch preflight — callers receive the queryset
    so they can inspect behavior (block vs. allow_with_exception) themselves.
    """
    from django.utils import timezone as tz

    now = at or tz.now()
    normalized = normalize_target_identifier(target_identifier) if target_identifier else ""

    # Base: active, time window covers now, same org.
    qs = FreezeRule.objects.filter(
        organization=organization,
        is_active=True,
        starts_at__lte=now,
        ends_at__gt=now,
    )

    from django.db.models import Q

    scope_filter = Q(scope_type=FreezeRule.ScopeType.ALL_PRODUCTION)
    if target_type:
        scope_filter |= Q(
            scope_type=FreezeRule.ScopeType.TARGET_TYPE,
            target_type=target_type,
        )
    if normalized:
        scope_filter |= Q(
            scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
            normalized_identifier=normalized,
        )

    return qs.filter(scope_filter).order_by("starts_at")


# ---------------------------------------------------------------------------
# Dispatch preflight service
# ---------------------------------------------------------------------------

_PREFLIGHT_TTL_SECONDS = 300  # 5 minutes

# Change statuses that are valid candidates for dispatch preflight.
_PREFLIGHT_ELIGIBLE_STATUSES = frozenset(
    [
        ChangeRecord.Status.APPROVED,
        ChangeRecord.Status.SCHEDULED,
        ChangeRecord.Status.DISPATCHABLE,
    ]
)


def run_dispatch_preflight(
    *,
    change: ChangeRecord,
    actor: AuditActor | None = None,
) -> DispatchEligibilityCheck:
    """Run all dispatch preflight checks and persist an immutable snapshot.

    Checks (in order):
    1. approved_status   — change is approved/scheduled/dispatchable and approval is valid
    2. policy_pass       — policy evaluation (if any) has an effective pass outcome
    3. window_open       — no window exists, or the change window is currently open
    4. freeze_conflicts  — no blocking freeze rules match the change's targets
    5. target_locks      — no active target locks conflict with the change's targets
    6. actor_authorized  — actor is present (view layer enforces operator role)

    All checks run regardless of prior failures so the caller gets a full picture.
    The result is PASSED only when every individual check passes.
    """
    from django.db.models import Q

    now = timezone.now()

    change = (
        ChangeRecord.objects.select_related(
            "operation_profile",
            "approval_request",
            "policy_evaluation",
        )
        .prefetch_related("targets")
        .get(pk=change.pk)
    )

    targets = list(change.targets.order_by("position"))
    checks: list[dict] = []
    conflicts: list[dict] = []

    approved_status_ok = _preflight_check_approval_status(change, checks)
    policy_pass_ok = _preflight_check_policy_gate(change, checks)
    window_open_ok, window_snapshot_sha256 = _preflight_check_window(change, now, checks)
    freeze_conflicts_ok = _preflight_check_freeze_conflicts(change, targets, now, checks, conflicts)
    target_locks_ok = _preflight_check_target_locks(change, targets, checks, conflicts)
    actor_authorized_ok = _preflight_check_actor(actor, checks)

    overall = all(
        [
            approved_status_ok,
            policy_pass_ok,
            window_open_ok,
            freeze_conflicts_ok,
            target_locks_ok,
            actor_authorized_ok,
        ]
    )
    result = (
        DispatchEligibilityCheck.Result.PASSED
        if overall
        else DispatchEligibilityCheck.Result.FAILED
    )

    input_snapshot_sha256 = change.request_snapshot_sha256 or sha256_canonical_json(
        change.request_snapshot
    )

    check = DispatchEligibilityCheck.objects.create(
        organization=change.organization,
        change_record=change,
        requested_by_id=(
            actor.actor_id
            if actor and actor.actor_type == AuditEvent.ActorType.USER
            else None
        ),
        result=result,
        checked_at=now,
        expires_at=now + timedelta(seconds=_PREFLIGHT_TTL_SECONDS),
        approved_status_ok=approved_status_ok,
        policy_pass_ok=policy_pass_ok,
        window_open_ok=window_open_ok,
        freeze_conflicts_ok=freeze_conflicts_ok,
        target_locks_ok=target_locks_ok,
        actor_authorized_ok=actor_authorized_ok,
        checks=checks,
        conflicts=conflicts,
        input_snapshot_sha256=input_snapshot_sha256,
        window_snapshot_sha256=window_snapshot_sha256,
    )

    audit_actor = actor or system_actor("Change service")
    AuditService.emit(
        organization_id=change.organization_id,
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.actor_id,
        actor_label=audit_actor.actor_label,
        event_type="change.preflight_checked",
        object_type=AuditEvent.ObjectType.DISPATCH_ELIGIBILITY_CHECK,
        object_id=check.id,
        metadata={
            "change_record_id": str(change.id),
            "result": result,
        },
    )

    return check


def _preflight_check_approval_status(
    change: ChangeRecord, checks: list
) -> bool:
    if change.status not in _PREFLIGHT_ELIGIBLE_STATUSES:
        checks.append(
            {
                "name": "approved_status",
                "ok": False,
                "detail": (
                    f"Change is not in an eligible status for dispatch "
                    f"(current: '{change.status}')."
                ),
            }
        )
        return False

    profile = change.operation_profile
    if profile.requires_approval:
        ar = change.approval_request
        if ar is None:
            checks.append(
                {
                    "name": "approved_status",
                    "ok": False,
                    "detail": "Profile requires approval but no approval request exists.",
                }
            )
            return False
        if ar.status != "approved":
            checks.append(
                {
                    "name": "approved_status",
                    "ok": False,
                    "detail": f"Approval request is '{ar.status}', expected 'approved'.",
                }
            )
            return False

    checks.append({"name": "approved_status", "ok": True, "detail": "Approval status is valid."})
    return True


def _preflight_check_policy_gate(change: ChangeRecord, checks: list) -> bool:
    pe = change.policy_evaluation
    if pe is None:
        checks.append(
            {
                "name": "policy_pass",
                "ok": True,
                "detail": "No policy evaluation linked; gate passes by default.",
            }
        )
        return True

    effective = getattr(pe, "effective_outcome", None)
    if effective == "pass":
        checks.append({"name": "policy_pass", "ok": True, "detail": "Policy evaluation passed."})
        return True

    checks.append(
        {
            "name": "policy_pass",
            "ok": False,
            "detail": (
                f"Policy evaluation effective outcome is '{effective}', expected 'pass'."
            ),
        }
    )
    return False


def _preflight_check_window(
    change: ChangeRecord, now, checks: list
) -> tuple[bool, str]:
    try:
        window = change.window
    except Exception:
        window = None

    if window is None:
        checks.append(
            {
                "name": "window_open",
                "ok": True,
                "detail": "No change window configured; gate passes by default.",
            }
        )
        return True, ""

    computed_status = recompute_window_status(window, now=now)
    window_snapshot = {
        "window_id": str(window.id),
        "starts_at": window.starts_at.isoformat(),
        "ends_at": window.ends_at.isoformat(),
        "status": computed_status,
    }
    window_sha256 = sha256_canonical_json(window_snapshot)

    if computed_status == ChangeWindow.Status.OPEN:
        checks.append({"name": "window_open", "ok": True, "detail": "Change window is open."})
        return True, window_sha256

    checks.append(
        {
            "name": "window_open",
            "ok": False,
            "detail": f"Change window is '{computed_status}', not open.",
        }
    )
    return False, window_sha256


def _preflight_check_freeze_conflicts(
    change: ChangeRecord,
    targets: list,
    now,
    checks: list,
    conflicts: list,
) -> bool:
    from django.db.models import Q

    if not targets:
        checks.append(
            {
                "name": "freeze_conflicts",
                "ok": True,
                "detail": "No targets; freeze check skipped.",
            }
        )
        return True

    base_qs = FreezeRule.objects.filter(
        organization=change.organization,
        is_active=True,
        starts_at__lte=now,
        ends_at__gt=now,
    )
    scope_filter = Q(scope_type=FreezeRule.ScopeType.ALL_PRODUCTION)
    for t in targets:
        scope_filter |= Q(
            scope_type=FreezeRule.ScopeType.TARGET_TYPE,
            target_type=t.target_type,
        )
        scope_filter |= Q(
            scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
            normalized_identifier=normalize_target_identifier(t.target_identifier),
        )

    matching_rules = list(base_qs.filter(scope_filter).order_by("starts_at"))

    blocking: list[FreezeRule] = []
    for rule in matching_rules:
        if rule.behavior == FreezeRule.Behavior.BLOCK:
            blocking.append(rule)
        elif rule.behavior == FreezeRule.Behavior.ALLOW_WITH_EXCEPTION:
            if not change.freeze_exception_reference:
                blocking.append(rule)

    for rule in blocking:
        conflicts.append(
            {
                "type": "freeze_rule",
                "id": str(rule.id),
                "name": rule.name,
                "behavior": rule.behavior,
                "scope_type": rule.scope_type,
            }
        )

    ok = not blocking
    if ok:
        checks.append(
            {
                "name": "freeze_conflicts",
                "ok": True,
                "detail": "No active freeze conflicts.",
            }
        )
    else:
        checks.append(
            {
                "name": "freeze_conflicts",
                "ok": False,
                "detail": f"{len(blocking)} freeze rule(s) block dispatch.",
            }
        )
    return ok


def _preflight_check_target_locks(
    change: ChangeRecord,
    targets: list,
    checks: list,
    conflicts: list,
) -> bool:
    from django.db.models import Q

    if not targets:
        checks.append(
            {"name": "target_locks", "ok": True, "detail": "No targets; lock check skipped."}
        )
        return True

    target_filter = Q()
    for t in targets:
        target_filter |= Q(
            target_type=t.target_type,
            normalized_identifier=normalize_target_identifier(t.target_identifier),
        )

    conflicting = list(
        TargetLock.objects.filter(
            organization=change.organization,
            status=TargetLock.Status.ACTIVE,
        )
        .filter(target_filter)
        .exclude(change_record=change)
        .select_related("change_record")
        .order_by("acquired_at")
    )

    for lock in conflicting:
        conflicts.append(
            {
                "type": "target_lock",
                "id": str(lock.id),
                "target_type": lock.target_type,
                "target_identifier": lock.target_identifier,
                "change_record_id": str(lock.change_record_id),
                "acquired_at": lock.acquired_at.isoformat(),
            }
        )

    ok = not conflicting
    if ok:
        checks.append(
            {"name": "target_locks", "ok": True, "detail": "No conflicting target locks."}
        )
    else:
        checks.append(
            {
                "name": "target_locks",
                "ok": False,
                "detail": f"{len(conflicting)} active lock(s) conflict with this change's targets.",
            }
        )
    return ok


def _preflight_check_actor(actor: AuditActor | None, checks: list) -> bool:
    if actor is not None:
        checks.append(
            {"name": "actor_authorized", "ok": True, "detail": "Actor is authorized to dispatch."}
        )
        return True
    checks.append(
        {
            "name": "actor_authorized",
            "ok": False,
            "detail": "No authenticated actor; dispatch authorization cannot be confirmed.",
        }
    )
    return False
