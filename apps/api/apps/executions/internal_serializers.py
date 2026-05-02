"""
Serializers for internal runner endpoints.

These must never be imported by public CRUD views.
"""

from rest_framework import serializers

from apps.executions.models import Execution, ExecutionStep


class ClaimNextRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    runner_version = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    requested_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )


class InternalExecutionStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionStep
        fields = [
            "id",
            "position",
            "step_key",
            "name",
            "step_type",
            "risk_level",
            "command",
            "requires_approval",
            "status",
        ]


class ClaimedExecutionSerializer(serializers.ModelSerializer):
    steps = InternalExecutionStepSerializer(many=True, read_only=True)
    change_record_id = serializers.SerializerMethodField()
    dispatch_token = serializers.SerializerMethodField()
    requested_inputs_sha256 = serializers.SerializerMethodField()
    operation_profile_key = serializers.SerializerMethodField()

    class Meta:
        model = Execution
        fields = [
            "id",
            "status",
            "workflow_id",
            "organization_id",
            "workflow_version",
            "workflow_snapshot",
            "claimed_by_runner_id",
            "claimed_at",
            "last_heartbeat_at",
            "steps",
            "change_record_id",
            "dispatch_token",
            "requested_inputs_sha256",
            "operation_profile_key",
        ]

    def _get_binding(self, obj):
        try:
            binding = obj.change_binding
        except Exception:
            return None
        if binding.bound_at is not None:
            return None
        from django.utils import timezone

        if binding.dispatch_token_expires_at <= timezone.now():
            return None
        if binding.change_record.status != "dispatchable":
            return None
        return binding

    def get_change_record_id(self, obj):
        binding = self._get_binding(obj)
        return str(binding.change_record_id) if binding else None

    def get_dispatch_token(self, obj):
        binding = self._get_binding(obj)
        if binding is None:
            return None
        from apps.changes.services import generate_dispatch_token

        return generate_dispatch_token(binding)

    def get_requested_inputs_sha256(self, obj):
        binding = self._get_binding(obj)
        return binding.requested_inputs_sha256 if binding else None

    def get_operation_profile_key(self, obj):
        binding = self._get_binding(obj)
        return binding.operation_profile_key if binding else None


class HeartbeatSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    observed_status = serializers.CharField(
        max_length=24, required=False, allow_blank=True, default=""
    )
    sent_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class StepUpdateSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    status = serializers.ChoiceField(
        choices=["running", "succeeded", "failed", "skipped"]
    )
    started_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )
    finished_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )
    exit_code = serializers.IntegerField(required=False, allow_null=True, default=None)
    error_message = serializers.CharField(required=False, allow_blank=True, default="")


class ExecutionCompleteSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    final_status = serializers.ChoiceField(choices=["succeeded", "failed"])
    finished_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )
    error_message = serializers.CharField(required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Step-start (replaces direct pending→running update for all steps)
# ---------------------------------------------------------------------------


class StepStartSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    sent_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class InternalApprovalRequestSerializer(serializers.Serializer):
    """Minimal approval request shape used inside runner responses."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    requested_at = serializers.DateTimeField()
    timeout_seconds = serializers.IntegerField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    resolved_at = serializers.DateTimeField(allow_null=True)

    def to_representation(self, instance):
        return {
            "id": str(instance.id),
            "status": instance.status,
            "requested_at": instance.requested_at,
            "timeout_seconds": instance.timeout_seconds,
            "expires_at": instance.expires_at,
            "resolved_at": instance.resolved_at,
        }


# ---------------------------------------------------------------------------
# Approval-status polling
# ---------------------------------------------------------------------------


class ApprovalStatusRequestSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.UUIDField()
    observed_step_status = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    sent_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
