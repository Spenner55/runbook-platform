import json

import pytest
from django.test import Client
from django.utils import timezone

from apps.integrations.crypto import encrypt_credentials
from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)
from apps.integrations.services import EVENT_EXECUTION_FAILED, IntegrationService
from apps.organizations.models import Organization


RAW_WEBHOOK_URL = "https://hooks.example.com/services/raw-secret-token"


def _create_connection(
    *,
    org,
    integration_fernet_key,
    name="Ops Webhook",
    url=RAW_WEBHOOK_URL,
    is_active=True,
):
    return IntegrationConnection.objects.create(
        organization=org,
        type=IntegrationConnection.Type.GENERIC_WEBHOOK,
        name=name,
        encrypted_credentials=encrypt_credentials({"url": url}),
        is_active=is_active,
    )


@pytest.fixture
def disable_ssrf_validation(monkeypatch):
    monkeypatch.setattr(
        IntegrationService,
        "validate_outbound_url",
        staticmethod(lambda url: url),
    )


@pytest.mark.django_db
def test_list_returns_only_organization_scoped_integrations(
    org, integration_fernet_key
):
    client = Client()
    other_org = Organization.objects.create(name="Other Corp", slug="other")
    own = _create_connection(
        org=org, integration_fernet_key=integration_fernet_key, name="Own"
    )
    _create_connection(
        org=other_org, integration_fernet_key=integration_fernet_key, name="Other"
    )

    response = client.get(f"/api/v1/integrations/?organization_id={org.id}")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(own.id)]
    assert body[0]["organization_id"] == str(org.id)


@pytest.mark.django_db
def test_create_stores_encrypted_credentials_and_response_excludes_secrets(
    org, integration_fernet_key, disable_ssrf_validation
):
    client = Client()

    response = client.post(
        "/api/v1/integrations/",
        data={
            "organization_id": str(org.id),
            "type": IntegrationConnection.Type.GENERIC_WEBHOOK,
            "name": "Ops Webhook",
            "credentials": {"url": RAW_WEBHOOK_URL},
            "event_types": [EVENT_EXECUTION_FAILED],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    connection = IntegrationConnection.objects.get(pk=body["id"])
    assert connection.get_credentials() == {"url": RAW_WEBHOOK_URL}
    assert RAW_WEBHOOK_URL.encode("utf-8") not in bytes(
        connection.encrypted_credentials
    )
    assert body["credentials_configured"] is True
    assert "encrypted_credentials" not in body
    assert "credentials" not in body
    assert RAW_WEBHOOK_URL not in json.dumps(body)


@pytest.mark.django_db
def test_detail_excludes_encrypted_credentials_and_plaintext_url(
    org, integration_fernet_key
):
    client = Client()
    connection = _create_connection(
        org=org, integration_fernet_key=integration_fernet_key
    )

    response = client.get(
        f"/api/v1/integrations/{connection.id}/?organization_id={org.id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(connection.id)
    assert body["credentials_configured"] is True
    assert "encrypted_credentials" not in body
    assert "credentials" not in body
    assert RAW_WEBHOOK_URL not in json.dumps(body)


@pytest.mark.django_db
def test_deactivate_prevents_future_dispatch(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    client = Client()
    connection = _create_connection(
        org=org, integration_fernet_key=integration_fernet_key
    )
    requests = []

    response = client.post(
        f"/api/v1/integrations/{connection.id}/deactivate/?organization_id={org.id}",
        data={},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False

    def fail_if_called(*, connection, event_type, context):
        requests.append((connection, event_type, context))

    monkeypatch.setattr(
        IntegrationService,
        "_notify_connection",
        fail_if_called,
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert requests == []
    assert IntegrationDeliveryAttempt.objects.count() == 0


@pytest.mark.django_db
def test_delivery_history_endpoint_returns_attempts(org, integration_fernet_key):
    client = Client()
    connection = _create_connection(
        org=org, integration_fernet_key=integration_fernet_key
    )
    attempt = IntegrationDeliveryAttempt.objects.create(
        integration=connection,
        organization=org,
        event_type=EVENT_EXECUTION_FAILED,
        payload_preview={"execution_id": "exec-1"},
        http_status=202,
        success=True,
        error_detail="",
        latency_ms=12,
        attempted_at=timezone.now(),
    )

    response = client.get(
        f"/api/v1/integrations/{connection.id}/delivery-attempts/"
        f"?organization_id={org.id}"
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["id"] == str(attempt.id)
    assert body["results"][0]["payload_preview"] == {"execution_id": "exec-1"}


@pytest.mark.django_db
def test_invalid_webhook_url_returns_validation_error(org, integration_fernet_key):
    client = Client()

    response = client.post(
        "/api/v1/integrations/",
        data={
            "organization_id": str(org.id),
            "type": IntegrationConnection.Type.GENERIC_WEBHOOK,
            "name": "Invalid Webhook",
            "credentials": {"url": "http://example.com/webhook"},
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "invalid"


@pytest.mark.django_db
def test_metadata_endpoint_url_is_blocked(org, integration_fernet_key):
    client = Client()

    response = client.post(
        "/api/v1/integrations/",
        data={
            "organization_id": str(org.id),
            "type": IntegrationConnection.Type.GENERIC_WEBHOOK,
            "name": "Metadata Webhook",
            "credentials": {"url": "https://169.254.169.254/latest/meta-data"},
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    body = response.json()
    assert "errors" in body
    assert "metadata" in body["errors"][0]["detail"].lower()


@pytest.mark.django_db
def test_serializer_redaction_regression_raw_credential_never_appears_in_response(
    org, integration_fernet_key, disable_ssrf_validation
):
    client = Client()
    create_response = client.post(
        "/api/v1/integrations/",
        data={
            "organization_id": str(org.id),
            "type": IntegrationConnection.Type.GENERIC_WEBHOOK,
            "name": "Ops Webhook",
            "credentials": {"url": RAW_WEBHOOK_URL},
            "event_types": [EVENT_EXECUTION_FAILED],
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    integration_id = create_response.json()["id"]

    responses = [
        create_response,
        client.get(f"/api/v1/integrations/?organization_id={org.id}"),
        client.get(f"/api/v1/integrations/{integration_id}/?organization_id={org.id}"),
        client.patch(
            f"/api/v1/integrations/{integration_id}/?organization_id={org.id}",
            data={"name": "Updated Ops Webhook"},
            content_type="application/json",
        ),
        client.post(
            f"/api/v1/integrations/{integration_id}/deactivate/"
            f"?organization_id={org.id}",
            data={},
            content_type="application/json",
        ),
    ]

    for response in responses:
        assert response.status_code in {200, 201}
        assert RAW_WEBHOOK_URL not in json.dumps(response.json())
