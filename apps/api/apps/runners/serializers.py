from django.utils import timezone
from rest_framework import serializers

from apps.runners.models import (
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
    TargetConnectivityRoute,
)


class RunnerPoolSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    active_runner_count = serializers.IntegerField(read_only=True, default=0)
    active_execution_count = serializers.IntegerField(read_only=True, default=0)
    capacity_summary = serializers.SerializerMethodField()

    class Meta:
        model = RunnerPool
        fields = [
            "id",
            "organization_id",
            "key",
            "name",
            "display_name",
            "description",
            "environment",
            "network_zone",
            "status",
            "max_concurrent_executions",
            "max_concurrent_per_target",
            "default_for_non_change_executions",
            "labels",
            "capabilities",
            "metadata",
            "drain_requested_at",
            "disabled_at",
            "active_runner_count",
            "active_execution_count",
            "capacity_summary",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "organization_id",
            "drain_requested_at",
            "disabled_at",
            "active_runner_count",
            "active_execution_count",
            "capacity_summary",
            "created_at",
        ]

    def get_capacity_summary(self, obj):
        active_exec = getattr(obj, "active_execution_count", None) or 0
        max_exec = obj.max_concurrent_executions
        return {
            "max_concurrent_executions": max_exec,
            "active_executions": active_exec,
            "available_capacity": max(0, max_exec - active_exec),
        }


class RunnerSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    pool_id = serializers.UUIDField(source="pool.id", read_only=True)
    active_execution_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Runner
        fields = [
            "id",
            "organization_id",
            "pool_id",
            "display_name",
            "status",
            "runner_version",
            "hostname",
            "last_seen_at",
            "last_heartbeat_at",
            "drain_requested_at",
            "disabled_at",
            "revoked_at",
            "active_execution_count",
            "metadata",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "organization_id",
            "pool_id",
            "active_execution_count",
            "created_at",
        ]
        # token_hash and fingerprint_sha256 are intentionally excluded.


class RunnerRegistrationTokenCreateSerializer(serializers.Serializer):
    label_policy = serializers.ListField(child=serializers.CharField(), default=list)
    capability_policy = serializers.ListField(
        child=serializers.CharField(), default=list
    )
    expires_at = serializers.DateTimeField()
    max_registrations = serializers.IntegerField(default=1, min_value=1)


class RunnerRegistrationTokenListSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    pool_id = serializers.UUIDField(source="pool.id", read_only=True)
    pool_key = serializers.CharField(source="pool.key", read_only=True)
    is_revoked = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    is_exhausted = serializers.SerializerMethodField()

    class Meta:
        model = RunnerRegistrationToken
        fields = [
            "id",
            "organization_id",
            "pool_id",
            "pool_key",
            "label_policy",
            "capability_policy",
            "expires_at",
            "max_registrations",
            "used_count",
            "revoked_at",
            "is_revoked",
            "is_expired",
            "is_exhausted",
            "created_at",
        ]
        # token_hash is intentionally excluded. Clear token is never stored or returned here.

    def get_is_revoked(self, obj):
        return obj.revoked_at is not None

    def get_is_expired(self, obj):
        return obj.expires_at < timezone.now()

    def get_is_exhausted(self, obj):
        return obj.used_count >= obj.max_registrations


class TargetConnectivityRouteSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    pool_id = serializers.UUIDField(source="pool.id", read_only=True)

    class Meta:
        model = TargetConnectivityRoute
        fields = [
            "id",
            "organization_id",
            "environment",
            "target_type",
            "normalized_identifier_pattern",
            "pool_id",
            "required_labels",
            "required_capabilities",
            "priority",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "organization_id", "pool_id", "created_at"]
