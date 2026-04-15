from django.db import models

from apps.common.models import BaseModel


class Workflow(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        SUPERSEDED = "superseded", "Superseded"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="workflows",
    )
    runbook = models.ForeignKey(
        "runbooks.Runbook",
        on_delete=models.PROTECT,
        related_name="workflows",
    )
    name = models.CharField(max_length=255)
    version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    definition_schema_version = models.CharField(max_length=20, default="1.0")
    definition = models.JSONField(default=dict)

    class Meta:
        ordering = ["name", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["runbook", "version"],
                name="unique_workflow_version_per_runbook",
            ),
            models.CheckConstraint(
                check=models.Q(version__gte=1),
                name="workflow_version_gte_1",
            ),
        ]

    def __str__(self):
        return f"{self.name} v{self.version}"
