"""Service-layer tests for changes app."""

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)


def _sys_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


@pytest.mark.django_db
class TestCreateChangeRecord:
    def test_creates_draft(self, org, operation_profile, published_workflow):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Test Change",
            justification="Needed",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "environment": "production",
                }
            ],
        )
        assert change.status == ChangeRecord.Status.DRAFT
        assert change.targets.count() == 1

    def test_invalid_profile_key_rejected(self, org, published_workflow):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="nonexistent",
                workflow_id=str(published_workflow.id),
                title="T",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "x",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "invalid_operation_profile"

    def test_inactive_profile_rejected(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.is_active = False
        operation_profile.save()
        with pytest.raises(DomainConflictError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="T",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "x",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "change_profile_inactive"

    def test_workflow_not_allowlisted_rejected(self, org, operation_profile, runbook):
        from apps.workflows import services as workflow_services
        from apps.workflows.internal_clients import StubWorkflowTransformClient

        other_wf = workflow_services.publish_workflow(
            workflow=workflow_services.create_workflow(
                runbook=runbook, transform_client=StubWorkflowTransformClient()
            )
        )
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(other_wf.id),
                title="T",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "x",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "workflow_not_allowlisted_for_profile"

    def test_non_production_target_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="T",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "x",
                        "environment": "staging",
                    }
                ],
            )
        assert exc_info.value.code == "non_production_target"

    def test_duplicate_targets_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="T",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "same",
                        "environment": "production",
                    },
                    {
                        "target_type": "server",
                        "target_identifier": "same",
                        "environment": "production",
                    },
                ],
            )
        assert exc_info.value.code == "duplicate_change_target"

    def test_zero_targets_rejected_by_default(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="T",
                targets=[],
            )
        assert exc_info.value.code == "change_requires_targets"

    def test_emits_change_created_audit(
        self, org, operation_profile, published_workflow
    ):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Audited Change",
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

    def test_requested_inputs_schema_enforced(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requested_inputs_schema = {
            "required": ["ticket"],
            "properties": {"ticket": {"type": "string"}},
            "additionalProperties": False,
        }
        operation_profile.save()

        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Schema Test",
                justification="Needed",
                requested_inputs={"ticket": 123},
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "requested_inputs_invalid"

    def test_target_metadata_secret_key_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Metadata Test",
                justification="Needed",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                        "metadata": {"token": "secret"},
                    }
                ],
            )
        assert exc_info.value.code == "target_metadata_forbidden_key"


@pytest.mark.django_db
class TestSubmitChangeRecord:
    def test_submit_moves_to_pending_approval(self, draft_change, operation_profile):
        operation_profile.requires_approval = True
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        assert change.status == ChangeRecord.Status.PENDING_APPROVAL
        assert change.submitted_at is not None
        assert change.requested_inputs_sha256 != ""
        assert change.request_snapshot_sha256 != ""
        assert change.approval_request is not None

    def test_submit_freezes_hashes(self, draft_change):
        change = change_services.submit_change_record(change=draft_change)
        expected_hash = change_services.sha256_canonical_json(
            draft_change.requested_inputs
        )
        assert change.requested_inputs_sha256 == expected_hash

    def test_submit_snapshot_covers_full_dossier(
        self, org, operation_profile, published_workflow
    ):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Snapshot Title",
            summary="Snapshot summary",
            justification="Snapshot justification",
            requested_inputs={"ticket": "CHG-1", "window": "night"},
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "display_name": "Prod 01",
                    "environment": "production",
                    "metadata": {"region": "us-west-2"},
                }
            ],
        )

        submitted = change_services.submit_change_record(change=change)
        snapshot = submitted.request_snapshot

        assert snapshot["title"] == "Snapshot Title"
        assert snapshot["summary"] == "Snapshot summary"
        assert snapshot["justification"] == "Snapshot justification"
        assert snapshot["operation_profile_id"] == str(operation_profile.id)
        assert snapshot["requested_input_keys"] == ["ticket", "window"]
        assert snapshot["targets"][0]["metadata"] == {"region": "us-west-2"}

    def test_submit_no_approval_moves_to_approved(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="No Approval Change",
            justification="Bypass approved",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
        )
        change = change_services.submit_change_record(change=change)
        assert change.status in (
            ChangeRecord.Status.APPROVED,
            ChangeRecord.Status.DISPATCHABLE,
            ChangeRecord.Status.SCHEDULED,
        )

    def test_submit_requires_justification(
        self, org, operation_profile, published_workflow
    ):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="No Justification",
            justification="",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                }
            ],
        )
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.submit_change_record(change=change)
        assert exc_info.value.code == "change_requires_justification"

    def test_submit_twice_rejected(self, draft_change):
        change_services.submit_change_record(change=draft_change)
        draft_change.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError):
            change_services.submit_change_record(change=draft_change)

    def test_post_submit_mutation_rejected(self, draft_change):
        from apps.changes.services import assert_change_request_mutable

        change_services.submit_change_record(change=draft_change)
        draft_change.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError):
            assert_change_request_mutable(draft_change)

    def test_post_submit_model_save_mutation_rejected(self, draft_change):
        change_services.submit_change_record(change=draft_change)
        draft_change.refresh_from_db()
        draft_change.requested_inputs = {"key": "changed"}
        with pytest.raises(ValidationError):
            draft_change.save()

    def test_post_submit_target_mutation_rejected(self, draft_change):
        change_services.submit_change_record(change=draft_change)
        target = draft_change.targets.first()
        target.display_name = "Changed"
        with pytest.raises(ValidationError):
            target.save()
        with pytest.raises(ValidationError):
            target.delete()

    def test_submit_emits_audit_events(self, draft_change):
        change = change_services.submit_change_record(change=draft_change)
        assert AuditEvent.objects.filter(
            event_type="change.submitted", object_id=change.id
        ).exists()
        assert AuditEvent.objects.filter(
            event_type="change.approval_bound", object_id=change.id
        ).exists()


@pytest.mark.django_db
class TestApprovalLifecycle:
    def test_approval_moves_change_to_approved(self, draft_change):
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.PENDING_APPROVAL
        ar = change.approval_request

        from apps.approvals import services as approval_services
        from apps.audit.services import AuditActor, AuditEvent

        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        approval_services.decide_approval(
            approval_request=ar,
            decision="approved",
            actor=actor,
        )
        change.refresh_from_db()
        assert change.status in (
            ChangeRecord.Status.APPROVED,
            ChangeRecord.Status.DISPATCHABLE,
        )

    def test_rejection_moves_change_to_rejected(self, draft_change):
        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request
        from apps.approvals import services as approval_services
        from apps.audit.services import AuditActor, AuditEvent

        actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
        approval_services.decide_approval(
            approval_request=ar,
            decision="rejected",
            actor=actor,
        )
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.REJECTED
        assert change.terminal_reason == "approval_rejected"


@pytest.mark.django_db
class TestDispatchableAndBinding:
    def test_make_dispatchable_creates_binding_and_execution(
        self, draft_change, operation_profile
    ):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()

        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)
            change.refresh_from_db()

        assert change.status == ChangeRecord.Status.DISPATCHABLE
        assert hasattr(change, "execution_binding")
        assert change.execution_binding is not None

    def test_dispatch_token_not_stored_in_cleartext(
        self, draft_change, operation_profile
    ):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()
        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)
            change.refresh_from_db()

        binding = change.execution_binding
        clear_token = change_services.generate_dispatch_token(binding)
        assert binding.dispatch_token_hash != clear_token

    def test_verify_dispatch_token(self, draft_change, operation_profile):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()
        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)
            change.refresh_from_db()

        binding = change.execution_binding
        clear_token = change_services.generate_dispatch_token(binding)
        assert change_services.verify_dispatch_token(binding, clear_token) is True
        assert change_services.verify_dispatch_token(binding, "wrong_token") is False

    def test_schedule_or_make_dispatchable_rejects_draft(self, draft_change):
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.schedule_or_make_dispatchable(change=draft_change)
        assert exc_info.value.code == "invalid_state_transition"

    def test_direct_execution_bypass_ignores_cross_org_corrupt_profile(
        self, org, operation_profile, published_workflow
    ):
        from apps.changes.models import OperationProfile
        from apps.executions import services as execution_services
        from apps.organizations.models import Organization

        operation_profile.allowed_workflows.clear()
        other_org = Organization.objects.create(name="Other", slug="other")
        other_profile = OperationProfile.objects.create(
            organization=other_org,
            key="other-prod",
            name="Other Prod",
            risk_level="high",
            allowed_target_types=["server"],
        )
        through = OperationProfile.allowed_workflows.through
        through.objects.create(
            operationprofile=other_profile,
            workflow=published_workflow,
        )

        execution = execution_services.create_execution(workflow=published_workflow)
        assert execution.workflow_id == published_workflow.id

    def test_direct_execution_bypass_rejects_same_org_profile(
        self, operation_profile, published_workflow
    ):
        from apps.executions import services as execution_services

        with pytest.raises(DomainConflictError) as exc_info:
            execution_services.create_execution(workflow=published_workflow)
        assert exc_info.value.code == "workflow_requires_change_record"

    def test_operation_profile_m2m_rejects_cross_org_workflow(
        self, operation_profile, published_workflow
    ):
        from apps.organizations.models import Organization

        operation_profile.allowed_workflows.clear()
        other_org = Organization.objects.create(name="Other", slug="other")
        operation_profile.organization = other_org
        operation_profile.save()

        with pytest.raises(ValidationError):
            operation_profile.allowed_workflows.add(published_workflow)
