from rest_framework import serializers

from apps.common.exceptions import DomainValidationError
from apps.policies import services
from apps.policies.models import Policy, PolicyEvaluation, PolicyRule


class PolicyEvaluationSummarySerializer(serializers.ModelSerializer):
    policy_id = serializers.UUIDField(allow_null=True, read_only=True)
    policy_name = serializers.SerializerMethodField()
    rule_id = serializers.UUIDField(allow_null=True, read_only=True)
    rule_name = serializers.SerializerMethodField()

    class Meta:
        model = PolicyEvaluation
        fields = [
            "id",
            "outcome",
            "effective_outcome",
            "decision_source",
            "matched",
            "policy_id",
            "policy_name",
            "rule_id",
            "rule_name",
            "reason",
            "evaluated_at",
        ]

    def get_policy_name(self, obj):
        return obj.policy.name if obj.policy_id else None

    def get_rule_name(self, obj):
        return obj.rule.name if obj.rule_id else None


class PolicyEvaluationDetailSerializer(PolicyEvaluationSummarySerializer):
    class Meta(PolicyEvaluationSummarySerializer.Meta):
        fields = PolicyEvaluationSummarySerializer.Meta.fields + [
            "step_id",
            "condition_type",
            "condition_params_snapshot",
            "context_snapshot",
            "error_code",
            "error_message",
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["step_id"] = str(instance.step_id)
        step_key = instance.context_snapshot.get("step_key", "")
        ret["step_key"] = step_key
        return ret


# ---------------------------------------------------------------------------
# PolicyRule serializers
# ---------------------------------------------------------------------------


class PolicyRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyRule
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "priority",
            "condition_type",
            "condition_params",
            "outcome",
            "reason",
            "created_at",
            "updated_at",
        ]


class PolicyRuleCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(min_value=1)
    condition_type = serializers.ChoiceField(
        choices=[ct.value for ct in PolicyRule.ConditionType]
    )
    condition_params = serializers.JSONField()
    outcome = serializers.ChoiceField(choices=[o.value for o in PolicyRule.Outcome])
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        try:
            services._validate_condition_params(
                data["condition_type"], data["condition_params"]
            )
        except DomainValidationError as exc:
            raise serializers.ValidationError({"condition_params": exc.detail})
        return data


class PolicyRuleUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    priority = serializers.IntegerField(min_value=1, required=False)
    condition_type = serializers.ChoiceField(
        choices=[ct.value for ct in PolicyRule.ConditionType], required=False
    )
    condition_params = serializers.JSONField(required=False)
    outcome = serializers.ChoiceField(
        choices=[o.value for o in PolicyRule.Outcome], required=False
    )
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        ct = data.get("condition_type") or getattr(
            self.context.get("rule"), "condition_type", None
        )
        cp = data.get("condition_params") or getattr(
            self.context.get("rule"), "condition_params", None
        )
        if ct and cp is not None:
            try:
                services._validate_condition_params(ct, cp)
            except DomainValidationError as exc:
                raise serializers.ValidationError({"condition_params": exc.detail})
        return data


# ---------------------------------------------------------------------------
# Policy serializers
# ---------------------------------------------------------------------------


class PolicyListSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    rule_count = serializers.SerializerMethodField()

    class Meta:
        model = Policy
        fields = [
            "id",
            "organization_id",
            "name",
            "description",
            "is_active",
            "rule_count",
            "created_at",
            "updated_at",
        ]

    def get_rule_count(self, obj):
        if (
            hasattr(obj, "_prefetched_objects_cache")
            and "rules" in obj._prefetched_objects_cache
        ):
            return obj.rules.count()
        return obj.rules.filter(is_active=True).count()


class PolicyDetailSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(read_only=True)
    rules = serializers.SerializerMethodField()

    class Meta:
        model = Policy
        fields = [
            "id",
            "organization_id",
            "name",
            "description",
            "is_active",
            "rules",
            "created_at",
            "updated_at",
        ]

    def get_rules(self, obj):
        rules = obj.rules.order_by("priority")
        return PolicyRuleSerializer(rules, many=True).data


class PolicyCreateSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField()
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)


class PolicyUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
