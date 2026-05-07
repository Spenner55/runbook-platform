from rest_framework import serializers

from apps.evidence.models import EvidenceBundle, EvidenceExport, LegalHold


class EvidenceBundleSerializer(serializers.ModelSerializer):
    """Public bundle representation. Never exposes storage keys or raw bytes."""

    change_record_id = serializers.UUIDField(read_only=True)
    organization_id = serializers.UUIDField(read_only=True)
    previous_bundle_id = serializers.UUIDField(read_only=True)
    created_by_id = serializers.UUIDField(read_only=True)
    sealed_by_id = serializers.UUIDField(read_only=True)
    invalidated_by_id = serializers.UUIDField(read_only=True)
    download_available = serializers.SerializerMethodField()
    is_current = serializers.SerializerMethodField()
    legal_hold_active = serializers.SerializerMethodField()

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
            "retention_expires_at",
            "storage_deleted_at",
            "is_current",
            "legal_hold_active",
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

    def get_is_current(self, obj):
        latest = (
            EvidenceBundle.objects.filter(
                organization_id=obj.organization_id,
                change_record_id=obj.change_record_id,
            )
            .exclude(status=EvidenceBundle.Status.INVALIDATED)
            .order_by("-version", "-created_at")
            .values_list("id", flat=True)
            .first()
        )
        if latest is None:
            latest = (
                EvidenceBundle.objects.filter(
                    organization_id=obj.organization_id,
                    change_record_id=obj.change_record_id,
                )
                .order_by("-version", "-created_at")
                .values_list("id", flat=True)
                .first()
            )
        return latest == obj.id

    def get_legal_hold_active(self, obj):
        return LegalHold.objects.filter(
            change_record_id=obj.change_record_id,
            status=LegalHold.Status.ACTIVE,
        ).exists()


class EvidenceBundleSummarySerializer(serializers.ModelSerializer):
    """Compact list/latest representation."""

    change_record_id = serializers.UUIDField(read_only=True)
    download_available = serializers.SerializerMethodField()
    legal_hold_active = serializers.SerializerMethodField()

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
            "retention_expires_at",
            "storage_deleted_at",
            "legal_hold_active",
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

    def get_legal_hold_active(self, obj):
        return LegalHold.objects.filter(
            change_record_id=obj.change_record_id,
            status=LegalHold.Status.ACTIVE,
        ).exists()


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


class EvidenceExportSerializer(serializers.ModelSerializer):
    """Public export representation. Never exposes storage keys or raw bytes."""

    bundle_id = serializers.UUIDField(read_only=True)
    organization_id = serializers.UUIDField(read_only=True)
    redaction_policy_id = serializers.UUIDField(read_only=True)
    requested_by_id = serializers.UUIDField(read_only=True)
    download_available = serializers.SerializerMethodField()

    class Meta:
        model = EvidenceExport
        fields = [
            "id",
            "organization_id",
            "bundle_id",
            "redaction_policy_id",
            "status",
            "requested_by_id",
            "requested_at",
            "ready_at",
            "expires_at",
            "content_sha256",
            "content_size_bytes",
            "manifest",
            "manifest_sha256",
            "source_manifest_sha256",
            "source_bundle_content_sha256",
            "redaction_summary",
            "receipt",
            "receipt_sha256",
            "failure_code",
            "failure_message",
            "download_count",
            "last_downloaded_at",
            "download_available",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_download_available(self, obj):
        return bool(
            obj.status == EvidenceExport.Status.READY
            and obj.storage_deleted_at is None
            and obj.content_sha256
        )


class EvidenceExportCreateSerializer(serializers.Serializer):
    redaction_policy_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )


class LegalHoldSerializer(serializers.ModelSerializer):
    change_record_id = serializers.UUIDField(read_only=True)
    evidence_bundle_id = serializers.UUIDField(read_only=True)
    placed_by_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = LegalHold
        fields = [
            "id",
            "status",
            "change_record_id",
            "evidence_bundle_id",
            "placed_by_id",
            "placed_at",
            "external_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class LegalHoldCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000)
    external_reference = serializers.CharField(
        max_length=512, required=False, allow_blank=True, default=""
    )


class LegalHoldReleaseSerializer(serializers.Serializer):
    release_reason = serializers.CharField(max_length=2000)
