from django.contrib import admin

from apps.artifacts.models import Artifact


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "kind", "upload_status", "size_bytes", "uploaded_at", "execution"]
    list_filter = ["kind", "upload_status"]
    search_fields = ["name", "uploaded_by_runner_id"]
    readonly_fields = [
        "id",
        "organization",
        "execution",
        "step",
        "kind",
        "name",
        "original_name",
        "mime_type",
        "size_bytes",
        "checksum_sha256",
        "storage_key",
        "uploaded_by_runner_id",
        "upload_status",
        "uploaded_at",
        "content_disposition",
        "metadata",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
