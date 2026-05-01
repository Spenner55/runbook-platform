"""Model-level tests for changes app."""

import pytest
from django.db import IntegrityError

from apps.changes.models import ChangeRecord, ChangeTarget, OperationProfile


@pytest.mark.django_db
class TestOperationProfile:
    def test_create_basic(self, org, published_workflow):
        profile = OperationProfile.objects.create(
            organization=org,
            key="test-profile",
            name="Test Profile",
            risk_level="high",
        )
        assert str(profile) == "OperationProfile test-profile"

    def test_key_unique_per_org(self, org, operation_profile):
        with pytest.raises(IntegrityError):
            OperationProfile.objects.create(
                organization=org,
                key="prod-maintenance",
                name="Duplicate",
                risk_level="high",
            )

    def test_invalid_risk_level_rejected(self, org):
        from django.db import transaction
        with pytest.raises(Exception):
            with transaction.atomic():
                OperationProfile.objects.create(
                    organization=org,
                    key="bad-risk",
                    name="Bad",
                    risk_level="low",
                )


@pytest.mark.django_db
class TestChangeRecord:
    def test_draft_status_default(self, draft_change):
        assert draft_change.status == ChangeRecord.Status.DRAFT

    def test_duplicate_target_rejected(self, draft_change, org):
        with pytest.raises(IntegrityError):
            from django.db import transaction
            with transaction.atomic():
                ChangeTarget.objects.create(
                    change_record=draft_change,
                    organization=org,
                    position=99,
                    target_type="server",
                    target_identifier="prod-server-01",
                    normalized_identifier="prod-server-01",
                    environment="production",
                )

    def test_non_production_env_rejected(self, draft_change, org):
        from django.db import transaction
        with pytest.raises(Exception):
            with transaction.atomic():
                ChangeTarget.objects.create(
                    change_record=draft_change,
                    organization=org,
                    position=99,
                    target_type="server",
                    target_identifier="staging-server",
                    normalized_identifier="staging-server",
                    environment="staging",
                )
