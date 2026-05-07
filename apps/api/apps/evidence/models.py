from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class EvidenceBundle(BaseModel):
    class Status(models.TextChoices):
        COMPILING = "compiling", "Compiling"
        SEALED = "sealed", "Sealed"
        INVALIDATED = "invalidated", "Invalidated"

    class CompletenessStatus(models.TextChoices):
        COMPLETE = "complete", "Complete"
        INCOMPLETE = "incomplete", "Incomplete"
        INVALID = "invalid", "Invalid"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="evidence_bundles",
    )
    change_record = models.ForeignKey(
        "changes.ChangeRecord",
        on_delete=models.PROTECT,
        related_name="evidence_bundles",
    )
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.COMPILING,
    )
    completeness_status = models.CharField(
        max_length=24,
        choices=CompletenessStatus.choices,
        default=CompletenessStatus.INCOMPLETE,
    )
    completeness_report = models.JSONField(default=dict)
    source_snapshot_sha256 = models.CharField(max_length=64, blank=True)
    source_cutoff_at = models.DateTimeField()
    source_high_watermark = models.JSONField(default=dict)
    manifest = models.JSONField(default=dict)
    manifest_sha256 = models.CharField(max_length=64, blank=True)
    payload_checksums_sha256 = models.CharField(max_length=64, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    content_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    storage_key = models.CharField(max_length=1024, blank=True)
    mime_type = models.CharField(max_length=128, default="application/zip")
    compiled_at = models.DateTimeField(default=timezone.now)
    sealed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidation_reason = models.CharField(max_length=128, blank=True)
    previous_bundle = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseding_bundles",
    )
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_evidence_bundles",
    )
    sealed_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sealed_evidence_bundles",
    )
    invalidated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invalidated_evidence_bundles",
    )
    retention_policy = models.ForeignKey(
        "evidence.EvidenceRetentionPolicy",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evidence_bundles",
    )
    retention_expires_at = models.DateTimeField(null=True, blank=True)
    storage_deleted_at = models.DateTimeField(null=True, blank=True)
    storage_delete_reason = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["change_record", "version"],
                name="evidence_bundle_change_version_unique",
            ),
            models.UniqueConstraint(
                fields=["storage_key"],
                condition=~models.Q(storage_key=""),
                name="evidence_bundle_storage_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["compiling", "sealed", "invalidated"]),
                name="evidence_bundle_status_valid_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    completeness_status__in=["complete", "incomplete", "invalid"]
                ),
                name="evidence_bundle_completeness_valid_chk",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="sealed")
                    | (
                        models.Q(sealed_at__isnull=False)
                        & ~models.Q(manifest_sha256="")
                        & ~models.Q(content_sha256="")
                        & models.Q(content_size_bytes__isnull=False)
                        & ~models.Q(storage_key="")
                    )
                ),
                name="evidence_bundle_sealed_fields_chk",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="invalidated")
                    | (
                        models.Q(invalidated_at__isnull=False)
                        & ~models.Q(invalidation_reason="")
                    )
                ),
                name="evidence_bundle_invalid_fields_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "change_record", "version"],
                name="ev_bundle_org_change_ver_idx",
            ),
            models.Index(
                fields=["organization", "status", "created_at"],
                name="ev_bundle_org_status_cr_idx",
            ),
            models.Index(
                fields=["organization", "completeness_status", "created_at"],
                name="ev_bundle_org_comp_cr_idx",
            ),
            models.Index(
                fields=["organization", "retention_expires_at"],
                name="ev_bundle_org_ret_exp_idx",
            ),
        ]

    IMMUTABLE_AFTER_SEAL = frozenset(
        [
            "organization_id",
            "change_record_id",
            "version",
            "completeness_status",
            "completeness_report",
            "source_snapshot_sha256",
            "source_cutoff_at",
            "source_high_watermark",
            "manifest",
            "manifest_sha256",
            "payload_checksums_sha256",
            "content_sha256",
            "content_size_bytes",
            "storage_key",
            "mime_type",
            "compiled_at",
            "sealed_at",
            "previous_bundle_id",
            "created_by_id",
            "sealed_by_id",
            "retention_policy_id",
            "retention_expires_at",
        ]
    )

    def __str__(self):
        return f"EvidenceBundle {self.change_record_id} v{self.version} [{self.status}]"

    @property
    def is_sealed(self) -> bool:
        return self.status == self.Status.SEALED

    def clean(self):
        super().clean()
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Evidence bundle organization must match the change organization."
            )
        if (
            self.previous_bundle_id
            and self.change_record_id
            and self.previous_bundle.change_record_id != self.change_record_id
        ):
            raise ValidationError(
                "Previous evidence bundle must belong to the same change."
            )
        if (
            self.retention_policy_id
            and self.organization_id
            and self.retention_policy.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Evidence retention policy organization must match the bundle organization."
            )

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None and previous.status == self.Status.SEALED:
                changed = [
                    field
                    for field in self.IMMUTABLE_AFTER_SEAL
                    if getattr(previous, field) != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        f"Sealed evidence bundles are immutable "
                        f"(attempted to change: {changed}).",
                        code="evidence_bundle_immutable",
                    )
                if self.status not in [
                    self.Status.SEALED,
                    self.Status.INVALIDATED,
                ]:
                    raise ValidationError(
                        "Sealed evidence bundles can only be invalidated.",
                        code="evidence_bundle_immutable",
                    )
        self.clean()
        return super().save(*args, **kwargs)


class EvidenceBundleItem(BaseModel):
    class ItemType(models.TextChoices):
        CHANGE_SNAPSHOT = "change_snapshot", "Change Snapshot"
        APPROVAL = "approval", "Approval"
        POLICY_DECISION = "policy_decision", "Policy Decision"
        EXECUTION = "execution", "Execution"
        AUDIT_EVENT = "audit_event", "Audit Event"
        ARTIFACT = "artifact", "Artifact"
        VERIFICATION_RESULT = "verification_result", "Verification Result"
        CLOSURE = "closure", "Closure"
        EXCEPTION = "exception", "Exception"
        EXTERNAL_REFERENCE = "external_reference", "External Reference"
        EXPORT_RECEIPT = "export_receipt", "Export Receipt"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="evidence_bundle_items",
    )
    bundle = models.ForeignKey(
        EvidenceBundle,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_type = models.CharField(max_length=32, choices=ItemType.choices)
    item_key = models.CharField(max_length=255)
    canonical_path = models.CharField(max_length=512)
    json_pointer = models.CharField(max_length=512, blank=True)
    position = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=True)
    present = models.BooleanField(default=True)
    valid = models.BooleanField(default=True)
    missing_reason = models.CharField(max_length=128, blank=True)
    validation_errors = models.JSONField(default=list)
    source_type = models.CharField(max_length=128, blank=True)
    source_id = models.CharField(max_length=128, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    source_metadata = models.JSONField(default=dict)
    artifact = models.ForeignKey(
        "artifacts.Artifact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evidence_items",
    )
    staging_storage_key = models.CharField(max_length=1024, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    content_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["item_type", "position", "canonical_path", "item_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["bundle", "item_type", "item_key"],
                name="evidence_item_bundle_type_key_unique",
            ),
            models.UniqueConstraint(
                fields=["bundle", "canonical_path", "json_pointer", "item_key"],
                name="evidence_item_bundle_path_ptr_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    item_type__in=[
                        "change_snapshot",
                        "approval",
                        "policy_decision",
                        "execution",
                        "audit_event",
                        "artifact",
                        "verification_result",
                        "closure",
                        "exception",
                        "external_reference",
                        "export_receipt",
                    ]
                ),
                name="evidence_item_type_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "item_type"],
                name="ev_item_org_type_idx",
            ),
            models.Index(
                fields=["bundle", "item_type", "position"],
                name="ev_item_bundle_type_pos_idx",
            ),
            models.Index(fields=["artifact"], name="ev_item_artifact_idx"),
        ]

    def __str__(self):
        return f"EvidenceBundleItem {self.item_type}:{self.item_key}"

    def clean(self):
        super().clean()
        if (
            self.bundle_id
            and self.organization_id
            and self.bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Evidence item organization must match the bundle organization."
            )
        if (
            self.artifact_id
            and self.organization_id
            and self.artifact.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Evidence item artifact organization must match the item organization."
            )

    def _parent_is_sealed(self) -> bool:
        if self.bundle_id is None:
            return False
        return EvidenceBundle.objects.filter(
            pk=self.bundle_id, status=EvidenceBundle.Status.SEALED
        ).exists()

    def save(self, *args, **kwargs):
        if self._parent_is_sealed():
            raise ValidationError(
                "Evidence bundle items are immutable once the bundle is sealed.",
                code="evidence_bundle_immutable",
            )
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._parent_is_sealed():
            raise ValidationError(
                "Evidence bundle items are immutable once the bundle is sealed.",
                code="evidence_bundle_immutable",
            )
        return super().delete(*args, **kwargs)


class EvidenceRedactionPolicy(BaseModel):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="evidence_redaction_policies",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    rules = models.JSONField(default=list)
    rules_sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_evidence_redaction_policies",
    )
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_evidence_redaction_policies",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="evidence_redaction_org_name_unique",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(is_default=True),
                name="evidence_redaction_default_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "name"],
                name="ev_redact_org_active_name_idx",
            ),
        ]

    def __str__(self):
        return self.name


class EvidenceExport(BaseModel):
    class Status(models.TextChoices):
        CREATING = "creating", "Creating"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="evidence_exports",
    )
    bundle = models.ForeignKey(
        EvidenceBundle,
        on_delete=models.PROTECT,
        related_name="exports",
    )
    redaction_policy = models.ForeignKey(
        EvidenceRedactionPolicy,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="evidence_exports",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.CREATING,
    )
    requested_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requested_evidence_exports",
    )
    requested_at = models.DateTimeField(default=timezone.now)
    ready_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    storage_key = models.CharField(max_length=1024, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    content_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    manifest = models.JSONField(default=dict)
    manifest_sha256 = models.CharField(max_length=64, blank=True)
    source_manifest_sha256 = models.CharField(max_length=64)
    source_bundle_content_sha256 = models.CharField(max_length=64)
    redaction_summary = models.JSONField(default=dict)
    receipt = models.JSONField(default=dict)
    receipt_sha256 = models.CharField(max_length=64, blank=True)
    failure_code = models.CharField(max_length=128, blank=True)
    failure_message = models.TextField(blank=True)
    download_count = models.PositiveIntegerField(default=0)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)
    storage_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["storage_key"],
                condition=~models.Q(storage_key=""),
                name="evidence_export_storage_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["creating", "ready", "failed", "expired"]
                ),
                name="evidence_export_status_valid_chk",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="ready")
                    | (
                        models.Q(ready_at__isnull=False)
                        & ~models.Q(storage_key="")
                        & ~models.Q(content_sha256="")
                        & models.Q(content_size_bytes__isnull=False)
                        & ~models.Q(manifest_sha256="")
                        & ~models.Q(receipt_sha256="")
                    )
                ),
                name="evidence_export_ready_fields_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "requested_at"],
                name="ev_export_org_status_req_idx",
            ),
            models.Index(
                fields=["bundle", "requested_at"], name="ev_export_bundle_req_idx"
            ),
            models.Index(
                fields=["organization", "expires_at"],
                name="ev_export_org_expires_idx",
            ),
        ]

    IMMUTABLE_AFTER_READY = frozenset(
        [
            "organization_id",
            "bundle_id",
            "redaction_policy_id",
            "requested_by_id",
            "requested_at",
            "ready_at",
            "storage_key",
            "content_sha256",
            "content_size_bytes",
            "manifest",
            "manifest_sha256",
            "source_manifest_sha256",
            "source_bundle_content_sha256",
            "redaction_summary",
            "receipt",
            "receipt_sha256",
        ]
    )

    def __str__(self):
        return f"EvidenceExport {self.id} [{self.status}]"

    def clean(self):
        super().clean()
        if (
            self.bundle_id
            and self.organization_id
            and self.bundle.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Evidence export organization must match the bundle organization."
            )
        if (
            self.redaction_policy_id
            and self.organization_id
            and self.redaction_policy.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Evidence export redaction policy organization must match."
            )

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous is not None and previous.status == self.Status.READY:
                changed = [
                    field
                    for field in self.IMMUTABLE_AFTER_READY
                    if getattr(previous, field) != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        f"Ready evidence exports are immutable "
                        f"(attempted to change: {changed}).",
                        code="evidence_export_immutable",
                    )
        self.clean()
        return super().save(*args, **kwargs)


class EvidenceRetentionPolicy(BaseModel):
    class CleanupAction(models.TextChoices):
        DELETE_CONTENT_KEEP_METADATA = (
            "delete_content_keep_metadata",
            "Delete Content Keep Metadata",
        )

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="evidence_retention_policies",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    sealed_bundle_retention_days = models.PositiveIntegerField()
    invalidated_bundle_retention_days = models.PositiveIntegerField()
    export_retention_days = models.PositiveIntegerField()
    cleanup_action = models.CharField(
        max_length=64,
        choices=CleanupAction.choices,
        default=CleanupAction.DELETE_CONTENT_KEEP_METADATA,
    )
    created_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_evidence_retention_policies",
    )
    updated_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_evidence_retention_policies",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="evidence_retention_org_name_unique",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(is_default=True),
                name="evidence_retention_default_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(sealed_bundle_retention_days__gt=0),
                name="evidence_retention_sealed_days_gt0_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(invalidated_bundle_retention_days__gt=0),
                name="evidence_retention_invalid_days_gt0_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(export_retention_days__gt=0),
                name="evidence_retention_export_days_gt0_chk",
            ),
            models.CheckConstraint(
                condition=models.Q(cleanup_action="delete_content_keep_metadata"),
                name="evidence_retention_cleanup_valid_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "name"],
                name="ev_retain_org_active_name_idx",
            ),
        ]

    def __str__(self):
        return self.name


class LegalHold(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RELEASED = "released", "Released"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="legal_holds",
    )
    change_record = models.ForeignKey(
        "changes.ChangeRecord",
        on_delete=models.PROTECT,
        related_name="legal_holds",
    )
    evidence_bundle = models.ForeignKey(
        EvidenceBundle,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legal_holds",
    )
    evidence_export = models.ForeignKey(
        EvidenceExport,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legal_holds",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    reason = models.TextField(max_length=2000)
    external_reference = models.CharField(max_length=512, blank=True)
    placed_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="placed_legal_holds",
    )
    placed_at = models.DateTimeField(default=timezone.now)
    released_by = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="released_legal_holds",
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.TextField(max_length=2000, blank=True)

    class Meta:
        ordering = ["-placed_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "released"]),
                name="legal_hold_status_valid_chk",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="released")
                    | (
                        models.Q(released_at__isnull=False)
                        & models.Q(released_by__isnull=False)
                        & ~models.Q(release_reason="")
                    )
                ),
                name="legal_hold_release_fields_chk",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "placed_at"],
                name="ev_hold_org_status_place_idx",
            ),
            models.Index(
                fields=["change_record", "status"], name="legal_hold_change_idx"
            ),
            models.Index(
                fields=["evidence_bundle", "status"],
                name="legal_hold_bundle_idx",
            ),
            models.Index(
                fields=["evidence_export", "status"],
                name="legal_hold_export_idx",
            ),
        ]

    def __str__(self):
        return f"LegalHold {self.id} [{self.status}]"

    def clean(self):
        super().clean()
        if (
            self.change_record_id
            and self.organization_id
            and self.change_record.organization_id != self.organization_id
        ):
            raise ValidationError(
                "Legal hold organization must match the change organization."
            )
        if self.evidence_bundle_id:
            if self.evidence_bundle.organization_id != self.organization_id:
                raise ValidationError(
                    "Legal hold bundle organization must match the hold organization."
                )
            if self.evidence_bundle.change_record_id != self.change_record_id:
                raise ValidationError(
                    "Legal hold bundle must belong to the held change."
                )
        if self.evidence_export_id:
            if self.evidence_export.organization_id != self.organization_id:
                raise ValidationError(
                    "Legal hold export organization must match the hold organization."
                )
            if self.evidence_export.bundle.change_record_id != self.change_record_id:
                raise ValidationError(
                    "Legal hold export must belong to the held change."
                )
        if self.status == self.Status.RELEASED:
            missing = []
            if self.released_by_id is None:
                missing.append("released_by")
            if self.released_at is None:
                missing.append("released_at")
            if not self.release_reason.strip():
                missing.append("release_reason")
            if missing:
                raise ValidationError(
                    f"Released legal holds require: {', '.join(missing)}.",
                    code="legal_hold_release_fields_required",
                )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
