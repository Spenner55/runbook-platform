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
            "requires_approval",
            "status",
            "started_at",
            "finished_at",
            "exit_code",
            "error_message",
            "policy_evaluation",
            "failure_kind",
            "timed_out",
            "cancelled",
            "sandbox_provider",
            "sandbox_run_id",
            "result_metadata",
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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field in ("sandbox_provider", "sandbox_run_id", "failure_kind"):
            if data.get(field) == "":
                data[field] = None
        return data


class ExecutionCreateSerializer(serializers.Serializer):
    workflow_id = serializers.UUIDField()
    mode = serializers.ChoiceField(
        choices=["live", "dry_run"],
        default="live",
        required=False,
    )


class ExecutionListSerializer(serializers.ModelSerializer):
    workflow_name = serializers.SerializerMethodField()

    class Meta:
        model = Execution
        fields = [
            "id",
            "status",
            "execution_mode",
            "workflow_id",
            "workflow_name",
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

    def get_workflow_name(self, obj):
        # _workflow_name is annotated by the list view queryset via scalar
        # subquery to avoid fetching the large workflow_snapshot JSON field.
        annotated = getattr(obj, "_workflow_name", None)
        if annotated:
            return annotated
        # Fallback when called outside the list view (e.g. in tests that
        # construct executions without the annotation).
        if "workflow_snapshot" in obj.__dict__:
            name = obj.workflow_snapshot.get("name")
            if name:
                return name
        return obj.workflow.name


class ExecutionDetailSerializer(serializers.ModelSerializer):
    steps = ExecutionStepSerializer(many=True, read_only=True)
    claim_token_present = serializers.SerializerMethodField()

    class Meta:
        model = Execution
        fields = [
            "id",
            "status",
            "execution_mode",
            "workflow_id",
            "organization_id",
            "workflow_version",
            "workflow_snapshot",
            "workflow_snapshot_hash_sha256",
            "claimed_by_runner_id",
            "claim_token_present",
            "claimed_at",
            "last_heartbeat_at",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
            "cancel_requested_at",
            "cancel_requested_by",
            "cancel_reason",
            "steps",
        ]

    def get_claim_token_present(self, obj):
        return obj.claim_token is not None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for field in ("cancel_requested_by", "cancel_reason"):
            if data.get(field) == "":
                data[field] = None
        # Strip command from workflow_snapshot steps — commands may contain inline secrets.
        snapshot = data.get("workflow_snapshot")
        if snapshot and isinstance(snapshot.get("steps"), list):
            for step in snapshot["steps"]:
                step.pop("command", None)
        return data


class ExecutionCancelSerializer(serializers.Serializer):
    pass
