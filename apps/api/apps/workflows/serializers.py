from rest_framework import serializers

from apps.workflows.models import Workflow


class WorkflowCreateSerializer(serializers.Serializer):
    runbook_id = serializers.UUIDField()


class WorkflowListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "version",
            "status",
            "definition_schema_version",
            "requires_review",
            "parse_source",
            "runbook_id",
            "organization_id",
            "created_at",
            "updated_at",
        ]


class WorkflowDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = [
            "id",
            "name",
            "version",
            "status",
            "definition_schema_version",
            "definition",
            "requires_review",
            "parse_source",
            "runbook_id",
            "organization_id",
            "created_at",
            "updated_at",
        ]


class WorkflowPublishSerializer(serializers.Serializer):
    pass


class WorkflowArchiveSerializer(serializers.Serializer):
    pass
