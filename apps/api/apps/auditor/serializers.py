from rest_framework import serializers

from apps.auditor.models import (
    AuditorAccessGrant,
    ChangeControlCoverage,
    ControlMappingProfile,
    ExternalChangeReference,
    ServiceCatalogEntry,
)


class AuditChangeListQuerySerializer(serializers.Serializer):
    service = serializers.CharField(max_length=128, required=False)
    target = serializers.CharField(max_length=255, required=False)
    risk = serializers.CharField(max_length=32, required=False)
    status = serializers.CharField(max_length=32, required=False)
    change_type = serializers.ChoiceField(
        choices=["standard", "emergency"], required=False
    )
    bundle_status = serializers.CharField(max_length=32, required=False)
    control_id = serializers.CharField(max_length=128, required=False)
    coverage_status = serializers.CharField(max_length=32, required=False)
    external_system = serializers.CharField(max_length=32, required=False)
    start_date = serializers.DateTimeField(required=False)
    end_date = serializers.DateTimeField(required=False)
    has_exception = serializers.BooleanField(required=False)
    ordering = serializers.CharField(max_length=32, required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200)
    offset = serializers.IntegerField(required=False, min_value=0)


class AuditTargetProjectionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    label = serializers.CharField()
    type = serializers.CharField()
    identifier = serializers.CharField()


class AuditBundleProjectionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    completeness_status = serializers.CharField()
    version = serializers.IntegerField()
    manifest_sha256 = serializers.CharField(allow_blank=True)
    content_sha256 = serializers.CharField(allow_blank=True)


class AuditExternalReferenceSummarySerializer(serializers.Serializer):
    system = serializers.CharField()
    reference_type = serializers.CharField()
    external_key = serializers.CharField(allow_blank=True)
    snapshot_status = serializers.CharField()


class AuditChangeSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    status = serializers.CharField()
    risk = serializers.CharField()
    change_type = serializers.CharField()
    targets = AuditTargetProjectionSerializer(many=True)
    submitted_at = serializers.DateTimeField(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)
    has_exception = serializers.BooleanField()
    bundle = AuditBundleProjectionSerializer(allow_null=True)
    external_references = AuditExternalReferenceSummarySerializer(many=True)
    coverage_summary = serializers.DictField()


class ExternalChangeReferenceSerializer(serializers.ModelSerializer):
    change_record_id = serializers.UUIDField(read_only=True)
    linked_by_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ExternalChangeReference
        fields = [
            "id",
            "change_record_id",
            "system",
            "reference_type",
            "external_id",
            "external_key",
            "display_label",
            "external_url",
            "snapshot",
            "snapshot_sha256",
            "snapshot_source",
            "snapshot_status",
            "snapshot_taken_at",
            "last_refresh_attempted_at",
            "last_refresh_error_code",
            "linked_by_id",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "change_record_id",
            "snapshot_sha256",
            "snapshot_taken_at",
            "last_refresh_attempted_at",
            "last_refresh_error_code",
            "linked_by_id",
            "created_at",
            "updated_at",
        ]


class ExternalChangeReferenceCreateSerializer(serializers.Serializer):
    system = serializers.CharField(max_length=32)
    reference_type = serializers.CharField(max_length=32)
    external_id = serializers.CharField(max_length=255)
    external_key = serializers.CharField(max_length=255, allow_blank=True, required=False)
    display_label = serializers.CharField(
        max_length=255, allow_blank=True, required=False
    )
    external_url = serializers.URLField(
        max_length=2048, allow_blank=True, required=False
    )
    snapshot = serializers.DictField(required=False)
    notes = serializers.CharField(allow_blank=True, required=False)


class ServiceCatalogEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCatalogEntry
        fields = [
            "id",
            "service_key",
            "name",
            "description",
            "owner_team",
            "business_owner",
            "criticality",
            "environment",
            "target_patterns",
            "metadata",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ControlMappingProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlMappingProfile
        fields = [
            "id",
            "key",
            "name",
            "standard",
            "version",
            "description",
            "mapping_rules",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ChangeControlCoverageSerializer(serializers.ModelSerializer):
    evidence_bundle_id = serializers.UUIDField(read_only=True)
    mapping_profile_id = serializers.UUIDField(read_only=True)
    computed_by_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ChangeControlCoverage
        fields = [
            "id",
            "evidence_bundle_id",
            "mapping_profile_id",
            "standard",
            "control_id",
            "control_title",
            "coverage_status",
            "matched_sections",
            "missing_sections",
            "evidence_paths",
            "coverage_fingerprint_sha256",
            "computed_at",
            "computed_by_id",
        ]
        read_only_fields = fields


class AuditChangeDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    justification = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    risk = serializers.CharField()
    change_type = serializers.CharField()
    targets = AuditTargetProjectionSerializer(many=True)
    submitted_at = serializers.DateTimeField(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)
    closed_at = serializers.DateTimeField(allow_null=True)
    has_exception = serializers.BooleanField()
    bundle = AuditBundleProjectionSerializer(allow_null=True)
    external_references = ExternalChangeReferenceSerializer(many=True)
    control_coverage = ChangeControlCoverageSerializer(many=True)
    coverage_summary = serializers.DictField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class CoverageRecomputeSerializer(serializers.Serializer):
    mapping_profile_id = serializers.UUIDField()
    evidence_bundle_id = serializers.UUIDField(required=False)


class AuditorAccessGrantSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField()
    created_by_id = serializers.UUIDField(read_only=True)
    revoked_by_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = AuditorAccessGrant
        fields = [
            "id",
            "user_id",
            "status",
            "scope",
            "reason",
            "starts_at",
            "expires_at",
            "revoked_at",
            "created_by_id",
            "revoked_by_id",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "revoked_at",
            "created_by_id",
            "revoked_by_id",
            "last_used_at",
            "created_at",
            "updated_at",
        ]

