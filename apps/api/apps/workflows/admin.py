from django.contrib import admin

from .models import Workflow

_WORKFLOW_ALWAYS_READONLY = ["id", "created_at", "updated_at", "version"]

_WORKFLOW_PUBLISHED_READONLY = [
    "definition",
    "name",
    "status",
    "runbook",
    "organization",
    "definition_schema_version",
]


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization",
        "runbook",
        "version",
        "status",
        "definition_schema_version",
        "created_at",
    )
    list_filter = ("status", "organization", "created_at")
    search_fields = ("name", "runbook__title", "runbook__slug")
    list_select_related = ("organization", "runbook")
    ordering = ("name", "-version")
    readonly_fields = _WORKFLOW_ALWAYS_READONLY

    def get_readonly_fields(self, request, obj=None):
        fields = list(_WORKFLOW_ALWAYS_READONLY)
        if obj is not None and obj.status in ("published", "superseded"):
            fields.extend(_WORKFLOW_PUBLISHED_READONLY)
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status in ("published", "superseded"):
            return False
        return super().has_delete_permission(request, obj)
