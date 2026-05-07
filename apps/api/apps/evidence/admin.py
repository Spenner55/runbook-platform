from django.contrib import admin

from apps.evidence.models import (
    EvidenceBundle,
    EvidenceBundleItem,
    EvidenceExport,
    EvidenceRedactionPolicy,
    EvidenceRetentionPolicy,
    LegalHold,
)


class ImmutableEvidenceAdminMixin:
    immutable_status_values: tuple[str, ...] = ()

    def has_delete_permission(self, request, obj=None):
        if obj is not None and self._is_immutable(obj):
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and self._is_immutable(obj):
            fields.extend(field.name for field in obj._meta.fields)
        return list(dict.fromkeys(fields))

    def _is_immutable(self, obj) -> bool:
        return getattr(obj, "status", None) in self.immutable_status_values


@admin.register(EvidenceBundle)
class EvidenceBundleAdmin(ImmutableEvidenceAdminMixin, admin.ModelAdmin):
    immutable_status_values = (
        EvidenceBundle.Status.SEALED,
        EvidenceBundle.Status.INVALIDATED,
    )
    list_display = [
        "id",
        "change_record",
        "version",
        "status",
        "completeness_status",
        "organization",
        "created_at",
    ]
    list_filter = ["status", "completeness_status"]
    search_fields = ["id", "change_record__id", "storage_key"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "compiled_at",
        "sealed_at",
        "invalidated_at",
        "storage_deleted_at",
    ]


@admin.register(EvidenceBundleItem)
class EvidenceBundleItemAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "bundle",
        "item_type",
        "item_key",
        "required",
        "present",
        "valid",
    ]
    list_filter = ["item_type", "required", "present", "valid"]
    search_fields = ["id", "item_key", "canonical_path", "source_id"]
    readonly_fields = ["id", "created_at", "updated_at"]

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.bundle.status == EvidenceBundle.Status.SEALED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.bundle.status == EvidenceBundle.Status.SEALED:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(EvidenceRedactionPolicy)
class EvidenceRedactionPolicyAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "is_active", "is_default", "created_at"]
    list_filter = ["is_active", "is_default"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(EvidenceExport)
class EvidenceExportAdmin(ImmutableEvidenceAdminMixin, admin.ModelAdmin):
    immutable_status_values = (EvidenceExport.Status.READY,)
    list_display = [
        "id",
        "bundle",
        "status",
        "organization",
        "requested_at",
        "ready_at",
    ]
    list_filter = ["status"]
    search_fields = ["id", "bundle__id", "storage_key"]
    readonly_fields = ["id", "created_at", "updated_at", "requested_at", "ready_at"]


@admin.register(EvidenceRetentionPolicy)
class EvidenceRetentionPolicyAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "is_active", "is_default", "cleanup_action"]
    list_filter = ["is_active", "is_default", "cleanup_action"]
    search_fields = ["name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(LegalHold)
class LegalHoldAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "change_record",
        "status",
        "organization",
        "placed_at",
        "released_at",
    ]
    list_filter = ["status"]
    search_fields = ["id", "change_record__id", "external_reference", "reason"]
    readonly_fields = ["id", "created_at", "updated_at", "placed_at", "released_at"]
