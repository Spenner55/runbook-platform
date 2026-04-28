from rest_framework import serializers

from apps.executions.models import Execution, ExecutionStep

# ---------------------------------------------------------------------------
# Public serializers
# ---------------------------------------------------------------------------


class ExecutionStepSerializer(serializers.ModelSerializer):
    policy_evaluation = serializers.SerializerMethodField()

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
            "started_at",
            "finished_at",
            "exit_code",
            "error_message",
            "policy_evaluation",
        ]

    def get_policy_evaluation(self, obj):
        # Expects policy_evaluations to be prefetched with to_attr="latest_policy_evaluation"
        # Falls back to a DB query if not prefetched
        if hasattr(obj, "latest_policy_evaluation"):
            evals = obj.latest_policy_evaluation
            if not evals:
                return None
            evaluation = evals[0]
        else:
            evaluation = obj.policy_evaluations.order_by("-evaluated_at").first()
            if evaluation is None:
                return None

        # Inline to avoid circular import; import here is safe
        from apps.policies.serializers import PolicyEvaluationSummarySerializer

        return PolicyEvaluationSummarySerializer(evaluation).data


class ExecutionCreateSerializer(serializers.Serializer):
    workflow_id = serializers.UUIDField()


class ExecutionListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Execution
        fields = [
            "id",
            "status",
            "workflow_id",
            "organization_id",
            "workflow_version",
            "claimed_by_runner_id",
            "claimed_at",
            "last_heartbeat_at",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        ]


class ExecutionDetailSerializer(serializers.ModelSerializer):
    steps = ExecutionStepSerializer(many=True, read_only=True)
    claim_token_present = serializers.SerializerMethodField()

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
            "claim_token_present",
            "claimed_at",
            "last_heartbeat_at",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
            "steps",
        ]

    def get_claim_token_present(self, obj):
        return obj.claim_token is not None


class ExecutionCancelSerializer(serializers.Serializer):
    pass
