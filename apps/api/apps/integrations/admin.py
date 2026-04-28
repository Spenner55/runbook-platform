from django.contrib import admin

from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "name",
        "organization",
        "type",
        "is_active",
        "credentials_configured",
        "last_delivery_status",
        "last_delivery_at",
        "created_at",
    ]
    list_filter = ["type", "is_active", "last_delivery_status"]
    search_fields = ["id", "name", "organization__name", "organization__slug"]
    readonly_fields = [
        "id",
        "credentials_configured",
        "last_delivery_at",
        "last_delivery_status",
        "created_at",
        "updated_at",
    ]
    exclude = ["encrypted_credentials"]

    @admin.display(boolean=True)
    def credentials_configured(self, obj):
        return bool(obj.encrypted_credentials)


@admin.register(IntegrationDeliveryAttempt)
class IntegrationDeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "integration",
        "organization",
        "event_type",
        "success",
        "http_status",
        "latency_ms",
        "attempted_at",
    ]
    list_filter = ["success", "event_type", "http_status"]
    search_fields = ["id", "integration__name", "organization__name"]
    readonly_fields = [
        "id",
        "integration",
        "organization",
        "event_type",
        "payload_preview",
        "http_status",
        "success",
        "error_detail",
        "latency_ms",
        "attempted_at",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
