"""
Tests for Phase 11.4 Batch 1: emergency fields and new model foundation.
Covers ChangeRecord emergency fields, ChangeException, BreakglassSession,
RetroReview constraints, indexes, and tenant invariants.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.changes.models import (
    BreakglassSession,
    ChangeException,
    ChangeRecord,
    RetroReview,
)
from apps.organizations.models import Organization

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return timezone.now()


def _future(seconds=3600):
    return _now() + timedelta(seconds=seconds)


def _past(seconds=60):
    return _now() - timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Additional fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def change_record(draft_change):
    return draft_change


@pytest.fixture
def submitted_change_record(draft_change):
    """A ChangeRecord with status manually advanced past draft for immutability tests."""
    ChangeRecord.objects.filter(pk=draft_change.pk).update(
        status=ChangeRecord.Status.PENDING_APPROVAL,
        submitted_at=_now(),
    )
    draft_change.refresh_from_db()
    return draft_change


@pytest.fixture
def other_organization():
    return Organization.objects.create(name="Other Org", slug="other-org")


@pytest.fixture
def second_change_record(org, operation_profile, published_workflow):
    from apps.audit.models import AuditEvent
    from apps.audit.services import AuditActor
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


# ---------------------------------------------------------------------------
# ChangeRecord emergency fields
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestChangeRecordEmergencyFields:
    def test_defaults_are_safe(self, change_record):
        assert change_record.is_emergency is False
        assert change_record.retro_review_required is False
        assert change_record.emergency_reason == ""
        assert change_record.emergency_declared_by is None
        assert change_record.emergency_declared_at is None
        assert change_record.retro_review_due_at is None
        assert change_record.retro_review_blocking_status == ""

    def test_emergency_fields_set_on_draft(self, change_record, user):
        change_record.is_emergency = True
        change_record.emergency_reason = "Critical incident mitigation"
        change_record.emergency_declared_by = user
        change_record.emergency_declared_at = _now()
        change_record.save()

        refreshed = ChangeRecord.objects.get(pk=change_record.pk)
        assert refreshed.is_emergency is True
        assert refreshed.emergency_reason == "Critical incident mitigation"
        assert refreshed.emergency_declared_by == user

    def test_is_emergency_immutable_after_submit(self, submitted_change_record):
        cr = submitted_change_record
        cr.is_emergency = True
        with pytest.raises(ValidationError, match="immutable after submit"):
            cr.save()

    def test_emergency_reason_immutable_after_submit(self, submitted_change_record):
        cr = submitted_change_record
        cr.emergency_reason = "should be blocked"
        with pytest.raises(ValidationError, match="immutable after submit"):
            cr.save()

    def test_retro_review_fields_are_mutable_after_submit(self, submitted_change_record):
        """retro_review_* fields can be updated after submit (service-managed)."""
        cr = submitted_change_record
        cr.retro_review_required = True
        cr.retro_review_blocking_status = "pending"
        cr.retro_review_due_at = _future()
        cr.save()  # must not raise

        refreshed = ChangeRecord.objects.get(pk=cr.pk)
        assert refreshed.retro_review_required is True
        assert refreshed.retro_review_blocking_status == "pending"


# ---------------------------------------------------------------------------
# OperationProfile emergency config fields
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestOperationProfileEmergencyConfig:
    def test_defaults(self, operation_profile):
        assert operation_profile.allow_emergency_changes is False
        assert operation_profile.max_breakglass_seconds is None
        assert operation_profile.retro_review_sla_seconds is None

    def test_can_enable_emergency(self, operation_profile):
        operation_profile.allow_emergency_changes = True
        operation_profile.max_breakglass_seconds = 3600
        operation_profile.retro_review_sla_seconds = 86400
        operation_profile.save()

        refreshed = type(operation_profile).objects.get(pk=operation_profile.pk)
        assert refreshed.allow_emergency_changes is True
        assert refreshed.max_breakglass_seconds == 3600
        assert refreshed.retro_review_sla_seconds == 86400


# ---------------------------------------------------------------------------
# ChangeException
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestChangeExceptionModel:
    def _make_exception(self, change_record, user, **kwargs):
        defaults = dict(
            organization=change_record.organization,
            change_record=change_record,
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            status=ChangeException.Status.PENDING_APPROVAL,
            reason="Production incident requires freeze override.",
            scope_json={"freeze_rule_id": "rule-1", "target_ids": ["t-1"]},
            requested_by=user,
            requested_at=_now(),
            expires_at=_future(7200),
        )
        defaults.update(kwargs)
        exc = ChangeException(**defaults)
        exc.save()
        return exc

    def test_create_valid_exception(self, change_record, user):
        exc = self._make_exception(change_record, user)
        assert exc.pk is not None
        assert exc.status == ChangeException.Status.PENDING_APPROVAL

    def test_invalid_exception_type_rejected(self, change_record, user):
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._make_exception(change_record, user, exception_type="not_a_type")

    def test_invalid_status_rejected(self, change_record, user):
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._make_exception(change_record, user, status="not_a_status")

    def test_expires_at_must_be_after_requested_at(self, change_record, user):
        """DB check constraint: expires_at > requested_at."""
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                exc = ChangeException(
                    organization=change_record.organization,
                    change_record=change_record,
                    exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
                    status=ChangeException.Status.PENDING_APPROVAL,
                    reason="test",
                    scope_json={},
                    requested_by=user,
                    requested_at=_future(100),  # in the future
                    expires_at=_past(10),       # before requested_at
                )
                exc.save()

    def test_org_must_match_change(self, change_record, user, other_organization):
        with pytest.raises(ValidationError):
            exc = ChangeException(
                organization=other_organization,
                change_record=change_record,
                exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
                status=ChangeException.Status.PENDING_APPROVAL,
                reason="test",
                scope_json={},
                requested_by=user,
                requested_at=_now(),
                expires_at=_future(),
            )
            exc.save()

    def test_all_exception_types_accepted(self, change_record, user):
        for exc_type in ChangeException.ExceptionType.values:
            exc = self._make_exception(change_record, user, exception_type=exc_type)
            assert exc.pk is not None

    def test_all_statuses_accepted(self, change_record, user):
        for status in ChangeException.Status.values:
            exc = self._make_exception(change_record, user, status=status)
            assert exc.pk is not None

    def test_str_representation(self, change_record, user):
        exc = self._make_exception(change_record, user)
        assert "freeze_override" in str(exc)
        assert "pending_approval" in str(exc)


# ---------------------------------------------------------------------------
# BreakglassSession
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBreakglassSessionModel:
    def _make_session(self, change_record, user, **kwargs):
        defaults = dict(
            organization=change_record.organization,
            change_record=change_record,
            status=BreakglassSession.Status.ACTIVE,
            scope_json={
                "allowed_actions": ["dispatch", "continue_running"],
                "gate_types": ["window_overrun"],
                "target_ids": ["t-1"],
            },
            scope_sha256="a" * 64,
            reason="Emergency production incident.",
            activated_by=user,
            started_at=_now(),
            expires_at=_future(3600),
            review_due_at=_future(86400),
            review_status=BreakglassSession.ReviewStatus.PENDING,
        )
        defaults.update(kwargs)
        session = BreakglassSession(**defaults)
        session.save()
        return session

    def test_create_valid_session(self, change_record, user):
        session = self._make_session(change_record, user)
        assert session.pk is not None
        assert session.status == BreakglassSession.Status.ACTIVE

    def test_expires_at_must_be_after_started_at(self, change_record, user):
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._make_session(
                    change_record, user,
                    started_at=_future(200),
                    expires_at=_future(100),  # before started_at
                    review_due_at=_future(300),
                )

    def test_review_due_at_must_not_be_before_started_at(self, change_record, user):
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._make_session(
                    change_record, user,
                    started_at=_future(100),
                    expires_at=_future(200),
                    review_due_at=_past(10),  # before started_at
                )

    def test_only_one_active_session_per_change(self, change_record, user):
        """Partial unique constraint: at most one active session per change."""
        from django.db import transaction

        self._make_session(change_record, user)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                self._make_session(change_record, user)

    def test_multiple_non_active_sessions_allowed(self, change_record, user):
        """Non-active sessions do not violate the partial unique constraint."""
        # Create and then mark ended via direct queryset update to avoid FK issues
        s1 = self._make_session(change_record, user)
        BreakglassSession.objects.filter(pk=s1.pk).update(
            status=BreakglassSession.Status.ENDED, ended_at=_now()
        )
        # Now another active session is allowed
        s2 = self._make_session(change_record, user)
        assert s2.pk is not None

    def test_org_must_match_change(self, change_record, user, other_organization):
        with pytest.raises(ValidationError):
            self._make_session(change_record, user, organization=other_organization)

    def test_invalid_status_rejected(self, change_record, user):
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._make_session(change_record, user, status="not_a_status")

    def test_invalid_review_status_rejected(self, change_record, user):
        from django.db import transaction

        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                self._make_session(
                    change_record, user,
                    status=BreakglassSession.Status.ENDED,
                    review_status="not_a_status",
                )

    def test_all_statuses_accepted(self, change_record, user):
        for i, status in enumerate(BreakglassSession.Status.values):
            session = BreakglassSession(
                organization=change_record.organization,
                change_record=change_record,
                status=status,
                scope_json={},
                scope_sha256="b" * 64,
                reason="test",
                activated_by=user,
                started_at=_now(),
                expires_at=_future(3600 + i),
                review_due_at=_future(86400),
                review_status=BreakglassSession.ReviewStatus.PENDING,
            )
            session.save()
            assert session.pk is not None

    def test_all_review_statuses_accepted(self, change_record, user):
        for i, rev_status in enumerate(BreakglassSession.ReviewStatus.values):
            session = BreakglassSession(
                organization=change_record.organization,
                change_record=change_record,
                status=BreakglassSession.Status.ENDED,
                scope_json={},
                scope_sha256="c" * 64,
                reason="test",
                activated_by=user,
                started_at=_now(),
                expires_at=_future(3600 + i),
                review_due_at=_future(86400),
                review_status=rev_status,
            )
            session.save()
            assert session.pk is not None

    def test_str_representation(self, change_record, user):
        session = self._make_session(change_record, user)
        assert "active" in str(session)


# ---------------------------------------------------------------------------
# RetroReview
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRetroReviewModel:
    def _make_session(self, change_record, user):
        session = BreakglassSession(
            organization=change_record.organization,
            change_record=change_record,
            status=BreakglassSession.Status.ENDED,
            scope_json={},
            scope_sha256="d" * 64,
            reason="test",
            activated_by=user,
            started_at=_now(),
            expires_at=_future(3600),
            review_due_at=_future(86400),
            review_status=BreakglassSession.ReviewStatus.PENDING,
        )
        session.save()
        return session

    def _make_exception(self, change_record, user):
        exc = ChangeException(
            organization=change_record.organization,
            change_record=change_record,
            exception_type=ChangeException.ExceptionType.FREEZE_OVERRIDE,
            status=ChangeException.Status.APPROVED,
            reason="test",
            scope_json={},
            requested_by=user,
            requested_at=_now(),
            expires_at=_future(),
        )
        exc.save()
        return exc

    def test_create_with_breakglass_session(self, change_record, user):
        session = self._make_session(change_record, user)
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            breakglass_session=session,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        review.save()
        assert review.pk is not None

    def test_create_with_change_exception(self, change_record, user):
        exc = self._make_exception(change_record, user)
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            change_exception=exc,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        review.save()
        assert review.pk is not None

    def test_source_required_neither_raises(self, change_record):
        """At least one of breakglass_session or change_exception must be set."""
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            breakglass_session=None,
            change_exception=None,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        with pytest.raises(ValidationError, match="must reference at least one"):
            review.save()

    def test_unique_breakglass_session_onetone(self, change_record, user):
        """One RetroReview per BreakglassSession enforced by OneToOne."""
        from django.db import transaction

        session = self._make_session(change_record, user)
        RetroReview.objects.create(
            organization=change_record.organization,
            change_record=change_record,
            breakglass_session=session,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                RetroReview.objects.create(
                    organization=change_record.organization,
                    change_record=change_record,
                    breakglass_session=session,
                    status=RetroReview.Status.PENDING,
                    due_at=_future(86400),
                )

    def test_invalid_status_rejected(self, change_record, user):
        from django.db import transaction

        exc = self._make_exception(change_record, user)
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                review = RetroReview(
                    organization=change_record.organization,
                    change_record=change_record,
                    change_exception=exc,
                    status="not_a_status",
                    due_at=_future(86400),
                )
                review.save()

    def test_invalid_disposition_rejected(self, change_record, user):
        from django.db import transaction

        exc = self._make_exception(change_record, user)
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                review = RetroReview(
                    organization=change_record.organization,
                    change_record=change_record,
                    change_exception=exc,
                    status=RetroReview.Status.PENDING,
                    disposition="not_a_disposition",
                    due_at=_future(86400),
                )
                review.save()

    def test_submitted_review_blank_disposition_rejected(self, change_record, user):
        """Submitted review with blank disposition violates DB constraint."""
        from django.db import transaction

        exc = self._make_exception(change_record, user)
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                RetroReview.objects.create(
                    organization=change_record.organization,
                    change_record=change_record,
                    change_exception=exc,
                    status=RetroReview.Status.SUBMITTED,
                    disposition="",
                    summary="test",
                    due_at=_future(86400),
                )

    def test_submitted_review_with_valid_disposition(self, change_record, user):
        exc = self._make_exception(change_record, user)
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            change_exception=exc,
            status=RetroReview.Status.SUBMITTED,
            disposition=RetroReview.Disposition.ACCEPTED,
            summary="All controls satisfied.",
            due_at=_future(86400),
        )
        review.save()
        assert review.pk is not None

    def test_org_must_match_change(self, change_record, user, other_organization):
        exc = self._make_exception(change_record, user)
        review = RetroReview(
            organization=other_organization,
            change_record=change_record,
            change_exception=exc,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        with pytest.raises(ValidationError):
            review.save()

    def test_breakglass_session_must_belong_to_same_change(
        self, change_record, user, second_change_record
    ):
        session = self._make_session(second_change_record, user)
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            breakglass_session=session,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        with pytest.raises(ValidationError):
            review.save()

    def test_exception_must_belong_to_same_change(
        self, change_record, user, second_change_record
    ):
        exc = self._make_exception(second_change_record, user)
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            change_exception=exc,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        with pytest.raises(ValidationError):
            review.save()

    def test_all_dispositions_accepted(self, change_record, user):
        exc = self._make_exception(change_record, user)
        for disp in RetroReview.Disposition.values:
            review = RetroReview(
                organization=change_record.organization,
                change_record=change_record,
                change_exception=exc,
                status=RetroReview.Status.SUBMITTED,
                disposition=disp,
                summary="submitted",
                due_at=_future(86400),
            )
            review.save()
            assert review.pk is not None

    def test_str_representation(self, change_record, user):
        exc = self._make_exception(change_record, user)
        review = RetroReview(
            organization=change_record.organization,
            change_record=change_record,
            change_exception=exc,
            status=RetroReview.Status.PENDING,
            due_at=_future(86400),
        )
        review.save()
        assert "pending" in str(review)
