from rest_framework import serializers

from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.executions.models import ExecutionStep


class ApprovalDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalDecision
        fields = [
            "id",
            "decision",
            "source_type",
            "decided_by_label",
            "decided_at",
            "notes",
        ]


class ApprovalStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionStep
        fields = [
            "id",
            "position",
            "step_key",
            "name",
            "step_type",
            "risk_level",
            "status",
            "requires_approval",
        ]


class ApprovalRequestSerializer(serializers.ModelSerializer):
    step = ApprovalStepSerializer(read_only=True)
    decision = ApprovalDecisionSerializer(read_only=True)
    execution_status = serializers.CharField(source="execution.status", read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "organization_id",
            "subject_type",
            "subject_id",
            "execution_id",
            "execution_status",
            "step",
            "status",
            "requested_by_runner_id",
            "requested_at",
            "timeout_seconds",
            "expires_at",
            "resolved_at",
            "decision",
        ]


class DecideApprovalSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    actor_display_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, write_only=True
    )
