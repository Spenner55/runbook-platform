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
            "definition_hash_sha256",
            "catalog_version",
            "validation_status",
            "validation_report",
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


class WorkflowValidateSerializer(serializers.Serializer):
    definition = serializers.JSONField()
    schema_version = serializers.ChoiceField(
        choices=["workflow.schema.v1", "workflow.schema.v2"],
        default="workflow.schema.v2",
        required=False,
    )
