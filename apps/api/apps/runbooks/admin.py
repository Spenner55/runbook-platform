from django.contrib import admin

from .models import Runbook


@admin.register(Runbook)
class RunbookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "slug", "organization", "status", "created_at", "updated_at")
    list_filter = ("status", "organization", "created_at")
    search_fields = ("title", "slug")
    list_select_related = ("organization",)
    ordering = ("title",)
