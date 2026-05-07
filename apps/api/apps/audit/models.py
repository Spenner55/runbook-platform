from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import BaseModel


class AuditEventQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Audit events are append-only and cannot be deleted.")

    def update(self, **kwargs):
        raise ValidationError("Audit events are append-only and cannot be updated.")


class AuditEvent(BaseModel):
    class ActorType(models.TextChoices):
        USER = "user", "User"
        RUNNER = "runner", "Runner"
        SYSTEM = "system", "System"
        API_CLIENT = "api_client", "API Client"
        UNKNOWN = "unknown", "Unknown"

    class ObjectType(models.TextChoices):
        ORGANIZATION = "organization", "Organization"
        RUNBOOK = "runbook", "Runbook"
        WORKFLOW = "workflow", "Workflow"
        EXECUTION = "execution", "Execution"
        EXECUTION_STEP = "execution_step", "Execution Step"
        APPROVAL_REQUEST = "approval_request", "Approval Request"
        APPROVAL_DECISION = "approval_decision", "Approval Decision"
        POLICY = "policy", "Policy"
        POLICY_RULE = "policy_rule", "Policy Rule"
        POLICY_EVALUATION = "policy_evaluation", "Policy Evaluation"
        ARTIFACT = "artifact", "Artifact"
        INTEGRATION_CONNECTION = "integration_connection", "Integration Connection"
        OPERATION_PROFILE = "operation_profile", "Operation Profile"
        CHANGE_RECORD = "change_record", "Change Record"
        CHANGE_TARGET = "change_target", "Change Target"
        CHANGE_EXECUTION_BINDING = (
            "change_execution_binding",
            "Change Execution Binding",
        )
        CHANGE_WINDOW = "change_window", "Change Window"
        FREEZE_RULE = "freeze_rule", "Freeze Rule"
        TARGET_LOCK = "target_lock", "Target Lock"
        DISPATCH_ELIGIBILITY_CHECK = (
            "dispatch_eligibility_check",
            "Dispatch Eligibility Check",
        )
        VERIFICATION_PLAN = "verification_plan", "Verification Plan"
        VERIFICATION_CHECK = "verification_check", "Verification Check"
        VERIFICATION_RESULT = "verification_result", "Verification Result"
        CHANGE_CLOSURE = "change_closure", "Change Closure"
        CHANGE_EXCEPTION = "change_exception", "Change Exception"
        BREAKGLASS_SESSION = "breakglass_session", "Breakglass Session"
        RETRO_REVIEW = "retro_review", "Retro Review"
        EVIDENCE_BUNDLE = "evidence_bundle", "Evidence Bundle"
        EVIDENCE_BUNDLE_ITEM = "evidence_bundle_item", "Evidence Bundle Item"
        EVIDENCE_REDACTION_POLICY = (
            "evidence_redaction_policy",
            "Evidence Redaction Policy",
        )
        EVIDENCE_EXPORT = "evidence_export", "Evidence Export"
        EVIDENCE_RETENTION_POLICY = (
            "evidence_retention_policy",
            "Evidence Retention Policy",
        )
        LEGAL_HOLD = "legal_hold", "Legal Hold"

    actor_type = models.CharField(max_length=32, choices=ActorType.choices)
    actor_id = models.CharField(max_length=255, blank=True)
    actor_label = models.CharField(max_length=255, blank=True)
    event_type = models.CharField(max_length=128)
    object_type = models.CharField(max_length=64, choices=ObjectType.choices)
    object_id = models.UUIDField()
    organization_id = models.UUIDField()
    metadata = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-occurred_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["organization_id", "occurred_at"],
                name="audit_org_occurred_idx",
            ),
            models.Index(
                fields=["organization_id", "-occurred_at"],
                name="audit_org_occurred_desc_idx",
            ),
            models.Index(
                fields=["object_type", "object_id", "occurred_at"],
                name="audit_object_occurred_idx",
            ),
            models.Index(
                fields=["event_type", "occurred_at"],
                name="audit_event_occurred_idx",
            ),
            models.Index(
                fields=["actor_type", "actor_id", "occurred_at"],
                name="audit_actor_occurred_idx",
            ),
            models.Index(
                fields=["organization_id", "event_type", "occurred_at"],
                name="audit_org_event_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    actor_type__in=[
                        "user",
                        "runner",
                        "system",
                        "api_client",
                        "unknown",
                    ]
                ),
                name="audit_actor_type_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    object_type__in=[
                        "organization",
                        "runbook",
                        "workflow",
                        "execution",
                        "execution_step",
                        "approval_request",
                        "approval_decision",
                        "policy",
                        "policy_rule",
                        "policy_evaluation",
                        "artifact",
                        "integration_connection",
                        "operation_profile",
                        "change_record",
                        "change_target",
                        "change_execution_binding",
                        "change_window",
                        "freeze_rule",
                        "target_lock",
                        "dispatch_eligibility_check",
                        "verification_plan",
                        "verification_check",
                        "verification_result",
                        "change_closure",
                        "change_exception",
                        "breakglass_session",
                        "retro_review",
                        "evidence_bundle",
                        "evidence_bundle_item",
                        "evidence_redaction_policy",
                        "evidence_export",
                        "evidence_retention_policy",
                        "legal_hold",
                    ]
                ),
                name="audit_object_type_valid_chk",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit events are append-only and cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only and cannot be deleted.")

    def __str__(self):
        return f"{self.event_type} on {self.object_type}:{self.object_id}"
