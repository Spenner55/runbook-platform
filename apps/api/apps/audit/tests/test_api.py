import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.organizations.models import Organization


def _make_event(org, event_type="execution.created", actor_type=AuditEvent.ActorType.SYSTEM, object_id=None):
    return AuditService.emit(
        organization_id=org.id,
        actor_type=actor_type,
        event_type=event_type,
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=object_id or org.id,
        metadata={},
    )


@pytest.mark.django_db
def test_audit_list_requires_organization_id():
    response = Client().get("/api/v1/audit/")

    assert response.status_code == 400
    assert response.json()["errors"][0]["attr"] == "organization_id"


@pytest.mark.django_db
def test_audit_list_filters_by_organization_and_object(org):
    other_org = Organization.objects.create(name="Other Corp", slug="other")
    execution_id = org.id
    other_execution_id = other_org.id

    event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=execution_id,
        metadata={},
    )
    AuditService.emit(
        organization_id=other_org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=other_execution_id,
        metadata={},
    )

    response = Client().get(
        "/api/v1/audit/",
        {
            "organization_id": str(org.id),
            "object_type": "execution",
            "object_id": str(execution_id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == str(event.id)


@pytest.mark.django_db
def test_audit_list_rejects_object_type_without_object_id(org):
    response = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "object_type": "execution"},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_execution_audit_includes_related_events(org):
    execution_id = org.id
    step_id = Organization.objects.create(name="Step Org", slug="step-org").id

    execution_event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=execution_id,
        metadata={},
    )
    step_event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.RUNNER,
        actor_id="runner-1",
        actor_label="runner-1",
        event_type="execution_step.started",
        object_type=AuditEvent.ObjectType.EXECUTION_STEP,
        object_id=step_id,
        metadata={"execution_id": str(execution_id), "step_key": "deploy"},
    )

    response = Client().get(
        f"/api/v1/executions/{execution_id}/audit/",
        {"organization_id": str(org.id)},
    )

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {str(execution_event.id), str(step_event.id)}


@pytest.mark.django_db
def test_audit_list_filters_by_event_type(org):
    _make_event(org, event_type="execution.created")
    cancelled = _make_event(org, event_type="execution.cancelled")

    response = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "event_type": "execution.cancelled"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == str(cancelled.id)


@pytest.mark.django_db
def test_audit_list_filters_by_actor_type(org):
    _make_event(org, actor_type=AuditEvent.ActorType.SYSTEM)
    runner_event = _make_event(org, actor_type=AuditEvent.ActorType.RUNNER)

    response = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "actor_type": "runner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == str(runner_event.id)


@pytest.mark.django_db
def test_audit_list_filters_by_occurred_after(org):
    past = timezone.now().replace(microsecond=0)
    early = _make_event(org)
    early_event = AuditEvent.objects.get(pk=early.id)
    early_event_time = early_event.occurred_at

    # Emit a second event at a later timestamp via occurred_at override
    later_event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.cancelled",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={},
    )

    cutoff = early_event_time.isoformat()
    response = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "occurred_after": cutoff},
    )

    assert response.status_code == 200
    returned_ids = {row["id"] for row in response.json()["results"]}
    assert str(later_event.id) in returned_ids


@pytest.mark.django_db
def test_audit_list_filters_by_occurred_before(org):
    early = _make_event(org, event_type="execution.created")

    response = Client().get(
        "/api/v1/audit/",
        {
            "organization_id": str(org.id),
            "occurred_before": "2000-01-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["count"] == 0


@pytest.mark.django_db
def test_audit_list_limit_and_offset(org):
    other = Organization.objects.create(name="Other", slug="other-2")
    for i in range(5):
        _make_event(org, event_type=f"execution.created")

    response_page1 = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "limit": "2", "offset": "0"},
    )
    response_page2 = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "limit": "2", "offset": "2"},
    )

    assert response_page1.status_code == 200
    assert len(response_page1.json()["results"]) == 2

    assert response_page2.status_code == 200
    assert len(response_page2.json()["results"]) == 2

    ids1 = {r["id"] for r in response_page1.json()["results"]}
    ids2 = {r["id"] for r in response_page2.json()["results"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.django_db
def test_audit_list_malformed_timestamp_returns_400(org):
    response = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "occurred_after": "not-a-date"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_audit_list_invalid_actor_type_returns_400(org):
    response = Client().get(
        "/api/v1/audit/",
        {"organization_id": str(org.id), "actor_type": "superuser"},
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_audit_list_write_methods_rejected(org):
    client = Client()
    url = "/api/v1/audit/"
    params = f"?organization_id={org.id}"

    assert client.post(url).status_code == 405
    assert client.put(url + params).status_code == 405
    assert client.patch(url + params).status_code == 405
    assert client.delete(url + params).status_code == 405
