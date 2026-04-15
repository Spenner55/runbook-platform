from django.db import models

from apps.common.models import BaseModel


class Runbook(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready"
        ARCHIVED = "archived", "Archived"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="runbooks",
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    raw_content = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"],
                name="unique_runbook_slug_per_org",
            )
        ]

    def __str__(self):
        return self.title
