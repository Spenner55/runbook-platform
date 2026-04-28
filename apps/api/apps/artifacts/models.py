from django.db import models

from apps.common.models import BaseModel


class Artifact(BaseModel):
    class Kind(models.TextChoices):
        STDOUT = "stdout", "Stdout"
        STDERR = "stderr", "Stderr"
        FILE = "file", "File"
        REPORT = "report", "Report"
        DIAGNOSTIC = "diagnostic", "Diagnostic"

    class UploadStatus(models.TextChoices):
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"

    class ContentDisposition(models.TextChoices):
        ATTACHMENT = "attachment", "Attachment"
        INLINE = "inline", "Inline"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="artifacts",
    )
    execution = models.ForeignKey(
        "executions.Execution",
        on_delete=models.PROTECT,
        related_name="artifacts",
    )
    step = models.ForeignKey(
        "executions.ExecutionStep",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artifacts",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    name = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=128)
    size_bytes = models.PositiveBigIntegerField()
    checksum_sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=1024, unique=True)
    uploaded_by_runner_id = models.CharField(max_length=255)
    upload_status = models.CharField(
        max_length=16,
        choices=UploadStatus.choices,
        default=UploadStatus.AVAILABLE,
    )
    uploaded_at = models.DateTimeField()
    content_disposition = models.CharField(
        max_length=16,
        choices=ContentDisposition.choices,
        default=ContentDisposition.ATTACHMENT,
    )
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(
                fields=["organization", "uploaded_at"],
                name="artifact_org_uploaded_idx",
            ),
            models.Index(
                fields=["execution", "uploaded_at"],
                name="artifact_exec_uploaded_idx",
            ),
            models.Index(
                fields=["step", "uploaded_at"],
                name="artifact_step_uploaded_idx",
            ),
            models.Index(
                fields=["kind", "uploaded_at"],
                name="artifact_kind_uploaded_idx",
            ),
            models.Index(
                fields=["checksum_sha256"],
                name="artifact_checksum_idx",
            ),
        ]

    def __str__(self):
        return f"Artifact {self.name} [{self.kind}] for execution {self.execution_id}"
