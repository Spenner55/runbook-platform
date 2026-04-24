from django.contrib import admin

from .models import Workflow


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
