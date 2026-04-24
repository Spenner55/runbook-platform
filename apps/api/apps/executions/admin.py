from django.contrib import admin

from .models import Execution, ExecutionStep


class ExecutionStepInline(admin.TabularInline):
    model = ExecutionStep
    extra = 0
    fields = (
        "position",
        "step_key",
        "name",
        "step_type",
        "risk_level",
        "status",
        "started_at",
        "finished_at",
    )
    readonly_fields = (
        "position",
        "step_key",
        "name",
        "step_type",
        "risk_level",
        "status",
        "started_at",
        "finished_at",
    )
    can_delete = False
    show_change_link = True
    ordering = ("position",)


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "workflow",
        "organization",
        "workflow_version",
        "status",
        "started_at",
        "finished_at",
        "created_at",
    )
    list_filter = ("status", "organization", "created_at")
    search_fields = ("workflow__name", "workflow__runbook__title")
    list_select_related = ("workflow", "organization")
    inlines = (ExecutionStepInline,)


@admin.register(ExecutionStep)
class ExecutionStepAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "execution",
        "position",
        "step_key",
        "name",
        "step_type",
        "risk_level",
        "status",
        "started_at",
        "finished_at",
    )
    list_filter = ("status", "step_type", "risk_level")
    search_fields = ("name", "step_key", "execution__id")
    list_select_related = ("execution",)
