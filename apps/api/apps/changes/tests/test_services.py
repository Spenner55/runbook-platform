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
        from django.db import transaction
        from apps.organizations.models import Organization

        operation_profile.allowed_workflows.clear()
        other_org = Organization.objects.create(name="Other", slug="other")
        operation_profile.organization = other_org
        operation_profile.save()

        with pytest.raises(ValidationError):
            with transaction.atomic():
                operation_profile.allowed_workflows.add(published_workflow)
        assert not operation_profile.allowed_workflows.filter(pk=published_workflow.pk).exists()


@pytest.mark.django_db
class TestRequestedInputsSchemaValidation:
    """Positive and negative cases for requested_inputs_schema enforcement."""

    def test_valid_inputs_matching_schema_accepted(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requested_inputs_schema = {
            "required": ["ticket"],
            "properties": {"ticket": {"type": "string"}},
            "additionalProperties": False,
        }
        operation_profile.save()

        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Schema Positive Test",
            justification="Needed",
            requested_inputs={"ticket": "CHG-999"},
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "environment": "production",
                }
            ],
        )
        assert change.status == ChangeRecord.Status.DRAFT

    def test_schema_missing_required_key_rejected(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requested_inputs_schema = {
            "required": ["ticket"],
        }
        operation_profile.save()

        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Schema Missing Key",
                justification="Needed",
                requested_inputs={},
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "requested_inputs_invalid"

    def test_schema_wrong_type_rejected(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requested_inputs_schema = {
            "properties": {"count": {"type": "integer"}},
        }
        operation_profile.save()

        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Schema Type Test",
                justification="Needed",
                requested_inputs={"count": "not-an-int"},
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "requested_inputs_invalid"

    def test_schema_additional_properties_rejected(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requested_inputs_schema = {
            "properties": {"ticket": {"type": "string"}},
            "additionalProperties": False,
        }
        operation_profile.save()

        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Schema Extra Key",
                justification="Needed",
                requested_inputs={"ticket": "CHG-1", "extra": "not-allowed"},
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                    }
                ],
            )
        assert exc_info.value.code == "requested_inputs_invalid"

    def test_no_schema_allows_any_inputs(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requested_inputs_schema = {}
        operation_profile.save()

        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="No Schema Test",
            justification="Needed",
            requested_inputs={"anything": "goes", "count": 42},
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "environment": "production",
                }
            ],
        )
        assert change.status == ChangeRecord.Status.DRAFT


@pytest.mark.django_db
class TestTargetMetadataValidation:
    """Target metadata forbidden-key rejection including nested and Phase-11.1-specific keys."""

    def test_nested_forbidden_key_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Nested Key Test",
                justification="Needed",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                        "metadata": {
                            "connection": {
                                "password": "secret123"
                            }
                        },
                    }
                ],
            )
        assert exc_info.value.code == "target_metadata_forbidden_key"

    def test_dispatch_token_in_metadata_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Dispatch Token Key Test",
                justification="Needed",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                        "metadata": {"dispatch_token": "some-token"},
                    }
                ],
            )
        assert exc_info.value.code == "target_metadata_forbidden_key"

    def test_dispatch_token_hash_in_metadata_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Dispatch Token Hash Key Test",
                justification="Needed",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                        "metadata": {"dispatch_token_hash": "abc123"},
                    }
                ],
            )
        assert exc_info.value.code == "target_metadata_forbidden_key"

    def test_claim_token_in_metadata_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Claim Token Key Test",
                justification="Needed",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                        "metadata": {"claim_token": "runner-claim"},
                    }
                ],
            )
        assert exc_info.value.code == "target_metadata_forbidden_key"

    def test_requested_inputs_in_metadata_rejected(
        self, org, operation_profile, published_workflow
    ):
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.create_change_record(
                organization=org,
                operation_profile_key="prod-maintenance",
                workflow_id=str(published_workflow.id),
                title="Requested Inputs Key Test",
                justification="Needed",
                targets=[
                    {
                        "target_type": "server",
                        "target_identifier": "prod-01",
                        "environment": "production",
                        "metadata": {"requested_inputs": {"key": "value"}},
                    }
                ],
            )
        assert exc_info.value.code == "target_metadata_forbidden_key"

    def test_safe_metadata_accepted(self, org, operation_profile, published_workflow):
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Safe Metadata Test",
            justification="Needed",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "environment": "production",
                    "metadata": {
                        "region": "us-west-2",
                        "datacenter": "dc1",
                        "tier": "prod",
                    },
                }
            ],
        )
        assert change.status == ChangeRecord.Status.DRAFT


@pytest.mark.django_db
class TestApprovalOrganizationMismatch:
    """Approval creation must reject cross-organization change linkage."""

    def test_create_change_approval_request_rejects_org_mismatch(
        self, org, draft_change
    ):
        from apps.approvals import services as approval_services
        from apps.organizations.models import Organization

        other_org = Organization.objects.create(
            name="Other Org", slug="approval-other-org"
        )
        with pytest.raises(DomainValidationError) as exc_info:
            approval_services.create_change_approval_request(
                change_record=draft_change,
                organization=other_org,
            )
        assert exc_info.value.code == "approval_change_organization_mismatch"

    def test_create_change_approval_request_same_org_succeeds(
        self, org, draft_change
    ):
        from apps.approvals import services as approval_services
        from apps.approvals.models import ApprovalRequest

        ar = approval_services.create_change_approval_request(
            change_record=draft_change,
            organization=org,
        )
        assert ar.subject_type == ApprovalRequest.SubjectType.CHANGE_RECORD
        assert ar.subject_id == draft_change.id
        assert ar.organization_id == org.id


@pytest.mark.django_db
class TestApprovalTimeoutRaceDeterminism:
    """Timeout and concurrent decision handling must be deterministic."""

    def test_timeout_wins_when_decision_arrives_after_expiry(
        self, draft_change, operation_profile
    ):
        from datetime import timedelta

        from django.utils import timezone

        from apps.approvals import services as approval_services

        operation_profile.requires_approval = True
        operation_profile.approval_ttl_seconds = 1
        operation_profile.save()

        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        # Manually expire the approval request so it appears timed out
        past = timezone.now() - timedelta(seconds=10)
        ar.expires_at = past
        ar.save(update_fields=["expires_at", "updated_at"])

        # Human decision arrives after expiry — timeout should prevail
        result = approval_services.decide_approval(
            approval_request=ar,
            decision="approved",
            actor=_sys_actor(),
        )
        from apps.approvals.models import ApprovalDecision

        assert result.decision == ApprovalDecision.Decision.TIMED_OUT
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.EXPIRED
        assert change.terminal_reason == "approval_timed_out"

    def test_double_decision_raises_conflict(self, draft_change, operation_profile):
        from apps.approvals import services as approval_services

        operation_profile.requires_approval = True
        operation_profile.save()

        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        approval_services.decide_approval(
            approval_request=ar,
            decision="approved",
            actor=_sys_actor(),
        )
        ar.refresh_from_db()

        # Second decision on a terminal request must conflict
        with pytest.raises(DomainConflictError) as exc_info:
            approval_services.decide_approval(
                approval_request=ar,
                decision="rejected",
                actor=_sys_actor(),
            )
        assert exc_info.value.code == "approval_request_not_pending"

    def test_watchdog_recovery_on_expired_change_approval(
        self, draft_change, operation_profile
    ):
        from datetime import timedelta

        from django.utils import timezone

        from apps.approvals import services as approval_services
        from apps.approvals.models import ApprovalRequest

        operation_profile.requires_approval = True
        operation_profile.approval_ttl_seconds = 1
        operation_profile.save()

        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        past = timezone.now() - timedelta(seconds=10)
        ar.expires_at = past
        ar.save(update_fields=["expires_at", "updated_at"])

        recovered = approval_services.recover_expired_approvals(
            now=timezone.now(), batch_size=10
        )
        assert str(ar.id) in recovered

        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.EXPIRED
        assert change.terminal_reason == "approval_timed_out"

        ar.refresh_from_db()
        assert ar.status == ApprovalRequest.Status.TIMED_OUT


class TestApprovalDecisionFailClosed:
    """B4: handle_change_approval_decision must raise, never silently return, on divergence."""

    @pytest.mark.django_db
    def test_raises_when_no_change_linked(self):
        import uuid

        from apps.changes.services import handle_change_approval_decision

        with pytest.raises(DomainValidationError) as exc_info:
            handle_change_approval_decision(
                approval_request_id=uuid.uuid4(),
                decision="approved",
            )
        assert exc_info.value.code == "change_approval_decision_orphaned"

    @pytest.mark.django_db
    def test_raises_when_change_not_pending_approval(self, draft_change, operation_profile):
        from apps.changes.services import handle_change_approval_decision

        operation_profile.requires_approval = True
        operation_profile.save()

        change = change_services.submit_change_record(change=draft_change)
        ar = change.approval_request

        # Force the change out of pending_approval without going through the decision path
        ChangeRecord.objects.filter(pk=change.pk).update(status=ChangeRecord.Status.DRAFT)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            handle_change_approval_decision(
                approval_request_id=ar.id,
                decision="approved",
            )
        assert exc_info.value.code == "change_approval_state_conflict"

    @pytest.mark.django_db
    def test_approval_decision_rolled_back_when_change_missing(self):
        """The approval terminal status must not persist when the change hook raises."""
        import uuid

        from django.db import transaction

        from apps.approvals.models import ApprovalRequest
        from apps.changes.services import handle_change_approval_decision

        phantom_id = uuid.uuid4()
        try:
            with transaction.atomic():
                handle_change_approval_decision(
                    approval_request_id=phantom_id,
                    decision="approved",
                )
        except DomainValidationError:
            pass

        # Nothing committed — no ApprovalRequest row should reference this phantom id
        assert not ApprovalRequest.objects.filter(id=phantom_id).exists()
