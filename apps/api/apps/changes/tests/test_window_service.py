"""Phase 11.2 — ChangeWindow service and API tests."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord, ChangeWindow
from apps.organizations.models import Membership, MembershipRole


def _now():
    return timezone.now()


def _actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


# ---------------------------------------------------------------------------
# recompute_window_status
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRecomputeWindowStatus:
    def _make_window(self, draft_change, starts_at, ends_at):
        return ChangeWindow.objects.create(
            change_record=draft_change,
            organization=draft_change.organization,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def test_future_window_is_scheduled(self, draft_change):
        now = _now()
        window = self._make_window(
            draft_change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
        assert (
            change_services.recompute_window_status(window, now=now)
            == ChangeWindow.Status.SCHEDULED
        )

    def test_active_window_is_open(self, draft_change):
        now = _now()
        window = self._make_window(
            draft_change,
            starts_at=now - timedelta(minutes=30),
            ends_at=now + timedelta(minutes=30),
        )
        assert (
            change_services.recompute_window_status(window, now=now)
            == ChangeWindow.Status.OPEN
        )

    def test_past_window_on_draft_change_is_expired(self, draft_change):
        now = _now()
        window = self._make_window(
            draft_change,
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
        assert (
            change_services.recompute_window_status(window, now=now)
            == ChangeWindow.Status.EXPIRED
        )

    def test_terminal_change_status_yields_closed(self, draft_change):
        now = _now()
        window = self._make_window(
            draft_change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
        )
        for terminal in (
            ChangeRecord.Status.CLOSED,
            ChangeRecord.Status.EXPIRED,
            ChangeRecord.Status.CANCELED,
            ChangeRecord.Status.REJECTED,
            ChangeRecord.Status.VERIFIED,
        ):
            window.change_record.status = terminal
            assert (
                change_services.recompute_window_status(window, now=now)
                == ChangeWindow.Status.CLOSED
            )

    def test_running_change_past_window_is_overrun(self, draft_change):
        now = _now()
        window = self._make_window(
            draft_change,
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
        window.change_record.status = ChangeRecord.Status.RUNNING
        assert (
            change_services.recompute_window_status(window, now=now)
            == ChangeWindow.Status.OVERRUN
        )

    def test_verification_pending_past_window_is_overrun(self, draft_change):
        now = _now()
        window = self._make_window(
            draft_change,
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
        window.change_record.status = ChangeRecord.Status.VERIFICATION_PENDING
        assert (
            change_services.recompute_window_status(window, now=now)
            == ChangeWindow.Status.OVERRUN
        )


# ---------------------------------------------------------------------------
# create_or_update_change_window — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateOrUpdateChangeWindow:
    def _window_times(self, offset_hours=1):
        now = _now()
        return {
            "starts_at": now + timedelta(hours=offset_hours),
            "ends_at": now + timedelta(hours=offset_hours + 1),
        }

    def test_creates_window_for_draft_change(self, draft_change):
        times = self._window_times()
        window = change_services.create_or_update_change_window(
            change=draft_change, actor=_actor(), **times
        )
        assert window.pk is not None
        assert window.status == ChangeWindow.Status.SCHEDULED
        assert window.change_record_id == draft_change.id

    def test_sets_open_status_for_current_window(self, draft_change):
        now = _now()
        window = change_services.create_or_update_change_window(
            change=draft_change,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
            actor=_actor(),
        )
        assert window.status == ChangeWindow.Status.OPEN

    def test_updates_existing_window(self, draft_change):
        times = self._window_times()
        w1 = change_services.create_or_update_change_window(
            change=draft_change, actor=_actor(), **times
        )
        new_times = self._window_times(offset_hours=2)
        w2 = change_services.create_or_update_change_window(
            change=draft_change, actor=_actor(), **new_times
        )
        assert w1.id == w2.id
        w2.refresh_from_db()
        assert w2.starts_at == new_times["starts_at"]
        assert w2.ends_at == new_times["ends_at"]

    def test_window_allowed_for_pending_approval_change(
        self, draft_change, operation_profile, published_workflow
    ):
        times = self._window_times()
        change_services.submit_change_record(change=draft_change, actor=_actor())
        draft_change.refresh_from_db()
        assert draft_change.status == ChangeRecord.Status.PENDING_APPROVAL

        window = change_services.create_or_update_change_window(
            change=draft_change, actor=_actor(), **times
        )
        assert window.pk is not None

    def test_emits_audit_event(self, draft_change):
        times = self._window_times()
        window = change_services.create_or_update_change_window(
            change=draft_change, actor=_actor(), **times
        )
        event = AuditEvent.objects.filter(
            event_type="change.window_updated",
            object_id=window.id,
        ).first()
        assert event is not None
        assert event.metadata["change_record_id"] == str(draft_change.id)
        assert event.metadata["approval_invalidated"] is False

    def test_stores_timezone_and_reason(self, draft_change):
        times = self._window_times()
        window = change_services.create_or_update_change_window(
            change=draft_change,
            timezone_name="America/New_York",
            reason="Quarterly maintenance",
            actor=_actor(),
            **times,
        )
        assert window.timezone == "America/New_York"
        assert window.reason == "Quarterly maintenance"


# ---------------------------------------------------------------------------
# create_or_update_change_window — approval invalidation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWindowApprovalInvalidation:
    def _submit_and_approve(self, draft_change):
        """Submit a requires_approval=True change and directly force-approve it."""
        change_services.submit_change_record(change=draft_change, actor=_actor())
        draft_change.refresh_from_db()
        # Directly set to approved to simulate an approved decision.
        draft_change.status = ChangeRecord.Status.APPROVED
        draft_change.approved_at = _now()
        draft_change.save(update_fields=["status", "approved_at", "updated_at"])
        return draft_change

    def test_invalidates_approval_for_approved_change(self, draft_change):
        change = self._submit_and_approve(draft_change)
        now = _now()
        change_services.create_or_update_change_window(
            change=change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            actor=_actor(),
        )
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.PENDING_APPROVAL
        assert change.approved_at is None

    def test_emits_approval_invalidated_audit_event(self, draft_change):
        change = self._submit_and_approve(draft_change)
        now = _now()
        change_services.create_or_update_change_window(
            change=change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            actor=_actor(),
        )
        event = AuditEvent.objects.filter(
            event_type="change.approval_invalidated",
            object_id=change.id,
        ).first()
        assert event is not None
        assert event.metadata["reason"] == "window_updated"

    def test_window_audit_event_marks_approval_invalidated(self, draft_change):
        change = self._submit_and_approve(draft_change)
        now = _now()
        window = change_services.create_or_update_change_window(
            change=change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            actor=_actor(),
        )
        event = AuditEvent.objects.filter(
            event_type="change.window_updated",
            object_id=window.id,
        ).first()
        assert event is not None
        assert event.metadata["approval_invalidated"] is True

    def test_no_invalidation_for_draft_change(self, draft_change):
        now = _now()
        change_services.create_or_update_change_window(
            change=draft_change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            actor=_actor(),
        )
        draft_change.refresh_from_db()
        assert draft_change.status == ChangeRecord.Status.DRAFT
        assert (
            AuditEvent.objects.filter(event_type="change.approval_invalidated").count()
            == 0
        )

    def test_no_invalidation_for_pending_approval_change(self, draft_change):
        change_services.submit_change_record(change=draft_change, actor=_actor())
        draft_change.refresh_from_db()
        now = _now()
        change_services.create_or_update_change_window(
            change=draft_change,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            actor=_actor(),
        )
        draft_change.refresh_from_db()
        assert draft_change.status == ChangeRecord.Status.PENDING_APPROVAL
        assert (
            AuditEvent.objects.filter(event_type="change.approval_invalidated").count()
            == 0
        )


# ---------------------------------------------------------------------------
# create_or_update_change_window — blocked statuses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestWindowBlockedStatuses:
    from apps.common.exceptions import InvalidStateTransitionError

    def test_rejects_dispatchable_change(self, draft_change):
        from apps.common.exceptions import InvalidStateTransitionError

        draft_change.status = ChangeRecord.Status.DISPATCHABLE
        draft_change.save(update_fields=["status", "updated_at"])
        now = _now()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.create_or_update_change_window(
                change=draft_change,
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                actor=_actor(),
            )
        assert exc_info.value.code == "window_update_not_allowed"

    def test_rejects_running_change(self, draft_change):
        from apps.common.exceptions import InvalidStateTransitionError

        draft_change.status = ChangeRecord.Status.RUNNING
        draft_change.save(update_fields=["status", "updated_at"])
        now = _now()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.create_or_update_change_window(
                change=draft_change,
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                actor=_actor(),
            )
        assert exc_info.value.code == "window_update_not_allowed"

    def test_rejects_closed_change(self, draft_change):
        from apps.common.exceptions import InvalidStateTransitionError

        draft_change.status = ChangeRecord.Status.CLOSED
        draft_change.save(update_fields=["status", "updated_at"])
        now = _now()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.create_or_update_change_window(
                change=draft_change,
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                actor=_actor(),
            )
        assert exc_info.value.code == "window_update_not_allowed"

    def test_rejects_ends_before_starts(self, draft_change):
        from apps.common.exceptions import DomainValidationError

        now = _now()
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_or_update_change_window(
                change=draft_change,
                starts_at=now + timedelta(hours=2),
                ends_at=now + timedelta(hours=1),
                actor=_actor(),
            )
        assert exc_info.value.code == "window_ends_before_starts"

    def test_rejects_equal_starts_ends(self, draft_change):
        from apps.common.exceptions import DomainValidationError

        at = _now() + timedelta(hours=1)
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_or_update_change_window(
                change=draft_change,
                starts_at=at,
                ends_at=at,
                actor=_actor(),
            )
        assert exc_info.value.code == "window_ends_before_starts"


# ---------------------------------------------------------------------------
# API: PATCH /api/v1/changes/{id}/window/
# ---------------------------------------------------------------------------


@pytest.fixture
def authed_client(org, org_user):
    from rest_framework_simplejwt.tokens import RefreshToken

    Membership.objects.create(
        organization=org, user=org_user, role=MembershipRole.OPERATOR
    )
    client = APIClient()
    token = RefreshToken.for_user(org_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


def _window_payload(offset_hours=1):
    now = _now()
    return {
        "starts_at": (now + timedelta(hours=offset_hours)).isoformat(),
        "ends_at": (now + timedelta(hours=offset_hours + 1)).isoformat(),
    }


@pytest.mark.django_db
class TestChangeWindowAPI:
    def _url(self, change_id):
        return f"/api/v1/changes/{change_id}/window/"

    def test_creates_window_returns_200(self, authed_client, draft_change):
        resp = authed_client.patch(
            self._url(draft_change.id), _window_payload(), format="json"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
        assert "starts_at" in data
        assert "ends_at" in data

    def test_updates_window_returns_200(self, authed_client, draft_change):
        authed_client.patch(
            self._url(draft_change.id), _window_payload(offset_hours=1), format="json"
        )
        resp = authed_client.patch(
            self._url(draft_change.id), _window_payload(offset_hours=3), format="json"
        )
        assert resp.status_code == 200

    def test_returns_404_for_unknown_change(self, authed_client):
        import uuid

        resp = authed_client.patch(
            self._url(uuid.uuid4()), _window_payload(), format="json"
        )
        assert resp.status_code == 404

    def test_returns_409_for_blocked_status(self, authed_client, draft_change):
        draft_change.status = ChangeRecord.Status.RUNNING
        draft_change.save(update_fields=["status", "updated_at"])
        resp = authed_client.patch(
            self._url(draft_change.id), _window_payload(), format="json"
        )
        assert resp.status_code == 409
        assert resp.json()["errors"][0]["code"] == "window_update_not_allowed"

    def test_returns_400_for_invalid_dates(self, authed_client, draft_change):
        now = _now()
        payload = {
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": (now + timedelta(hours=1)).isoformat(),
        }
        resp = authed_client.patch(self._url(draft_change.id), payload, format="json")
        assert resp.status_code == 400

    def test_requires_authentication(self, draft_change):
        client = APIClient()
        client.defaults["HTTP_X_ORGANIZATION_ID"] = str(draft_change.organization_id)
        resp = client.patch(
            self._url(draft_change.id), _window_payload(), format="json"
        )
        assert resp.status_code == 401

    def test_window_response_includes_timezone_and_reason(
        self, authed_client, draft_change
    ):
        now = _now()
        payload = {
            "starts_at": (now + timedelta(hours=1)).isoformat(),
            "ends_at": (now + timedelta(hours=2)).isoformat(),
            "timezone": "UTC",
            "reason": "Maintenance window",
        }
        resp = authed_client.patch(self._url(draft_change.id), payload, format="json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["timezone"] == "UTC"
        assert data["reason"] == "Maintenance window"
