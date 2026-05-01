from django.contrib import admin

from apps.changes.models import (
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    OperationProfile,
)


@admin.register(OperationProfile)
class OperationProfileAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "organization", "risk_level", "is_active"]
    list_filter = ["is_active", "risk_level"]
    search_fields = ["key", "name"]
    filter_horizontal = ["allowed_workflows"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(ChangeRecord)
class ChangeRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "status", "organization", "operation_profile", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "id"]
    readonly_fields = [
        "id",
        "requested_inputs_sha256",
        "request_snapshot",
        "request_snapshot_sha256",
        "operation_profile_key_snapshot",
        "workflow_version_snapshot",
        "submitted_at",
        "approved_at",
        "dispatchable_at",
        "running_at",
        "verification_pending_at",
        "closed_at",
        "rejected_at",
        "canceled_at",
        "expired_at",
        "created_at",
        "updated_at",
    ]


@admin.register(ChangeTarget)
class ChangeTargetAdmin(admin.ModelAdmin):
    list_display = ["change_record", "target_type", "target_identifier", "environment"]
    readonly_fields = ["id", "created_at", "updated_at", "normalized_identifier"]


@admin.register(ChangeExecutionBinding)
class ChangeExecutionBindingAdmin(admin.ModelAdmin):
    list_display = ["id", "change_record", "execution", "reserved_at", "bound_at"]
    readonly_fields = [
        "id",
        "dispatch_token_nonce",
        "dispatch_token_hash",
        "dispatch_token_expires_at",
        "reserved_at",
        "bound_at",
        "runner_payload_snapshot",
        "created_at",
        "updated_at",
    ]
