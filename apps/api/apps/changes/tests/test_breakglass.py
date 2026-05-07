"""
Phase 11.4 Batch 3 tests: BreakglassSession services and APIs.

Covers:
- activation: valid scope, invalid scope, TTL enforcement, one active per change
- expiry enforcement before gate checks
- scope assertion: gate_type, action, target_ids out of scope
- end_breakglass: manual end, invalid state transition
- record_breakglass_heartbeat: observation recorded, no expiry extension
- mark_breakglass_review_overdue: pending -> overdue
- API endpoints: activate and end
- audit events emitted
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import BreakglassSession, ChangeRecord, RetroReview
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)
from apps.organizations.models import Membership, MembershipRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now():
    return timezone.now()


def _future(seconds=3600):
    return _now() + timedelta(seconds=seconds)


def _past(seconds=60):
    return _now() - timedelta(seconds=seconds)


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _user_actor(user):
    return AuditActor(
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.pk),
        actor_label=user.email,
    )


def _make_scope(change, *, actions=None, gates=None, target_ids=None):
    actual_ids = list(str(tid) for tid in change.targets.values_list("id", flat=True))
    return {
        "allowed_actions": actions or ["dispatch", "continue_running"],
        "gate_types": gates or ["window_overrun"],
        "target_ids": target_ids if target_ids is not None else actual_ids,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def running_change(db, draft_change, user, org):
    """A change record in 'running' status (force-set for testing)."""
    profile = draft_change.operation_profile
    profile.allow_emergency_changes = True
    profile.save(update_fields=["allow_emergency_changes", "updated_at"])
    draft_change.status = ChangeRecord.Status.RUNNING
    draft_change.save(update_fields=["status", "updated_at"])
    return draft_change


@pytest.fixture
def dispatchable_change(db, draft_change):
    """A change record in 'dispatchable' status."""
    profile = draft_change.operation_profile
    profile.allow_emergency_changes = True
    profile.save(update_fields=["allow_emergency_changes", "updated_at"])
    draft_change.status = ChangeRecord.Status.DISPATCHABLE
    draft_change.save(update_fields=["status", "updated_at"])
    return draft_change


@pytest.fixture
def operator_user(db, org):
    from apps.users.models import User

    u = User.objects.create_user(email="operator@example.com", password="pass!")
    Membership.objects.create(organization=org, user=u, role=MembershipRole.OPERATOR)
    return u


@pytest.fixture
def admin_user(db, org):
    from apps.users.models import User

    u = User.objects.create_user(email="admin@example.com", password="pass!")
    Membership.objects.create(organization=org, user=u, role=MembershipRole.ADMIN)
    return u


@pytest.fixture
def api_client_operator(operator_user, org):
    client = APIClient()
    client.force_authenticate(user=operator_user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


# ---------------------------------------------------------------------------
# Service: activate_breakglass
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_activate_breakglass_success(running_change, operator_user, db):
    scope = _make_scope(running_change)
    actor = _user_actor(operator_user)
    expires_at = _future(1800)

    session = change_services.activate_breakglass(
        change=running_change,
        actor=actor,
        scope_json=scope,
        reason="Emergency prod incident.",
        expires_at=expires_at,
        actor_user=operator_user,
    )

    assert session.status == BreakglassSession.Status.ACTIVE
    assert session.activated_by == operator_user
    assert session.change_record == running_change
    assert session.scope_sha256 != ""
    assert session.review_due_at > session.started_at


@pytest.mark.django_db
def test_activate_breakglass_creates_retro_review(running_change, operator_user, db):
    scope = _make_scope(running_change)
    actor = _user_actor(operator_user)

    session = change_services.activate_breakglass(
        change=running_change,
        actor=actor,
        scope_json=scope,
        reason="Incident mitigation",
        expires_at=_future(1800),
        actor_user=operator_user,
    )

    review = RetroReview.objects.get(breakglass_session=session)
    assert review.status == RetroReview.Status.PENDING
    assert review.due_at == session.review_due_at


@pytest.mark.django_db
def test_activate_breakglass_sets_change_retro_review_required(
    running_change, operator_user, db
):
    scope = _make_scope(running_change)
    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    running_change.refresh_from_db()
    assert running_change.retro_review_required is True
    assert running_change.retro_review_due_at is not None


@pytest.mark.django_db
def test_activate_breakglass_emits_audit_events(running_change, operator_user, db):
    scope = _make_scope(running_change)
    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Incident",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    events = AuditEvent.objects.filter(
        organization_id=running_change.organization_id,
        event_type="breakglass.activated",
    )
    assert events.exists()


@pytest.mark.django_db
def test_activate_breakglass_invalid_status(draft_change, operator_user, db):
    profile = draft_change.operation_profile
    profile.allow_emergency_changes = True
    profile.save(update_fields=["allow_emergency_changes", "updated_at"])
    scope = _make_scope(draft_change)
    with pytest.raises(DomainConflictError) as exc_info:
        change_services.activate_breakglass(
            change=draft_change,
            actor=_user_actor(operator_user),
            scope_json=scope,
            reason="Reason",
            expires_at=_future(1800),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "change_status_invalid_for_breakglass"


@pytest.mark.django_db
def test_activate_breakglass_requires_profile_emergency_enabled(
    running_change, operator_user, db
):
    profile = running_change.operation_profile
    profile.allow_emergency_changes = False
    profile.save(update_fields=["allow_emergency_changes", "updated_at"])

    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=_make_scope(running_change),
            reason="Reason",
            expires_at=_future(1800),
            actor_user=operator_user,
        )

    assert exc_info.value.code == "breakglass_not_allowed"


@pytest.mark.django_db
def test_activate_breakglass_expires_at_past(running_change, operator_user, db):
    scope = _make_scope(running_change)
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=scope,
            reason="Reason",
            expires_at=_past(60),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "breakglass_expires_at_past"


@pytest.mark.django_db
def test_activate_breakglass_ttl_exceeded(running_change, operator_user, db):
    """TTL must not exceed profile max_breakglass_seconds."""
    profile = running_change.operation_profile
    profile.max_breakglass_seconds = 300
    profile.save(update_fields=["max_breakglass_seconds"])

    scope = _make_scope(running_change)
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=scope,
            reason="Reason",
            expires_at=_future(3600),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "breakglass_ttl_exceeded"


@pytest.mark.django_db
def test_activate_breakglass_missing_scope_keys(running_change, operator_user, db):
    bad_scope = {"allowed_actions": ["dispatch"]}  # missing target_ids and gate_types
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=bad_scope,
            reason="Reason",
            expires_at=_future(1800),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "breakglass_scope_missing_keys"


@pytest.mark.django_db
def test_activate_breakglass_empty_scope_list(running_change, operator_user, db):
    scope = _make_scope(running_change)
    scope["allowed_actions"] = []
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=scope,
            reason="Reason",
            expires_at=_future(1800),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "breakglass_scope_empty_list"


@pytest.mark.django_db
def test_activate_breakglass_forbidden_scope_key(running_change, operator_user, db):
    scope = _make_scope(running_change)
    scope["ssh_key"] = "do-not-include-credentials"
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=scope,
            reason="Reason",
            expires_at=_future(1800),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "breakglass_scope_forbidden_key"


@pytest.mark.django_db
def test_activate_breakglass_unknown_target_ids(running_change, operator_user, db):
    import uuid

    scope = _make_scope(running_change, target_ids=[str(uuid.uuid4())])
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.activate_breakglass(
            change=running_change,
            actor=_user_actor(operator_user),
            scope_json=scope,
            reason="Reason",
            expires_at=_future(1800),
            actor_user=operator_user,
        )
    assert exc_info.value.code == "breakglass_scope_unknown_targets"


@pytest.mark.django_db
def test_activate_breakglass_one_active_per_change(running_change, operator_user, db):
    """Only one active breakglass session per change."""
    scope = _make_scope(running_change)
    actor = _user_actor(operator_user)

    change_services.activate_breakglass(
        change=running_change,
        actor=actor,
        scope_json=scope,
        reason="First session",
        expires_at=_future(1800),
        actor_user=operator_user,
    )

    with pytest.raises(Exception):  # DB uniqueness constraint
        change_services.activate_breakglass(
            change=running_change,
            actor=actor,
            scope_json=scope,
            reason="Second session",
            expires_at=_future(900),
            actor_user=operator_user,
        )


# ---------------------------------------------------------------------------
# Service: expire_breakglass_sessions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_expire_breakglass_sessions_marks_expired(running_change, operator_user, db):
    scope = _make_scope(running_change)
    session = change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Incident",
        expires_at=_future(1),
        actor_user=operator_user,
    )

    future_now = _now() + timedelta(seconds=10)
    expired = change_services.expire_breakglass_sessions(
        change=running_change, now=future_now
    )

    assert len(expired) == 1
    assert expired[0].id == session.id
    session.refresh_from_db()
    assert session.status == BreakglassSession.Status.EXPIRED
    assert session.end_reason == "expired"


@pytest.mark.django_db
def test_expire_breakglass_sessions_emits_audit(running_change, operator_user, db):
    scope = _make_scope(running_change)
    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Incident",
        expires_at=_future(1),
        actor_user=operator_user,
    )
    change_services.expire_breakglass_sessions(
        change=running_change, now=_now() + timedelta(seconds=10)
    )
    assert AuditEvent.objects.filter(event_type="breakglass.expired").exists()


# ---------------------------------------------------------------------------
# Service: assert_breakglass_allows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assert_breakglass_allows_success(running_change, operator_user, db):
    scope = _make_scope(running_change, actions=["dispatch"], gates=["window_overrun"])
    target_ids = scope["target_ids"]

    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )

    session = change_services.assert_breakglass_allows(
        change=running_change,
        gate_type="window_overrun",
        action="dispatch",
        target_ids=target_ids,
    )
    assert session.status == BreakglassSession.Status.ACTIVE


@pytest.mark.django_db
def test_assert_breakglass_allows_no_session(running_change, db):
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.assert_breakglass_allows(
            change=running_change,
            gate_type="window_overrun",
            action="dispatch",
            target_ids=[],
        )
    assert exc_info.value.code == "no_active_breakglass_session"


@pytest.mark.django_db
def test_assert_breakglass_allows_gate_type_not_in_scope(
    running_change, operator_user, db
):
    scope = _make_scope(running_change, gates=["window_overrun"])
    target_ids = scope["target_ids"]
    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.assert_breakglass_allows(
            change=running_change,
            gate_type="freeze_override",
            action="dispatch",
            target_ids=target_ids,
        )
    assert exc_info.value.code == "breakglass_gate_type_not_in_scope"


@pytest.mark.django_db
def test_assert_breakglass_allows_action_not_in_scope(
    running_change, operator_user, db
):
    scope = _make_scope(running_change, actions=["dispatch"])
    target_ids = scope["target_ids"]
    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.assert_breakglass_allows(
            change=running_change,
            gate_type="window_overrun",
            action="continue_running",
            target_ids=target_ids,
        )
    assert exc_info.value.code == "breakglass_action_not_in_scope"


@pytest.mark.django_db
def test_assert_breakglass_allows_expired_session_fails(
    running_change, operator_user, db
):
    scope = _make_scope(running_change)
    change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1),
        actor_user=operator_user,
    )
    future_now = _now() + timedelta(seconds=10)
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.assert_breakglass_allows(
            change=running_change,
            gate_type="window_overrun",
            action="dispatch",
            target_ids=scope["target_ids"],
            now=future_now,
        )
    assert exc_info.value.code == "no_active_breakglass_session"


# ---------------------------------------------------------------------------
# Service: end_breakglass
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_end_breakglass_success(running_change, operator_user, db):
    scope = _make_scope(running_change)
    session = change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    session = change_services.end_breakglass(
        session=session,
        actor=_user_actor(operator_user),
        end_reason="manual_end",
        actor_user=operator_user,
    )
    assert session.status == BreakglassSession.Status.ENDED
    assert session.end_reason == "manual_end"
    assert AuditEvent.objects.filter(event_type="breakglass.ended").exists()


@pytest.mark.django_db
def test_end_breakglass_already_expired_raises(running_change, operator_user, db):
    scope = _make_scope(running_change)
    session = change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1),
        actor_user=operator_user,
    )
    change_services.expire_breakglass_sessions(
        change=running_change, now=_now() + timedelta(seconds=10)
    )
    session.refresh_from_db()
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.end_breakglass(
            session=session,
            actor=_user_actor(operator_user),
        )
    assert exc_info.value.code == "breakglass_not_active"


# ---------------------------------------------------------------------------
# Service: record_breakglass_heartbeat — no extension
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_record_breakglass_heartbeat_does_not_extend_expiry(
    running_change, operator_user, db
):
    """Heartbeat updates last_heartbeat_at but must never change expires_at."""
    scope = _make_scope(running_change)
    session = change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    original_expires = session.expires_at

    # Simulate an execution binding so the service can validate runner ownership.
    from apps.changes.models import ChangeExecutionBinding
    from apps.executions.models import Execution

    execution = Execution.objects.create(
        organization=running_change.organization,
        workflow=running_change.workflow,
        workflow_version=running_change.workflow.version,
        workflow_snapshot={},
        status=Execution.Status.RUNNING,
        claimed_by_runner_id="runner-1",
        claim_token="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    ChangeExecutionBinding.objects.create(
        organization=running_change.organization,
        change_record=running_change,
        execution=execution,
        operation_profile_key="prod-maintenance",
        requested_inputs_sha256="abc123",
        dispatch_token_nonce="nonce",
        dispatch_token_hash="hash",
        dispatch_token_expires_at=_future(3600),
        reserved_at=_now(),
        bound_at=_now(),
        bound_by_runner_id="runner-1",
    )

    result = change_services.record_breakglass_heartbeat(
        change=running_change,
        runner_id="runner-1",
        claim_token="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        observed_session_id=str(session.id),
    )

    assert result is not None
    assert result.id == session.id
    result.refresh_from_db()
    assert result.expires_at == original_expires  # expiry unchanged
    assert result.last_heartbeat_at is not None


@pytest.mark.django_db
def test_execution_heartbeat_synchronously_expires_breakglass(
    running_change, operator_user, db
):
    scope = _make_scope(running_change)
    session = change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )

    from apps.changes.models import ChangeExecutionBinding
    from apps.executions import services as execution_services
    from apps.executions.models import Execution

    execution = Execution.objects.create(
        organization=running_change.organization,
        workflow=running_change.workflow,
        workflow_version=running_change.workflow.version,
        workflow_snapshot={},
        status=Execution.Status.RUNNING,
        claimed_by_runner_id="runner-1",
        claim_token="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    ChangeExecutionBinding.objects.create(
        organization=running_change.organization,
        change_record=running_change,
        execution=execution,
        operation_profile_key="prod-maintenance",
        requested_inputs_sha256="abc123",
        dispatch_token_nonce="nonce",
        dispatch_token_hash="hash",
        dispatch_token_expires_at=_future(3600),
        reserved_at=_now(),
        bound_at=_now(),
        bound_by_runner_id="runner-1",
    )
    BreakglassSession.objects.filter(pk=session.pk).update(
        started_at=_past(120),
        expires_at=_past(60),
    )

    execution_services.heartbeat_execution(
        execution=execution,
        runner_id="runner-1",
        claim_token="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    session.refresh_from_db()
    assert session.status == BreakglassSession.Status.EXPIRED
    assert session.end_reason == "expired"


# ---------------------------------------------------------------------------
# Service: mark_breakglass_review_overdue
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_breakglass_review_overdue(running_change, operator_user, db):
    scope = _make_scope(running_change)
    session = change_services.activate_breakglass(
        change=running_change,
        actor=_user_actor(operator_user),
        scope_json=scope,
        reason="Reason",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    assert session.review_status == BreakglassSession.ReviewStatus.PENDING

    overdue = change_services.mark_breakglass_review_overdue(
        now=session.review_due_at + timedelta(seconds=1)
    )

    assert len(overdue) >= 1
    session.refresh_from_db()
    assert session.review_status == BreakglassSession.ReviewStatus.OVERDUE
    assert AuditEvent.objects.filter(event_type="retro_review.overdue").exists()


# ---------------------------------------------------------------------------
# API: POST /api/v1/changes/{id}/breakglass/activate/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_activate_breakglass(api_client_operator, running_change, db):
    scope = _make_scope(running_change)
    response = api_client_operator.post(
        f"/api/v1/changes/{running_change.id}/breakglass/activate/",
        {
            "reason": "Emergency prod incident.",
            "scope_json": scope,
            "expires_at": (_future(1800)).isoformat(),
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    data = response.json()
    assert data["status"] == "active"
    assert data["scope_sha256"] != ""


@pytest.mark.django_db
def test_api_activate_breakglass_invalid_status(api_client_operator, draft_change, db):
    scope = _make_scope(draft_change)
    response = api_client_operator.post(
        f"/api/v1/changes/{draft_change.id}/breakglass/activate/",
        {
            "reason": "Reason",
            "scope_json": scope,
            "expires_at": _future(1800).isoformat(),
        },
        format="json",
    )
    assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
def test_api_activate_breakglass_missing_scope_keys(
    api_client_operator, running_change, db
):
    response = api_client_operator.post(
        f"/api/v1/changes/{running_change.id}/breakglass/activate/",
        {
            "reason": "Reason",
            "scope_json": {"allowed_actions": ["dispatch"]},
            "expires_at": _future(1800).isoformat(),
        },
        format="json",
    )
    assert response.status_code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_409_CONFLICT,
    )


@pytest.mark.django_db
def test_api_activate_breakglass_unauthenticated(running_change, db):
    client = APIClient()
    scope = _make_scope(running_change)
    response = client.post(
        f"/api/v1/changes/{running_change.id}/breakglass/activate/",
        {"reason": "R", "scope_json": scope, "expires_at": _future(1800).isoformat()},
        format="json",
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# API: POST /api/v1/changes/{id}/breakglass/end/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_end_breakglass(api_client_operator, running_change, db):
    scope = _make_scope(running_change)
    change_services.activate_breakglass(
        change=running_change,
        actor=AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test"),
        scope_json=scope,
        reason="Incident",
        expires_at=_future(1800),
    )
    response = api_client_operator.post(
        f"/api/v1/changes/{running_change.id}/breakglass/end/",
        {"end_reason": "manual_end"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ended"


@pytest.mark.django_db
def test_api_end_breakglass_no_active_session(api_client_operator, running_change, db):
    response = api_client_operator.post(
        f"/api/v1/changes/{running_change.id}/breakglass/end/",
        {},
        format="json",
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
