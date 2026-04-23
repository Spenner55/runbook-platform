"""
Serializers for internal runner endpoints.

These must never be imported by public CRUD views.
"""
from rest_framework import serializers

from apps.executions.models import Execution, ExecutionStep


class ClaimNextRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    runner_version = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    requested_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class InternalExecutionStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionStep
        fields = [
            "id", "position", "step_key", "name", "step_type",
            "risk_level", "command", "requires_approval", "status",
        ]


class ClaimedExecutionSerializer(serializers.ModelSerializer):
    steps = InternalExecutionStepSerializer(many=True, read_only=True)

    class Meta:
        model = Execution
        fields = [
            "id", "status", "workflow_id", "organization_id",
            "workflow_version", "workflow_snapshot",
            "claimed_by_runner_id", "claimed_at", "last_heartbeat_at",
            "steps",
        ]


class HeartbeatSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    observed_status = serializers.CharField(max_length=24, required=False, allow_blank=True, default="")
    sent_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class StepUpdateSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["running", "succeeded", "failed", "skipped"])
    started_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    finished_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    exit_code = serializers.IntegerField(required=False, allow_null=True, default=None)
    error_message = serializers.CharField(required=False, allow_blank=True, default="")


class ExecutionCompleteSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    final_status = serializers.ChoiceField(choices=["succeeded", "failed"])
    finished_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    error_message = serializers.CharField(required=False, allow_blank=True, default="")
