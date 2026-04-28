from rest_framework import serializers

from apps.audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "actor_type",
            "actor_id",
            "actor_label",
            "event_type",
            "object_type",
            "object_id",
            "organization_id",
            "metadata",
            "occurred_at",
        ]


class AuditEventListQuerySerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(required=True)
    object_type = serializers.ChoiceField(
        choices=[choice.value for choice in AuditEvent.ObjectType], required=False
    )
    object_id = serializers.UUIDField(required=False)
    event_type = serializers.CharField(max_length=128, required=False)
    actor_type = serializers.ChoiceField(
        choices=[choice.value for choice in AuditEvent.ActorType], required=False
    )
    occurred_after = serializers.DateTimeField(required=False)
    occurred_before = serializers.DateTimeField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200)
    offset = serializers.IntegerField(required=False, min_value=0)

    def validate(self, attrs):
        object_type = attrs.get("object_type")
        object_id = attrs.get("object_id")
        if bool(object_type) != bool(object_id):
            raise serializers.ValidationError(
                "object_type and object_id must be provided together."
            )
        return attrs
