"""Serializers for the changes app."""

from django.utils import timezone
from rest_framework import serializers

from apps.changes.models import (
    ChangeClosure,
    ChangeExecutionBinding,
    ChangeRecord,
    ChangeTarget,
    ChangeWindow,
    DispatchEligibilityCheck,
    FreezeRule,
    OperationProfile,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
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
    window = serializers.SerializerMethodField()

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
            "window",
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

    def get_window(self, obj):
        try:
            return ChangeWindowOutputSerializer(obj.window).data
        except Exception:
            return None


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


class ExecutionTimingCallbackSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    execution_id = serializers.UUIDField()
    observed_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )


class InternalRunnerVerificationResultSerializer(serializers.Serializer):
    runner_id = serializers.CharField(max_length=255)
    claim_token = serializers.CharField(max_length=128)
    execution_id = serializers.UUIDField()
    check_key = serializers.CharField(max_length=128)
    verification_key = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    outcome = serializers.ChoiceField(choices=VerificationResult.Outcome.choices)
    step_key = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    artifact_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
    )
    artifact_checksums = serializers.DictField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=dict,
    )
    observed_value = serializers.DictField(required=False, default=dict)
    metadata = serializers.DictField(required=False, default=dict)
    sent_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class VerificationCheckDetailSerializer(serializers.ModelSerializer):
    last_result_id = serializers.UUIDField(
        source="last_result.id", read_only=True, allow_null=True
    )

    class Meta:
        model = VerificationCheck
        fields = [
            "id",
            "position",
            "key",
            "name",
            "description",
            "check_type",
            "required",
            "status",
            "verification_key",
            "source_step_key",
            "artifact_kind",
            "artifact_name_pattern",
            "api_assertion",
            "external_reference_config",
            "manual_attestation_config",
            "last_result_id",
            "satisfied_at",
            "failed_at",
            "created_at",
            "updated_at",
        ]


class VerificationPlanDetailSerializer(serializers.ModelSerializer):
    checks = VerificationCheckDetailSerializer(many=True, read_only=True)

    class Meta:
        model = VerificationPlan
        fields = [
            "id",
            "change_record_id",
            "mode",
            "status",
            "generated_from_profile_sha256",
            "required_check_count",
            "optional_check_count",
            "satisfied_required_count",
            "failed_required_count",
            "generated_at",
            "activated_at",
            "satisfied_at",
            "failed_at",
            "checks",
            "created_at",
            "updated_at",
        ]


class VerificationResultCreateSerializer(serializers.Serializer):
    check_key = serializers.CharField(max_length=128)
    outcome = serializers.ChoiceField(choices=VerificationResult.Outcome.choices)
    verification_key = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    source_step_key = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    artifact_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    artifact_checksum_sha256 = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    external_reference = serializers.CharField(
        max_length=1024, required=False, allow_blank=True, default=""
    )
    api_assertion_snapshot = serializers.DictField(required=False, default=dict)
    manual_attestation_text = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    observed_value = serializers.DictField(required=False, default=dict)


class VerificationResultDetailSerializer(serializers.ModelSerializer):
    check_key = serializers.CharField(source="verification_check.key", read_only=True)

    class Meta:
        model = VerificationResult
        fields = [
            "id",
            "change_record_id",
            "plan_id",
            "verification_check_id",
            "check_key",
            "source",
            "outcome",
            "validation_status",
            "verification_key",
            "artifact_id",
            "artifact_checksum_sha256",
            "external_reference",
            "api_assertion_snapshot",
            "manual_attestation_text",
            "observed_value",
            "validation_errors",
            "submitted_at",
            "validated_at",
            "created_at",
        ]


class ChangeClosureCreateSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(
        choices=ChangeClosure.Outcome.choices,
        default=ChangeClosure.Outcome.SUCCESS,
    )
    summary = serializers.CharField(allow_blank=False)
    independent_reviewer_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )


class ChangeClosureDetailSerializer(serializers.ModelSerializer):
    closed_by_id = serializers.UUIDField(
        source="closed_by.id", read_only=True, allow_null=True
    )
    independent_reviewer_id = serializers.UUIDField(
        source="independent_reviewer.id", read_only=True, allow_null=True
    )

    class Meta:
        model = ChangeClosure
        fields = [
            "id",
            "change_record_id",
            "outcome",
            "closed_by_id",
            "independent_reviewer_id",
            "summary",
            "verification_plan_id",
            "verification_summary",
            "execution_summary",
            "closed_at",
            "created_at",
        ]


class ChangeWindowOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChangeWindow
        fields = [
            "id",
            "status",
            "starts_at",
            "ends_at",
            "timezone",
            "reason",
            "approved_at",
            "opened_at",
            "expired_at",
            "overrun_at",
            "closed_at",
            "created_at",
            "updated_at",
        ]


class ChangeWindowInputSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    timezone = serializers.CharField(max_length=64, allow_blank=True, default="")
    reason = serializers.CharField(allow_blank=True, default="")


class FreezeRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FreezeRule
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "behavior",
            "starts_at",
            "ends_at",
            "scope_type",
            "target_type",
            "target_identifier",
            "requires_exception_reference",
            "created_at",
            "updated_at",
        ]


class CreateFreezeRuleSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(allow_blank=True, default="")
    behavior = serializers.ChoiceField(choices=FreezeRule.Behavior.choices)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    scope_type = serializers.ChoiceField(choices=FreezeRule.ScopeType.choices)
    target_type = serializers.CharField(max_length=64, allow_blank=True, default="")
    target_identifier = serializers.CharField(
        max_length=255, allow_blank=True, default=""
    )
    requires_exception_reference = serializers.BooleanField(default=False)


class UpdateFreezeRuleSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    behavior = serializers.ChoiceField(
        choices=FreezeRule.Behavior.choices, required=False
    )
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    scope_type = serializers.ChoiceField(
        choices=FreezeRule.ScopeType.choices, required=False
    )
    target_type = serializers.CharField(max_length=64, allow_blank=True, required=False)
    target_identifier = serializers.CharField(
        max_length=255, allow_blank=True, required=False
    )
    requires_exception_reference = serializers.BooleanField(required=False)


class DispatchEligibilityCheckSerializer(serializers.ModelSerializer):
    is_stale = serializers.SerializerMethodField()

    class Meta:
        model = DispatchEligibilityCheck
        fields = [
            "id",
            "result",
            "checked_at",
            "expires_at",
            "is_stale",
            "approved_status_ok",
            "policy_pass_ok",
            "window_open_ok",
            "freeze_conflicts_ok",
            "target_locks_ok",
            "actor_authorized_ok",
            "checks",
            "conflicts",
            "input_snapshot_sha256",
            "window_snapshot_sha256",
        ]

    def get_is_stale(self, obj):
        return timezone.now() > obj.expires_at
