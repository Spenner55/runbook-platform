from django.contrib import admin

from apps.runners.models import (
    ExecutionLease,
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
    TargetConnectivityRoute,
)


@admin.register(RunnerPool)
class RunnerPoolAdmin(admin.ModelAdmin):
    list_display = (
        "key",
        "name",
        "display_name",
        "organization",
        "environment",
        "status",
        "default_for_non_change_executions",
        "created_at",
    )
    list_filter = ("status", "environment", "default_for_non_change_executions")
    search_fields = ("key", "name", "display_name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Runner)
class RunnerAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "organization",
        "pool",
        "status",
        "hostname",
        "last_heartbeat_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("display_name", "hostname", "fingerprint_sha256")
    readonly_fields = ("id", "token_hash", "created_at", "updated_at")
    exclude = ("token_hash",)


@admin.register(RunnerRegistrationToken)
class RunnerRegistrationTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization",
        "pool",
        "expires_at",
        "used_count",
        "max_registrations",
        "revoked_at",
    )
    list_filter = ("pool",)
    readonly_fields = ("id", "token_hash", "created_at", "updated_at")
    exclude = ("token_hash",)


@admin.register(TargetConnectivityRoute)
class TargetConnectivityRouteAdmin(admin.ModelAdmin):
    list_display = (
        "target_type",
        "normalized_identifier_pattern",
        "pool",
        "organization",
        "environment",
        "priority",
        "is_active",
    )
    list_filter = ("is_active", "environment", "target_type")
    search_fields = ("target_type", "normalized_identifier_pattern")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ExecutionLease)
class ExecutionLeaseAdmin(admin.ModelAdmin):
    list_display = (
        "execution",
        "runner",
        "pool",
        "status",
        "claimed_at",
        "released_at",
    )
    list_filter = ("status",)
    readonly_fields = ("id", "created_at", "updated_at")
