import hashlib
import json
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel

MAX_EXTERNAL_SNAPSHOT_BYTES = 16 * 1024
MAX_EXTERNAL_SNAPSHOT_DEPTH = 4
MAX_EXTERNAL_SNAPSHOT_KEYS = 64
MAX_EXTERNAL_SNAPSHOT_STRING_LENGTH = 2048
MAX_SCOPE_ITEMS = 256

FORBIDDEN_EXTERNAL_SNAPSHOT_KEYS = {
    "api_key",
    "api_token",
    "apikey",
    "apitoken",
    "auth",
    "auth_header",
    "authorization",
    "bearer",
    "bearer_token",
    "cookie",
    "credentials",
    "headers",
    "password",
    "private_key",
    "raw",
    "raw_response",
    "raw_response_body",
    "request_body",
    "response_body",
    "secret",
    "session",
    "session_token",
    "token",
}

MUTATING_SCOPE_KEYS = {
    "actions",
    "approval_permissions",
    "can_approve",
    "can_close",
    "can_create",
    "can_delete",
    "can_execute",
    "can_export",
    "can_mutate",
    "can_refresh",
    "can_revoke",
    "can_seal",
    "can_update",
    "mutation_permissions",
    "permissions",
    "write",
}

READONLY_SCOPE_DIMENSIONS = {
    "bundle_statuses",
    "change_types",
    "control_ids",
    "coverage_statuses",
    "risk_levels",
    "service_keys",
    "standards",
    "statuses",
    "target_ids",
}


class ExternalSystem(models.TextChoices):
    SERVICENOW = "servicenow", "ServiceNow"
    JIRA = "jira", "Jira"
    PAGERDUTY = "pagerduty", "PagerDuty"
    CUSTOM = "custom", "Custom"


class ExternalReferenceType(models.TextChoices):
    TICKET = "ticket", "Ticket"
    INCIDENT = "incident", "Incident"
    PROBLEM = "problem", "Problem"
    CMDB_CI = "cmdb_ci", "CMDB CI"
    RELEASE = "release", "Release"


class ControlStandard(models.TextChoices):
    SOC2 = "soc2", "SOC 2"
    ISO27001 = "iso27001", "ISO 27001"
    NIST = "nist", "NIST"
    CUSTOM = "custom", "Custom"


class ControlCoverageStatus(models.TextChoices):
    COVERED = "covered", "Covered"
    PARTIALLY_COVERED = "partially_covered", "Partially Covered"
    NOT_COVERED = "not_covered", "Not Covered"
    NOT_APPLICABLE = "not_applicable", "Not Applicable"
    STALE = "stale", "Stale"


class AuditorGrantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"


class SnapshotSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    API_REFRESH = "api_refresh", "API Refresh"
    IMPORTED = "imported", "Imported"


class SnapshotStatus(models.TextChoices):
    CURRENT = "current", "Current"
    STALE = "stale", "Stale"
    REFRESH_FAILED = "refresh_failed", "Refresh Failed"
    UNAVAILABLE = "unavailable", "Unavailable"


class ExternalChangeReference(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="external_change_references",
    )
    change_record = models.ForeignKey(
        "changes.ChangeRecord",
        on_delete=models.PROTECT,
        related_name="external_references",
    )
    system = models.CharField(
        max_length=32,
        choices=ExternalSystem.choices,
    )
    reference_type = models.CharField(
        max_length=32,
        choices=ExternalReferenceType.choices,
    )
    external_id = models.CharField(max_length=255)
    external_key = models.CharField(max_length=255, blank=True)
    display_label = models.CharField(max_length=255)
    external_url = models.URLField(max_length=2048, blank=True)
    snapshot = models.JSONField(default=dict)
    snapshot_sha256 = models.CharField(max_length=64, blank=True)
    snapshot_source = models.CharField(
        max_length=32,
        choices=SnapshotSource.choices,
        default=SnapshotSource.MANUAL,
    )
    snapshot_status = models.CharField(
        max_length=32,
        choices=SnapshotStatus.choices,
        default=SnapshotStatus.CURRENT,
    )
    snapshot_taken_at = models.DateTimeField(null=True, blank=True)
    last_refresh_attempted_at = models.DateTimeField(null=True, blank=True)
    last_refresh_error_code = models.CharField(max_length=64, blank=True)
    linked_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="linked_external_change_references",
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "change_record",
                    "system",
                    "reference_type",
                    "external_id",
                ],
                name="aud_ext_ref_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(system__in=ExternalSystem.values),
                name="aud_ext_ref_system_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(reference_type__in=ExternalReferenceType.values),
                name="aud_ext_ref_type_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(snapshot_source__in=SnapshotSource.values),
                name="aud_ext_ref_source_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(snapshot_status__in=SnapshotStatus.values),
                name="aud_ext_ref_snap_status_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "system", "reference_type"],
                name="aud_ext_ref_org_sys_type_idx",
            ),
            models.Index(
                fields=["organization", "external_key"],
                name="aud_ext_ref_org_key_idx",
            ),
            models.Index(
                fields=["change_record", "system"],
                name="aud_ext_ref_change_sys_idx",
            ),
        ]

    def __str__(self):
        label = self.display_label or self.external_key or self.external_id
        return f"{self.system}:{label}"

    def clean(self):
        super().clean()
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "External reference organization must match the change organization."
            )
        _validate_safe_url(self.external_url)
        self.snapshot = sanitize_external_snapshot(self.snapshot)
        self.snapshot_sha256 = (
            canonical_json_sha256(self.snapshot) if self.snapshot else ""
        )
        if self.snapshot and self.snapshot_taken_at is None:
            self.snapshot_taken_at = timezone.now()

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ServiceCatalogEntry(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="service_catalog_entries",
    )
    service_key = models.SlugField(max_length=128)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner_team = models.CharField(max_length=255, blank=True)
    business_owner = models.CharField(max_length=255, blank=True)
    criticality = models.CharField(max_length=32, blank=True)
    environment = models.CharField(max_length=64, blank=True)
    target_patterns = models.JSONField(default=list)
    metadata = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_service_catalog_entries",
    )
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_service_catalog_entries",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "service_key"],
                name="aud_svc_catalog_org_key_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "service_key"],
                name="aud_svc_org_active_key_idx",
            ),
            models.Index(
                fields=["organization", "criticality"],
                name="aud_svc_org_crit_idx",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        _validate_target_patterns(self.target_patterns)
        _validate_context_metadata(self.metadata)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ControlMappingProfile(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="control_mapping_profiles",
    )
    key = models.SlugField(max_length=128)
    name = models.CharField(max_length=255)
    standard = models.CharField(max_length=32, choices=ControlStandard.choices)
    version = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)
    mapping_rules = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_control_mapping_profiles",
    )
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_control_mapping_profiles",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "key", "version"],
                name="aud_ctrl_profile_org_key_ver_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(standard__in=ControlStandard.values),
                name="aud_ctrl_profile_standard_chk",
            ),
            models.UniqueConstraint(
                fields=["organization", "standard", "key"],
                condition=models.Q(is_active=True),
                name="aud_ctrl_profile_one_active",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "standard", "is_active"],
                name="aud_ctrl_profile_org_std_idx",
            ),
        ]

    def __str__(self):
        return f"{self.key} v{self.version}"

    def clean(self):
        super().clean()
        _validate_mapping_rules(self.mapping_rules)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ChangeControlCoverage(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="change_control_coverages",
    )
    change_record = models.ForeignKey(
        "changes.ChangeRecord",
        on_delete=models.PROTECT,
        related_name="control_coverages",
    )
    evidence_bundle = models.ForeignKey(
        "evidence.EvidenceBundle",
        on_delete=models.PROTECT,
        related_name="control_coverages",
    )
    mapping_profile = models.ForeignKey(
        ControlMappingProfile,
        on_delete=models.PROTECT,
        related_name="coverages",
    )
    standard = models.CharField(max_length=32, choices=ControlStandard.choices)
    control_id = models.CharField(max_length=128)
    control_title = models.CharField(max_length=255, blank=True)
    coverage_status = models.CharField(
        max_length=32,
        choices=ControlCoverageStatus.choices,
    )
    matched_sections = models.JSONField(default=list)
    missing_sections = models.JSONField(default=list)
    evidence_paths = models.JSONField(default=list)
    coverage_fingerprint_sha256 = models.CharField(max_length=64)
    computed_at = models.DateTimeField(default=timezone.now)
    computed_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="computed_control_coverages",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["evidence_bundle", "mapping_profile", "control_id"],
                name="aud_ctrl_cov_bundle_profile_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(standard__in=ControlStandard.values),
                name="aud_ctrl_cov_standard_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(coverage_status__in=ControlCoverageStatus.values),
                name="aud_ctrl_cov_status_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "standard", "control_id"],
                name="aud_ctrl_cov_org_std_id_idx",
            ),
            models.Index(
                fields=["organization", "change_record", "standard"],
                name="aud_ctrl_cov_org_chg_std_idx",
            ),
            models.Index(
                fields=["organization", "coverage_status"],
                name="aud_ctrl_cov_org_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.control_id} [{self.coverage_status}]"

    def clean(self):
        super().clean()
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Coverage organization must match the change organization."
            )
        if (
            self.evidence_bundle_id
            and self.organization_id
            and self.evidence_bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Coverage organization must match the evidence bundle organization."
            )
        if (
            self.mapping_profile_id
            and self.organization_id
            and self.mapping_profile.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Coverage organization must match the mapping profile organization."
            )
        if (
            self.evidence_bundle_id
            and self.change_record_id
            and self.evidence_bundle.change_record_id != self.change_record_id
        ):
            raise ValidationError("Coverage bundle must belong to the same change.")
        if self.evidence_bundle_id and self.evidence_bundle.status != "sealed":
            raise ValidationError("Control coverage requires a sealed evidence bundle.")
        if (
            self.mapping_profile_id
            and self.standard
            and self.mapping_profile.standard != self.standard
        ):
            raise ValidationError(
                "Coverage standard must match the mapping profile standard."
            )
        _validate_json_list("matched_sections", self.matched_sections)
        _validate_json_list("missing_sections", self.missing_sections)
        _validate_json_list("evidence_paths", self.evidence_paths)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class AuditorAccessGrant(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="auditor_access_grants",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="auditor_access_grants",
    )
    status = models.CharField(
        max_length=32,
        choices=AuditorGrantStatus.choices,
        default=AuditorGrantStatus.ACTIVE,
    )
    scope = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_auditor_grants",
    )
    revoked_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revoked_auditor_grants",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=AuditorGrantStatus.values),
                name="aud_grant_status_valid_chk",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=AuditorGrantStatus.REVOKED)
                    | models.Q(revoked_at__isnull=False)
                ),
                name="aud_grant_revoked_at_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "user", "status"],
                name="aud_grant_org_user_status_idx",
            ),
            models.Index(
                fields=["organization", "status", "expires_at"],
                name="aud_grant_org_status_exp_idx",
            ),
        ]

    def __str__(self):
        return f"AuditorAccessGrant {self.user_id} [{self.status}]"

    def clean(self):
        super().clean()
        validate_auditor_scope(self.scope)
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValidationError("Auditor grant expires_at must be after starts_at.")
        if self.status == AuditorGrantStatus.REVOKED and self.revoked_at is None:
            raise ValidationError("Revoked auditor grants require revoked_at.")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


def canonical_json_sha256(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sanitize_external_snapshot(snapshot):
    if snapshot in (None, ""):
        return {}
    if not isinstance(snapshot, dict):
        raise ValidationError("External reference snapshot must be a JSON object.")

    sanitized = _sanitize_snapshot_value(snapshot, depth=0)
    encoded = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_EXTERNAL_SNAPSHOT_BYTES:
        raise ValidationError(
            f"External reference snapshot must be smaller than "
            f"{MAX_EXTERNAL_SNAPSHOT_BYTES} bytes."
        )
    return sanitized


def _sanitize_snapshot_value(value, *, depth: int):
    if depth > MAX_EXTERNAL_SNAPSHOT_DEPTH:
        raise ValidationError("External reference snapshot is too deeply nested.")
    if isinstance(value, dict):
        if len(value) > MAX_EXTERNAL_SNAPSHOT_KEYS:
            raise ValidationError("External reference snapshot has too many fields.")
        sanitized = {}
        for key, child in value.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            key_lower = key_text.lower()
            if key_lower in FORBIDDEN_EXTERNAL_SNAPSHOT_KEYS:
                continue
            if any(marker in key_lower for marker in ["token", "secret", "password"]):
                continue
            sanitized[key_text[:128]] = _sanitize_snapshot_value(
                child,
                depth=depth + 1,
            )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_snapshot_value(item, depth=depth + 1)
            for item in value[:MAX_EXTERNAL_SNAPSHOT_KEYS]
        ]
    if isinstance(value, str):
        return value[:MAX_EXTERNAL_SNAPSHOT_STRING_LENGTH]
    if isinstance(value, bool | int | float) or value is None:
        return value
    raise ValidationError("External reference snapshot values must be JSON scalars.")


def _validate_safe_url(url: str) -> None:
    if not url:
        return
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        raise ValidationError("External reference URL must not contain credentials.")
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("External reference URL must be HTTP or HTTPS.")


def _validate_target_patterns(value) -> None:
    if not isinstance(value, list):
        raise ValidationError("Service target_patterns must be a list.")
    if len(value) > MAX_SCOPE_ITEMS:
        raise ValidationError("Service target_patterns contains too many entries.")
    for item in value:
        if isinstance(item, str):
            if not item.strip() or len(item) > 255:
                raise ValidationError("Service target pattern strings are invalid.")
            continue
        if isinstance(item, dict):
            _validate_context_metadata(item)
            if "query" in item or "url" in item or "expression" in item:
                raise ValidationError(
                    "Service target patterns cannot contain remote queries or expressions."
                )
            continue
        raise ValidationError(
            "Service target_patterns entries must be strings or objects."
        )


def _validate_context_metadata(value) -> None:
    if not isinstance(value, dict):
        raise ValidationError("Metadata must be a JSON object.")
    sanitized = sanitize_external_snapshot(value)
    if sanitized != value:
        raise ValidationError("Metadata contains forbidden sensitive fields.")


def _validate_mapping_rules(value) -> None:
    if not isinstance(value, list):
        raise ValidationError("Control mapping_rules must be a list.")
    if len(value) > MAX_SCOPE_ITEMS:
        raise ValidationError("Control mapping_rules contains too many entries.")
    for rule in value:
        if not isinstance(rule, dict):
            raise ValidationError("Control mapping rules must be JSON objects.")
        forbidden = {"query", "url", "webhook", "python", "expression", "script"}
        if forbidden.intersection(rule):
            raise ValidationError(
                "Control mapping rules must not contain live queries or executable hooks."
            )
        control_id = str(rule.get("control_id", "")).strip()
        if not control_id or len(control_id) > 128:
            raise ValidationError("Control mapping rules require bounded control_id.")


def _validate_json_list(field_name: str, value) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a JSON list.")
    if len(value) > MAX_SCOPE_ITEMS:
        raise ValidationError(f"{field_name} contains too many entries.")


def validate_auditor_scope(scope) -> None:
    if not isinstance(scope, dict):
        raise ValidationError("Auditor grant scope must be a JSON object.")
    if not scope:
        raise ValidationError("Auditor grant scope must not be empty.")

    lowered_keys = {str(key).lower() for key in scope}
    if lowered_keys.intersection(MUTATING_SCOPE_KEYS):
        raise ValidationError("Auditor grants cannot include mutation permissions.")

    for key, value in scope.items():
        key_text = str(key)
        key_lower = key_text.lower()
        if any(
            marker in key_lower for marker in ["write", "mutate", "approve", "execute"]
        ):
            raise ValidationError("Auditor grants cannot include mutation permissions.")
        if key_text in READONLY_SCOPE_DIMENSIONS:
            _validate_scope_dimension(key_text, value)
        elif key_text in {"date_from", "date_to"}:
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{key_text} must be a datetime string.")
        elif key_text == "include_exceptions":
            if not isinstance(value, bool):
                raise ValidationError("include_exceptions must be a boolean.")
        elif key_text == "all":
            if value is not True:
                raise ValidationError(
                    "The top-level all scope must be true when present."
                )
        else:
            raise ValidationError(f"Unsupported auditor grant scope key: {key_text}.")


def _validate_scope_dimension(key: str, value) -> None:
    if isinstance(value, list):
        if not value:
            raise ValidationError(
                f"{key} cannot be an empty list; use an explicit all scope or omit it."
            )
        if len(value) > MAX_SCOPE_ITEMS:
            raise ValidationError(f"{key} contains too many entries.")
        for item in value:
            if not isinstance(item, str) or not item.strip() or len(item) > 255:
                raise ValidationError(f"{key} entries must be bounded strings.")
        return
    if isinstance(value, dict):
        if value != {"all": True}:
            raise ValidationError(f"{key} object scope only supports {{'all': true}}.")
        return
    raise ValidationError(f"{key} must be a list or explicit all object.")
