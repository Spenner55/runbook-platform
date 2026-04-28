from django.db import models

from apps.common.models import BaseModel


class Policy(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="policies",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by_label = models.CharField(max_length=255, blank=True)
    updated_by_label = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "is_active", "name"]),
            models.Index(fields=["organization", "created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class PolicyRule(BaseModel):
    class ConditionType(models.TextChoices):
        RISK_LEVEL = "risk_level", "Risk Level"
        STEP_TYPE = "step_type", "Step Type"
        TIME_WINDOW = "time_window", "Time Window"

    class Outcome(models.TextChoices):
        APPROVAL_REQUIRED = "approval_required", "Approval Required"
        AUTO_APPROVE = "auto_approve", "Auto Approve"
        BLOCK = "block", "Block"

    policy = models.ForeignKey(
        Policy,
        on_delete=models.CASCADE,
        related_name="rules",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField()
    condition_type = models.CharField(max_length=32, choices=ConditionType.choices)
    condition_params = models.JSONField(default=dict)
    outcome = models.CharField(max_length=32, choices=Outcome.choices)
    reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["policy", "is_active", "priority"]),
            models.Index(fields=["condition_type", "outcome"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "priority"], name="unique_policy_rule_priority"
            ),
            models.UniqueConstraint(
                fields=["policy", "name"], name="unique_policy_rule_name"
            ),
        ]

    def __str__(self):
        return f"{self.name} (priority={self.priority}, outcome={self.outcome})"


class PolicyEvaluation(BaseModel):
    class DecisionSource(models.TextChoices):
        POLICY_RULE = "policy_rule", "Policy Rule"
        WORKFLOW_DEFAULT = "workflow_default", "Workflow Default"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="policy_evaluations",
    )
    execution = models.ForeignKey(
        "executions.Execution",
        on_delete=models.CASCADE,
        related_name="policy_evaluations",
    )
    step = models.ForeignKey(
        "executions.ExecutionStep",
        on_delete=models.CASCADE,
        related_name="policy_evaluations",
    )
    policy = models.ForeignKey(
        Policy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )
    rule = models.ForeignKey(
        PolicyRule,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evaluations",
    )
    matched = models.BooleanField()
    outcome = models.CharField(max_length=32)
    effective_outcome = models.CharField(max_length=32)
    decision_source = models.CharField(max_length=32, choices=DecisionSource.choices)
    condition_type = models.CharField(max_length=32, blank=True)
    condition_params_snapshot = models.JSONField(default=dict)
    context_snapshot = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    evaluated_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["organization", "evaluated_at"]),
            models.Index(fields=["execution", "evaluated_at"]),
            models.Index(fields=["step", "evaluated_at"]),
            models.Index(fields=["policy", "rule", "evaluated_at"]),
            models.Index(fields=["outcome", "evaluated_at"]),
        ]

    def __str__(self):
        return f"PolicyEvaluation({self.effective_outcome}) for step={self.step_id}"
