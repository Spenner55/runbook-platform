from rest_framework import serializers

from apps.evidence.models import EvidenceBundle


class EvidenceBundleSerializer(serializers.ModelSerializer):
    """Public bundle representation. Never exposes storage keys or raw bytes."""

    change_record_id = serializers.UUIDField(read_only=True)
    organization_id = serializers.UUIDField(read_only=True)
    previous_bundle_id = serializers.UUIDField(read_only=True)
    created_by_id = serializers.UUIDField(read_only=True)
    sealed_by_id = serializers.UUIDField(read_only=True)
    invalidated_by_id = serializers.UUIDField(read_only=True)
    download_available = serializers.SerializerMethodField()

    class Meta:
        model = EvidenceBundle
        fields = [
            "id",
            "organization_id",
            "change_record_id",
            "version",
            "status",
            "completeness_status",
            "completeness_report",
            "source_snapshot_sha256",
            "source_cutoff_at",
            "source_high_watermark",
            "manifest",
            "manifest_sha256",
            "payload_checksums_sha256",
            "content_sha256",
            "content_size_bytes",
            "mime_type",
            "compiled_at",
            "sealed_at",
            "invalidated_at",
            "invalidation_reason",
            "previous_bundle_id",
            "created_by_id",
            "sealed_by_id",
            "invalidated_by_id",
            "download_available",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_download_available(self, obj):
        return bool(
            obj.status == EvidenceBundle.Status.SEALED
            and obj.storage_deleted_at is None
            and obj.content_sha256
        )


class EvidenceBundleSummarySerializer(serializers.ModelSerializer):
    """Compact list/latest representation."""

    change_record_id = serializers.UUIDField(read_only=True)
    download_available = serializers.SerializerMethodField()

    class Meta:
        model = EvidenceBundle
        fields = [
            "id",
            "change_record_id",
            "version",
            "status",
            "completeness_status",
            "manifest_sha256",
            "payload_checksums_sha256",
            "content_sha256",
            "content_size_bytes",
            "compiled_at",
            "sealed_at",
            "invalidated_at",
            "invalidation_reason",
            "download_available",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_download_available(self, obj):
        return bool(
            obj.status == EvidenceBundle.Status.SEALED
            and obj.storage_deleted_at is None
            and obj.content_sha256
        )


class EvidenceBundleCreateSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(required=False, write_only=True)


class EvidenceBundleSealSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(required=False, write_only=True)


class EvidenceBundleInvalidateSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(required=False, write_only=True)
    reason = serializers.CharField(max_length=128)


class EvidenceBundleManifestSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceBundle
        fields = [
            "id",
            "change_record_id",
            "version",
            "status",
            "manifest",
            "manifest_sha256",
            "payload_checksums_sha256",
            "content_sha256",
            "content_size_bytes",
            "sealed_at",
        ]
        read_only_fields = fields


class EvidenceBundleCompletenessSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceBundle
        fields = [
            "id",
            "change_record_id",
            "version",
            "status",
            "completeness_status",
            "completeness_report",
            "source_snapshot_sha256",
            "source_cutoff_at",
            "source_high_watermark",
            "compiled_at",
        ]
        read_only_fields = fields
