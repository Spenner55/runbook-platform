from django.contrib import admin

from apps.auditor.models import (
    AuditorAccessGrant,
    ChangeControlCoverage,
    ControlMappingProfile,
    ExternalChangeReference,
    ServiceCatalogEntry,
)


@admin.register(ExternalChangeReference)
class ExternalChangeReferenceAdmin(admin.ModelAdmin):
    list_display = (
        "display_label",
        "organization",
        "change_record",
        "system",
        "reference_type",
        "snapshot_status",
        "created_at",
    )
    list_filter = ("system", "reference_type", "snapshot_status", "snapshot_source")
    search_fields = ("display_label", "external_id", "external_key")
    readonly_fields = ("snapshot_sha256", "created_at", "updated_at")


@admin.register(ServiceCatalogEntry)
class ServiceCatalogEntryAdmin(admin.ModelAdmin):
    list_display = ("service_key", "name", "organization", "criticality", "is_active")
    list_filter = ("criticality", "environment", "is_active")
    search_fields = ("service_key", "name", "owner_team", "business_owner")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ControlMappingProfile)
class ControlMappingProfileAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "organization", "standard", "version", "is_active")
    list_filter = ("standard", "is_active")
    search_fields = ("key", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ChangeControlCoverage)
class ChangeControlCoverageAdmin(admin.ModelAdmin):
    list_display = (
        "control_id",
        "organization",
        "change_record",
        "standard",
        "coverage_status",
        "computed_at",
    )
    list_filter = ("standard", "coverage_status")
    search_fields = ("control_id", "control_title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AuditorAccessGrant)
class AuditorAccessGrantAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "status", "starts_at", "expires_at")
    list_filter = ("status",)
    search_fields = ("user__email", "reason")
    readonly_fields = ("created_at", "updated_at", "last_used_at")
