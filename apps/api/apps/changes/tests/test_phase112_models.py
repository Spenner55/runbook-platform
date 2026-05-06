"""Phase 11.2 model and constraint tests.

Covers: ChangeWindow, FreezeRule, TargetLock, DispatchEligibilityCheck,
freeze exception fields on ChangeRecord, and the partial unique active-lock
constraint on TargetLock.
"""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.changes.models import (
    ChangeWindow,
    DispatchEligibilityCheck,
    FreezeRule,
    TargetLock,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now():
    return timezone.now()


def _window_kwargs(change, **overrides):
    base = {
        "organization": change.organization,
        "change_record": change,
        "starts_at": _now() + timedelta(hours=1),
        "ends_at": _now() + timedelta(hours=2),
        "status": ChangeWindow.Status.SCHEDULED,
    }
    base.update(overrides)
    return base


def _freeze_kwargs(org, **overrides):
    base = {
        "organization": org,
        "name": "Test Freeze",
        "behavior": FreezeRule.Behavior.BLOCK,
        "starts_at": _now() - timedelta(hours=1),
        "ends_at": _now() + timedelta(hours=1),
        "scope_type": FreezeRule.ScopeType.ALL_PRODUCTION,
        "requires_exception_reference": False,
    }
    base.update(overrides)
    return base


def _lock_kwargs(change, target_type="server", identifier="prod-01", **overrides):
    base = {
        "organization": change.organization,
        "change_record": change,
        "target_type": target_type,
        "target_identifier": identifier,
        "normalized_identifier": identifier.lower(),
        "status": TargetLock.Status.ACTIVE,
        "acquired_at": _now(),
    }
    base.update(overrides)
    return base


def _check_kwargs(change, user, **overrides):
    base = {
        "organization": change.organization,
        "change_record": change,
        "requested_by": user,
        "result": DispatchEligibilityCheck.Result.PASSED,
        "checked_at": _now(),
        "expires_at": _now() + timedelta(seconds=60),
        "approved_status_ok": True,
        "policy_pass_ok": True,
        "window_open_ok": True,
        "freeze_conflicts_ok": True,
        "target_locks_ok": True,
        "actor_authorized_ok": True,
        "checks": [],
        "conflicts": [],
        "input_snapshot_sha256": "a" * 64,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ChangeWindow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangeWindow:
    def test_create_scheduled_window(self, draft_change):
        window = ChangeWindow.objects.create(**_window_kwargs(draft_change))
        assert window.pk is not None
        assert window.status == ChangeWindow.Status.SCHEDULED

    def test_one_window_per_change(self, draft_change):
        ChangeWindow.objects.create(**_window_kwargs(draft_change))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ChangeWindow.objects.create(**_window_kwargs(draft_change))

    def test_ends_before_starts_raises_validation(self, draft_change):
        now = _now()
        window = ChangeWindow(
            **_window_kwargs(
                draft_change,
                starts_at=now + timedelta(hours=2),
                ends_at=now + timedelta(hours=1),
            )
        )
        with pytest.raises(ValidationError, match="ends_at must be after starts_at"):
            window.full_clean()

    def test_valid_status_values(self, draft_change):
        for status in ChangeWindow.Status:
            w = ChangeWindow(**_window_kwargs(draft_change, status=status))
            w.full_clean()

    def test_org_mismatch_raises(self, draft_change, org_factory):
        other_org = org_factory("other-org")
        window = ChangeWindow(**_window_kwargs(draft_change, organization=other_org))
        with pytest.raises(ValidationError, match="organization must match"):
            window.full_clean()

    def test_all_status_transitions_storable(self, draft_change):
        window = ChangeWindow.objects.create(**_window_kwargs(draft_change))
        for status in ChangeWindow.Status:
            window.status = status
            window.save(update_fields=["status"])
        window.refresh_from_db()
        assert window.status == ChangeWindow.Status.CLOSED


# ---------------------------------------------------------------------------
# FreezeRule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFreezeRule:
    def test_create_block_rule(self, org):
        rule = FreezeRule.objects.create(**_freeze_kwargs(org))
        assert rule.pk is not None
        assert rule.behavior == FreezeRule.Behavior.BLOCK

    def test_allow_with_exception_requires_exception_ref(self, org):
        rule = FreezeRule(
            **_freeze_kwargs(
                org,
                behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
                requires_exception_reference=False,
            )
        )
        with pytest.raises(ValidationError, match="requires_exception_reference"):
            rule.full_clean()

    def test_allow_with_exception_valid_when_ref_true(self, org):
        rule = FreezeRule(
            **_freeze_kwargs(
                org,
                behavior=FreezeRule.Behavior.ALLOW_WITH_EXCEPTION,
                requires_exception_reference=True,
            )
        )
        rule.full_clean()

    def test_ends_before_starts_raises(self, org):
        now = _now()
        rule = FreezeRule(
            **_freeze_kwargs(
                org,
                starts_at=now + timedelta(hours=2),
                ends_at=now + timedelta(hours=1),
            )
        )
        with pytest.raises(ValidationError, match="ends_at must be after starts_at"):
            rule.full_clean()

    def test_invalid_behavior_rejected(self, org):
        rule = FreezeRule(**_freeze_kwargs(org, behavior="not_valid"))
        with pytest.raises(ValidationError):
            rule.full_clean()

    def test_invalid_scope_type_rejected(self, org):
        rule = FreezeRule(**_freeze_kwargs(org, scope_type="unknown_scope"))
        with pytest.raises(ValidationError):
            rule.full_clean()

    def test_target_type_scope(self, org):
        rule = FreezeRule.objects.create(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_TYPE,
                target_type="database",
            )
        )
        assert rule.scope_type == FreezeRule.ScopeType.TARGET_TYPE

    def test_identifier_scope(self, org):
        rule = FreezeRule.objects.create(
            **_freeze_kwargs(
                org,
                scope_type=FreezeRule.ScopeType.TARGET_IDENTIFIER,
                target_type="database",
                target_identifier="prod-primary",
                normalized_identifier="prod-primary",
            )
        )
        assert rule.scope_type == FreezeRule.ScopeType.TARGET_IDENTIFIER


# ---------------------------------------------------------------------------
# TargetLock — general behavior
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTargetLock:
    def test_create_active_lock(self, draft_change):
        lock = TargetLock.objects.create(**_lock_kwargs(draft_change))
        assert lock.pk is not None
        assert lock.status == TargetLock.Status.ACTIVE

    def test_release_lock(self, draft_change):
        lock = TargetLock.objects.create(**_lock_kwargs(draft_change))
        lock.status = TargetLock.Status.RELEASED
        lock.released_at = _now()
        lock.release_reason = "execution_finished"
        lock.save()
        lock.refresh_from_db()
        assert lock.status == TargetLock.Status.RELEASED

    def test_expire_lock(self, draft_change):
        lock = TargetLock.objects.create(**_lock_kwargs(draft_change))
        lock.status = TargetLock.Status.EXPIRED
        lock.released_at = _now()
        lock.release_reason = "window_expired"
        lock.save()
        lock.refresh_from_db()
        assert lock.status == TargetLock.Status.EXPIRED

    def test_org_mismatch_raises(self, draft_change, org_factory):
        other_org = org_factory("lock-other-org")
        lock = TargetLock(**_lock_kwargs(draft_change, organization=other_org))
        with pytest.raises(ValidationError, match="organization must match"):
            lock.full_clean()

    def test_invalid_status_rejected(self, draft_change):
        lock = TargetLock(**_lock_kwargs(draft_change, status="unknown"))
        with pytest.raises(ValidationError):
            lock.full_clean()


# ---------------------------------------------------------------------------
# TargetLock — partial unique active constraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTargetLockActiveUniqueConstraint:
    def test_two_active_locks_same_target_raises_integrity_error(
        self, draft_change, org_factory, operation_profile, published_workflow
    ):
        """Partial unique index must reject a second active lock for the same target key."""
        TargetLock.objects.create(**_lock_kwargs(draft_change, identifier="prod-db"))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                TargetLock.objects.create(
                    **_lock_kwargs(draft_change, identifier="prod-db")
                )

    def test_released_lock_allows_new_active_lock(self, draft_change):
        """A released lock for the same key must not block a new active lock."""
        lock = TargetLock.objects.create(
            **_lock_kwargs(draft_change, identifier="re-db")
        )
        lock.status = TargetLock.Status.RELEASED
        lock.released_at = _now()
        lock.release_reason = "execution_finished"
        lock.save()

        new_lock = TargetLock.objects.create(
            **_lock_kwargs(draft_change, identifier="re-db")
        )
        assert new_lock.status == TargetLock.Status.ACTIVE

    def test_expired_lock_allows_new_active_lock(self, draft_change):
        """An expired lock must not block a new active lock."""
        lock = TargetLock.objects.create(
            **_lock_kwargs(draft_change, identifier="ex-db")
        )
        lock.status = TargetLock.Status.EXPIRED
        lock.released_at = _now()
        lock.save()

        new_lock = TargetLock.objects.create(
            **_lock_kwargs(draft_change, identifier="ex-db")
        )
        assert new_lock.status == TargetLock.Status.ACTIVE

    def test_different_target_types_can_both_be_active(self, draft_change):
        """Active locks for different target_types on the same identifier are allowed."""
        TargetLock.objects.create(
            **_lock_kwargs(draft_change, target_type="server", identifier="same-id")
        )
        lock2 = TargetLock.objects.create(
            **_lock_kwargs(draft_change, target_type="database", identifier="same-id")
        )
        assert lock2.status == TargetLock.Status.ACTIVE

    def test_different_identifiers_can_both_be_active(self, draft_change):
        """Two active locks for different normalized identifiers must coexist."""
        TargetLock.objects.create(**_lock_kwargs(draft_change, identifier="prod-01"))
        lock2 = TargetLock.objects.create(
            **_lock_kwargs(draft_change, identifier="prod-02")
        )
        assert lock2.status == TargetLock.Status.ACTIVE


# ---------------------------------------------------------------------------
# DispatchEligibilityCheck
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDispatchEligibilityCheck:
    def test_create_passed_check(self, draft_change, org_user):
        check = DispatchEligibilityCheck.objects.create(
            **_check_kwargs(draft_change, org_user)
        )
        assert check.pk is not None
        assert check.result == DispatchEligibilityCheck.Result.PASSED

    def test_create_failed_check(self, draft_change, org_user):
        check = DispatchEligibilityCheck.objects.create(
            **_check_kwargs(
                draft_change,
                org_user,
                result=DispatchEligibilityCheck.Result.FAILED,
                window_open_ok=False,
            )
        )
        assert check.result == DispatchEligibilityCheck.Result.FAILED

    def test_immutable_after_creation(self, draft_change, org_user):
        check = DispatchEligibilityCheck.objects.create(
            **_check_kwargs(draft_change, org_user)
        )
        check.result = DispatchEligibilityCheck.Result.FAILED
        with pytest.raises(ValidationError, match="immutable after creation"):
            check.save()

    def test_invalid_result_rejected(self, draft_change, org_user):
        check = DispatchEligibilityCheck(
            **_check_kwargs(draft_change, org_user, result="maybe")
        )
        with pytest.raises(ValidationError):
            check.full_clean()


# ---------------------------------------------------------------------------
# ChangeRecord freeze exception fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangeRecordFreezeExceptionFields:
    def test_freeze_exception_fields_default_blank(self, draft_change):
        assert draft_change.freeze_exception_reference == ""
        assert draft_change.freeze_exception_reason == ""
        assert draft_change.freeze_exception_recorded_by is None
        assert draft_change.freeze_exception_recorded_at is None

    def test_set_freeze_exception_reference(self, draft_change):
        draft_change.freeze_exception_reference = "CHG-FREEZE-001"
        draft_change.freeze_exception_reason = "Approved by CAB"
        draft_change.save(
            update_fields=["freeze_exception_reference", "freeze_exception_reason"]
        )
        draft_change.refresh_from_db()
        assert draft_change.freeze_exception_reference == "CHG-FREEZE-001"
        assert draft_change.freeze_exception_reason == "Approved by CAB"
