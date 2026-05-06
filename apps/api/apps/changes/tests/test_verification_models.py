"""Phase 11.3 verification and closure model tests."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.changes.models import (
    ChangeClosure,
    ChangeRecord,
    OperationProfile,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
)


def _plan_kwargs(change, **overrides):
    base = {
        "organization": change.organization,
        "change_record": change,
        "operation_profile": change.operation_profile,
        "mode": VerificationPlan.Mode.MIXED,
        "status": VerificationPlan.Status.ACTIVE,
        "generated_from_profile_snapshot": {"verification_mode": "mixed"},
        "generated_from_profile_sha256": "a" * 64,
        "required_check_count": 1,
        "optional_check_count": 0,
        "generated_at": timezone.now(),
    }
    base.update(overrides)
    return base


def _check_kwargs(plan, **overrides):
    base = {
        "organization": plan.organization,
        "plan": plan,
        "change_record": plan.change_record,
        "position": 1,
        "key": "runner-health-check",
        "name": "Runner health check",
        "check_type": VerificationCheck.CheckType.RUNNER_STEP,
        "required": True,
        "status": VerificationCheck.Status.PENDING,
        "verification_key": "postdeploy.health.ok",
        "source_step_key": "health-check",
    }
    base.update(overrides)
    return base


def _result_kwargs(check, **overrides):
    base = {
        "organization": check.organization,
        "change_record": check.change_record,
        "plan": check.plan,
        "verification_check": check,
        "source": VerificationResult.Source.USER,
        "outcome": VerificationResult.Outcome.PASSED,
        "validation_status": VerificationResult.ValidationStatus.ACCEPTED,
        "manual_attestation_text": "Verified post-change health.",
        "submitted_at": timezone.now(),
        "validated_at": timezone.now(),
    }
    base.update(overrides)
    return base


def _closure_kwargs(plan, user, **overrides):
    base = {
        "organization": plan.organization,
        "change_record": plan.change_record,
        "outcome": ChangeClosure.Outcome.SUCCESS,
        "closed_by": user,
        "summary": "Change verified and closed.",
        "verification_plan": plan,
        "verification_summary": {"required": 1, "satisfied": 1},
        "execution_summary": {},
        "closed_at": timezone.now(),
    }
    base.update(overrides)
    return base


@pytest.mark.django_db
class TestOperationProfileVerificationConfig:
    def test_defaults_to_mixed_mode_and_independent_reviewer(self, operation_profile):
        assert (
            operation_profile.verification_mode
            == OperationProfile.VerificationMode.MIXED
        )
        assert "checks" in operation_profile.verification_plan_template
        assert operation_profile.requires_independent_reviewer is True
        assert operation_profile.verification_timeout_seconds is None

    def test_invalid_verification_mode_rejected_by_constraint(self, org):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OperationProfile.objects.create(
                    organization=org,
                    key="bad-mode",
                    name="Bad Mode",
                    risk_level="high",
                    verification_mode="invalid",
                )


@pytest.mark.django_db
class TestVerificationPlan:
    def test_create_plan(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        assert plan.pk is not None
        assert plan.mode == VerificationPlan.Mode.MIXED
        assert str(plan).startswith("VerificationPlan")

    def test_one_plan_per_change(self, draft_change):
        VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                VerificationPlan.objects.create(**_plan_kwargs(draft_change))

    def test_invalid_status_rejected_by_constraint(self, draft_change):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                VerificationPlan.objects.create(
                    **_plan_kwargs(draft_change, status="unknown")
                )

    def test_tenant_mismatch_raises_validation(self, draft_change, org_factory):
        other_org = org_factory("verif-plan-other-org")
        plan = VerificationPlan(**_plan_kwargs(draft_change, organization=other_org))
        with pytest.raises(ValidationError, match="organization must match"):
            plan.full_clean()


@pytest.mark.django_db
class TestVerificationCheck:
    def test_create_required_check(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        check = VerificationCheck.objects.create(**_check_kwargs(plan))
        assert check.pk is not None
        assert check.status == VerificationCheck.Status.PENDING

    def test_key_unique_per_plan(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        VerificationCheck.objects.create(**_check_kwargs(plan))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                VerificationCheck.objects.create(
                    **_check_kwargs(plan, position=2, name="Duplicate key")
                )

    def test_position_unique_per_plan(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        VerificationCheck.objects.create(**_check_kwargs(plan))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                VerificationCheck.objects.create(
                    **_check_kwargs(plan, key="other-check", name="Duplicate position")
                )

    def test_invalid_type_rejected_by_constraint(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                VerificationCheck.objects.create(
                    **_check_kwargs(plan, check_type="unknown")
                )

    def test_tenant_mismatch_raises_validation(self, draft_change, org_factory):
        other_org = org_factory("verif-check-other-org")
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        check = VerificationCheck(**_check_kwargs(plan, organization=other_org))
        with pytest.raises(ValidationError, match="organization must match"):
            check.full_clean()


@pytest.mark.django_db
class TestVerificationResult:
    def test_create_accepted_result(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        check = VerificationCheck.objects.create(**_check_kwargs(plan))
        result = VerificationResult.objects.create(**_result_kwargs(check))
        assert result.pk is not None
        assert result.validation_status == VerificationResult.ValidationStatus.ACCEPTED

    def test_invalid_validation_status_rejected_by_constraint(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        check = VerificationCheck.objects.create(**_check_kwargs(plan))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                VerificationResult.objects.create(
                    **_result_kwargs(check, validation_status="unknown")
                )

    def test_result_is_immutable_after_creation(self, draft_change):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        check = VerificationCheck.objects.create(**_check_kwargs(plan))
        result = VerificationResult.objects.create(**_result_kwargs(check))
        result.outcome = VerificationResult.Outcome.FAILED
        with pytest.raises(ValidationError, match="immutable"):
            result.save()

    def test_tenant_mismatch_raises_validation(self, draft_change, org_factory):
        other_org = org_factory("verif-result-other-org")
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        check = VerificationCheck.objects.create(**_check_kwargs(plan))
        result = VerificationResult(**_result_kwargs(check, organization=other_org))
        with pytest.raises(ValidationError, match="organization must match"):
            result.full_clean()


@pytest.mark.django_db
class TestChangeClosure:
    def test_create_closure(self, draft_change, org_user):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        closure = ChangeClosure.objects.create(**_closure_kwargs(plan, org_user))
        assert closure.pk is not None
        assert closure.outcome == ChangeClosure.Outcome.SUCCESS

    def test_one_closure_per_change(self, draft_change, org_user):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        ChangeClosure.objects.create(**_closure_kwargs(plan, org_user))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ChangeClosure.objects.create(**_closure_kwargs(plan, org_user))

    def test_invalid_outcome_rejected_by_constraint(self, draft_change, org_user):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ChangeClosure.objects.create(
                    **_closure_kwargs(plan, org_user, outcome="unknown")
                )

    def test_closure_is_immutable_after_creation(self, draft_change, org_user):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        closure = ChangeClosure.objects.create(**_closure_kwargs(plan, org_user))
        closure.summary = "Tampered"
        with pytest.raises(ValidationError, match="immutable"):
            closure.save()

    def test_closure_delete_is_rejected(self, draft_change, org_user):
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        closure = ChangeClosure.objects.create(**_closure_kwargs(plan, org_user))
        with pytest.raises(ValidationError, match="immutable"):
            closure.delete()

    def test_tenant_mismatch_raises_validation(
        self, draft_change, org_user, org_factory
    ):
        other_org = org_factory("closure-other-org")
        plan = VerificationPlan.objects.create(**_plan_kwargs(draft_change))
        closure = ChangeClosure(
            **_closure_kwargs(plan, org_user, organization=other_org)
        )
        with pytest.raises(ValidationError, match="organization must match"):
            closure.full_clean()


@pytest.mark.django_db
def test_verification_failed_status_is_storable(draft_change):
    draft_change.status = ChangeRecord.Status.VERIFICATION_FAILED
    draft_change.verification_failed_at = timezone.now() - timedelta(minutes=1)
    draft_change.save(update_fields=["status", "verification_failed_at", "updated_at"])
    draft_change.refresh_from_db()
    assert draft_change.status == ChangeRecord.Status.VERIFICATION_FAILED


@pytest.mark.django_db
def test_change_record_invalid_status_rejected_by_constraint(draft_change):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ChangeRecord.objects.filter(pk=draft_change.pk).update(status="unknown")
