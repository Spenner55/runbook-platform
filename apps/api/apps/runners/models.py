from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import BaseModel

SECRET_METADATA_KEY_FRAGMENTS = (
    "api_key",
    "auth",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)


def _validate_operational_metadata(value, *, field_name="metadata"):
    if not isinstance(value, dict):
        raise ValidationError({field_name: "Metadata must be a JSON object."})

    def walk(node, path="metadata"):
        if isinstance(node, dict):
            for key, child in node.items():
                normalized_key = str(key).lower()
                if any(
                    fragment in normalized_key
                    for fragment in SECRET_METADATA_KEY_FRAGMENTS
                ):
                    raise ValidationError(
                        {
                            field_name: (
                                f"Metadata key '{path}.{key}' looks secret-bearing; "
                                "store sanitized operational facts only."
                            )
                        }
                    )
                walk(child, f"{path}.{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    walk(value)


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
    display_name = models.CharField(max_length=255, blank=True)
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
    default_for_non_change_executions = models.BooleanField(default=False)
    labels = models.JSONField(default=dict, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    drain_requested_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

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
            models.CheckConstraint(
                condition=models.Q(max_concurrent_executions__gte=1),
                name="runner_pool_max_concurrent_gte_1_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(max_concurrent_per_target__gte=1),
                name="runner_pool_target_concurrent_gte_1_chk",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(default_for_non_change_executions=True),
                name="runner_pool_one_default_non_change_per_org",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status"],
                name="runner_pool_org_status_idx",
            ),
            models.Index(
                fields=["organization", "default_for_non_change_executions", "status"],
                name="runner_pool_org_default_idx",
            ),
        ]

    def clean(self):
        super().clean()
        _validate_operational_metadata(self.metadata)

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
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["token_hash"],
                name="runner_token_hash_unique",
            ),
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
                fields=["organization", "status"],
                name="runner_org_status_idx",
            ),
            models.Index(
                fields=["organization", "pool", "status", "last_heartbeat_at"],
                name="runner_org_pool_status_hb_idx",
            ),
            models.Index(
                fields=["pool", "status", "last_seen_at"],
                name="runner_pool_status_seen_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.organization_id
            and self.pool_id
            and self.pool.organization_id != self.organization_id
        ):
            raise ValidationError(
                {
                    "pool": "Runner pool must belong to the same organization as the runner."
                }
            )
        _validate_operational_metadata(self.metadata)

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
    label_policy = models.JSONField(default=list, blank=True)
    capability_policy = models.JSONField(default=list, blank=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=["token_hash"],
                name="runner_reg_token_hash_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(max_registrations__gte=1),
                name="runner_reg_max_registrations_gte_1_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(used_count__lte=models.F("max_registrations")),
                name="runner_reg_used_count_lte_max_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "pool", "expires_at"],
                name="reg_token_org_pool_exp_idx",
            ),
            models.Index(
                fields=["organization", "revoked_at"],
                name="reg_token_org_revoked_idx",
            ),
            models.Index(
                fields=["pool", "revoked_at", "expires_at"],
                name="reg_token_pool_usable_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.organization_id
            and self.pool_id
            and self.pool.organization_id != self.organization_id
        ):
            raise ValidationError(
                {
                    "pool": (
                        "Registration token pool must belong to the same organization "
                        "as the token."
                    )
                }
            )
        if self.used_count > self.max_registrations:
            raise ValidationError(
                {"used_count": "Used count cannot exceed max registrations."}
            )

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
    required_labels = models.JSONField(default=dict, blank=True)
    required_capabilities = models.JSONField(default=list, blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "environment",
                    "target_type",
                    "normalized_identifier_pattern",
                    "pool",
                ],
                name="tcr_org_env_type_pattern_pool_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "environment", "target_type", "is_active"],
                name="tcr_org_env_type_active_idx",
            ),
            models.Index(
                fields=["organization", "pool", "is_active"],
                name="tcr_org_pool_active_idx",
            ),
            models.Index(
                fields=[
                    "organization",
                    "environment",
                    "target_type",
                    "priority",
                    "is_active",
                ],
                name="tcr_sched_lookup_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.organization_id
            and self.pool_id
            and self.pool.organization_id != self.organization_id
        ):
            raise ValidationError(
                {
                    "pool": "Route pool must belong to the same organization as the route."
                }
            )
        if (
            self.is_active
            and self.pool_id
            and self.pool.status != RunnerPool.Status.ACTIVE
        ):
            raise ValidationError(
                {"pool": "Active routes require an active runner pool."}
            )

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
