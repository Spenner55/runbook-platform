from django.db import models

from apps.common.models import BaseModel


class OperationProfile(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="operation_profiles",
    )
    key = models.CharField(max_length=96)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    risk_level = models.CharField(max_length=32)
    requires_approval = models.BooleanField(default=True)
    verification_required = models.BooleanField(default=True)
    approval_ttl_seconds = models.PositiveIntegerField(null=True, blank=True)
    dispatch_ttl_seconds = models.PositiveIntegerField(default=900)
    allowed_target_types = models.JSONField(default=list)
    requested_inputs_schema = models.JSONField(default=dict)
    target_schema = models.JSONField(default=dict)
    allowed_workflows = models.ManyToManyField(
        "workflows.Workflow",
        blank=True,
        related_name="operation_profiles",
    )
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_operation_profiles",
    )
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_operation_profiles",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"],
                name="op_profile_org_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(risk_level__in=["high", "critical"]),
                name="op_profile_risk_level_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "key"],
                name="op_profile_org_active_key_idx",
            ),
        ]

    def __str__(self):
        return f"OperationProfile {self.key}"


class ChangeRecord(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        APPROVED = "approved", "Approved"
        SCHEDULED = "scheduled", "Scheduled"
        DISPATCHABLE = "dispatchable", "Dispatchable"
        RUNNING = "running", "Running"
        VERIFICATION_PENDING = "verification_pending", "Verification Pending"
        VERIFIED = "verified", "Verified"
        CLOSED = "closed", "Closed"
        REJECTED = "rejected", "Rejected"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="change_records",
    )
    operation_profile = models.ForeignKey(
        OperationProfile,
        on_delete=models.PROTECT,
        related_name="change_records",
    )
    workflow = models.ForeignKey(
        "workflows.Workflow",
        on_delete=models.PROTECT,
        related_name="change_records",
    )
    requested_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_changes",
    )
    submitted_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="submitted_changes",
    )
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    justification = models.TextField(blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    requested_inputs = models.JSONField(default=dict)
    requested_inputs_sha256 = models.CharField(max_length=64, blank=True)
    request_snapshot = models.JSONField(default=dict)
    request_snapshot_sha256 = models.CharField(max_length=64, blank=True)
    operation_profile_key_snapshot = models.CharField(max_length=96, blank=True)
    workflow_version_snapshot = models.PositiveIntegerField(null=True, blank=True)
    approval_request = models.ForeignKey(
        "approvals.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="change_records",
    )
    policy_evaluation = models.ForeignKey(
        "policies.PolicyEvaluation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="change_records",
    )
    policy_decision_snapshot = models.JSONField(default=dict)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    dispatchable_at = models.DateTimeField(null=True, blank=True)
    running_at = models.DateTimeField(null=True, blank=True)
    verification_pending_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    terminal_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["organization", "status", "created_at"],
                name="chgrec_org_status_created_idx",
            ),
            models.Index(
                fields=["organization", "operation_profile", "status"],
                name="chgrec_org_profile_status_idx",
            ),
            models.Index(
                fields=["approval_request"],
                name="change_rec_approval_req_idx",
            ),
            models.Index(
                fields=["workflow", "status"],
                name="change_rec_workflow_status_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "pending_approval",
                        "approved",
                        "scheduled",
                        "dispatchable",
                        "running",
                        "verification_pending",
                        "verified",
                        "closed",
                        "rejected",
                        "canceled",
                        "expired",
                    ]
                ),
                name="change_rec_status_valid_chk",
            ),
        ]

    def __str__(self):
        return f"ChangeRecord {self.id} [{self.status}]"


class ChangeTarget(BaseModel):
    change_record = models.ForeignKey(
        ChangeRecord,
        on_delete=models.CASCADE,
        related_name="targets",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="change_targets",
    )
    position = models.PositiveIntegerField()
    target_type = models.CharField(max_length=64)
    target_identifier = models.CharField(max_length=255)
    normalized_identifier = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True)
    environment = models.CharField(max_length=32)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["change_record", "target_type", "normalized_identifier"],
                name="change_target_unique_type_id",
            ),
            models.UniqueConstraint(
                fields=["change_record", "position"],
                name="change_target_unique_position",
            ),
            models.CheckConstraint(
                condition=models.Q(environment="production"),
                name="change_target_env_production_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "target_type", "normalized_identifier"],
                name="change_target_org_type_id_idx",
            ),
        ]

    def __str__(self):
        return f"ChangeTarget {self.target_type}:{self.target_identifier}"


class ChangeExecutionBinding(BaseModel):
    change_record = models.OneToOneField(
        ChangeRecord,
        on_delete=models.PROTECT,
        related_name="execution_binding",
    )
    execution = models.OneToOneField(
        "executions.Execution",
        on_delete=models.PROTECT,
        related_name="change_binding",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="change_execution_bindings",
    )
    operation_profile_key = models.CharField(max_length=96)
    requested_inputs_sha256 = models.CharField(max_length=64)
    dispatch_token_nonce = models.CharField(max_length=128)
    dispatch_token_hash = models.CharField(max_length=128)
    dispatch_token_expires_at = models.DateTimeField()
    reserved_at = models.DateTimeField()
    bound_at = models.DateTimeField(null=True, blank=True)
    bound_by_runner_id = models.CharField(max_length=255, blank=True)
    runner_payload_snapshot = models.JSONField(default=dict)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "reserved_at"],
                name="chgexecbind_org_reserved_idx",
            ),
            models.Index(
                fields=["dispatch_token_expires_at"],
                name="change_exec_binding_exp_idx",
            ),
        ]

    def __str__(self):
        return f"ChangeExecutionBinding {self.id}"
