"""
Phase 11.4 Batch 4 tests: RetroReview services and APIs.

Covers:
- ensure_retro_review_for_exception: create, idempotent, non-qualifying
- submit_retro_review: accepted, needs_remediation, self-review, already-submitted
- mark_overdue_retro_reviews: pending -> overdue, idempotent
- assert_retro_reviews_allow_closure: pending blocks, accepted passes, remediation
- close_change blocked by pending retro-review
- approve_exception creates RetroReview for policy_override
- API endpoints: list, submit, inbox
- control_failure disposition updates change status
- overdue audit event emitted
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import ChangeException, ChangeRecord, FreezeRule, RetroReview
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


def _make_valid_policy_scope(change):
    from apps.executions.models import Execution, ExecutionStep
    from apps.policies.models import PolicyEvaluation

    execution = Execution.objects.create(
        organization=change.organization,
        workflow=change.workflow,
        workflow_version=change.workflow.version,
        workflow_snapshot={},
    )
    step = ExecutionStep.objects.create(
        execution=execution,
        position=1,
        step_key="policy-step",
        name="Policy step",
        step_type="shell",
        risk_level="high",
    )
    evaluation = PolicyEvaluation.objects.create(
        organization=change.organization,
        execution=execution,
        step=step,
        matched=True,
        outcome="block",
        effective_outcome="block",
        decision_source="workflow_default",
        evaluated_at=_now(),
    )
    change.refresh_from_db()
    change.policy_evaluation = evaluation
    change.save(update_fields=["policy_evaluation", "updated_at"])
    return {
        "policy_evaluation_id": str(evaluation.id),
        "policy_rule_ids": [],
        "overridden_outcome": "block",
    }


def _make_valid_freeze_scope(change):
    rule = FreezeRule.objects.create(
        organization=change.organization,
        name="Retro freeze",
        behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
        starts_at=_past(3600),
        ends_at=_future(3600),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=True,
    )
    return {
        "freeze_rule_id": str(rule.id),
        "target_ids": [str(tid) for tid in change.targets.values_list("id", flat=True)],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def operator_user(org, db):
    from apps.users.models import User

    u = User.objects.create_user(email="operator@retro.test", password="pass!")
    Membership.objects.create(organization=org, user=u, role=MembershipRole.OPERATOR)
    return u


@pytest.fixture
def admin_user(org, db):
    from apps.users.models import User

    u = User.objects.create_user(email="admin@retro.test", password="pass!")
    Membership.objects.create(organization=org, user=u, role=MembershipRole.ADMIN)
    return u


@pytest.fixture
def approver_user(org, db):
    from apps.users.models import User

    u = User.objects.create_user(email="approver@retro.test", password="pass!")
    Membership.objects.create(organization=org, user=u, role=MembershipRole.OPERATOR)
    return u


@pytest.fixture
def api_client_operator(operator_user, org):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    tokens = RefreshToken.for_user(operator_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


@pytest.fixture
def api_client_admin(admin_user, org):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    tokens = RefreshToken.for_user(admin_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


@pytest.fixture
def policy_override_exception(draft_change, operator_user, admin_user):
    """An approved policy_override exception."""
    exc = change_services.request_exception(
        change=draft_change,
        actor=_user_actor(operator_user),
        exception_type=ChangeException.ExceptionType.POLICY_OVERRIDE,
        reason="Override policy block for maintenance",
        scope_json=_make_valid_policy_scope(draft_change),
        expires_at=_future(7200),
        actor_user=operator_user,
    )
    return exc


@pytest.fixture
def approved_policy_override_exception(policy_override_exception, admin_user):
    return change_services.approve_exception(
        change_exception=policy_override_exception,
        actor=_user_actor(admin_user),
        actor_user=admin_user,
    )


@pytest.fixture
def freeze_override_exception(draft_change, operator_user):
    """A pending freeze_override exception (non-qualifying for retro-review)."""
    return change_services.request_exception(
        change=draft_change,
        actor=_user_actor(operator_user),
        exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
        reason="Override freeze",
        scope_json=_make_valid_freeze_scope(draft_change),
        expires_at=_future(7200),
        actor_user=operator_user,
    )


@pytest.fixture
def approved_freeze_override_exception(freeze_override_exception, approver_user):
    return change_services.approve_exception(
        change_exception=freeze_override_exception,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
    )


@pytest.fixture
def pending_retro_review(draft_change, approved_policy_override_exception, org):
    """A pending RetroReview created for an approved policy_override exception."""
    return RetroReview.objects.get(
        change_record=draft_change,
        change_exception=approved_policy_override_exception,
    )


# ---------------------------------------------------------------------------
# Service: ensure_retro_review_for_exception
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ensure_retro_review_for_exception_creates_review(
    draft_change, policy_override_exception, admin_user
):
    """Approving a policy_override creates a RetroReview."""
    change_services.approve_exception(
        change_exception=policy_override_exception,
        actor=_user_actor(admin_user),
        actor_user=admin_user,
    )
    review = RetroReview.objects.filter(
        change_record=draft_change,
        change_exception=policy_override_exception,
    ).first()
    assert review is not None
    assert review.status == RetroReview.Status.PENDING
    assert review.due_at is not None


@pytest.mark.django_db
def test_ensure_retro_review_for_exception_idempotent(
    approved_policy_override_exception,
):
    """Calling ensure_retro_review_for_exception twice returns the same review."""
    r1 = change_services.ensure_retro_review_for_exception(approved_policy_override_exception)
    r2 = change_services.ensure_retro_review_for_exception(approved_policy_override_exception)
    assert r1 is not None
    assert r2 is not None
    assert r1.pk == r2.pk
    assert RetroReview.objects.filter(change_exception=approved_policy_override_exception).count() == 1


@pytest.mark.django_db
def test_ensure_retro_review_for_nonqualifying_exception(
    approved_freeze_override_exception,
):
    """freeze_override exception returns None — not a qualifying type."""
    result = change_services.ensure_retro_review_for_exception(approved_freeze_override_exception)
    assert result is None
    assert not RetroReview.objects.filter(change_exception=approved_freeze_override_exception).exists()


# ---------------------------------------------------------------------------
# Service: submit_retro_review
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_retro_review_accepted(pending_retro_review, approver_user):
    """Accepted disposition: status becomes submitted."""
    review = change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
        disposition=RetroReview.Disposition.ACCEPTED,
        summary="Everything looks fine.",
    )
    assert review.status == RetroReview.Status.SUBMITTED
    assert review.disposition == RetroReview.Disposition.ACCEPTED
    assert review.reviewed_by == approver_user
    assert review.reviewed_at is not None
    assert review.remediation_required is False


@pytest.mark.django_db
def test_submit_retro_review_needs_remediation_requires_reference(
    pending_retro_review, approver_user
):
    """needs_remediation without remediation_reference raises DomainValidationError."""
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.submit_retro_review(
            review=pending_retro_review,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
            disposition=RetroReview.Disposition.NEEDS_REMEDIATION,
            summary="Needs fix",
            remediation_reference="",
        )
    assert exc_info.value.code == "retro_review_remediation_reference_required"


@pytest.mark.django_db
def test_submit_retro_review_needs_remediation_with_reference(
    pending_retro_review, approver_user
):
    """needs_remediation with remediation_reference succeeds."""
    review = change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
        disposition=RetroReview.Disposition.NEEDS_REMEDIATION,
        summary="Needs fix",
        remediation_reference="TICKET-123",
    )
    assert review.status == RetroReview.Status.SUBMITTED
    assert review.remediation_required is True
    assert review.remediation_reference == "TICKET-123"


@pytest.mark.django_db
def test_submit_retro_review_self_review_exception_rejected(
    pending_retro_review, operator_user
):
    """Exception requester cannot review their own exception."""
    with pytest.raises(DomainValidationError) as exc_info:
        change_services.submit_retro_review(
            review=pending_retro_review,
            actor=_user_actor(operator_user),
            actor_user=operator_user,
            disposition=RetroReview.Disposition.ACCEPTED,
            summary="I approve my own exception",
        )
    assert exc_info.value.code == "retro_review_self_review_rejected"


@pytest.mark.django_db
def test_submit_retro_review_self_review_breakglass_rejected(
    draft_change, operator_user
):
    """Breakglass activator cannot review their own session."""
    profile = draft_change.operation_profile
    profile.allow_emergency_changes = True
    profile.save(update_fields=["allow_emergency_changes", "updated_at"])
    draft_change.status = ChangeRecord.Status.RUNNING
    draft_change.save(update_fields=["status", "updated_at"])

    target_ids = list(str(tid) for tid in draft_change.targets.values_list("id", flat=True))
    session = change_services.activate_breakglass(
        change=draft_change,
        actor=_user_actor(operator_user),
        scope_json={
            "allowed_actions": ["dispatch"],
            "gate_types": ["window_overrun"],
            "target_ids": target_ids,
        },
        reason="Emergency incident",
        expires_at=_future(1800),
        actor_user=operator_user,
    )
    review = RetroReview.objects.get(breakglass_session=session)

    with pytest.raises(DomainValidationError) as exc_info:
        change_services.submit_retro_review(
            review=review,
            actor=_user_actor(operator_user),
            actor_user=operator_user,
            disposition=RetroReview.Disposition.ACCEPTED,
            summary="Self reviewing breakglass",
        )
    assert exc_info.value.code == "retro_review_self_review_rejected"


@pytest.mark.django_db
def test_submit_retro_review_already_submitted(pending_retro_review, approver_user):
    """Submitting an already-submitted review raises InvalidStateTransitionError."""
    change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
        disposition=RetroReview.Disposition.ACCEPTED,
        summary="First submission",
    )
    pending_retro_review.refresh_from_db()
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        change_services.submit_retro_review(
            review=pending_retro_review,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
            disposition=RetroReview.Disposition.ACCEPTED,
            summary="Second submission",
        )
    assert exc_info.value.code == "retro_review_not_pending"


# ---------------------------------------------------------------------------
# Service: mark_overdue_retro_reviews
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_overdue_retro_reviews(pending_retro_review, draft_change):
    """Pending review past due_at updates change retro_review_blocking_status."""
    pending_retro_review.due_at = _past(3600)
    pending_retro_review.save(update_fields=["due_at", "updated_at"])

    affected = change_services.mark_overdue_retro_reviews(now=_now())

    assert pending_retro_review in affected
    draft_change.refresh_from_db()
    assert draft_change.retro_review_blocking_status == "overdue"


@pytest.mark.django_db
def test_mark_overdue_retro_reviews_already_overdue(pending_retro_review, draft_change):
    """Idempotent: already-overdue change does not emit a second audit event."""
    pending_retro_review.due_at = _past(3600)
    pending_retro_review.save(update_fields=["due_at", "updated_at"])

    draft_change.retro_review_blocking_status = "overdue"
    draft_change.save(update_fields=["retro_review_blocking_status", "updated_at"])

    before_count = AuditEvent.objects.filter(
        event_type="retro_review.overdue",
        object_id=pending_retro_review.id,
    ).count()

    affected = change_services.mark_overdue_retro_reviews(now=_now())

    # Review is past due but change was already marked overdue — not in affected list
    assert pending_retro_review not in affected

    after_count = AuditEvent.objects.filter(
        event_type="retro_review.overdue",
        object_id=pending_retro_review.id,
    ).count()
    assert after_count == before_count


# ---------------------------------------------------------------------------
# Service: assert_retro_reviews_allow_closure
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_assert_retro_reviews_allow_closure_blocks_pending(
    pending_retro_review, draft_change
):
    """Pending review blocks closure."""
    draft_change.refresh_from_db()
    with pytest.raises(DomainConflictError) as exc_info:
        change_services.assert_retro_reviews_allow_closure(draft_change)
    assert exc_info.value.code == "retro_review_blocking_closure"


@pytest.mark.django_db
def test_assert_retro_reviews_allow_closure_passes_all_submitted(
    pending_retro_review, draft_change, approver_user
):
    """All reviews submitted/accepted passes the gate."""
    change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
        disposition=RetroReview.Disposition.ACCEPTED,
        summary="All good",
    )
    draft_change.refresh_from_db()
    # Should not raise
    change_services.assert_retro_reviews_allow_closure(draft_change)


@pytest.mark.django_db
def test_assert_retro_reviews_allow_closure_needs_remediation_without_ref(
    pending_retro_review, draft_change, approver_user
):
    """needs_remediation without remediation_reference still blocks closure."""
    # Submit with reference first to get through validation, then clear it
    change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
        disposition=RetroReview.Disposition.NEEDS_REMEDIATION,
        summary="Needs fix",
        remediation_reference="TICKET-999",
    )
    # Clear remediation_reference to simulate the blocking state
    pending_retro_review.refresh_from_db()
    pending_retro_review.remediation_reference = ""
    pending_retro_review.save(update_fields=["remediation_reference", "updated_at"])

    draft_change.refresh_from_db()
    with pytest.raises(DomainConflictError) as exc_info:
        change_services.assert_retro_reviews_allow_closure(draft_change)
    assert exc_info.value.code == "retro_review_blocking_closure"


@pytest.mark.django_db
def test_assert_retro_reviews_allow_closure_needs_remediation_with_ref(
    pending_retro_review, draft_change, approver_user
):
    """needs_remediation with remediation_reference passes closure gate."""
    change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(approver_user),
        actor_user=approver_user,
        disposition=RetroReview.Disposition.NEEDS_REMEDIATION,
        summary="Needs fix",
        remediation_reference="TICKET-123",
    )
    draft_change.refresh_from_db()
    # Should not raise
    change_services.assert_retro_reviews_allow_closure(draft_change)


# ---------------------------------------------------------------------------
# Service: close_change blocked
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_close_change_blocked_by_pending_retro_review(
    pending_retro_review, draft_change
):
    """close_change raises DomainConflictError when retro-review is pending."""
    # Force change to verified status so the only blocker is the retro-review
    draft_change.status = ChangeRecord.Status.VERIFIED
    draft_change.save(update_fields=["status", "updated_at"])

    actor = _system_actor()

    # We expect a conflict error due to retro-review blocking (or verification plan missing)
    # The assert_retro_reviews_allow_closure gate fires before the verification plan check
    with pytest.raises(DomainConflictError) as exc_info:
        change_services.close_change(
            change=draft_change,
            actor=actor,
            outcome="success",
            summary="Closing change",
        )
    assert exc_info.value.code == "retro_review_blocking_closure"


# ---------------------------------------------------------------------------
# Service: approve_exception creates RetroReview
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_exception_creates_retro_review(
    policy_override_exception, admin_user, draft_change
):
    """approve_exception creates a RetroReview for policy_override."""
    assert not RetroReview.objects.filter(change_record=draft_change).exists()

    change_services.approve_exception(
        change_exception=policy_override_exception,
        actor=_user_actor(admin_user),
        actor_user=admin_user,
    )

    assert RetroReview.objects.filter(
        change_record=draft_change,
        change_exception=policy_override_exception,
    ).exists()


# ---------------------------------------------------------------------------
# Service: control_failure disposition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_control_failure_disposition_updates_change_status(
    pending_retro_review, draft_change, admin_user
):
    """control_failure disposition sets retro_review_blocking_status=control_failure."""
    change_services.submit_retro_review(
        review=pending_retro_review,
        actor=_user_actor(admin_user),
        actor_user=admin_user,
        disposition=RetroReview.Disposition.CONTROL_FAILURE,
        summary="Control failure identified",
        evidence_json={"control_failure_category": "access_control"},
        remediation_reference="TICKET-CTRL-1",
    )
    draft_change.refresh_from_db()
    assert draft_change.retro_review_blocking_status == "control_failure"


# ---------------------------------------------------------------------------
# Service: mark_overdue emits audit event
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_overdue_emits_audit_event(pending_retro_review, draft_change):
    """mark_overdue_retro_reviews emits a retro_review.overdue audit event."""
    pending_retro_review.due_at = _past(3600)
    pending_retro_review.save(update_fields=["due_at", "updated_at"])

    change_services.mark_overdue_retro_reviews(now=_now())

    events = AuditEvent.objects.filter(
        event_type="retro_review.overdue",
        object_id=pending_retro_review.id,
    )
    assert events.exists()


# ---------------------------------------------------------------------------
# API: retro-review list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_retro_review_list_api(api_client_operator, draft_change, pending_retro_review):
    """GET endpoint returns reviews for change."""
    url = f"/api/v1/changes/{draft_change.id}/retro-reviews/"
    response = api_client_operator.get(url)
    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    assert len(results) == 1
    assert str(results[0]["id"]) == str(pending_retro_review.id)


# ---------------------------------------------------------------------------
# API: retro-review submit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_retro_review_submit_api(
    api_client_operator, draft_change, pending_retro_review, approver_user
):
    """POST to submit endpoint returns 200 with accepted disposition."""
    # Use approver_user (operator) client — not the original requester
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    tokens = RefreshToken.for_user(approver_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(draft_change.organization_id)

    url = f"/api/v1/changes/{draft_change.id}/retro-reviews/{pending_retro_review.id}/submit/"
    payload = {
        "retro_review_id": str(pending_retro_review.id),
        "disposition": "accepted",
        "summary": "Looks good.",
    }
    response = client.post(url, data=payload, format="json")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "submitted"
    assert response.data["disposition"] == "accepted"


# ---------------------------------------------------------------------------
# API: retro-review inbox
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_retro_review_inbox_api(api_client_operator, pending_retro_review):
    """GET inbox endpoint returns pending reviews."""
    url = "/api/v1/changes/retro-reviews/inbox/"
    response = api_client_operator.get(url)
    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    ids = [r["id"] for r in results]
    assert str(pending_retro_review.id) in [str(i) for i in ids]
