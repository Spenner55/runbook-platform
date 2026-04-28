import pytest
from django.test import Client

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.organizations.models import Organization


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
