"""Change record lifecycle services."""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.changes.models import (
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    OperationProfile,
)
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)
from apps.workflows.models import Workflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical hashing helpers
# ---------------------------------------------------------------------------


def canonical_json_bytes(value) -> bytes:
    """Produce canonical UTF-8 JSON bytes with sorted keys and compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_canonical_json(value) -> str:
    """Return hex SHA-256 of canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_request_snapshot(change_record: ChangeRecord, targets: list) -> dict:
    """Build the immutable request snapshot dict for a change record."""
    target_list = [
        {
            "position": t.position,
            "target_type": t.target_type,
            "target_identifier": t.target_identifier,
            "normalized_identifier": t.normalized_identifier,
            "display_name": t.display_name,
            "environment": t.environment,
        }
        for t in sorted(targets, key=lambda t: t.position)
    ]
    return {
        "change_record_id": str(change_record.id),
        "operation_profile_key": change_record.operation_profile.key,
        "workflow_id": str(change_record.workflow_id),
        "workflow_version": change_record.workflow.version,
        "requested_inputs_sha256": sha256_canonical_json(change_record.requested_inputs),
        "scheduled_for": change_record.scheduled_for.isoformat()
        if change_record.scheduled_for
        else None,
        "targets": target_list,
        "submitted_at": timezone.now().isoformat(),
    }


def hash_dispatch_token(token: str) -> str:
    """SHA-256 hash of the clear dispatch token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_dispatch_token(binding: ChangeExecutionBinding) -> str:
    """Regenerate the clear dispatch token from stored nonce + server secret."""
    secret = getattr(settings, "CHANGE_DISPATCH_TOKEN_SECRET", "insecure-change-me")
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
    """Constant-time comparison of submitted token against expected regenerated token."""
    expected = generate_dispatch_token(binding)
    return hmac.compare_digest(expected, token)


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

    _validate_targets(targets, profile)

    with transaction.atomic():
        change = ChangeRecord.objects.create(
            organization=organization,
            operation_profile=profile,
            workflow=workflow,
            requested_by_id=actor.actor_id if actor and actor.actor_type == AuditEvent.ActorType.USER else None,
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
        if not profile.allowed_target_types or ttype not in profile.allowed_target_types:
            raise DomainValidationError(
                code="target_type_not_allowed",
                detail=f"Target type '{ttype}' is not allowed by profile.",
            )
        normalized = normalize_target_identifier(t.get("target_identifier", ""))
        key = (ttype, normalized)
        if key in seen:
            raise DomainValidationError(
                code="duplicate_change_target",
                detail=f"Duplicate target: type='{ttype}', identifier='{t.get('target_identifier')}'.",
            )
        seen.add(key)


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

        profile = (
            OperationProfile.objects.prefetch_related("allowed_workflows").get(
                pk=change.operation_profile_id
            )
        )
        if not profile.is_active:
            raise DomainConflictError(
                code="change_profile_inactive",
                detail=f"Operation profile '{profile.key}' is no longer active.",
            )

        workflow = Workflow.objects.get(pk=change.workflow_id)
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
        _validate_targets(
            [
                {
                    "environment": t.environment,
                    "target_type": t.target_type,
                    "target_identifier": t.target_identifier,
                }
                for t in targets
            ],
            profile,
        )

        now = timezone.now()
        inputs_hash = sha256_canonical_json(change.requested_inputs)
        snapshot = build_request_snapshot(change, targets)
        snapshot_hash = sha256_canonical_json(snapshot)

        change.requested_inputs_sha256 = inputs_hash
        change.request_snapshot = snapshot
        change.request_snapshot_sha256 = snapshot_hash
        change.operation_profile_key_snapshot = profile.key
        change.workflow_version_snapshot = workflow.version
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
            change.status = ChangeRecord.Status.PENDING_APPROVAL
            change.save(
                update_fields=[
                    "requested_inputs_sha256",
                    "request_snapshot",
                    "request_snapshot_sha256",
                    "operation_profile_key_snapshot",
                    "workflow_version_snapshot",
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
            change.status = ChangeRecord.Status.APPROVED
            change.approved_at = now
            change.save(
                update_fields=[
                    "requested_inputs_sha256",
                    "request_snapshot",
                    "request_snapshot_sha256",
                    "operation_profile_key_snapshot",
                    "workflow_version_snapshot",
                    "submitted_at",
                    "submitted_by",
                    "status",
                    "approved_at",
                    "updated_at",
                ]
            )
            _emit(
                change=change,
                event_type="change.status_changed",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                actor=actor or system_actor("Change service"),
                metadata={
                    "previous_status": ChangeRecord.Status.DRAFT,
                    "new_status": change.status,
                },
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
        return

    if change.status != ChangeRecord.Status.PENDING_APPROVAL:
        return

    now = timezone.now()
    previous_status = change.status

    if decision == "approved":
        change.status = ChangeRecord.Status.APPROVED
        change.approved_at = now
        change.save(update_fields=["status", "approved_at", "updated_at"])
        _emit(
            change=change,
            event_type="change.status_changed",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=actor or system_actor("Change service"),
            metadata={
                "previous_status": previous_status,
                "new_status": change.status,
            },
        )
        schedule_or_make_dispatchable(change=change, actor=actor)

    elif decision == "rejected":
        change.status = ChangeRecord.Status.REJECTED
        change.rejected_at = now
        change.terminal_reason = "approval_rejected"
        change.save(
            update_fields=["status", "rejected_at", "terminal_reason", "updated_at"]
        )
        _emit(
            change=change,
            event_type="change.status_changed",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=actor or system_actor("Change service"),
            metadata={
                "previous_status": previous_status,
                "new_status": change.status,
                "terminal_reason": change.terminal_reason,
            },
        )

    elif decision == "timed_out":
        change.status = ChangeRecord.Status.EXPIRED
        change.expired_at = now
        change.terminal_reason = "approval_timed_out"
        change.save(
            update_fields=["status", "expired_at", "terminal_reason", "updated_at"]
        )
        _emit(
            change=change,
            event_type="change.status_changed",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=actor or system_actor("Change service"),
            metadata={
                "previous_status": previous_status,
                "new_status": change.status,
                "terminal_reason": change.terminal_reason,
            },
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
    now = timezone.now()
    if change.scheduled_for and change.scheduled_for > now:
        previous_status = change.status
        change.status = ChangeRecord.Status.SCHEDULED
        change.save(update_fields=["status", "updated_at"])
        _emit(
            change=change,
            event_type="change.status_changed",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=actor or system_actor("Change service"),
            metadata={
                "previous_status": previous_status,
                "new_status": change.status,
                "scheduled_for": change.scheduled_for.isoformat(),
            },
        )
    else:
        make_dispatchable(change=change, actor=actor)


def make_dispatchable(
    *,
    change: ChangeRecord,
    actor: AuditActor | None = None,
) -> None:
    """Reserve an execution and create the ChangeExecutionBinding."""
    from apps.executions import services as execution_services  # avoid circular

    change = ChangeRecord.objects.select_for_update().get(pk=change.pk)
    if change.status not in (ChangeRecord.Status.APPROVED, ChangeRecord.Status.SCHEDULED):
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot dispatch change with status '{change.status}'.",
        )

    profile = OperationProfile.objects.get(pk=change.operation_profile_id)
    workflow = Workflow.objects.get(pk=change.workflow_id)

    execution = execution_services.create_execution(
        workflow=workflow,
        actor=actor or system_actor("Change service"),
        _from_change_service=True,
    )

    now = timezone.now()
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
        update_fields=["dispatch_token_hash", "runner_payload_snapshot", "updated_at"]
    )

    previous_status = change.status
    change.status = ChangeRecord.Status.DISPATCHABLE
    change.dispatchable_at = now
    change.save(update_fields=["status", "dispatchable_at", "updated_at"])

    _emit(
        change=change,
        event_type="change.execution_binding_reserved",
        object_type=AuditEvent.ObjectType.CHANGE_EXECUTION_BINDING,
        actor=actor or system_actor("Change service"),
        metadata={
            "change_record_id": str(change.id),
            "execution_id": str(execution.id),
            "operation_profile_key": profile.key,
            "requested_inputs_sha256": inputs_hash,
        },
        object_id=binding.id,
    )
    _emit(
        change=change,
        event_type="change.status_changed",
        object_type=AuditEvent.ObjectType.CHANGE_RECORD,
        actor=actor or system_actor("Change service"),
        metadata={
            "previous_status": previous_status,
            "new_status": change.status,
        },
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

        # Idempotency: same runner/execution/payload already bound — return success.
        if binding.bound_at is not None:
            if binding.bound_by_runner_id == runner_id:
                return {
                    "change_record_id": str(change.id),
                    "execution_id": str(execution.id),
                    "binding_id": str(binding.id),
                    "status": change.status,
                    "bound_at": binding.bound_at,
                }
            raise InvalidStateTransitionError(
                code="execution_binding_conflict",
                detail="Binding already claimed by a different runner.",
            )

        # Status check comes after idempotency so retries never fail here.
        if change.status != ChangeRecord.Status.DISPATCHABLE:
            raise InvalidStateTransitionError(
                code="change_not_dispatchable",
                detail=f"Change is not dispatchable (status: '{change.status}').",
            )

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

        now = timezone.now()
        if binding.dispatch_token_expires_at <= now:
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

        previous_status = change.status
        change.status = ChangeRecord.Status.RUNNING
        change.running_at = now
        change.save(update_fields=["status", "running_at", "updated_at"])

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
        _emit(
            change=change,
            event_type="change.status_changed",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=_runner_actor(runner_id),
            metadata={
                "previous_status": previous_status,
                "new_status": change.status,
            },
        )

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
        if change.status != ChangeRecord.Status.RUNNING:
            return

        profile = OperationProfile.objects.get(pk=change.operation_profile_id)
        now = timezone.now()
        previous_status = change.status

        from apps.executions.models import Execution  # avoid circular

        if execution.status == Execution.Status.SUCCEEDED:
            if profile.verification_required:
                change.status = ChangeRecord.Status.VERIFICATION_PENDING
                change.verification_pending_at = now
                change.save(
                    update_fields=["status", "verification_pending_at", "updated_at"]
                )
            else:
                change.status = ChangeRecord.Status.CLOSED
                change.closed_at = now
                change.terminal_reason = "execution_succeeded"
                change.save(
                    update_fields=[
                        "status",
                        "closed_at",
                        "terminal_reason",
                        "updated_at",
                    ]
                )
        else:
            terminal_reason = (
                "execution_cancelled"
                if execution.status == Execution.Status.CANCELLED
                else "execution_failed"
            )
            change.status = ChangeRecord.Status.CLOSED
            change.closed_at = now
            change.terminal_reason = terminal_reason
            change.save(
                update_fields=["status", "closed_at", "terminal_reason", "updated_at"]
            )

        _emit(
            change=change,
            event_type="change.status_changed",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            actor=system_actor("Change service"),
            metadata={
                "previous_status": previous_status,
                "new_status": change.status,
                "terminal_reason": change.terminal_reason,
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
