from django.db import models

from apps.common.models import BaseModel


class ApprovalRequest(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        TIMED_OUT = "timed_out", "Timed Out"

    class SubjectType(models.TextChoices):
        EXECUTION_STEP = "execution_step", "Execution Step"
        CHANGE_RECORD = "change_record", "Change Record"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="approval_requests",
    )
    subject_type = models.CharField(
        max_length=32,
        choices=SubjectType.choices,
        default=SubjectType.EXECUTION_STEP,
    )
    subject_id = models.UUIDField(null=True, blank=True)
    execution = models.ForeignKey(
        "executions.Execution",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="approval_requests",
    )
    step = models.OneToOneField(
        "executions.ExecutionStep",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="approval_request",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    requested_by_runner_id = models.CharField(max_length=255)
    requested_at = models.DateTimeField()
    timeout_seconds = models.PositiveIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(
                fields=["organization", "status", "requested_at"],
                name="approval_req_org_status_idx",
            ),
            models.Index(
                fields=["status", "requested_at"],
                name="approval_req_status_req_idx",
            ),
            models.Index(
                fields=["execution", "status"],
                name="approval_req_exec_status_idx",
            ),
            models.Index(
                fields=["status", "expires_at"],
                name="approval_req_expires_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["pending", "approved", "rejected", "timed_out"]
                ),
                name="approval_req_status_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    subject_type__in=["execution_step", "change_record"]
                ),
                name="approval_req_subject_type_valid_chk",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        subject_type="execution_step",
                        execution_id__isnull=False,
                        step_id__isnull=False,
                    )
                    | models.Q(
                        subject_type="change_record",
                        subject_id__isnull=False,
                        execution_id__isnull=True,
                        step_id__isnull=True,
                    )
                ),
                name="approval_req_subject_integrity_chk",
            ),
        ]

    def __str__(self):
        return f"ApprovalRequest {self.id} [{self.status}]"


class ApprovalDecision(BaseModel):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        TIMED_OUT = "timed_out", "Timed Out"

    class SourceType(models.TextChoices):
        HUMAN = "human", "Human"
        SYSTEM = "system", "System"

    approval_request = models.OneToOneField(
        ApprovalRequest,
        on_delete=models.CASCADE,
        related_name="decision",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    decided_by_user = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_decisions",
    )
    decided_by_label = models.CharField(max_length=255, blank=True)
    decided_by_label_source = models.CharField(
        max_length=64, default="unverified_pre_auth"
    )
    notes = models.TextField(blank=True)
    decided_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(
                fields=["decision", "decided_at"],
                name="approval_dec_decision_idx",
            ),
            models.Index(
                fields=["decided_by_user", "decided_at"],
                name="approval_dec_user_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(decision__in=["approved", "rejected", "timed_out"]),
                name="approval_dec_decision_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(source_type__in=["human", "system"]),
                name="approval_dec_source_valid_chk",
            ),
        ]

    def __str__(self):
        return f"ApprovalDecision {self.id} [{self.decision}]"
