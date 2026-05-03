"""Tests for C2: Submitted change immutability and request integrity verification."""

import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord, ChangeTarget
from apps.common.exceptions import InvalidStateTransitionError


def _sys_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _submit(change, operation_profile=None):
    """Submit a draft change; assumes approval is not required."""
    if operation_profile is not None:
        operation_profile.requires_approval = False
        operation_profile.save()
    return change_services.submit_change_record(change=change)


@pytest.fixture
def submitted_change(draft_change, operation_profile):
    """A change that has been submitted (no approval required for simplicity)."""
    operation_profile.requires_approval = False
    operation_profile.save()
    return change_services.submit_change_record(change=draft_change)


# ---------------------------------------------------------------------------
# Model-level immutability: ChangeRecord fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangeRecordModelImmutability:
    """Direct .save() calls on submitted ChangeRecord request fields must raise."""

    def _assert_immutable(self, change, **kwargs):
        for attr, value in kwargs.items():
            setattr(change, attr, value)
        with pytest.raises(ValidationError) as exc_info:
            change.save()
        assert exc_info.value.code == "change_request_immutable"

    def test_title_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, title="New Title")

    def test_summary_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, summary="New summary")

    def test_justification_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, justification="New justification")

    def test_requested_inputs_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, requested_inputs={"new": "value"})

    def test_scheduled_for_immutable_after_submit(self, submitted_change):
        from django.utils import timezone

        self._assert_immutable(
            submitted_change, scheduled_for=timezone.now() + timezone.timedelta(days=1)
        )

    def test_operation_profile_immutable_after_submit(
        self, submitted_change, org, published_workflow
    ):
        from apps.changes.models import OperationProfile

        other_profile = OperationProfile.objects.create(
            organization=org,
            key="other-profile",
            name="Other",
            risk_level="high",
        )
        other_profile.allowed_workflows.add(published_workflow)
        self._assert_immutable(submitted_change, operation_profile=other_profile)

    def test_workflow_immutable_after_submit(self, submitted_change, runbook):
        from apps.workflows import services as workflow_services
        from apps.workflows.internal_clients import StubWorkflowTransformClient

        other_wf = workflow_services.publish_workflow(
            workflow=workflow_services.create_workflow(
                runbook=runbook, transform_client=StubWorkflowTransformClient()
            )
        )
        self._assert_immutable(submitted_change, workflow=other_wf)

    def test_requested_inputs_sha256_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, requested_inputs_sha256="deadbeef" * 8)

    def test_request_snapshot_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, request_snapshot={"tampered": "value"})

    def test_request_snapshot_sha256_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, request_snapshot_sha256="cafebabe" * 8)

    def test_operation_profile_key_snapshot_immutable_after_submit(
        self, submitted_change
    ):
        self._assert_immutable(
            submitted_change, operation_profile_key_snapshot="different-key"
        )

    def test_workflow_version_snapshot_immutable_after_submit(self, submitted_change):
        self._assert_immutable(submitted_change, workflow_version_snapshot=99)

    def test_draft_change_fields_are_mutable(self, draft_change):
        """Sanity check: fields on a draft should still be editable."""
        draft_change.title = "Updated Title"
        draft_change.save(update_fields=["title", "updated_at"])
        draft_change.refresh_from_db()
        assert draft_change.title == "Updated Title"


# ---------------------------------------------------------------------------
# Model-level immutability: ChangeTarget rows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChangeTargetModelImmutability:
    def test_update_submitted_target_raises(self, submitted_change):
        target = submitted_change.targets.first()
        target.display_name = "Hacked"
        with pytest.raises(ValidationError) as exc_info:
            target.save()
        assert exc_info.value.code == "change_request_immutable"

    def test_delete_submitted_target_raises(self, submitted_change):
        target = submitted_change.targets.first()
        with pytest.raises(ValidationError) as exc_info:
            target.delete()
        assert exc_info.value.code == "change_request_immutable"

    def test_add_target_to_submitted_change_raises(self, submitted_change):
        with pytest.raises(ValidationError) as exc_info:
            ChangeTarget.objects.create(
                change_record=submitted_change,
                organization=submitted_change.organization,
                position=99,
                target_type="server",
                target_identifier="new-server",
                normalized_identifier="new-server",
                environment="production",
            )
        assert exc_info.value.code == "change_request_immutable"

    def test_draft_target_is_mutable(self, draft_change):
        target = draft_change.targets.first()
        target.display_name = "OK"
        target.save()  # should not raise


# ---------------------------------------------------------------------------
# Service-level immutability: assert_change_request_mutable()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssertChangeRequestMutable:
    def test_raises_for_non_draft(self, submitted_change):
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.assert_change_request_mutable(submitted_change)
        assert exc_info.value.code == "change_request_immutable"

    def test_passes_for_draft(self, draft_change):
        change_services.assert_change_request_mutable(draft_change)  # no raise


# ---------------------------------------------------------------------------
# Admin immutability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAdminImmutability:
    def test_change_record_admin_get_readonly_fields_submitted(
        self, submitted_change, rf
    ):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import (
            _CHANGE_RECORD_SUBMITTED_READONLY,
            ChangeRecordAdmin,
        )

        admin = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        request.user = None
        fields = admin.get_readonly_fields(request, obj=submitted_change)
        for field in _CHANGE_RECORD_SUBMITTED_READONLY:
            assert field in fields, f"Expected {field} in readonly_fields for submitted"

    def test_change_record_admin_get_readonly_fields_draft(self, draft_change, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import (
            _CHANGE_RECORD_SUBMITTED_READONLY,
            ChangeRecordAdmin,
        )

        admin = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        request.user = None
        fields = admin.get_readonly_fields(request, obj=draft_change)
        for field in _CHANGE_RECORD_SUBMITTED_READONLY:
            assert field not in fields, (
                f"Expected {field} to be editable for draft in admin"
            )

    def test_change_target_admin_add_always_blocked(self, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeTargetAdmin

        admin = ChangeTargetAdmin(ChangeTarget, AdminSite())
        request = rf.get("/")
        request.user = None
        assert not admin.has_add_permission(request)

    def test_change_target_admin_change_blocked_for_submitted(
        self, submitted_change, rf
    ):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeTargetAdmin

        target = submitted_change.targets.first()
        admin = ChangeTargetAdmin(ChangeTarget, AdminSite())
        request = rf.get("/")
        request.user = None
        assert not admin.has_change_permission(request, obj=target)

    def test_change_target_admin_delete_blocked_for_submitted(
        self, submitted_change, rf
    ):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeTargetAdmin

        target = submitted_change.targets.first()
        admin = ChangeTargetAdmin(ChangeTarget, AdminSite())
        request = rf.get("/")
        request.user = None
        assert not admin.has_delete_permission(request, obj=target)

    def test_change_target_admin_change_allowed_for_draft(self, draft_change, rf):
        from unittest.mock import MagicMock

        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeTargetAdmin

        target = draft_change.targets.first()
        admin = ChangeTargetAdmin(ChangeTarget, AdminSite())
        request = rf.get("/")
        request.user = MagicMock()
        request.user.has_perm.return_value = True
        # Draft targets: block is not applied, so super() is called and perm check passes.
        assert admin.has_change_permission(request, obj=target)

    def test_change_record_approval_fields_always_readonly(self, submitted_change, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeRecordAdmin

        admin_instance = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        request.user = None
        fields = admin_instance.get_readonly_fields(request, obj=submitted_change)
        for field in ("approval_request", "policy_evaluation", "policy_decision_snapshot", "terminal_reason"):
            assert field in fields, f"Expected {field} in always-readonly fields"

    def test_change_record_approval_fields_readonly_even_for_draft(self, draft_change, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeRecordAdmin

        admin_instance = ChangeRecordAdmin(ChangeRecord, AdminSite())
        request = rf.get("/")
        request.user = None
        fields = admin_instance.get_readonly_fields(request, obj=draft_change)
        for field in ("approval_request", "policy_evaluation", "policy_decision_snapshot", "terminal_reason"):
            assert field in fields, f"Expected {field} in always-readonly even for draft"

    def test_change_execution_binding_admin_blocks_add(self, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeExecutionBindingAdmin
        from apps.changes.models import ChangeExecutionBinding

        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        request = rf.get("/")
        request.user = None
        assert not admin_instance.has_add_permission(request)

    def test_change_execution_binding_admin_blocks_change(self, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeExecutionBindingAdmin
        from apps.changes.models import ChangeExecutionBinding

        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        request = rf.get("/")
        request.user = None
        assert not admin_instance.has_change_permission(request)

    def test_change_execution_binding_admin_blocks_delete(self, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeExecutionBindingAdmin
        from apps.changes.models import ChangeExecutionBinding

        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        request = rf.get("/")
        request.user = None
        assert not admin_instance.has_delete_permission(request)

    def test_change_execution_binding_identity_fields_all_readonly(self, rf):
        from django.contrib.admin.sites import AdminSite

        from apps.changes.admin import ChangeExecutionBindingAdmin
        from apps.changes.models import ChangeExecutionBinding

        admin_instance = ChangeExecutionBindingAdmin(ChangeExecutionBinding, AdminSite())
        for field in ("change_record", "execution", "organization", "operation_profile_key",
                      "requested_inputs_sha256", "bound_by_runner_id"):
            assert field in admin_instance.readonly_fields, (
                f"Expected {field} in ChangeExecutionBindingAdmin.readonly_fields"
            )


@pytest.mark.django_db
class TestBindingModelImmutability:
    def _make_dispatchable(self, org, operation_profile, published_workflow):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Binding Immutability Test",
            justification="Needed",
            targets=[{"target_type": "server", "target_identifier": "prod-bind-01", "environment": "production"}],
        )
        return change_services.submit_change_record(change=change)

    def test_identity_field_immutable_after_creation(self, org, operation_profile, published_workflow):
        from django.core.exceptions import ValidationError

        change = self._make_dispatchable(org, operation_profile, published_workflow)
        binding = change.execution_binding
        original = binding.operation_profile_key
        binding.operation_profile_key = "tampered-key"
        with pytest.raises(ValidationError, match="immutable after creation"):
            binding.save()
        binding.refresh_from_db()
        assert binding.operation_profile_key == original

    def test_non_identity_field_can_update(self, org, operation_profile, published_workflow):
        change = self._make_dispatchable(org, operation_profile, published_workflow)
        binding = change.execution_binding
        # runner_payload_snapshot is not an identity field — it may be updated
        binding.runner_payload_snapshot = {"note": "test update"}
        binding.save(update_fields=["runner_payload_snapshot", "updated_at"])
        binding.refresh_from_db()
        assert binding.runner_payload_snapshot == {"note": "test update"}


# ---------------------------------------------------------------------------
# build_request_snapshot completeness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestSnapshotCompleteness:
    def test_snapshot_includes_title(self, submitted_change):
        assert submitted_change.request_snapshot["title"] == submitted_change.title

    def test_snapshot_includes_summary(self, submitted_change):
        assert submitted_change.request_snapshot["summary"] == submitted_change.summary

    def test_snapshot_includes_justification(self, submitted_change):
        assert (
            submitted_change.request_snapshot["justification"]
            == submitted_change.justification
        )

    def test_snapshot_includes_scheduled_for(
        self, org, operation_profile, published_workflow
    ):
        from django.utils import timezone

        operation_profile.requires_approval = False
        operation_profile.save()
        scheduled = timezone.now() + timezone.timedelta(hours=2)
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Scheduled Change",
            justification="Needed",
            scheduled_for=scheduled,
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-01",
                    "environment": "production",
                }
            ],
        )
        submitted = change_services.submit_change_record(change=change)
        assert submitted.request_snapshot["scheduled_for"] == scheduled.isoformat()

    def test_snapshot_includes_targets(self, submitted_change):
        targets = submitted_change.request_snapshot["targets"]
        assert len(targets) >= 1
        first = targets[0]
        assert "target_type" in first
        assert "target_identifier" in first
        assert "environment" in first
        assert first["environment"] == "production"

    def test_snapshot_includes_target_metadata(
        self, org, operation_profile, published_workflow
    ):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Meta Change",
            justification="Needed",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "srv",
                    "environment": "production",
                    "metadata": {"region": "eu-west-1", "role": "primary"},
                }
            ],
        )
        submitted = change_services.submit_change_record(change=change)
        target_in_snapshot = submitted.request_snapshot["targets"][0]
        assert target_in_snapshot["metadata"] == {
            "region": "eu-west-1",
            "role": "primary",
        }

    def test_snapshot_includes_operation_profile_snapshot(
        self, submitted_change, operation_profile
    ):
        snap = submitted_change.request_snapshot
        assert "operation_profile_snapshot" in snap
        op_snap = snap["operation_profile_snapshot"]
        assert op_snap["key"] == operation_profile.key
        assert op_snap["name"] == operation_profile.name
        assert op_snap["risk_level"] == operation_profile.risk_level
        assert op_snap["requires_approval"] == operation_profile.requires_approval
        assert (
            op_snap["verification_required"] == operation_profile.verification_required
        )

    def test_snapshot_includes_workflow_snapshot(
        self, submitted_change, published_workflow
    ):
        snap = submitted_change.request_snapshot
        assert "workflow_snapshot" in snap
        wf_snap = snap["workflow_snapshot"]
        assert wf_snap["id"] == str(published_workflow.id)
        assert wf_snap["name"] == published_workflow.name
        assert wf_snap["version"] == published_workflow.version
        assert wf_snap["status"] == published_workflow.status

    def test_snapshot_includes_workflow_definition_sha256(
        self, submitted_change, published_workflow
    ):
        wf_snap = submitted_change.request_snapshot["workflow_snapshot"]
        assert "definition_sha256" in wf_snap
        assert len(wf_snap["definition_sha256"]) == 64

    def test_workflow_definition_sha256_field_set_on_submit(self, submitted_change):
        assert submitted_change.workflow_definition_sha256 != ""
        assert len(submitted_change.workflow_definition_sha256) == 64

    def test_integrity_fails_when_workflow_definition_mutated(
        self, submitted_change, published_workflow
    ):
        published_workflow.definition = {"steps": [{"id": "injected", "name": "bad"}]}
        published_workflow.save(update_fields=["definition", "updated_at"])

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_snapshot_includes_requested_input_keys(self, submitted_change):
        keys = submitted_change.request_snapshot["requested_input_keys"]
        expected = sorted(submitted_change.requested_inputs.keys())
        assert keys == expected

    def test_snapshot_documents_inputs_as_redacted(self, submitted_change):
        rep = submitted_change.request_snapshot.get("requested_inputs_representation")
        assert rep == "sha256_and_keys_only"

    def test_snapshot_hash_is_stable(self, submitted_change):
        h1 = change_services.sha256_canonical_json(submitted_change.request_snapshot)
        h2 = change_services.sha256_canonical_json(submitted_change.request_snapshot)
        assert h1 == h2
        assert h1 == submitted_change.request_snapshot_sha256


# ---------------------------------------------------------------------------
# validate_request_integrity: pass and fail cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestValidateRequestIntegrity:
    def test_passes_for_valid_submitted_change(self, submitted_change):
        change_services.validate_request_integrity(submitted_change)

    def test_skips_for_draft(self, draft_change):
        change_services.validate_request_integrity(draft_change)  # must not raise

    def test_fails_when_requested_inputs_mutated(self, submitted_change):
        # Bypass model protection by using update() (direct ORM path)
        ChangeRecord.objects.filter(pk=submitted_change.pk).update(
            requested_inputs={"tampered": "value"}
        )
        submitted_change.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_fails_when_request_snapshot_mutated(self, submitted_change):
        ChangeRecord.objects.filter(pk=submitted_change.pk).update(
            request_snapshot={"tampered": "snapshot"}
        )
        submitted_change.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_fails_when_hashes_missing(self, submitted_change):
        ChangeRecord.objects.filter(pk=submitted_change.pk).update(
            requested_inputs_sha256="",
            request_snapshot_sha256="",
        )
        submitted_change.refresh_from_db()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_missing"

    def _assert_bulk_update_detected(self, change, **updates):
        ChangeRecord.objects.filter(pk=change.pk).update(**updates)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_fails_when_title_bulk_updated(self, submitted_change):
        self._assert_bulk_update_detected(submitted_change, title="Tampered title")

    def test_fails_when_summary_bulk_updated(self, submitted_change):
        self._assert_bulk_update_detected(submitted_change, summary="Tampered summary")

    def test_fails_when_justification_bulk_updated(self, submitted_change):
        self._assert_bulk_update_detected(
            submitted_change, justification="Tampered justification"
        )

    def test_fails_when_scheduled_for_bulk_updated(self, submitted_change):
        from django.utils import timezone

        self._assert_bulk_update_detected(
            submitted_change,
            scheduled_for=timezone.now() + timezone.timedelta(days=1),
        )

    def test_fails_when_operation_profile_bulk_updated(
        self, submitted_change, org, published_workflow
    ):
        from apps.changes.models import OperationProfile

        other_profile = OperationProfile.objects.create(
            organization=org,
            key="bulk-profile",
            name="Bulk Profile",
            risk_level="high",
            requires_approval=False,
            verification_required=True,
            allowed_target_types=["server"],
        )
        other_profile.allowed_workflows.add(published_workflow)

        self._assert_bulk_update_detected(
            submitted_change,
            operation_profile_id=other_profile.id,
        )

    def test_fails_when_workflow_bulk_updated(self, submitted_change, runbook):
        from apps.workflows import services as workflow_services
        from apps.workflows.internal_clients import StubWorkflowTransformClient

        other_workflow = workflow_services.publish_workflow(
            workflow=workflow_services.create_workflow(
                runbook=runbook,
                transform_client=StubWorkflowTransformClient(),
            )
        )

        self._assert_bulk_update_detected(
            submitted_change,
            workflow_id=other_workflow.id,
        )

    def test_fails_when_operation_profile_key_snapshot_bulk_updated(
        self, submitted_change
    ):
        self._assert_bulk_update_detected(
            submitted_change,
            operation_profile_key_snapshot="",
        )

    def test_fails_when_workflow_version_snapshot_bulk_updated(self, submitted_change):
        self._assert_bulk_update_detected(
            submitted_change,
            workflow_version_snapshot=None,
        )

    def test_fails_when_target_bulk_updated(self, submitted_change):
        ChangeTarget.objects.filter(change_record=submitted_change).update(
            display_name="Tampered target"
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_fails_when_target_bulk_created(self, submitted_change):
        ChangeTarget.objects.bulk_create(
            [
                ChangeTarget(
                    change_record=submitted_change,
                    organization=submitted_change.organization,
                    position=99,
                    target_type="server",
                    target_identifier="prod-added",
                    normalized_identifier="prod-added",
                    display_name="Added",
                    environment="production",
                    metadata={},
                )
            ]
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_fails_when_target_bulk_deleted(self, submitted_change):
        ChangeTarget.objects.filter(change_record=submitted_change).delete()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.validate_request_integrity(submitted_change)
        assert exc_info.value.code == "change_request_integrity_mismatch"


# ---------------------------------------------------------------------------
# Dispatch (make_dispatchable) refuses when integrity fails
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDispatchIntegrityCheck:
    def _make_approved_change(self, org, operation_profile, published_workflow, ident):
        """Create a change that ends up in 'approved' status (not yet dispatched).

        Uses scheduled_for in the future so submit goes draft→approved→scheduled,
        then we force the change back to 'approved' via ORM to allow make_dispatchable
        to attempt dispatch, giving us a window to tamper before the integrity check.
        """
        from django.utils import timezone

        operation_profile.requires_approval = False
        operation_profile.save()
        future = timezone.now() + timezone.timedelta(hours=2)
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title=f"Dispatch Test {ident}",
            justification="Needed",
            scheduled_for=future,
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": ident,
                    "environment": "production",
                }
            ],
        )
        change = change_services.submit_change_record(change=change)
        # After submit with scheduled_for in the future the change is 'scheduled'.
        # Force to 'approved' via ORM so make_dispatchable accepts it.
        ChangeRecord.objects.filter(pk=change.pk).update(status="approved")
        change.refresh_from_db()
        return change

    def test_dispatch_refuses_when_inputs_tampered(
        self, org, operation_profile, published_workflow
    ):
        change = self._make_approved_change(
            org, operation_profile, published_workflow, "prod-disp-01"
        )
        # Tamper via direct ORM (bypasses model.save() guard)
        ChangeRecord.objects.filter(pk=change.pk).update(
            requested_inputs={"tampered": "value"}
        )
        change.refresh_from_db()

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.make_dispatchable(change=change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_dispatch_refuses_when_snapshot_tampered(
        self, org, operation_profile, published_workflow
    ):
        change = self._make_approved_change(
            org, operation_profile, published_workflow, "prod-disp-02"
        )
        ChangeRecord.objects.filter(pk=change.pk).update(
            request_snapshot={"tampered": "snapshot"}
        )
        change.refresh_from_db()

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.make_dispatchable(change=change)
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_dispatch_refuses_when_live_title_tampered(
        self, org, operation_profile, published_workflow
    ):
        change = self._make_approved_change(
            org, operation_profile, published_workflow, "prod-disp-03"
        )
        ChangeRecord.objects.filter(pk=change.pk).update(title="Tampered dispatch")

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.make_dispatchable(change=change)
        assert exc_info.value.code == "change_request_integrity_mismatch"


# ---------------------------------------------------------------------------
# Bind refuses when frozen request integrity fails
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBindIntegrityCheck:
    def _make_dispatchable_change(self, org, operation_profile, published_workflow):
        """Submit without approval so the change ends up directly in 'dispatchable'."""
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.create_change_record(
            organization=org,
            operation_profile_key="prod-maintenance",
            workflow_id=str(published_workflow.id),
            title="Bind Test",
            justification="Needed",
            targets=[
                {
                    "target_type": "server",
                    "target_identifier": "prod-03",
                    "environment": "production",
                }
            ],
        )
        change = change_services.submit_change_record(change=change)
        # submit_change_record with requires_approval=False calls
        # schedule_or_make_dispatchable which leaves the change 'dispatchable'.
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.DISPATCHABLE
        return change

    def _claim_execution(self, change):

        binding = change.execution_binding
        execution = binding.execution
        execution.status = "claimed"
        execution.claimed_by_runner_id = "test-runner-1"
        import uuid

        execution.claim_token = uuid.uuid4()
        execution.save(
            update_fields=[
                "status",
                "claimed_by_runner_id",
                "claim_token",
                "updated_at",
            ]
        )
        return execution, str(execution.claim_token)

    def test_bind_refuses_when_requested_inputs_tampered(
        self, org, operation_profile, published_workflow
    ):
        change = self._make_dispatchable_change(
            org, operation_profile, published_workflow
        )
        binding = change.execution_binding
        execution, claim_token = self._claim_execution(change)

        # Tamper with requested_inputs via direct ORM
        ChangeRecord.objects.filter(pk=change.pk).update(
            requested_inputs={"tampered": "post-dispatch"}
        )

        clear_token = change_services.generate_dispatch_token(binding)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.bind_execution(
                change_id=str(change.id),
                runner_id="test-runner-1",
                claim_token=claim_token,
                execution_id=str(execution.id),
                dispatch_token=clear_token,
                requested_inputs_sha256=binding.requested_inputs_sha256,
                operation_profile_key=binding.operation_profile_key,
            )
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_bind_refuses_when_request_snapshot_tampered(
        self, org, operation_profile, published_workflow
    ):
        change = self._make_dispatchable_change(
            org, operation_profile, published_workflow
        )
        binding = change.execution_binding
        execution, claim_token = self._claim_execution(change)

        ChangeRecord.objects.filter(pk=change.pk).update(
            request_snapshot={"tampered": "snapshot-post-dispatch"}
        )

        clear_token = change_services.generate_dispatch_token(binding)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.bind_execution(
                change_id=str(change.id),
                runner_id="test-runner-1",
                claim_token=claim_token,
                execution_id=str(execution.id),
                dispatch_token=clear_token,
                requested_inputs_sha256=binding.requested_inputs_sha256,
                operation_profile_key=binding.operation_profile_key,
            )
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_bind_refuses_when_live_target_tampered(
        self, org, operation_profile, published_workflow
    ):
        change = self._make_dispatchable_change(
            org, operation_profile, published_workflow
        )
        binding = change.execution_binding
        execution, claim_token = self._claim_execution(change)

        ChangeTarget.objects.filter(change_record=change).update(
            display_name="Tampered bind target"
        )

        clear_token = change_services.generate_dispatch_token(binding)
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.bind_execution(
                change_id=str(change.id),
                runner_id="test-runner-1",
                claim_token=claim_token,
                execution_id=str(execution.id),
                dispatch_token=clear_token,
                requested_inputs_sha256=binding.requested_inputs_sha256,
                operation_profile_key=binding.operation_profile_key,
            )
        assert exc_info.value.code == "change_request_integrity_mismatch"

    def test_completion_refuses_when_live_target_tampered(
        self, org, operation_profile, published_workflow
    ):
        from apps.executions import services as execution_services
        from apps.executions.models import Execution

        change = self._make_dispatchable_change(
            org, operation_profile, published_workflow
        )
        binding = change.execution_binding
        execution, claim_token = self._claim_execution(change)

        clear_token = change_services.generate_dispatch_token(binding)
        change_services.bind_execution(
            change_id=str(change.id),
            runner_id="test-runner-1",
            claim_token=claim_token,
            execution_id=str(execution.id),
            dispatch_token=clear_token,
            requested_inputs_sha256=binding.requested_inputs_sha256,
            operation_profile_key=binding.operation_profile_key,
        )

        ChangeTarget.objects.filter(change_record=change).update(
            display_name="Tampered completion target"
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            execution_services.complete_execution(
                execution=execution,
                runner_id="test-runner-1",
                claim_token=claim_token,
                outcome=Execution.Status.SUCCEEDED,
            )
        assert exc_info.value.code == "change_request_integrity_mismatch"
        execution.refresh_from_db()
        assert execution.status == Execution.Status.CLAIMED


# ---------------------------------------------------------------------------
# Approval refuses when live request integrity fails
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApprovalIntegrityCheck:
    def test_approval_refuses_when_live_title_tampered(self, draft_change):
        from apps.approvals import services as approval_services
        from apps.approvals.models import ApprovalRequest

        change = change_services.submit_change_record(change=draft_change)
        assert change.status == ChangeRecord.Status.PENDING_APPROVAL

        ChangeRecord.objects.filter(pk=change.pk).update(title="Tampered approval")

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            approval_services.decide_approval(
                approval_request=change.approval_request,
                decision=ApprovalRequest.Status.APPROVED,
                actor=_sys_actor(),
            )

        assert exc_info.value.code == "change_request_integrity_mismatch"
        change.refresh_from_db()
        change.approval_request.refresh_from_db()
        assert change.status == ChangeRecord.Status.PENDING_APPROVAL
        assert change.approval_request.status == ApprovalRequest.Status.PENDING
