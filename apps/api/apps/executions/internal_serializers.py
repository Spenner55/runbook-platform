"""
Serializers for internal runner endpoints.

These must never be imported by public CRUD views.
"""

import logging

from rest_framework import serializers

from apps.executions.models import Execution, ExecutionStep

logger = logging.getLogger(__name__)


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
    verification_plan_id = serializers.SerializerMethodField()
    verification_keys = serializers.SerializerMethodField()
    breakglass = serializers.SerializerMethodField()

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
            "verification_plan_id",
            "verification_keys",
            "breakglass",
        ]

    def _get_binding(self, obj):
        # Cache per serializer instance — _get_binding is called once per field.
        try:
            return self.__binding_cache
        except AttributeError:
            pass
        result = self.__load_binding(obj)
        self.__binding_cache = result
        return result

    def __load_binding(self, obj):
        try:
            binding = obj.change_binding
        except Exception:
            return None
        if binding.bound_at is not None:
            return None
        from django.utils import timezone

        now = timezone.now()
        if binding.dispatch_token_expires_at <= now:
            # Dispatch window expired.  Ensure the change lifecycle is updated
            # so the change does not remain stranded in 'dispatchable'.
            if binding.change_record.status == "dispatchable":
                try:
                    from apps.changes import services as change_services

                    change_services.expire_dispatchable_change(
                        change=binding.change_record,
                        now=now,
                        terminal_reason="dispatch_token_expired",
                    )
                except Exception:
                    logger.exception(
                        "Failed to expire dispatchable change %s at claim serialization",
                        binding.change_record_id,
                    )
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

    def get_verification_plan_id(self, obj):
        binding = self._get_binding(obj)
        if binding is None:
            return None
        try:
            plan = binding.change_record.verification_plan
        except Exception:
            return None
        return str(plan.id)

    def get_verification_keys(self, obj):
        binding = self._get_binding(obj)
        if binding is None:
            return []
        try:
            plan = binding.change_record.verification_plan
        except Exception:
            return []
        checks = plan.checks.filter(
            check_type__in=["runner_step", "artifact_presence"]
        ).exclude(verification_key="")
        return [
            {
                "check_key": check.key,
                "verification_key": check.verification_key,
                "step_key": check.source_step_key,
                "check_type": check.check_type,
            }
            for check in checks.order_by("position")
        ]

    def get_breakglass(self, obj):
        """Return sanitized breakglass session facts if an active session exists."""
        binding = self._get_binding(obj)
        if binding is None:
            return None
        try:
            from apps.changes.models import BreakglassSession
            from apps.changes.services import _build_scope_summary

            session = BreakglassSession.objects.get(
                change_record=binding.change_record,
                status=BreakglassSession.Status.ACTIVE,
            )
        except Exception:
            return None
        return {
            "breakglass_session_id": str(session.id),
            "scope_sha256": session.scope_sha256,
            "scope_summary": _build_scope_summary(session.scope_json),
            "started_at": session.started_at,
            "expires_at": session.expires_at,
            "review_due_at": session.review_due_at,
        }


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
    status = serializers.ChoiceField(choices=["succeeded", "failed", "skipped"])
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
