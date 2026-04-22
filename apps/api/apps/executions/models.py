from django.db import models

from apps.common.models import BaseModel


class Execution(BaseModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        CLAIMED = "claimed", "Claimed"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="executions",
    )
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.PROTECT,
        related_name="executions",
    )
    workflow_version = models.PositiveIntegerField()
    workflow_snapshot = models.JSONField(default=dict)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # Runner ownership fields — set when a runner claims this execution
    claimed_by_runner_id = models.CharField(max_length=255, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="exec_status_created_idx"),
            models.Index(fields=["organization", "created_at"], name="exec_org_created_idx"),
            models.Index(fields=["workflow", "created_at"], name="exec_workflow_created_idx"),
        ]

    def __str__(self):
        return f"Execution {self.id} [{self.status}]"


class ExecutionStep(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    execution = models.ForeignKey(
        Execution,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    position = models.PositiveIntegerField()
    step_key = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    step_type = models.CharField(max_length=64)
    risk_level = models.CharField(max_length=32)
    command = models.TextField(blank=True)
    requires_approval = models.BooleanField(default=False)
    step_snapshot = models.JSONField(default=dict)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["position"]
        indexes = [
            models.Index(
                fields=["execution", "status", "position"],
                name="step_exec_status_pos_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["execution", "position"],
                name="unique_step_position_per_execution",
            ),
            models.UniqueConstraint(
                fields=["execution", "step_key"],
                name="unique_step_key_per_execution",
            ),
        ]

    def __str__(self):
        return f"Step {self.position}: {self.name} [{self.status}]"
