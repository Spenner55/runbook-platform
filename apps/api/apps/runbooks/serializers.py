from rest_framework import serializers

from apps.runbooks.models import Runbook


class RunbookCreateSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=96)
    raw_content = serializers.CharField(allow_blank=True, default="")


class RunbookListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Runbook
        fields = [
            "id",
            "title",
            "slug",
            "status",
            "organization_id",
            "created_at",
            "updated_at",
        ]


class RunbookDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Runbook
        fields = [
            "id",
            "title",
            "slug",
            "status",
            "raw_content",
            "organization_id",
            "created_at",
            "updated_at",
        ]


class RunbookMarkReadySerializer(serializers.Serializer):
    pass


class RunbookArchiveSerializer(serializers.Serializer):
    pass
