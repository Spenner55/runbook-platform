"""Centralized ChangeRecord lifecycle transition table and helper.

All ChangeRecord status changes must flow through ``transition_change``.
Direct ``change.status = ...`` assignments outside this module are forbidden
for lifecycle writes.
"""

from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService, system_actor
from apps.changes.models import ChangeRecord
from apps.common.exceptions import InvalidStateTransitionError

# ---------------------------------------------------------------------------
# Transition table — single source of truth for valid lifecycle moves.
# ---------------------------------------------------------------------------

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ChangeRecord.Status.DRAFT: {
        ChangeRecord.Status.PENDING_APPROVAL,
        ChangeRecord.Status.APPROVED,
        ChangeRecord.Status.CANCELED,
    },
    ChangeRecord.Status.PENDING_APPROVAL: {
        ChangeRecord.Status.APPROVED,
        ChangeRecord.Status.REJECTED,
        ChangeRecord.Status.EXPIRED,
        ChangeRecord.Status.CANCELED,
    },
    ChangeRecord.Status.APPROVED: {
        ChangeRecord.Status.SCHEDULED,
        ChangeRecord.Status.DISPATCHABLE,
        ChangeRecord.Status.CANCELED,
    },
    ChangeRecord.Status.SCHEDULED: {
        ChangeRecord.Status.DISPATCHABLE,
        ChangeRecord.Status.EXPIRED,
        ChangeRecord.Status.CANCELED,
    },
    ChangeRecord.Status.DISPATCHABLE: {
        ChangeRecord.Status.RUNNING,
        ChangeRecord.Status.EXPIRED,
    },
    ChangeRecord.Status.RUNNING: {
        ChangeRecord.Status.VERIFICATION_PENDING,
        ChangeRecord.Status.CLOSED,
    },
    ChangeRecord.Status.VERIFICATION_PENDING: {
        ChangeRecord.Status.VERIFIED,
        ChangeRecord.Status.VERIFICATION_FAILED,
    },
    ChangeRecord.Status.VERIFICATION_FAILED: {ChangeRecord.Status.CLOSED},
    ChangeRecord.Status.VERIFIED: {ChangeRecord.Status.CLOSED},
    # Terminal states have no outgoing transitions.
    ChangeRecord.Status.CLOSED: set(),
    ChangeRecord.Status.REJECTED: set(),
    ChangeRecord.Status.CANCELED: set(),
    ChangeRecord.Status.EXPIRED: set(),
}

# Map each status to the timestamp field set when it is entered, or None.
_STATUS_TIMESTAMP_FIELDS: dict[str, str | None] = {
    ChangeRecord.Status.PENDING_APPROVAL: None,
    ChangeRecord.Status.APPROVED: "approved_at",
    ChangeRecord.Status.SCHEDULED: None,
    ChangeRecord.Status.DISPATCHABLE: "dispatchable_at",
    ChangeRecord.Status.RUNNING: "running_at",
    ChangeRecord.Status.VERIFICATION_PENDING: "verification_pending_at",
    ChangeRecord.Status.VERIFICATION_FAILED: "verification_failed_at",
    ChangeRecord.Status.VERIFIED: "verified_at",
    ChangeRecord.Status.CLOSED: "closed_at",
    ChangeRecord.Status.REJECTED: "rejected_at",
    ChangeRecord.Status.CANCELED: "canceled_at",
    ChangeRecord.Status.EXPIRED: "expired_at",
}


# ---------------------------------------------------------------------------
# Transition helper
# ---------------------------------------------------------------------------


def transition_change(
    *,
    change: ChangeRecord,
    new_status: str,
    actor: AuditActor | None = None,
    now=None,
    terminal_reason: str = "",
    audit_metadata: dict | None = None,
    save: bool = True,
) -> str:
    """Apply one allowed lifecycle transition and emit exactly one ``change.status_changed`` audit event.

    Returns the previous status.
    Raises ``InvalidStateTransitionError`` for disallowed transitions without
    persisting any change or emitting any audit event.
    """
    previous_status = change.status
    allowed = ALLOWED_STATUS_TRANSITIONS.get(previous_status, set())
    if new_status not in allowed:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Invalid change transition: '{previous_status}' -> '{new_status}'.",
        )

    now = now or timezone.now()
    change.status = new_status
    update_fields = ["status", "updated_at"]

    timestamp_field = _STATUS_TIMESTAMP_FIELDS.get(new_status)
    if timestamp_field is not None:
        setattr(change, timestamp_field, now)
        update_fields.append(timestamp_field)

    if terminal_reason:
        change.terminal_reason = terminal_reason
        update_fields.append("terminal_reason")

    if save:
        change.save(update_fields=update_fields)

    resolved_actor = actor or system_actor("Change service")
    metadata: dict = {
        "previous_status": previous_status,
        "new_status": new_status,
    }
    if terminal_reason:
        metadata["terminal_reason"] = terminal_reason
    if audit_metadata:
        metadata.update(audit_metadata)

    AuditService.emit(
        organization_id=change.organization_id,
        actor_type=resolved_actor.actor_type,
        actor_id=resolved_actor.actor_id,
        actor_label=resolved_actor.actor_label,
        event_type="change.status_changed",
        object_type=AuditEvent.ObjectType.CHANGE_RECORD,
        object_id=change.id,
        metadata=metadata,
    )
    return previous_status
