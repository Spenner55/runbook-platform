from rest_framework import serializers

from apps.executions.models import Execution, ExecutionStep


# ---------------------------------------------------------------------------
# Public serializers
# ---------------------------------------------------------------------------

class ExecutionStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionStep
        fields = [
            "id", "position", "step_key", "name", "step_type", "risk_level",
            "command", "requires_approval", "status",
            "started_at", "finished_at", "exit_code", "error_message",
        ]


class ExecutionCreateSerializer(serializers.Serializer):
    workflow_id = serializers.UUIDField()


class ExecutionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = [
            "id", "status", "workflow_id", "organization_id", "workflow_version",
            "claimed_by_runner_id", "claimed_at", "last_heartbeat_at",
            "started_at", "finished_at", "created_at", "updated_at",
        ]


class ExecutionDetailSerializer(serializers.ModelSerializer):
    steps = ExecutionStepSerializer(many=True, read_only=True)
    claim_token_present = serializers.SerializerMethodField()

    class Meta:
        model = Execution
        fields = [
            "id", "status", "workflow_id", "organization_id", "workflow_version",
            "workflow_snapshot",
            "claimed_by_runner_id", "claim_token_present",
            "claimed_at", "last_heartbeat_at",
            "started_at", "finished_at",
            "created_at", "updated_at",
            "steps",
        ]

    def get_claim_token_present(self, obj):
        return obj.claim_token is not None


class ExecutionCancelSerializer(serializers.Serializer):
    pass
