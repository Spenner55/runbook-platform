from django.contrib import admin
from django.core.exceptions import PermissionDenied

from apps.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "event_type",
        "object_type",
        "object_id",
        "actor_type",
        "actor_label",
        "organization_id",
        "occurred_at",
    )
    list_filter = ("actor_type", "event_type", "object_type")
    search_fields = ("event_type", "actor_id", "actor_label", "object_id")
    ordering = ("-occurred_at",)

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionDenied("Audit events are read-only.")
