from django.core.exceptions import ValidationError
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
    workflow_definition_sha256 = models.CharField(max_length=64, blank=True)
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

    # Freeze exception fields — support for allow_with_exception freeze rules only.
    # These are NOT breakglass; they satisfy freeze exception requirements but do not
    # bypass approval, policy, window, target lock, or authorization checks.
    freeze_exception_reference = models.CharField(max_length=255, blank=True)
    freeze_exception_reason = models.TextField(blank=True)
    freeze_exception_recorded_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_freeze_exceptions",
    )
    freeze_exception_recorded_at = models.DateTimeField(null=True, blank=True)

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

    def clean(self):
        super().clean()
        if (
            self.operation_profile_id
            and self.organization_id
            and self.operation_profile.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Change operation profile must belong to the same organization."
            )
        if (
            self.workflow_id
            and self.organization_id
            and self.workflow.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Change workflow must belong to the same organization."
            )

    # Fields frozen at submit time — cannot be altered after status leaves draft.
    IMMUTABLE_AFTER_SUBMIT = (
        "operation_profile_id",
        "workflow_id",
        "title",
        "summary",
        "justification",
        "requested_inputs",
        "scheduled_for",
        "requested_inputs_sha256",
        "request_snapshot",
        "request_snapshot_sha256",
        "operation_profile_key_snapshot",
        "workflow_version_snapshot",
    )

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None and previous.status != self.Status.DRAFT:
                changed = [
                    f
                    for f in self.IMMUTABLE_AFTER_SUBMIT
                    if getattr(previous, f) != getattr(self, f)
                ]
                if changed:
                    raise ValidationError(
                        f"Change request content is immutable after submit "
                        f"(attempted to change: {changed}).",
                        code="change_request_immutable",
                    )
        self.clean()
        return super().save(*args, **kwargs)


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

    def clean(self):
        super().clean()
        change = None
        if self.change_record_id:
            change = ChangeRecord.objects.only("organization_id", "status").get(
                pk=self.change_record_id
            )
        if (
            self.change_record_id
            and self.organization_id
            and change.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Change target organization must match the change organization."
            )

        if self.change_record_id and change.status != ChangeRecord.Status.DRAFT:
            raise ValidationError(
                "Change targets are immutable after submit.",
                code="change_request_immutable",
            )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        change = ChangeRecord.objects.only("status").get(pk=self.change_record_id)
        if change.status != ChangeRecord.Status.DRAFT:
            raise ValidationError(
                "Change targets are immutable after submit.",
                code="change_request_immutable",
            )
        return super().delete(*args, **kwargs)


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
    execution_accepted_at = models.DateTimeField(null=True, blank=True)
    execution_started_at = models.DateTimeField(null=True, blank=True)
    execution_finished_at = models.DateTimeField(null=True, blank=True)

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

    def clean(self):
        super().clean()
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Binding organization must match the change organization."
            )
        if (
            self.execution_id
            and self.organization_id
            and self.execution.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Binding organization must match the execution organization."
            )
        if (
            self.change_record_id
            and self.execution_id
            and self.change_record.organization_id != self.execution.organization_id
        ):
            raise ValidationError(
                "Binding change and execution organizations must match."
            )

    _IMMUTABLE_AFTER_CREATION = frozenset(
        [
            "change_record_id",
            "execution_id",
            "organization_id",
            "operation_profile_key",
            "requested_inputs_sha256",
        ]
    )

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None:
                for field in self._IMMUTABLE_AFTER_CREATION:
                    if getattr(previous, field) != getattr(self, field):
                        raise ValidationError(
                            f"ChangeExecutionBinding.{field} is immutable after creation."
                        )
                if (
                    previous.bound_at is not None
                    and previous.bound_by_runner_id != self.bound_by_runner_id
                ):
                    raise ValidationError("Bound change executions cannot be rebound.")
        self.clean()
        return super().save(*args, **kwargs)


class ChangeWindow(BaseModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        OPEN = "open", "Open"
        EXPIRED = "expired", "Expired"
        OVERRUN = "overrun", "Overrun"
        CLOSED = "closed", "Closed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="change_windows",
    )
    change_record = models.OneToOneField(
        ChangeRecord,
        on_delete=models.CASCADE,
        related_name="window",
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )
    timezone = models.CharField(max_length=64, blank=True)
    reason = models.TextField(blank=True)
    approved_snapshot_sha256 = models.CharField(max_length=64, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    overrun_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_change_windows",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["scheduled", "open", "expired", "overrun", "closed"]
                ),
                name="change_window_status_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="change_window_ends_after_starts_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "starts_at"],
                name="chgwin_org_status_start_idx",
            ),
            models.Index(
                fields=["organization", "ends_at"],
                name="change_window_org_ends_idx",
            ),
        ]

    def __str__(self):
        return f"ChangeWindow {self.id} [{self.status}]"

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("ends_at must be after starts_at.")
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "ChangeWindow organization must match the change organization."
            )


class FreezeRule(BaseModel):
    class Behavior(models.TextChoices):
        BLOCK = "block", "Block"
        ALLOW_WITH_EXCEPTION = "allow_with_exception", "Allow With Exception"

    class ScopeType(models.TextChoices):
        ALL_PRODUCTION = "all_production", "All Production"
        TARGET_TYPE = "target_type", "Target Type"
        TARGET_IDENTIFIER = "target_identifier", "Target Identifier"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="freeze_rules",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    behavior = models.CharField(max_length=32, choices=Behavior.choices)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    scope_type = models.CharField(max_length=32, choices=ScopeType.choices)
    target_type = models.CharField(max_length=64, blank=True)
    target_identifier = models.CharField(max_length=255, blank=True)
    normalized_identifier = models.CharField(max_length=255, blank=True)
    requires_exception_reference = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_freeze_rules",
    )
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_freeze_rules",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(behavior__in=["block", "allow_with_exception"]),
                name="freeze_rule_behavior_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    scope_type__in=["all_production", "target_type", "target_identifier"]
                ),
                name="freeze_rule_scope_type_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="freeze_rule_ends_after_starts_chk",
            ),
            # allow_with_exception requires requires_exception_reference=True
            models.CheckConstraint(
                condition=~models.Q(behavior="allow_with_exception")
                | models.Q(requires_exception_reference=True),
                name="freeze_rule_exception_behavior_requires_ref_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "starts_at", "ends_at"],
                name="freeze_org_active_range_idx",
            ),
            models.Index(
                fields=[
                    "organization",
                    "scope_type",
                    "target_type",
                    "normalized_identifier",
                ],
                name="freeze_org_scope_target_idx",
            ),
        ]

    def __str__(self):
        return f"FreezeRule {self.name} [{self.behavior}]"

    def clean(self):
        super().clean()
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError("ends_at must be after starts_at.")
        if (
            self.behavior == self.Behavior.ALLOW_WITH_EXCEPTION
            and not self.requires_exception_reference
        ):
            raise ValidationError(
                "allow_with_exception behavior requires requires_exception_reference=True."
            )


class TargetLock(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="target_locks",
    )
    change_record = models.ForeignKey(
        ChangeRecord,
        on_delete=models.PROTECT,
        related_name="target_locks",
    )
    execution = models.ForeignKey(
        "executions.Execution",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="target_locks",
    )
    change_target = models.ForeignKey(
        ChangeTarget,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="target_locks",
    )
    target_type = models.CharField(max_length=64)
    target_identifier = models.CharField(max_length=255)
    normalized_identifier = models.CharField(max_length=255)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    acquired_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "released", "expired"]),
                name="target_lock_status_valid_chk",
            ),
            # Partial unique: only one active lock per (org, target_type, normalized_identifier).
            # This is the DB-level concurrency guard; service preflight queries also check
            # for conflicts before insert to produce useful error messages.
            models.UniqueConstraint(
                fields=["organization", "target_type", "normalized_identifier"],
                condition=models.Q(status="active"),
                name="target_lock_active_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "acquired_at"],
                name="target_lock_org_status_acq_idx",
            ),
            models.Index(
                fields=["change_record", "status"],
                name="target_lock_change_status_idx",
            ),
            models.Index(
                fields=["execution", "status"],
                name="target_lock_exec_status_idx",
            ),
            models.Index(
                fields=[
                    "organization",
                    "target_type",
                    "normalized_identifier",
                    "status",
                ],
                name="tlock_org_type_id_status_idx",
            ),
        ]

    def __str__(self):
        return f"TargetLock {self.target_type}:{self.normalized_identifier} [{self.status}]"

    def clean(self):
        super().clean()
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "TargetLock organization must match the change organization."
            )


class DispatchEligibilityCheck(BaseModel):
    class Result(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="dispatch_eligibility_checks",
    )
    change_record = models.ForeignKey(
        ChangeRecord,
        on_delete=models.PROTECT,
        related_name="eligibility_checks",
    )
    requested_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_eligibility_checks",
    )
    result = models.CharField(max_length=16, choices=Result.choices)
    checked_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    approved_status_ok = models.BooleanField()
    policy_pass_ok = models.BooleanField()
    window_open_ok = models.BooleanField()
    freeze_conflicts_ok = models.BooleanField()
    target_locks_ok = models.BooleanField()
    actor_authorized_ok = models.BooleanField()
    checks = models.JSONField(default=list)
    conflicts = models.JSONField(default=list)
    input_snapshot_sha256 = models.CharField(max_length=64)
    window_snapshot_sha256 = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(result__in=["passed", "failed"]),
                name="dispatch_check_result_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "change_record", "checked_at"],
                name="dispatch_chk_org_chg_idx",
            ),
            models.Index(
                fields=["organization", "result", "checked_at"],
                name="dispatch_chk_org_res_idx",
            ),
            models.Index(
                fields=["expires_at"],
                name="dispatch_check_expires_idx",
            ),
        ]

    def __str__(self):
        return f"DispatchEligibilityCheck {self.id} [{self.result}]"

    def save(self, *args, **kwargs):
        # Immutable after creation — preflight results are append-only snapshots.
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "DispatchEligibilityCheck is immutable after creation."
            )
        return super().save(*args, **kwargs)
