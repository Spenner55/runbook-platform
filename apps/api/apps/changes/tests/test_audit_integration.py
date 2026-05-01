"""Audit event emission and metadata scrubbing tests for changes app."""

import pytest

from apps.audit.models import AuditEvent
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord


@pytest.mark.django_db
class TestChangeAuditEvents:
    def test_change_created_event_emitted(self, org, operation_profile, published_workflow):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Audit Test Change",
            justification="Testing audit",
            targets=[{"target_type": "server", "target_identifier": "srv", "environment": "production"}],
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

    def test_approval_bound_event_emitted_on_submit(self, draft_change, operation_profile):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        assert AuditEvent.objects.filter(
            event_type="change.approval_bound",
            object_id=change.id,
        ).exists()

    def test_approval_decision_emits_status_changed_event(self, draft_change, operation_profile):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        from apps.approvals import services as approval_services
        from apps.audit.services import AuditActor
        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        approval_services.decide_approval(approval_request=ar, decision="approved", actor=actor)

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

    def test_rejection_emits_status_changed_event(self, draft_change, operation_profile):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        from apps.approvals import services as approval_services
        from apps.audit.services import AuditActor
        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        approval_services.decide_approval(approval_request=ar, decision="rejected", actor=actor)

        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.REJECTED
        assert AuditEvent.objects.filter(
            event_type="change.status_changed",
            object_id=change.id,
        ).exists()


@pytest.mark.django_db
class TestAuditMetadataScrubbing:
    def test_dispatch_token_not_in_audit_metadata(self, org, operation_profile, published_workflow):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Token Scrub Test",
            justification="Test",
            targets=[{"target_type": "server", "target_identifier": "srv", "environment": "production"}],
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

    def test_requested_inputs_not_in_audit_metadata(self, org, operation_profile, published_workflow):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Inputs Scrub Test",
            justification="Test",
            targets=[{"target_type": "server", "target_identifier": "srv", "environment": "production"}],
        )
        for event in AuditEvent.objects.filter(object_id=change.id):
            meta = event.metadata or {}
            assert "requested_inputs" not in meta
            assert "request_snapshot" not in meta

    def test_audit_events_have_correct_object_type(self, org, operation_profile, published_workflow):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Object Type Test",
            justification="Test",
            targets=[{"target_type": "server", "target_identifier": "srv", "environment": "production"}],
        )
        event = AuditEvent.objects.filter(
            event_type="change.created",
            object_id=change.id,
        ).first()
        assert event is not None
        assert event.object_type == "change_record"
