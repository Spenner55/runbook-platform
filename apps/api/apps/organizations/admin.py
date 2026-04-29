from django.contrib import admin

from .models import Membership, Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "created_at", "updated_at")
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "user", "role", "created_at", "updated_at")
    list_filter = ("role", "organization")
    search_fields = ("organization__name", "organization__slug", "user__email")
    ordering = ("organization__name", "user__email")
    raw_id_fields = ("organization", "user")
