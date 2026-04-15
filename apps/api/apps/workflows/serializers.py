from rest_framework import serializers

from apps.workflows.models import Workflow


class WorkflowCreateSerializer(serializers.Serializer):
    runbook_id = serializers.UUIDField()


class WorkflowListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = ["id", "name", "version", "status", "runbook_id", "organization_id", "created_at"]


class WorkflowDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workflow
        fields = [
            "id", "name", "version", "status", "definition", "definition_schema_version",
            "runbook_id", "organization_id", "created_at", "updated_at",
        ]
