"""
Phase 11.4 Batch 2 tests: ChangeException services and APIs.

Covers:
- exception creation / validation / type-specific scope
- approval, rejection, self-approval rejection
- expiry enforcement before gate checks
- freeze_override cannot override block freeze rules
- window_overrun cannot authorize dispatch before window opens
- late_verification does not satisfy checks
- missing_artifact scope validation
- policy_override scope validation
- API endpoints (list, create, approve, reject, resolve)
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
from apps.changes.models import (
    ChangeException,
    ChangeRecord,
    ChangeWindow,
    FreezeRule,
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
        actor_label=str(user.pk),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def operator_user(org, db):
    from apps.users.models import User

    u = User.objects.create_user(email="operator@test.com", password="pass")
    Membership.objects.create(user=u, organization=org, role=MembershipRole.OPERATOR)
    return u


@pytest.fixture
def approver_user(org, db):
    from apps.users.models import User

    u = User.objects.create_user(email="approver@test.com", password="pass")
    Membership.objects.create(user=u, organization=org, role=MembershipRole.OPERATOR)
    return u


@pytest.fixture
def admin_user(org, db):
    from apps.users.models import User

    u = User.objects.create_user(email="admin@test.com", password="pass")
    Membership.objects.create(user=u, organization=org, role=MembershipRole.ADMIN)
    return u


@pytest.fixture
def change(draft_change):
    return draft_change


@pytest.fixture
def freeze_rule_block(org):
    return FreezeRule.objects.create(
        organization=org,
        name="Block rule",
        behavior=FreezeRule.Behavior.BLOCK,
        starts_at=_past(86400),
        ends_at=_future(86400),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=False,
    )


@pytest.fixture
def freeze_rule_allow_exception(org):
    return FreezeRule.objects.create(
        organization=org,
        name="Allow-with-exception rule",
        behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
        starts_at=_past(86400),
        ends_at=_future(86400),
        scope_type=FreezeRule.ScopeType.ALL_PRODUCTION,
        requires_exception_reference=True,
    )


@pytest.fixture
def second_change_record(org, operation_profile, published_workflow):
    from apps.audit.services import AuditActor
    from apps.audit.models import AuditEvent
    from apps.changes import services as change_services

    actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
    return change_services.create_change_record(
        organization=org,
        operation_profile_key="prod-maintenance",
        workflow_id=str(published_workflow.id),
        title="Second Test Change",
        summary="Another test change",
        justification="Required for maintenance",
        requested_inputs={"key": "value2"},
        targets=[
            {
                "target_type": "server",
                "target_identifier": "prod-server-02",
                "environment": "production",
            }
        ],
        actor=actor,
    )


@pytest.fixture
def api_client_operator(operator_user, org):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    tokens = RefreshToken.for_user(operator_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


@pytest.fixture
def api_client_approver(approver_user, org):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    tokens = RefreshToken.for_user(approver_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


# ---------------------------------------------------------------------------
# Exception service: request_exception
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestException:
    def test_creates_pending_exception_with_approval_request(self, change, operator_user):
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="Production freeze exception needed.",
            scope_json={"freeze_rule_id": "rule-1", "target_ids": ["t-1"]},
            expires_at=_future(7200),
            actor_user=operator_user,
        )
        assert exc.pk is not None
        assert exc.status == ChangeException.Status.PENDING_APPROVAL
        assert exc.approval_request_id is not None
        assert exc.requested_by == operator_user
        assert exc.exception_type == ChangeException.ExceptionType.FREEZE_OVERRIDE

    def test_emits_requested_audit_event(self, change, operator_user):
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.WINDOW_OVERRUN,
            reason="Running past window end.",
            scope_json={"change_window_id": "w-1", "allowed_until": "2026-01-01T00:00:00Z"},
            expires_at=_future(3600),
            actor_user=operator_user,
        )
        events = AuditEvent.objects.filter(
            event_type="change_exception.requested",
            object_id=exc.id,
        )
        assert events.exists()

    def test_invalid_exception_type_raises(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="Invalid exception type"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type="not_a_type",
                reason="test",
                scope_json={},
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_missing_reason_raises(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="reason is required"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
                reason="   ",
                scope_json={"freeze_rule_id": "x", "target_ids": []},
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_past_expiry_raises(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="expires_at must be a future"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
                reason="test",
                scope_json={"freeze_rule_id": "x", "target_ids": []},
                expires_at=_past(60),
                actor_user=operator_user,
            )

    # --- Type-specific scope key validation ---

    def test_freeze_override_requires_scope_keys(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="requires scope keys"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
                reason="test",
                scope_json={"target_ids": ["t-1"]},  # missing freeze_rule_id
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_window_overrun_requires_scope_keys(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="requires scope keys"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.WINDOW_OVERRUN,
                reason="test",
                scope_json={"change_window_id": "w-1"},  # missing allowed_until
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_late_verification_requires_scope_keys(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="requires scope keys"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.LATE_VERIFICATION,
                reason="test",
                scope_json={"verification_plan_id": "vp-1"},  # missing others
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_policy_override_requires_scope_keys(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="requires scope keys"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.POLICY_OVERRIDE,
                reason="test",
                scope_json={"policy_evaluation_id": "pe-1"},  # missing others
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_missing_artifact_requires_scope_keys(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="requires scope keys"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.MISSING_ARTIFACT,
                reason="test",
                scope_json={"verification_check_id": "vc-1"},  # missing others
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_freeze_override_cannot_reference_block_rule(
        self, change, operator_user, freeze_rule_block
    ):
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError, match="allow_with_exception"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
                reason="trying to override block rule",
                scope_json={
                    "freeze_rule_id": str(freeze_rule_block.id),
                    "target_ids": ["t-1"],
                },
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_freeze_override_can_reference_allow_exception_rule(
        self, change, operator_user, freeze_rule_allow_exception
    ):
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="override allow_with_exception freeze",
            scope_json={
                "freeze_rule_id": str(freeze_rule_allow_exception.id),
                "target_ids": ["t-1"],
            },
            expires_at=_future(),
            actor_user=operator_user,
        )
        assert exc.pk is not None

    def test_window_overrun_blocked_before_window_opens(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        # Create a window that starts in the future
        ChangeWindow.objects.create(
            organization=change.organization,
            change_record=change,
            starts_at=_future(7200),
            ends_at=_future(14400),
        )
        with pytest.raises(DomainValidationError, match="before the change window opens"):
            change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=ChangeException.ExceptionType.WINDOW_OVERRUN,
                reason="window not open yet",
                scope_json={
                    "change_window_id": "w-1",
                    "allowed_until": _future(20000).isoformat(),
                },
                expires_at=_future(),
                actor_user=operator_user,
            )

    def test_all_exception_types_can_be_created(self, change, operator_user):
        """All valid types with valid scope produce a pending exception."""
        valid_scopes = {
            ChangeException.ExceptionType.FREEZE_OVERRIDE: {
                "freeze_rule_id": "r-1",
                "target_ids": ["t-1"],
            },
            ChangeException.ExceptionType.WINDOW_OVERRUN: {
                "change_window_id": "w-1",
                "allowed_until": "2099-01-01T00:00:00Z",
            },
            ChangeException.ExceptionType.LATE_VERIFICATION: {
                "verification_plan_id": "vp-1",
                "verification_check_ids": ["vc-1"],
                "due_at": "2099-01-01T00:00:00Z",
            },
            ChangeException.ExceptionType.POLICY_OVERRIDE: {
                "policy_evaluation_id": "pe-1",
                "policy_rule_ids": ["pr-1"],
                "overridden_outcome": "blocked",
            },
            ChangeException.ExceptionType.MISSING_ARTIFACT: {
                "verification_check_id": "vc-1",
                "expected_artifact_kind": "test_report",
                "replacement_evidence": "See INC-001",
            },
        }
        for exc_type, scope in valid_scopes.items():
            exc = change_services.request_exception(
                change=change,
                actor=_user_actor(operator_user),
                exception_type=exc_type,
                reason="test",
                scope_json=scope,
                expires_at=_future(3600),
                actor_user=operator_user,
            )
            assert exc.pk is not None
            assert exc.status == ChangeException.Status.PENDING_APPROVAL


# ---------------------------------------------------------------------------
# Exception service: approve_exception
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApproveException:
    def _pending_exception(self, change, user):
        return change_services.request_exception(
            change=change,
            actor=_user_actor(user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="Need freeze override",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=_future(7200),
            actor_user=user,
        )

    def test_approve_moves_to_approved(self, change, operator_user, approver_user):
        exc = self._pending_exception(change, operator_user)
        exc = change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        assert exc.status == ChangeException.Status.APPROVED
        assert exc.approved_by == approver_user
        assert exc.approved_at is not None

    def test_approve_resolves_approval_request(self, change, operator_user, approver_user):
        from apps.approvals.models import ApprovalRequest

        exc = self._pending_exception(change, operator_user)
        approval_req_id = exc.approval_request_id
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        ar = ApprovalRequest.objects.get(pk=approval_req_id)
        assert ar.status == ApprovalRequest.Status.APPROVED

    def test_self_approval_rejected(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        exc = self._pending_exception(change, operator_user)
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.approve_exception(
                change_exception=exc,
                actor=_user_actor(operator_user),
                actor_user=operator_user,
            )
        assert exc_info.value.code == "exception_self_approval_rejected"

    def test_self_approval_emits_audit_event(self, change, operator_user):
        from apps.common.exceptions import DomainValidationError

        exc = self._pending_exception(change, operator_user)
        with pytest.raises(DomainValidationError):
            change_services.approve_exception(
                change_exception=exc,
                actor=_user_actor(operator_user),
                actor_user=operator_user,
            )
        events = AuditEvent.objects.filter(
            event_type="retro_review.self_review_rejected",
            object_id=exc.id,
        )
        assert events.exists()

    def test_approve_emits_audit_event(self, change, operator_user, approver_user):
        exc = self._pending_exception(change, operator_user)
        exc = change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        events = AuditEvent.objects.filter(
            event_type="change_exception.approved",
            object_id=exc.id,
        )
        assert events.exists()

    def test_cannot_approve_non_pending(self, change, operator_user, approver_user):
        from apps.common.exceptions import InvalidStateTransitionError

        exc = self._pending_exception(change, operator_user)
        # Reject first
        change_services.reject_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        exc.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.approve_exception(
                change_exception=exc,
                actor=_user_actor(approver_user),
                actor_user=approver_user,
            )
        assert exc_info.value.code == "exception_not_pending"

    def test_policy_override_sets_retro_review_required(
        self, change, operator_user, approver_user
    ):
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.POLICY_OVERRIDE,
            reason="Override policy block",
            scope_json={
                "policy_evaluation_id": "pe-1",
                "policy_rule_ids": ["r-1"],
                "overridden_outcome": "blocked",
            },
            expires_at=_future(),
            actor_user=operator_user,
        )
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        change.refresh_from_db()
        assert change.retro_review_required is True

    def test_missing_artifact_sets_retro_review_required(
        self, change, operator_user, approver_user
    ):
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.MISSING_ARTIFACT,
            reason="Artifact missing",
            scope_json={
                "verification_check_id": "vc-1",
                "expected_artifact_kind": "report",
                "replacement_evidence": "INC-001",
            },
            expires_at=_future(),
            actor_user=operator_user,
        )
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        change.refresh_from_db()
        assert change.retro_review_required is True


# ---------------------------------------------------------------------------
# Exception service: reject_exception
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRejectException:
    def _pending_exception(self, change, user):
        return change_services.request_exception(
            change=change,
            actor=_user_actor(user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="Need freeze override",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=_future(7200),
            actor_user=user,
        )

    def test_reject_moves_to_rejected(self, change, operator_user, approver_user):
        exc = self._pending_exception(change, operator_user)
        exc = change_services.reject_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        assert exc.status == ChangeException.Status.REJECTED
        assert exc.rejected_at is not None

    def test_reject_resolves_approval_request(self, change, operator_user, approver_user):
        from apps.approvals.models import ApprovalRequest

        exc = self._pending_exception(change, operator_user)
        approval_req_id = exc.approval_request_id
        change_services.reject_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        ar = ApprovalRequest.objects.get(pk=approval_req_id)
        assert ar.status == ApprovalRequest.Status.REJECTED

    def test_reject_emits_audit_event(self, change, operator_user, approver_user):
        exc = self._pending_exception(change, operator_user)
        exc = change_services.reject_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        events = AuditEvent.objects.filter(
            event_type="change_exception.rejected",
            object_id=exc.id,
        )
        assert events.exists()

    def test_cannot_reject_non_pending(self, change, operator_user, approver_user):
        from apps.common.exceptions import InvalidStateTransitionError

        exc = self._pending_exception(change, operator_user)
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        exc.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.reject_exception(
                change_exception=exc,
                actor=_user_actor(approver_user),
                actor_user=approver_user,
            )
        assert exc_info.value.code == "exception_not_pending"


# ---------------------------------------------------------------------------
# Exception service: expire_exceptions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExpireExceptions:
    def _make_exception(self, change, user, expires_at):
        return change_services.request_exception(
            change=change,
            actor=_user_actor(user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=expires_at,
            actor_user=user,
        )

    def test_expire_pending_exceptions(self, change, operator_user, approver_user):
        expires_at = _future(3600)
        exc = self._make_exception(change, operator_user, expires_at)

        # Pass a "now" beyond expires_at to simulate time passing
        future_now = expires_at + timedelta(seconds=60)
        expired = change_services.expire_exceptions(change=change, now=future_now)
        assert len(expired) == 1
        exc.refresh_from_db()
        assert exc.status == ChangeException.Status.EXPIRED

    def test_expire_approved_exceptions(self, change, operator_user, approver_user):
        expires_at = _future(3600)
        exc = self._make_exception(change, operator_user, expires_at)
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )

        future_now = expires_at + timedelta(seconds=60)
        expired = change_services.expire_exceptions(change=change, now=future_now)
        assert len(expired) >= 1
        exc.refresh_from_db()
        assert exc.status == ChangeException.Status.EXPIRED

    def test_non_expired_exceptions_not_touched(self, change, operator_user):
        exc = self._make_exception(change, operator_user, _future(3600))
        expired = change_services.expire_exceptions(change=change)
        assert len(expired) == 0
        exc.refresh_from_db()
        assert exc.status == ChangeException.Status.PENDING_APPROVAL

    def test_expire_emits_audit_events(self, change, operator_user):
        expires_at = _future(3600)
        exc = self._make_exception(change, operator_user, expires_at)
        future_now = expires_at + timedelta(seconds=60)
        change_services.expire_exceptions(change=change, now=future_now)
        events = AuditEvent.objects.filter(
            event_type="change_exception.expired",
            object_id=exc.id,
        )
        assert events.exists()


# ---------------------------------------------------------------------------
# Exception service: find_applicable_exception
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFindApplicableException:
    def test_finds_approved_non_expired(self, change, operator_user, approver_user):
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=_future(3600),
            actor_user=operator_user,
        )
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        found = change_services.find_applicable_exception(
            change=change,
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
        )
        assert found is not None
        assert found.pk == exc.pk

    def test_returns_none_if_no_approved_exception(self, change):
        found = change_services.find_applicable_exception(
            change=change,
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
        )
        assert found is None

    def test_returns_none_for_expired_exception(self, change, operator_user, approver_user):
        expires_at = _future(3600)
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=expires_at,
            actor_user=operator_user,
        )
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        # Find with a "now" that is beyond expires_at
        future_now = expires_at + timedelta(seconds=60)
        found = change_services.find_applicable_exception(
            change=change,
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            now=future_now,
        )
        assert found is None

    def test_expired_is_enforced_before_find(self, change, operator_user, approver_user):
        """find_applicable_exception expires stale records before querying."""
        expires_at = _future(3600)
        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=expires_at,
            actor_user=operator_user,
        )
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )

        # Call find with a "now" that is past expires_at; it should expire and return None
        future_now = expires_at + timedelta(seconds=60)
        result = change_services.find_applicable_exception(
            change=change,
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            now=future_now,
        )
        assert result is None
        exc.refresh_from_db()
        assert exc.status == ChangeException.Status.EXPIRED


# ---------------------------------------------------------------------------
# API: ChangeExceptionListCreateView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangeExceptionAPI:
    def _create_url(self, change_id):
        return f"/api/v1/changes/{change_id}/exceptions/"

    def test_create_exception_201(self, change, api_client_operator):
        resp = api_client_operator.post(
            self._create_url(change.id),
            {
                "exception_type": "freeze_override",
                "reason": "Production incident.",
                "scope_json": {"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
                "expires_at": _future(7200).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["status"] == "pending_approval"
        assert data["exception_type"] == "freeze_override"
        assert data["approval_request_id"] is not None

    def test_list_exceptions_200(self, change, api_client_operator, operator_user, org):
        change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=_future(7200),
            actor_user=operator_user,
        )
        resp = api_client_operator.get(self._create_url(change.id))
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()["results"]) == 1

    def test_create_invalid_scope_returns_400(self, change, api_client_operator):
        resp = api_client_operator.post(
            self._create_url(change.id),
            {
                "exception_type": "freeze_override",
                "reason": "test",
                "scope_json": {"target_ids": ["t-1"]},  # missing freeze_rule_id
                "expires_at": _future(3600).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_invalid_type_returns_400(self, change, api_client_operator):
        resp = api_client_operator.post(
            self._create_url(change.id),
            {
                "exception_type": "not_real",
                "reason": "test",
                "scope_json": {},
                "expires_at": _future(3600).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_unauthenticated_returns_401(self, change):
        client = APIClient()
        resp = client.post(
            self._create_url(change.id),
            {
                "exception_type": "freeze_override",
                "reason": "test",
                "scope_json": {"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
                "expires_at": _future(3600).isoformat(),
            },
            format="json",
        )
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_create_wrong_org_returns_404(
        self, change, api_client_operator, org_factory
    ):
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.users.models import User

        other_org = org_factory("other-org-exc")
        u2 = User.objects.create_user(email="other@test.com", password="pass")
        Membership.objects.create(user=u2, organization=other_org, role=MembershipRole.OPERATOR)
        client = APIClient()
        tokens = RefreshToken.for_user(u2)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
        client.defaults["HTTP_X_ORGANIZATION_ID"] = str(other_org.id)

        resp = client.post(
            self._create_url(change.id),
            {
                "exception_type": "freeze_override",
                "reason": "test",
                "scope_json": {"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
                "expires_at": _future(3600).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_filter_by_status(self, change, api_client_operator, operator_user):
        change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=_future(7200),
            actor_user=operator_user,
        )
        resp = api_client_operator.get(
            self._create_url(change.id) + "?status=pending_approval"
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()["results"]) == 1

        resp2 = api_client_operator.get(
            self._create_url(change.id) + "?status=approved"
        )
        assert resp2.status_code == status.HTTP_200_OK
        assert len(resp2.json()["results"]) == 0


# ---------------------------------------------------------------------------
# API: approve / reject / resolve
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExceptionApproveRejectAPI:
    def _create_exception(self, change, operator_user):
        return change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            reason="test",
            scope_json={"freeze_rule_id": "r-1", "target_ids": ["t-1"]},
            expires_at=_future(7200),
            actor_user=operator_user,
        )

    def _approve_url(self, change_id, exception_id):
        return f"/api/v1/changes/{change_id}/exceptions/{exception_id}/approve/"

    def _reject_url(self, change_id, exception_id):
        return f"/api/v1/changes/{change_id}/exceptions/{exception_id}/reject/"

    def _resolve_url(self, change_id, exception_id):
        return f"/api/v1/changes/{change_id}/exceptions/{exception_id}/resolve/"

    def test_approve_by_different_user_200(
        self, change, api_client_approver, operator_user
    ):
        exc = self._create_exception(change, operator_user)
        resp = api_client_approver.post(self._approve_url(change.id, exc.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "approved"

    def test_self_approve_returns_400(self, change, api_client_operator, operator_user):
        exc = self._create_exception(change, operator_user)
        resp = api_client_operator.post(self._approve_url(change.id, exc.id))
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "self_approval_rejected" in str(resp.json())

    def test_reject_returns_200(self, change, api_client_approver, operator_user):
        exc = self._create_exception(change, operator_user)
        resp = api_client_approver.post(self._reject_url(change.id, exc.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "rejected"

    def test_resolve_approved_exception_200(
        self, change, api_client_operator, operator_user, approver_user
    ):
        exc = self._create_exception(change, operator_user)
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        resp = api_client_operator.post(
            self._resolve_url(change.id, exc.id),
            {"resolution_note": "Issue resolved."},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "resolved"

    def test_resolve_pending_exception_409(
        self, change, api_client_operator, operator_user
    ):
        exc = self._create_exception(change, operator_user)
        resp = api_client_operator.post(
            self._resolve_url(change.id, exc.id),
            {"resolution_note": "Not yet approved"},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_approve_wrong_change_returns_404(
        self, change, api_client_approver, operator_user, second_change_record
    ):
        exc = self._create_exception(change, operator_user)
        url = f"/api/v1/changes/{second_change_record.id}/exceptions/{exc.id}/approve/"
        resp = api_client_approver.post(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Late verification does not satisfy checks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestLateVerificationSemantics:
    def test_late_verification_does_not_mark_checks_passed(
        self, change, operator_user, approver_user
    ):
        """
        Approving a late_verification exception must NOT change any
        VerificationCheck status to 'passed'. Checks remain pending.
        """
        from apps.changes.models import VerificationCheck

        exc = change_services.request_exception(
            change=change,
            actor=_user_actor(operator_user),
            exception_type=ChangeException.ExceptionType.LATE_VERIFICATION,
            reason="Late verification needed",
            scope_json={
                "verification_plan_id": "vp-1",
                "verification_check_ids": ["vc-1"],
                "due_at": "2099-01-01T00:00:00Z",
            },
            expires_at=_future(7200),
            actor_user=operator_user,
        )
        change_services.approve_exception(
            change_exception=exc,
            actor=_user_actor(approver_user),
            actor_user=approver_user,
        )
        # No VerificationCheck should be marked passed just from the exception
        passed_count = VerificationCheck.objects.filter(
            change_record=change, status=VerificationCheck.Status.PASSED
        ).count()
        assert passed_count == 0
