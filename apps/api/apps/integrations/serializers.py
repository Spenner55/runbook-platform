from rest_framework import serializers

from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)


class IntegrationConnectionSerializer(serializers.ModelSerializer):
    config = serializers.SerializerMethodField()
    credentials_configured = serializers.SerializerMethodField()

    class Meta:
        model = IntegrationConnection
        fields = [
            "id",
            "organization_id",
            "type",
            "name",
            "config",
            "event_types",
            "is_active",
            "credentials_configured",
            "last_delivery_at",
            "last_delivery_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_credentials_configured(self, obj) -> bool:
        return bool(obj.encrypted_credentials)

    def get_config(self, obj) -> dict:
        return _redact_config(obj.config)


def _redact_config(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_sensitive_config_key(key) else _redact_config(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_config(item) for item in value]
    if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
        return "[redacted]"
    return value


def _is_sensitive_config_key(key) -> bool:
    return any(
        fragment in str(key).lower()
        for fragment in ("credential", "secret", "token", "url", "webhook")
    )


class IntegrationConnectionCreateSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField()
    type = serializers.ChoiceField(
        choices=[
            IntegrationConnection.Type.SLACK_WEBHOOK,
            IntegrationConnection.Type.GENERIC_WEBHOOK,
        ]
    )
    name = serializers.CharField(max_length=128, trim_whitespace=True)
    credentials = serializers.DictField(write_only=True)
    config = serializers.DictField(required=False, default=dict)


class IntegrationConnectionUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128, trim_whitespace=True, required=False)
    credentials = serializers.DictField(write_only=True, required=False)
    config = serializers.DictField(required=False)

    def validate(self, attrs):
        if not attrs and "event_types" not in self.initial_data:
            raise serializers.ValidationError("At least one field is required.")
        return attrs


class IntegrationDeactivateSerializer(serializers.Serializer):
    pass


class IntegrationDeliveryAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationDeliveryAttempt
        fields = [
            "id",
            "integration_id",
            "organization_id",
            "event_type",
            "payload_preview",
            "http_status",
            "success",
            "error_detail",
            "latency_ms",
            "attempted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
