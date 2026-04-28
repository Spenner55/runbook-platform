import json

from rest_framework import serializers

from apps.artifacts.models import Artifact


class ArtifactUploadSerializer(serializers.Serializer):
    """Validates multipart runner upload requests."""

    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=Artifact.Kind.choices)
    name = serializers.CharField(max_length=255)
    mime_type = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    checksum_sha256 = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    metadata = serializers.JSONField(required=False, default=dict)
    file = serializers.FileField()

    def validate_metadata(self, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError(
                    "metadata must be valid JSON."
                ) from exc
            if not isinstance(parsed, dict):
                raise serializers.ValidationError("metadata must be a JSON object.")
            return parsed
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata must be a JSON object.")
        return value


class ArtifactSerializer(serializers.ModelSerializer):
    """Public artifact representation — never exposes storage_key."""

    class Meta:
        model = Artifact
        fields = [
            "id",
            "execution_id",
            "step_id",
            "kind",
            "name",
            "mime_type",
            "size_bytes",
            "checksum_sha256",
            "uploaded_by_runner_id",
            "uploaded_at",
            "metadata",
        ]
        read_only_fields = fields
