"""Serializers for the changes app."""

from rest_framework import serializers

from apps.changes.models import (
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    OperationProfile,
)


class AllowedWorkflowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    version = serializers.IntegerField()


class OperationProfileSerializer(serializers.ModelSerializer):
    allowed_workflows = AllowedWorkflowSerializer(many=True, read_only=True)

    class Meta:
        model = OperationProfile
        fields = [
            "id",
            "key",
            "name",
            "description",
            "risk_level",
            "requires_approval",
            "verification_required",
            "allowed_target_types",
            "allowed_workflows",
        ]


class OperationProfileSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationProfile
        fields = ["id", "key", "name"]


class ChangeTargetSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    target_type = serializers.CharField(max_length=64)
    target_identifier = serializers.CharField(max_length=255)
    display_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
    environment = serializers.CharField(max_length=32)
    metadata = serializers.DictField(required=False, default=dict)


class ChangeTargetOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChangeTarget
        fields = [
            "id",
            "position",
            "target_type",
            "target_identifier",
            "display_name",
            "environment",
        ]


class ApprovalRequestSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    requested_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)


class ExecutionBindingSummarySerializer(serializers.ModelSerializer):
    execution_id = serializers.UUIDField(source="execution.id", read_only=True)
    execution_status = serializers.CharField(source="execution.status", read_only=True)

    class Meta:
        model = ChangeExecutionBinding
        fields = [
            "id",
            "execution_id",
            "execution_status",
            "reserved_at",
            "bound_at",
            "operation_profile_key",
            "requested_inputs_sha256",
        ]


class ChangeRecordDetailSerializer(serializers.ModelSerializer):
    operation_profile = OperationProfileSummarySerializer(read_only=True)
    targets = ChangeTargetOutputSerializer(many=True, read_only=True)
    approval_request = serializers.SerializerMethodField()
    execution_binding = serializers.SerializerMethodField()
    policy_decision = serializers.SerializerMethodField()

    class Meta:
        model = ChangeRecord
        fields = [
            "id",
            "status",
            "title",
            "summary",
            "justification",
            "operation_profile",
            "workflow_id",
            "workflow_version_snapshot",
            "requested_inputs_sha256",
            "request_snapshot_sha256",
            "operation_profile_key_snapshot",
            "scheduled_for",
            "submitted_at",
            "approved_at",
            "dispatchable_at",
            "running_at",
            "verification_pending_at",
            "closed_at",
            "rejected_at",
            "canceled_at",
            "expired_at",
            "terminal_reason",
            "targets",
            "approval_request",
            "policy_decision",
            "execution_binding",
            "created_at",
            "updated_at",
        ]

    def get_approval_request(self, obj):
        ar = obj.approval_request
        if ar is None:
            return None
        return ApprovalRequestSummarySerializer(ar).data

    def get_execution_binding(self, obj):
        try:
            binding = obj.execution_binding
        except Exception:
            return None
        if binding is None:
            return None
        return ExecutionBindingSummarySerializer(binding).data

    def get_policy_decision(self, obj):
        snapshot = obj.policy_decision_snapshot
        if not snapshot:
            return None
        return snapshot


class CreateChangeRecordSerializer(serializers.Serializer):
    operation_profile_key = serializers.CharField(max_length=96)
    workflow_id = serializers.UUIDField()
    title = serializers.CharField(max_length=255)
    summary = serializers.CharField(allow_blank=True, default="")
    justification = serializers.CharField(allow_blank=True, default="")
    requested_inputs = serializers.DictField(required=False, default=dict)
    scheduled_for = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )
    targets = ChangeTargetSerializer(many=True, required=False, default=list)


class SubmitChangeRecordSerializer(serializers.Serializer):
    submitter_note = serializers.CharField(allow_blank=True, required=False, default="")


class BindChangeExecutionSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.CharField(max_length=128)
    execution_id = serializers.UUIDField()
    dispatch_token = serializers.CharField(max_length=256)
    requested_inputs_sha256 = serializers.CharField(max_length=64)
    operation_profile_key = serializers.CharField(max_length=96)
    sent_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
