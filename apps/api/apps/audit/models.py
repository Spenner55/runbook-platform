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

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit events are append-only and cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only and cannot be deleted.")

    def __str__(self):
        return f"{self.event_type} on {self.object_type}:{self.object_id}"
