"""Audit event emission and metadata scrubbing tests for changes app."""

import pytest

from apps.audit.models import AuditEvent
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord


@pytest.mark.django_db
class TestChangeAuditEvents:
    def test_change_created_event_emitted(
        self, org, operation_profile, published_workflow
    ):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Audit Test Change",
            justification="Testing audit",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
        )
        assert AuditEvent.objects.filter(
            event_type="change.created",
            object_id=change.id,
        ).exists()

    def test_change_submitted_event_emitted(self, draft_change):
        change = change_services.submit_change_record(change=draft_change)
        assert AuditEvent.objects.filter(
            event_type="change.submitted",
            object_id=change.id,
        ).exists()

    def test_approval_bound_event_emitted_on_submit(
        self, draft_change, operation_profile
    ):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        assert AuditEvent.objects.filter(
            event_type="change.approval_bound",
            object_id=change.id,
        ).exists()

    def test_change_approval_request_emits_approval_requested(
        self, draft_change, operation_profile
    ):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)

        event = AuditEvent.objects.filter(
            event_type="approval.requested",
            object_type=AuditEvent.ObjectType.APPROVAL_REQUEST,
            object_id=change.approval_request_id,
        ).first()

        assert event is not None
        assert event.metadata["subject_type"] == "change_record"
        assert event.metadata["change_record_id"] == str(change.id)

    def test_approval_decision_emits_status_changed_event(
        self, draft_change, operation_profile
    ):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        from apps.approvals import services as approval_services
        from apps.audit.services import AuditActor

        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        approval_services.decide_approval(
            approval_request=ar, decision="approved", actor=actor
        )

        change.refresh_from_db()
        # After approval the change should have moved to approved/dispatchable/scheduled
        assert change.status in (
            ChangeRecord.Status.APPROVED,
            ChangeRecord.Status.DISPATCHABLE,
            ChangeRecord.Status.SCHEDULED,
        )
        # A status_changed event should exist for this change
        assert AuditEvent.objects.filter(
            event_type="change.status_changed",
            object_id=change.id,
        ).exists()

    def test_rejection_emits_status_changed_event(
        self, draft_change, operation_profile
    ):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        from apps.approvals import services as approval_services
        from apps.audit.services import AuditActor

        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        approval_services.decide_approval(
            approval_request=ar, decision="rejected", actor=actor
        )

        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.REJECTED
        assert AuditEvent.objects.filter(
            event_type="change.status_changed",
            object_id=change.id,
        ).exists()

    def test_operation_profile_direct_orm_emits_governance_events(self, org):
        from apps.changes.models import OperationProfile

        profile = OperationProfile.objects.create(
            organization=org,
            key="audited-profile",
            name="Audited Profile",
            risk_level="high",
            allowed_target_types=["server"],
        )
        profile.name = "Audited Profile Updated"
        profile.save(update_fields=["name", "updated_at"])
        profile.is_active = False
        profile.save(update_fields=["is_active", "updated_at"])

        events = list(
            AuditEvent.objects.filter(
                object_type=AuditEvent.ObjectType.OPERATION_PROFILE,
                object_id=profile.id,
            ).values_list("event_type", flat=True)
        )

        assert "operation_profile.created" in events
        assert "operation_profile.updated" in events
        assert "operation_profile.deactivated" in events


@pytest.mark.django_db
class TestOperationProfileServiceGovernance:
    """Tests for create_operation_profile / update_operation_profile / deactivate_operation_profile."""

    def test_create_emits_created_event(self, org, published_workflow):
        from apps.audit.services import AuditActor
        from apps.changes import services as change_services

        actor = AuditActor(
            actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test-create"
        )
        profile = change_services.create_operation_profile(
            organization=org,
            key="svc-create-test",
            name="Service Create Test",
            risk_level="high",
            allowed_target_types=["server"],
            actor=actor,
        )
        assert AuditEvent.objects.filter(
            event_type="operation_profile.created",
            object_type=AuditEvent.ObjectType.OPERATION_PROFILE,
            object_id=profile.id,
        ).exists()

    def test_create_with_workflows_enforces_same_org(self, org, published_workflow):
        from apps.changes import services as change_services
        from apps.common.exceptions import DomainValidationError
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(name="Other", slug="svc-other")
        from apps.changes.models import OperationProfile

        profile = OperationProfile.objects.create(
            organization=other_org,
            key="other-svc-profile",
            name="Other",
            risk_level="high",
        )
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.update_operation_profile(
                profile=profile,
                workflow_ids=[str(published_workflow.id)],
            )
        assert exc_info.value.code == "operation_profile_workflow_org_mismatch"

    def test_update_emits_updated_event(self, org, operation_profile):
        from apps.changes import services as change_services

        change_services.update_operation_profile(
            profile=operation_profile,
            name="Updated Name",
        )
        operation_profile.refresh_from_db()
        assert operation_profile.name == "Updated Name"
        assert AuditEvent.objects.filter(
            event_type="operation_profile.updated",
            object_type=AuditEvent.ObjectType.OPERATION_PROFILE,
            object_id=operation_profile.id,
        ).exists()

    def test_update_invalid_risk_level_rejected(self, org, operation_profile):
        from apps.changes import services as change_services
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError) as exc_info:
            change_services.update_operation_profile(
                profile=operation_profile,
                risk_level="low",
            )
        assert exc_info.value.code == "invalid_risk_level"

    def test_deactivate_emits_deactivated_event(self, org, operation_profile):
        from apps.changes import services as change_services

        change_services.deactivate_operation_profile(profile=operation_profile)
        operation_profile.refresh_from_db()
        assert not operation_profile.is_active
        assert AuditEvent.objects.filter(
            event_type="operation_profile.deactivated",
            object_type=AuditEvent.ObjectType.OPERATION_PROFILE,
            object_id=operation_profile.id,
        ).exists()

    def test_deactivate_is_idempotent(self, org, operation_profile):
        from apps.changes import services as change_services

        operation_profile.is_active = False
        operation_profile.save(update_fields=["is_active", "updated_at"])
        events_before = AuditEvent.objects.filter(
            event_type="operation_profile.deactivated",
            object_id=operation_profile.id,
        ).count()
        change_services.deactivate_operation_profile(profile=operation_profile)
        events_after = AuditEvent.objects.filter(
            event_type="operation_profile.deactivated",
            object_id=operation_profile.id,
        ).count()
        assert events_after == events_before  # no new event emitted

    def test_service_create_invalid_risk_level(self, org):
        from apps.changes import services as change_services
        from apps.common.exceptions import DomainValidationError

        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_operation_profile(
                organization=org,
                key="bad-risk",
                name="Bad Risk",
                risk_level="low",
            )
        assert exc_info.value.code == "invalid_risk_level"


@pytest.mark.django_db
class TestAdminCrossOrgGovernance:
    """Verify the M2M signal prevents cross-org allowlisting via any code path."""

    def test_m2m_add_rejects_cross_org_workflow(self, org, operation_profile, published_workflow):
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.organizations.models import Organization
        from apps.changes.models import OperationProfile

        other_org = Organization.objects.create(name="Admin Other", slug="admin-other")
        other_profile = OperationProfile.objects.create(
            organization=other_org,
            key="admin-other-profile",
            name="Admin Other Profile",
            risk_level="high",
        )
        # Wrap in savepoint so the outer transaction stays usable after the error.
        with pytest.raises(ValidationError):
            with transaction.atomic():
                other_profile.allowed_workflows.add(published_workflow)
        assert not other_profile.allowed_workflows.filter(pk=published_workflow.pk).exists()

    def test_m2m_set_rejects_cross_org_workflow(self, org, operation_profile, published_workflow):
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from apps.organizations.models import Organization
        from apps.changes.models import OperationProfile

        other_org = Organization.objects.create(name="Admin Other2", slug="admin-other2")
        other_profile = OperationProfile.objects.create(
            organization=other_org,
            key="admin-other-profile-2",
            name="Admin Other Profile 2",
            risk_level="high",
        )
        with pytest.raises(ValidationError):
            with transaction.atomic():
                other_profile.allowed_workflows.set([published_workflow])
        assert not other_profile.allowed_workflows.filter(pk=published_workflow.pk).exists()

    def test_admin_save_related_fallback_removes_cross_org(
        self, org, operation_profile, published_workflow
    ):
        """
        Simulate what admin.save_related does after super() if the M2M signal
        somehow allowed a cross-org workflow through (defense-in-depth test).
        The fallback cleanup in save_related catches anything the signal missed.
        """
        from apps.changes.models import OperationProfile
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(name="Admin Other3", slug="admin-other3")
        other_profile = OperationProfile.objects.create(
            organization=other_org,
            key="admin-other-profile-3",
            name="Admin Other Profile 3",
            risk_level="high",
        )
        # Force-insert via through model to bypass signal (simulates corrupted data)
        through = OperationProfile.allowed_workflows.through
        through.objects.create(
            operationprofile=other_profile,
            workflow=published_workflow,
        )
        assert other_profile.allowed_workflows.filter(pk=published_workflow.pk).exists()

        # Simulate what admin save_related fallback does
        cross_org = other_profile.allowed_workflows.exclude(organization=other_org)
        for wf in cross_org:
            other_profile.allowed_workflows.remove(wf)

        assert not other_profile.allowed_workflows.filter(pk=published_workflow.pk).exists()


@pytest.mark.django_db
class TestAuditMetadataScrubbing:
    def test_dispatch_token_not_in_audit_metadata(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Token Scrub Test",
            justification="Test",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
        )
        change_services.submit_change_record(change=change)
        change.refresh_from_db()
        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)

        # No audit event should contain dispatch_token or dispatch_token_hash in metadata
        for event in AuditEvent.objects.filter(object_id=change.id):
            meta = event.metadata or {}
            assert "dispatch_token" not in meta
            assert "dispatch_token_hash" not in meta
            assert "change_dispatch_token" not in meta

    def test_requested_inputs_not_in_audit_metadata(
        self, org, operation_profile, published_workflow
    ):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Inputs Scrub Test",
            justification="Test",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
        )
        for event in AuditEvent.objects.filter(object_id=change.id):
            meta = event.metadata or {}
            assert "requested_inputs" not in meta
            assert "request_snapshot" not in meta

    def test_audit_events_have_correct_object_type(
        self, org, operation_profile, published_workflow
    ):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Object Type Test",
            justification="Test",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
        )
        event = AuditEvent.objects.filter(
            event_type="change.created",
            object_id=change.id,
        ).first()
        assert event is not None
        assert event.object_type == "change_record"


@pytest.mark.django_db
class TestAuditScrubberForbiddenKeys:
    """Audit scrubber rejects and strips forbidden keys including nested dicts."""

    def test_audit_scrubber_rejects_dispatch_token(self, org):
        from django.core.exceptions import ValidationError

        from apps.audit.services import AuditService

        with pytest.raises(ValidationError):
            AuditService.emit(
                organization_id=org.id,
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_label="test",
                event_type="test.scrub",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                object_id=org.id,
                metadata={"dispatch_token": "clear-token-value"},
            )

    def test_audit_scrubber_rejects_dispatch_token_hash(self, org):
        from django.core.exceptions import ValidationError

        from apps.audit.services import AuditService

        with pytest.raises(ValidationError):
            AuditService.emit(
                organization_id=org.id,
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_label="test",
                event_type="test.scrub",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                object_id=org.id,
                metadata={"dispatch_token_hash": "abc123"},
            )

    def test_audit_scrubber_rejects_requested_inputs(self, org):
        from django.core.exceptions import ValidationError

        from apps.audit.services import AuditService

        with pytest.raises(ValidationError):
            AuditService.emit(
                organization_id=org.id,
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_label="test",
                event_type="test.scrub",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                object_id=org.id,
                metadata={"requested_inputs": {"ticket": "CHG-1"}},
            )

    def test_audit_scrubber_rejects_request_snapshot(self, org):
        from django.core.exceptions import ValidationError

        from apps.audit.services import AuditService

        with pytest.raises(ValidationError):
            AuditService.emit(
                organization_id=org.id,
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_label="test",
                event_type="test.scrub",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                object_id=org.id,
                metadata={"request_snapshot": {"title": "Change"}},
            )

    def test_audit_scrubber_strips_forbidden_key_in_nested_dict(self, org):
        from apps.audit.services import AuditService

        # "token" is in FORBIDDEN_METADATA_KEYS (not REJECTED) so it is silently stripped.
        event = AuditService.emit(
            organization_id=org.id,
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_label="test",
            event_type="test.scrub.nested",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            object_id=org.id,
            metadata={
                "context": {
                    "change_id": "abc",
                    "token": "should-be-stripped",
                }
            },
        )
        assert "token" not in event.metadata.get("context", {})
        assert event.metadata["context"]["change_id"] == "abc"

    def test_audit_scrubber_rejects_nested_dispatch_token(self, org):
        from django.core.exceptions import ValidationError

        from apps.audit.services import AuditService

        # dispatch_token is in REJECTED_METADATA_KEYS — raises even when nested.
        with pytest.raises(ValidationError):
            AuditService.emit(
                organization_id=org.id,
                actor_type=AuditEvent.ActorType.SYSTEM,
                actor_label="test",
                event_type="test.scrub.nested.rejected",
                object_type=AuditEvent.ObjectType.CHANGE_RECORD,
                object_id=org.id,
                metadata={
                    "context": {
                        "change_id": "abc",
                        "dispatch_token": "nested-clear-token",
                    }
                },
            )

    def test_audit_scrubber_rejects_nested_claim_token_via_forbidden(self, org):
        from apps.audit.services import AuditService

        # claim_token is in FORBIDDEN_METADATA_KEYS — silently stripped even nested.
        event = AuditService.emit(
            organization_id=org.id,
            actor_type=AuditEvent.ActorType.SYSTEM,
            actor_label="test",
            event_type="test.scrub.nested.claim",
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            object_id=org.id,
            metadata={
                "runner_context": {
                    "runner_id": "runner-prod-1",
                    "claim_token": "some-claim-token",
                }
            },
        )
        assert "claim_token" not in event.metadata.get("runner_context", {})
        assert event.metadata["runner_context"]["runner_id"] == "runner-prod-1"
