from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class Organization(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=64, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    OPERATOR = "operator", "Operator"
    VIEWER = "viewer", "Viewer"


class Membership(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(
        max_length=16, choices=MembershipRole.choices, default=MembershipRole.OPERATOR
    )

    class Meta:
        ordering = ["user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"], name="unique_membership_per_org_user"
            )
        ]
        indexes = [
            models.Index(fields=["organization", "role"], name="member_org_role_idx"),
            models.Index(fields=["user", "organization"], name="member_user_org_idx"),
        ]

    def __str__(self):
        return f"{self.user} in {self.organization} ({self.role})"
