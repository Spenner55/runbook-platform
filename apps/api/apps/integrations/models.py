from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import BaseModel


class IntegrationConnection(BaseModel):
    class Type(models.TextChoices):
        SLACK_WEBHOOK = "slack_webhook", "Slack Webhook"
        GENERIC_WEBHOOK = "generic_webhook", "Generic Webhook"
        PAGERDUTY = "pagerduty", "PagerDuty"

    class LastDeliveryStatus(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_connections",
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    name = models.CharField(max_length=128)
    config = models.JSONField(default=dict)
    encrypted_credentials = models.BinaryField(null=True, blank=True)
    event_types = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_delivery_status = models.CharField(
        max_length=32,
        choices=LastDeliveryStatus.choices,
        blank=True,
    )

    class Meta:
        ordering = ["organization", "name"]
        indexes = [
            models.Index(
                fields=["organization", "is_active", "type"],
                name="integ_conn_org_active_type_idx",
            ),
            models.Index(
                fields=["organization", "is_active", "created_at"],
                name="integ_conn_dispatch_idx",
            ),
            models.Index(
                fields=["organization", "created_at"],
                name="integ_conn_org_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    type__in=["slack_webhook", "generic_webhook", "pagerduty"]
                ),
                name="integ_conn_type_valid_chk",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(last_delivery_status="")
                    | models.Q(last_delivery_status__in=["success", "failed"])
                ),
                name="integ_conn_last_status_chk",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.type})"

    def clean(self):
        super().clean()
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Integration name is required."})
        if not isinstance(self.config, dict):
            raise ValidationError(
                {"config": "Integration config must be a JSON object."}
            )
        if not isinstance(self.event_types, list) or not all(
            isinstance(event_type, str) and event_type.strip()
            for event_type in self.event_types
        ):
            raise ValidationError(
                {"event_types": "Integration event types must be a list of strings."}
            )
        if (
            self.type
            in {
                self.Type.SLACK_WEBHOOK,
                self.Type.GENERIC_WEBHOOK,
            }
            and not self.encrypted_credentials
        ):
            raise ValidationError(
                {"encrypted_credentials": "Webhook credentials are required."}
            )

    def set_credentials(self, credentials: dict) -> None:
        from apps.integrations.crypto import encrypt_credentials

        self.encrypted_credentials = encrypt_credentials(credentials)

    def get_credentials(self) -> dict:
        from apps.integrations.crypto import decrypt_credentials

        return decrypt_credentials(self.encrypted_credentials)


class IntegrationDeliveryAttempt(BaseModel):
    integration = models.ForeignKey(
        IntegrationConnection,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="integration_delivery_attempts",
    )
    event_type = models.CharField(max_length=64)
    payload_preview = models.JSONField(default=dict)
    http_status = models.IntegerField(null=True, blank=True)
    success = models.BooleanField()
    error_detail = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    attempted_at = models.DateTimeField()

    class Meta:
        ordering = ["-attempted_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["integration", "attempted_at"],
                name="integ_attempt_conn_time_idx",
            ),
            models.Index(
                fields=["organization", "attempted_at"],
                name="integ_attempt_org_time_idx",
            ),
            models.Index(
                fields=["event_type", "attempted_at"],
                name="integ_attempt_event_time_idx",
            ),
        ]

    def __str__(self):
        status = "success" if self.success else "failed"
        return f"{self.event_type} delivery to {self.integration_id} ({status})"
