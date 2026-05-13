from rest_framework import serializers

from apps.runners.models import (
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
    TargetConnectivityRoute,
)


class RunnerPoolSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)

    class Meta:
        model = RunnerPool
        fields = [
            "id",
            "organization_id",
            "key",
            "name",
            "description",
            "environment",
            "network_zone",
            "status",
            "max_concurrent_executions",
            "max_concurrent_per_target",
            "labels",
            "capabilities",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "organization_id", "created_at"]


class RunnerSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    pool_id = serializers.UUIDField(source="pool.id", read_only=True)

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
            "metadata",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "organization_id",
            "pool_id",
            "created_at",
        ]
        # token_hash is intentionally excluded.


class RunnerRegistrationTokenCreateSerializer(serializers.Serializer):
    pool = serializers.UUIDField()
    label_policy = serializers.ListField(child=serializers.CharField(), default=list)
    capability_policy = serializers.ListField(child=serializers.CharField(), default=list)
    expires_at = serializers.DateTimeField()
    max_registrations = serializers.IntegerField(default=1, min_value=1)


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
