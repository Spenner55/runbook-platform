from django.contrib import admin, messages

from apps.audit.services import actor_from_request
from apps.changes import services as change_services
from apps.changes.models import (
    ChangeClosure,
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    ChangeWindow,
    DispatchEligibilityCheck,
    FreezeRule,
    OperationProfile,
    TargetLock,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
)


@admin.register(OperationProfile)
class OperationProfileAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "organization", "risk_level", "is_active"]
    list_filter = ["is_active", "risk_level"]
    search_fields = ["key", "name"]
    filter_horizontal = ["allowed_workflows"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def save_model(self, request, obj, form, change):
        actor = actor_from_request(request)
        obj._audit_actor = actor
        # Delegate to the audited service when deactivating so the deactivated
        # event is emitted with the right event type (not just "updated").
        if change and "is_active" in form.changed_data and not obj.is_active:
            change_services.deactivate_operation_profile(profile=obj, actor=actor)
        else:
            super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        # Set _audit_actor so M2M post_add signals carry the admin user as actor.
        form.instance._audit_actor = actor_from_request(request)
        super().save_related(request, form, formsets, change)
        # Defense-in-depth: remove any cross-org workflows that slipped through
        # (the pre_add M2M signal is the primary enforcement; this is a fallback).
        obj = form.instance
        cross_org = obj.allowed_workflows.exclude(organization=obj.organization)
        if cross_org.exists():
            cross_org_ids = list(cross_org.values_list("id", flat=True))
            for wf in cross_org:
                obj.allowed_workflows.remove(wf)
            self.message_user(
                request,
                f"Removed {len(cross_org_ids)} cross-organization workflow(s) from allowed_workflows.",
                level=messages.WARNING,
            )


_CHANGE_RECORD_ALWAYS_READONLY = [
    "id",
    "status",
    "approval_request",
    "policy_evaluation",
    "policy_decision_snapshot",
    "terminal_reason",
    "requested_inputs_sha256",
    "request_snapshot",
    "request_snapshot_sha256",
    "operation_profile_key_snapshot",
    "workflow_version_snapshot",
    "workflow_definition_sha256",
    "submitted_at",
    "approved_at",
    "dispatchable_at",
    "running_at",
    "verification_pending_at",
    "verification_failed_at",
    "closed_at",
    "rejected_at",
    "canceled_at",
    "expired_at",
    "created_at",
    "updated_at",
]

_CHANGE_RECORD_SUBMITTED_READONLY = [
    "operation_profile",
    "workflow",
    "title",
    "summary",
    "justification",
    "requested_inputs",
    "scheduled_for",
]


@admin.register(ChangeRecord)
class ChangeRecordAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "title",
        "status",
        "organization",
        "operation_profile",
        "created_at",
    ]
    list_filter = ["status"]
    search_fields = ["title", "id"]
    readonly_fields = _CHANGE_RECORD_ALWAYS_READONLY

    def get_readonly_fields(self, request, obj=None):
        fields = list(_CHANGE_RECORD_ALWAYS_READONLY)
        if obj is not None and obj.status != ChangeRecord.Status.DRAFT:
            fields.extend(_CHANGE_RECORD_SUBMITTED_READONLY)
        return fields


@admin.register(ChangeTarget)
class ChangeTargetAdmin(admin.ModelAdmin):
    list_display = ["change_record", "target_type", "target_identifier", "environment"]
    readonly_fields = ["id", "created_at", "updated_at", "normalized_identifier"]

    def _change_is_draft(self, obj) -> bool:
        return obj is not None and obj.change_record.status == ChangeRecord.Status.DRAFT

    def has_change_permission(self, request, obj=None):
        if obj is not None and not self._change_is_draft(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request, obj=None):
        # Targets are always created through the change service, never directly in admin.
        return False

    def has_delete_permission(self, request, obj=None):
        if obj is not None and not self._change_is_draft(obj):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(ChangeExecutionBinding)
class ChangeExecutionBindingAdmin(admin.ModelAdmin):
    list_display = ["id", "change_record", "execution", "reserved_at", "bound_at"]
    readonly_fields = [
        "id",
        "change_record",
        "execution",
        "organization",
        "operation_profile_key",
        "requested_inputs_sha256",
        "dispatch_token_nonce",
        "dispatch_token_hash",
        "dispatch_token_expires_at",
        "reserved_at",
        "bound_at",
        "bound_by_runner_id",
        "runner_payload_snapshot",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChangeWindow)
class ChangeWindowAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "change_record",
        "organization",
        "status",
        "starts_at",
        "ends_at",
    ]
    list_filter = ["status"]
    readonly_fields = [
        "id",
        "status",
        "approved_snapshot_sha256",
        "approved_at",
        "opened_at",
        "expired_at",
        "overrun_at",
        "closed_at",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FreezeRule)
class FreezeRuleAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "organization",
        "behavior",
        "scope_type",
        "is_active",
        "starts_at",
        "ends_at",
    ]
    list_filter = ["behavior", "scope_type", "is_active"]
    search_fields = ["name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(TargetLock)
class TargetLockAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "organization",
        "change_record",
        "target_type",
        "target_identifier",
        "status",
        "acquired_at",
    ]
    list_filter = ["status"]
    readonly_fields = [
        "id",
        "organization",
        "change_record",
        "execution",
        "change_target",
        "target_type",
        "target_identifier",
        "normalized_identifier",
        "status",
        "acquired_at",
        "released_at",
        "expires_at",
        "release_reason",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DispatchEligibilityCheck)
class DispatchEligibilityCheckAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "organization",
        "change_record",
        "result",
        "checked_at",
        "expires_at",
    ]
    list_filter = ["result"]
    readonly_fields = [
        "id",
        "organization",
        "change_record",
        "requested_by",
        "result",
        "checked_at",
        "expires_at",
        "approved_status_ok",
        "policy_pass_ok",
        "window_open_ok",
        "freeze_conflicts_ok",
        "target_locks_ok",
        "actor_authorized_ok",
        "checks",
        "conflicts",
        "input_snapshot_sha256",
        "window_snapshot_sha256",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VerificationPlan)
class VerificationPlanAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "change_record",
        "organization",
        "operation_profile",
        "mode",
        "status",
        "generated_at",
    ]
    list_filter = ["mode", "status"]
    search_fields = ["id", "change_record__id", "operation_profile__key"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(VerificationCheck)
class VerificationCheckAdmin(admin.ModelAdmin):
    list_display = [
        "key",
        "plan",
        "change_record",
        "check_type",
        "required",
        "status",
    ]
    list_filter = ["check_type", "required", "status"]
    search_fields = ["key", "name", "change_record__id"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(VerificationResult)
class VerificationResultAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "change_record",
        "verification_check",
        "source",
        "outcome",
        "validation_status",
        "submitted_at",
    ]
    list_filter = ["source", "outcome", "validation_status"]
    search_fields = ["id", "change_record__id", "verification_check__key", "runner_id"]
    readonly_fields = [
        "id",
        "organization",
        "change_record",
        "plan",
        "verification_check",
        "source",
        "outcome",
        "validation_status",
        "submitted_by",
        "runner_id",
        "verification_key",
        "artifact",
        "artifact_checksum_sha256",
        "external_reference",
        "api_assertion_snapshot",
        "manual_attestation_text",
        "observed_value",
        "validation_errors",
        "submitted_at",
        "validated_at",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChangeClosure)
class ChangeClosureAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "change_record",
        "organization",
        "outcome",
        "closed_by",
        "independent_reviewer",
        "closed_at",
    ]
    list_filter = ["outcome"]
    search_fields = ["id", "change_record__id", "summary"]
    readonly_fields = [
        "id",
        "organization",
        "change_record",
        "outcome",
        "closed_by",
        "independent_reviewer",
        "summary",
        "verification_plan",
        "verification_summary",
        "execution_summary",
        "closed_at",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
