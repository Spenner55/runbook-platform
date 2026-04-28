import pytest
from django.utils import timezone

from apps.integrations.crypto import encrypt_credentials
from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)


@pytest.mark.django_db
def test_integration_connection_creation(org, integration_fernet_key):
    credentials = {"url": "https://example.com/webhook"}

    connection = IntegrationConnection.objects.create(
        organization=org,
        type=IntegrationConnection.Type.GENERIC_WEBHOOK,
        name="Ops Webhook",
        config={"label": "ops"},
        event_types=["execution.failed"],
    )
    connection.set_credentials(credentials)
    connection.save(update_fields=["encrypted_credentials", "updated_at"])

    assert connection.id is not None
    assert connection.organization == org
    assert connection.is_active is True
    assert connection.encrypted_credentials != credentials["url"].encode("utf-8")
    assert connection.get_credentials() == credentials


@pytest.mark.django_db
def test_delivery_attempt_creation(org, integration_fernet_key):
    connection = IntegrationConnection.objects.create(
        organization=org,
        type=IntegrationConnection.Type.GENERIC_WEBHOOK,
        name="Ops Webhook",
        encrypted_credentials=encrypt_credentials({"url": "https://example.com/hook"}),
    )

    attempt = IntegrationDeliveryAttempt.objects.create(
        integration=connection,
        organization=org,
        event_type="execution.failed",
        payload_preview={"execution_id": "example"},
        http_status=202,
        success=True,
        latency_ms=42,
        attempted_at=timezone.now(),
    )

    assert attempt.id is not None
    assert attempt.integration == connection
    assert attempt.organization == org
    assert attempt.success is True
