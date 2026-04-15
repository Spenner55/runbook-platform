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
        fields = ["id", "status", "workflow_id", "organization_id", "workflow_version", "created_at"]


class ExecutionDetailSerializer(serializers.ModelSerializer):
    steps = ExecutionStepSerializer(many=True, read_only=True)

    class Meta:
        model = Execution
        fields = [
            "id", "status", "workflow_id", "organization_id", "workflow_version",
            "workflow_snapshot", "started_at", "finished_at",
            "created_at", "updated_at", "steps",
        ]


# ---------------------------------------------------------------------------
# Internal runner serializers
# ---------------------------------------------------------------------------

class ClaimNextRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)


class HeartbeatRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()


class StepUpdateRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["running", "succeeded", "failed"])
    started_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    finished_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    exit_code = serializers.IntegerField(required=False, allow_null=True, default=None)
    error_message = serializers.CharField(required=False, allow_blank=True, default="")


class CompleteExecutionRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=["succeeded", "failed"])


class ClaimedStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionStep
        fields = [
            "id", "position", "step_key", "name", "step_type",
            "risk_level", "command", "requires_approval", "status",
        ]


class ClaimedExecutionSerializer(serializers.ModelSerializer):
    steps = ClaimedStepSerializer(many=True, read_only=True)

    class Meta:
        model = Execution
        fields = [
            "id", "status", "workflow_id", "organization_id",
            "workflow_version", "workflow_snapshot", "claim_token", "steps",
        ]
