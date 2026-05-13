from django.db import models

from apps.common.models import BaseModel


class RunnerPool(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DRAINING = "draining", "Draining"
        DISABLED = "disabled", "Disabled"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="runner_pools",
    )
    key = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    environment = models.CharField(max_length=32, default="production")
    network_zone = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    max_concurrent_executions = models.PositiveIntegerField(default=1)
    max_concurrent_per_target = models.PositiveIntegerField(default=1)
    labels = models.JSONField(default=dict)
    capabilities = models.JSONField(default=list)
    metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key"],
                name="runner_pool_org_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "draining", "disabled"]),
                name="runner_pool_status_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status"],
                name="runner_pool_org_status_idx",
            ),
        ]

    def __str__(self):
        return f"RunnerPool {self.key} [{self.status}]"


class Runner(BaseModel):
    class Status(models.TextChoices):
        REGISTERED = "registered", "Registered"
        ACTIVE = "active", "Active"
        DRAINING = "draining", "Draining"
        OFFLINE = "offline", "Offline"
        DISABLED = "disabled", "Disabled"
        REVOKED = "revoked", "Revoked"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="runners",
    )
    pool = models.ForeignKey(
        RunnerPool,
        on_delete=models.PROTECT,
        related_name="runners",
    )
    display_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.REGISTERED,
    )
    runner_version = models.CharField(max_length=64, blank=True)
    hostname = models.CharField(max_length=255, blank=True)
    fingerprint_sha256 = models.CharField(max_length=64, blank=True)
    token_hash = models.CharField(max_length=128)
    registered_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    drain_requested_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "registered",
                        "active",
                        "draining",
                        "offline",
                        "disabled",
                        "revoked",
                    ]
                ),
                name="runner_status_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "pool", "status", "last_heartbeat_at"],
                name="runner_org_pool_status_hb_idx",
            ),
        ]

    def __str__(self):
        return f"Runner {self.display_name} [{self.status}]"


class RunnerRegistrationToken(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="runner_registration_tokens",
    )
    pool = models.ForeignKey(
        RunnerPool,
        on_delete=models.PROTECT,
        related_name="registration_tokens",
    )
    token_hash = models.CharField(max_length=128)
    label_policy = models.JSONField(default=list)
    capability_policy = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    max_registrations = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_registration_tokens",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "pool", "expires_at"],
                name="reg_token_org_pool_exp_idx",
            ),
            models.Index(
                fields=["organization", "revoked_at"],
                name="reg_token_org_revoked_idx",
            ),
        ]

    def __str__(self):
        return f"RunnerRegistrationToken {self.id}"


class TargetConnectivityRoute(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="target_connectivity_routes",
    )
    environment = models.CharField(max_length=32, default="production")
    target_type = models.CharField(max_length=64)
    normalized_identifier_pattern = models.CharField(max_length=255)
    pool = models.ForeignKey(
        RunnerPool,
        on_delete=models.PROTECT,
        related_name="connectivity_routes",
    )
    required_labels = models.JSONField(default=dict)
    required_capabilities = models.JSONField(default=list)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "environment", "target_type", "is_active"],
                name="tcr_org_env_type_active_idx",
            ),
            models.Index(
                fields=["organization", "pool", "is_active"],
                name="tcr_org_pool_active_idx",
            ),
        ]

    def __str__(self):
        return f"TargetConnectivityRoute {self.target_type}:{self.normalized_identifier_pattern}"


class ExecutionLease(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"
        EXPIRED = "expired", "Expired"

    execution = models.OneToOneField(
        "executions.Execution",
        on_delete=models.PROTECT,
        related_name="lease",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="execution_leases",
    )
    runner = models.ForeignKey(
        Runner,
        on_delete=models.PROTECT,
        related_name="execution_leases",
    )
    pool = models.ForeignKey(
        RunnerPool,
        on_delete=models.PROTECT,
        related_name="execution_leases",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    claimed_at = models.DateTimeField()
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "released", "expired"]),
                name="exec_lease_status_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "pool", "status"],
                name="exec_lease_org_pool_status_idx",
            ),
            models.Index(
                fields=["runner", "status"],
                name="exec_lease_runner_status_idx",
            ),
            models.Index(
                fields=["status", "last_heartbeat_at"],
                name="exec_lease_status_hb_idx",
            ),
        ]

    def __str__(self):
        return f"ExecutionLease {self.execution_id} [{self.status}]"
