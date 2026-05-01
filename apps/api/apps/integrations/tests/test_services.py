import httpx
import pytest
from prometheus_client import REGISTRY

from apps.audit.models import AuditEvent
from apps.integrations.crypto import encrypt_credentials
from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)
from apps.integrations.services import (
    EVENT_EXECUTION_COMPLETED,
    EVENT_EXECUTION_FAILED,
    IntegrationService,
)
from apps.organizations.models import Organization


def _connection(
    *,
    org,
    integration_fernet_key,
    name="Ops Webhook",
    type=IntegrationConnection.Type.GENERIC_WEBHOOK,
    url="https://example.com/webhook",
    event_types=None,
    is_active=True,
):
    return IntegrationConnection.objects.create(
        organization=org,
        type=type,
        name=name,
        encrypted_credentials=encrypt_credentials({"url": url}),
        event_types=event_types or [],
        is_active=is_active,
    )


def _mock_client_factory(handler):
    transport = httpx.MockTransport(handler)

    def factory(*, timeout):
        assert timeout == httpx.Timeout(3.0)
        return httpx.Client(transport=transport, timeout=timeout)

    return factory


@pytest.fixture
def disable_ssrf_validation(monkeypatch):
    monkeypatch.setattr(
        IntegrationService,
        "validate_outbound_url",
        staticmethod(lambda url: url),
    )


@pytest.mark.django_db
def test_successful_dispatch_creates_success_attempt(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    connection = _connection(org=org, integration_fernet_key=integration_fernet_key)
    requests = []
    labels = {
        "integration_type": IntegrationConnection.Type.GENERIC_WEBHOOK,
        "outcome": "success",
    }
    before = (
        REGISTRY.get_sample_value(
            "runbook_integration_dispatch_duration_seconds_count",
            labels,
        )
        or 0
    )

    def handler(request):
        requests.append(request)
        return httpx.Response(202, json={"ok": True})

    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(handler),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={
            "organization_id": str(org.id),
            "execution_id": "exec-1",
            "execution_status": "failed",
            "workflow_name": "Deploy API",
        },
    )

    attempt = IntegrationDeliveryAttempt.objects.get()
    connection.refresh_from_db()

    assert len(requests) == 1
    assert attempt.integration == connection
    assert attempt.organization == org
    assert attempt.event_type == EVENT_EXECUTION_FAILED
    assert attempt.success is True
    assert attempt.http_status == 202
    assert attempt.error_detail == ""
    assert (
        connection.last_delivery_status
        == IntegrationConnection.LastDeliveryStatus.SUCCESS
    )
    after = REGISTRY.get_sample_value(
        "runbook_integration_dispatch_duration_seconds_count",
        labels,
    )
    assert after > before


@pytest.mark.django_db
def test_failed_dispatch_creates_failed_attempt_and_does_not_raise(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    connection = _connection(org=org, integration_fernet_key=integration_fernet_key)

    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(lambda request: httpx.Response(500, text="nope")),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    attempt = IntegrationDeliveryAttempt.objects.get()
    connection.refresh_from_db()

    assert attempt.success is False
    assert attempt.http_status == 500
    assert attempt.error_detail == "non_2xx_response"
    assert (
        connection.last_delivery_status
        == IntegrationConnection.LastDeliveryStatus.FAILED
    )


@pytest.mark.django_db
def test_timeout_creates_failed_attempt_and_does_not_raise(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    _connection(org=org, integration_fernet_key=integration_fernet_key)

    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(handler),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    attempt = IntegrationDeliveryAttempt.objects.get()
    assert attempt.success is False
    assert attempt.http_status is None
    assert attempt.error_detail == "timeout"


@pytest.mark.django_db
def test_org_a_dispatch_never_sends_to_org_b_connections(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    other_org = Organization.objects.create(name="Other Corp", slug="other")
    _connection(org=org, integration_fernet_key=integration_fernet_key, name="Org A")
    _connection(
        org=other_org, integration_fernet_key=integration_fernet_key, name="Org B"
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(handler),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert len(requests) == 1
    assert IntegrationDeliveryAttempt.objects.count() == 1
    assert IntegrationDeliveryAttempt.objects.get().organization == org


@pytest.mark.django_db
def test_inactive_connection_does_not_dispatch(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    _connection(
        org=org,
        integration_fernet_key=integration_fernet_key,
        is_active=False,
    )
    requests = []
    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(
            lambda request: requests.append(request) or httpx.Response(204)
        ),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert requests == []
    assert IntegrationDeliveryAttempt.objects.count() == 0


@pytest.mark.django_db
def test_event_type_filtering_works(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    _connection(
        org=org,
        integration_fernet_key=integration_fernet_key,
        event_types=[EVENT_EXECUTION_COMPLETED],
    )
    requests = []
    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(
            lambda request: requests.append(request) or httpx.Response(204)
        ),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )
    IntegrationService.notify(
        event_type=EVENT_EXECUTION_COMPLETED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert len(requests) == 1
    assert IntegrationDeliveryAttempt.objects.count() == 1
    assert (
        IntegrationDeliveryAttempt.objects.get().event_type == EVENT_EXECUTION_COMPLETED
    )


@pytest.mark.django_db
def test_notify_respects_max_per_trigger(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation, settings
):
    settings.INTEGRATION_MAX_PER_TRIGGER = 1
    _connection(org=org, integration_fernet_key=integration_fernet_key, name="First")
    _connection(org=org, integration_fernet_key=integration_fernet_key, name="Second")
    requests = []
    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(
            lambda request: requests.append(request) or httpx.Response(204)
        ),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert len(requests) == 1
    assert IntegrationDeliveryAttempt.objects.count() == 1


@pytest.mark.django_db
def test_notify_respects_dispatch_budget(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation, settings
):
    settings.INTEGRATION_DISPATCH_BUDGET_SECONDS = 0
    _connection(org=org, integration_fernet_key=integration_fernet_key)
    requests = []
    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(
            lambda request: requests.append(request) or httpx.Response(204)
        ),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert requests == []
    assert IntegrationDeliveryAttempt.objects.count() == 0


@pytest.mark.django_db
def test_notify_continues_after_connection_failure(
    org, integration_fernet_key, monkeypatch
):
    first = _connection(org=org, integration_fernet_key=integration_fernet_key)
    second = _connection(
        org=org, integration_fernet_key=integration_fernet_key, name="Second"
    )
    notified = []

    def notify_connection(*, connection, event_type, context):
        notified.append(connection.id)
        if connection.id == first.id:
            raise RuntimeError("record attempt failed")

    monkeypatch.setattr(IntegrationService, "_notify_connection", notify_connection)

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    assert notified == [first.id, second.id]


@pytest.mark.django_db
def test_credential_decryption_failure_records_failed_attempt(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    connection = _connection(org=org, integration_fernet_key=integration_fernet_key)
    IntegrationConnection.objects.filter(pk=connection.pk).update(
        encrypted_credentials=b"not-a-fernet-token"
    )
    requests = []
    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(
            lambda request: requests.append(request) or httpx.Response(204)
        ),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={"execution_id": "exec-1"},
    )

    attempt = IntegrationDeliveryAttempt.objects.get()
    assert requests == []
    assert attempt.success is False
    assert attempt.http_status is None
    assert attempt.error_detail == "validation_error"


@pytest.mark.django_db
def test_payload_preview_redacts_secrets_and_webhook_url(
    org, integration_fernet_key, monkeypatch, disable_ssrf_validation
):
    _connection(org=org, integration_fernet_key=integration_fernet_key)
    monkeypatch.setattr(
        IntegrationService,
        "http_client_factory",
        _mock_client_factory(lambda request: httpx.Response(204)),
    )

    IntegrationService.notify(
        event_type=EVENT_EXECUTION_FAILED,
        organization=org,
        context={
            "execution_id": "exec-1",
            "webhook_url": "https://example.com/secret",
            "claim_token": "claim-secret",
            "nested": {"api_token": "api-secret"},
        },
    )

    preview = IntegrationDeliveryAttempt.objects.get().payload_preview
    assert "https://example.com/secret" not in str(preview)
    assert "claim-secret" not in str(preview)
    assert "api-secret" not in str(preview)
    assert preview["webhook_url"] == "[redacted]"
    assert preview["claim_token"] == "[redacted]"
    assert preview["nested"]["api_token"] == "[redacted]"


@pytest.mark.django_db
def test_audit_event_emitted_for_create_update_deactivate(
    org, integration_fernet_key, disable_ssrf_validation
):
    connection = IntegrationService.create_connection(
        organization=org,
        type=IntegrationConnection.Type.GENERIC_WEBHOOK,
        name="Ops Webhook",
        credentials={"url": "https://example.com/webhook"},
        event_types=[EVENT_EXECUTION_FAILED],
    )
    IntegrationService.update_connection(
        connection=connection,
        name="Updated Webhook",
        credentials={"url": "https://example.com/updated"},
    )
    IntegrationService.deactivate_connection(connection=connection)

    assert list(
        AuditEvent.objects.order_by("created_at").values_list("event_type", flat=True)
    ) == [
        "integration.created",
        "integration.updated",
        "integration.deactivated",
    ]
    assert (
        AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.INTEGRATION_CONNECTION,
            object_id=connection.id,
        ).count()
        == 3
    )
