"""Comprehensive tests for the centralized ChangeRecord lifecycle transition system.

Covers:
- Every entry in the allowed-transition table succeeds.
- Every disallowed transition raises InvalidStateTransitionError.
- Exactly one ``change.status_changed`` audit event is emitted per valid transition.
- No audit event is emitted for rejected transitions.
- ``schedule_or_make_dispatchable()`` rejects every status except ``approved``.
"""

import pytest

from apps.audit.models import AuditEvent
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord
from apps.changes.transitions import ALLOWED_STATUS_TRANSITIONS, transition_change
from apps.common.exceptions import InvalidStateTransitionError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_STATUSES = [s.value for s in ChangeRecord.Status]


def _set_status(change: ChangeRecord, status: str) -> ChangeRecord:
    """Force change into given status via queryset update (bypasses model hooks)."""
    ChangeRecord.objects.filter(pk=change.pk).update(status=status)
    change.refresh_from_db()
    return change


def _status_changed_count(change: ChangeRecord) -> int:
    return AuditEvent.objects.filter(
        event_type="change.status_changed",
        object_id=change.id,
    ).count()


# ---------------------------------------------------------------------------
# Build parametrize lists from the canonical transition table.
# ---------------------------------------------------------------------------

_ALLOWED_PAIRS = [
    (from_s, to_s)
    for from_s, allowed in ALLOWED_STATUS_TRANSITIONS.items()
    for to_s in sorted(allowed)
]

_FORBIDDEN_PAIRS = [
    (from_s, to_s)
    for from_s in _ALL_STATUSES
    for to_s in _ALL_STATUSES
    if to_s not in ALLOWED_STATUS_TRANSITIONS.get(from_s, set())
]


# ---------------------------------------------------------------------------
# Every allowed transition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("from_status,to_status", _ALLOWED_PAIRS)
def test_allowed_transition_succeeds(from_status, to_status, draft_change):
    change = _set_status(draft_change, from_status)
    before = _status_changed_count(change)

    transition_change(change=change, new_status=to_status)

    change.refresh_from_db()
    assert change.status == to_status, (
        f"Expected status={to_status!r} after {from_status!r}->{to_status!r}"
    )
    assert _status_changed_count(change) == before + 1, (
        "Expected exactly one new change.status_changed audit event"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("from_status,to_status", _ALLOWED_PAIRS)
def test_allowed_transition_sets_timestamp(from_status, to_status, draft_change):
    """Each terminal-path status should record a non-null timestamp when entered."""
    _TIMESTAMP_FIELDS = {
        "approved": "approved_at",
        "dispatchable": "dispatchable_at",
        "running": "running_at",
        "verification_pending": "verification_pending_at",
        "verification_failed": "verification_failed_at",
        "verified": "verified_at",
        "closed": "closed_at",
        "rejected": "rejected_at",
        "canceled": "canceled_at",
        "expired": "expired_at",
    }
    change = _set_status(draft_change, from_status)
    transition_change(change=change, new_status=to_status)
    change.refresh_from_db()

    ts_field = _TIMESTAMP_FIELDS.get(to_status)
    if ts_field is not None:
        assert getattr(change, ts_field) is not None, (
            f"{ts_field} should be set after transitioning to {to_status!r}"
        )


# ---------------------------------------------------------------------------
# Every forbidden transition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("from_status,to_status", _FORBIDDEN_PAIRS)
def test_forbidden_transition_raises(from_status, to_status, draft_change):
    change = _set_status(draft_change, from_status)
    before = _status_changed_count(change)

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        transition_change(change=change, new_status=to_status)

    assert exc_info.value.code == "invalid_state_transition"

    change.refresh_from_db()
    assert change.status == from_status, "Status must not change on rejected transition"
    assert _status_changed_count(change) == before, (
        "No audit event should be emitted for a rejected transition"
    )


# ---------------------------------------------------------------------------
# Terminal state immutability — terminal states have zero outgoing transitions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "terminal_status",
    [
        ChangeRecord.Status.CLOSED,
        ChangeRecord.Status.REJECTED,
        ChangeRecord.Status.CANCELED,
        ChangeRecord.Status.EXPIRED,
    ],
)
def test_terminal_status_has_no_outgoing_transitions(terminal_status):
    assert ALLOWED_STATUS_TRANSITIONS.get(terminal_status, set()) == set(), (
        f"Terminal status {terminal_status!r} must have no outgoing transitions"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "terminal_status",
    [
        ChangeRecord.Status.CLOSED,
        ChangeRecord.Status.REJECTED,
        ChangeRecord.Status.CANCELED,
        ChangeRecord.Status.EXPIRED,
    ],
)
def test_terminal_status_rejects_all_transitions(terminal_status, draft_change):
    change = _set_status(draft_change, terminal_status)
    before = _status_changed_count(change)

    for to_status in _ALL_STATUSES:
        with pytest.raises(InvalidStateTransitionError):
            transition_change(change=change, new_status=to_status)

    assert _status_changed_count(change) == before, (
        "No audit events should be emitted from a terminal status"
    )


# ---------------------------------------------------------------------------
# Audit event exactly-once guarantee
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_single_audit_event_per_transition(draft_change):
    """Each call to transition_change emits exactly one status_changed event."""
    before = _status_changed_count(draft_change)
    transition_change(
        change=draft_change, new_status=ChangeRecord.Status.PENDING_APPROVAL
    )
    assert _status_changed_count(draft_change) == before + 1

    transition_change(change=draft_change, new_status=ChangeRecord.Status.APPROVED)
    assert _status_changed_count(draft_change) == before + 2

    transition_change(change=draft_change, new_status=ChangeRecord.Status.CANCELED)
    assert _status_changed_count(draft_change) == before + 3


@pytest.mark.django_db
def test_rejected_transition_emits_no_audit_event(draft_change):
    """A disallowed transition must produce zero new audit events."""
    before = _status_changed_count(draft_change)
    with pytest.raises(InvalidStateTransitionError):
        transition_change(change=draft_change, new_status=ChangeRecord.Status.RUNNING)
    assert _status_changed_count(draft_change) == before


@pytest.mark.django_db
def test_audit_event_metadata_contains_previous_and_new_status(draft_change):
    transition_change(
        change=draft_change, new_status=ChangeRecord.Status.PENDING_APPROVAL
    )
    event = AuditEvent.objects.filter(
        event_type="change.status_changed",
        object_id=draft_change.id,
    ).latest("created_at")
    assert event.metadata["previous_status"] == ChangeRecord.Status.DRAFT
    assert event.metadata["new_status"] == ChangeRecord.Status.PENDING_APPROVAL


@pytest.mark.django_db
def test_audit_event_metadata_contains_terminal_reason(draft_change):
    _set_status(draft_change, ChangeRecord.Status.DISPATCHABLE)
    transition_change(
        change=draft_change,
        new_status=ChangeRecord.Status.EXPIRED,
        terminal_reason="dispatch_token_expired",
    )
    event = AuditEvent.objects.filter(
        event_type="change.status_changed",
        object_id=draft_change.id,
    ).latest("created_at")
    assert event.metadata["terminal_reason"] == "dispatch_token_expired"


# ---------------------------------------------------------------------------
# schedule_or_make_dispatchable — rejects every non-approved status
# ---------------------------------------------------------------------------

_NON_APPROVED_STATUSES = [s for s in _ALL_STATUSES if s != ChangeRecord.Status.APPROVED]


@pytest.mark.django_db
@pytest.mark.parametrize("bad_status", _NON_APPROVED_STATUSES)
def test_schedule_or_make_dispatchable_rejects_non_approved(bad_status, draft_change):
    """schedule_or_make_dispatchable must only accept approved changes."""
    change = _set_status(draft_change, bad_status)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=change)
    assert exc_info.value.code == "invalid_state_transition", (
        f"Expected invalid_state_transition for status={bad_status!r}"
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "terminal_status",
    [
        ChangeRecord.Status.CLOSED,
        ChangeRecord.Status.REJECTED,
        ChangeRecord.Status.CANCELED,
        ChangeRecord.Status.EXPIRED,
    ],
)
def test_schedule_or_make_dispatchable_rejects_terminal_states(
    terminal_status, draft_change
):
    change = _set_status(draft_change, terminal_status)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=change)
    assert exc_info.value.code == "invalid_state_transition"


@pytest.mark.django_db
def test_schedule_or_make_dispatchable_rejects_draft(draft_change):
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=draft_change)
    assert exc_info.value.code == "invalid_state_transition"


@pytest.mark.django_db
def test_schedule_or_make_dispatchable_rejects_pending_approval(draft_change):
    change = _set_status(draft_change, ChangeRecord.Status.PENDING_APPROVAL)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=change)
    assert exc_info.value.code == "invalid_state_transition"


@pytest.mark.django_db
def test_schedule_or_make_dispatchable_rejects_running(draft_change):
    change = _set_status(draft_change, ChangeRecord.Status.RUNNING)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=change)
    assert exc_info.value.code == "invalid_state_transition"


@pytest.mark.django_db
def test_schedule_or_make_dispatchable_rejects_dispatchable(draft_change):
    change = _set_status(draft_change, ChangeRecord.Status.DISPATCHABLE)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=change)
    assert exc_info.value.code == "invalid_state_transition"


@pytest.mark.django_db
def test_schedule_or_make_dispatchable_rejects_scheduled(draft_change):
    change = _set_status(draft_change, ChangeRecord.Status.SCHEDULED)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.schedule_or_make_dispatchable(change=change)
    assert exc_info.value.code == "invalid_state_transition"


# ---------------------------------------------------------------------------
# Transition table completeness — all ChangeRecord.Status values are present
# ---------------------------------------------------------------------------


def test_transition_table_covers_all_statuses():
    """Every status defined on ChangeRecord must appear as a key in the table."""
    defined = {s.value for s in ChangeRecord.Status}
    table_keys = set(ALLOWED_STATUS_TRANSITIONS.keys())
    missing = defined - table_keys
    assert not missing, f"Statuses missing from ALLOWED_STATUS_TRANSITIONS: {missing}"


def test_transition_table_targets_are_valid_statuses():
    """Every target status in the table must be a valid ChangeRecord.Status value."""
    valid = {s.value for s in ChangeRecord.Status}
    for from_s, allowed in ALLOWED_STATUS_TRANSITIONS.items():
        invalid_targets = allowed - valid
        assert not invalid_targets, (
            f"Invalid target statuses from {from_s!r}: {invalid_targets}"
        )


def test_all_status_values_are_in_all_statuses_list():
    """Sanity: _ALL_STATUSES must match ChangeRecord.Status exactly."""
    assert set(_ALL_STATUSES) == {s.value for s in ChangeRecord.Status}
