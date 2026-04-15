import pytest
from django.test import Client

from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Deploy", slug="deploy", raw_content=""
    )


@pytest.fixture
def draft_workflow(runbook):
    return workflow_services.create_workflow_from_runbook(runbook=runbook)


@pytest.mark.django_db
def test_create_workflow_returns_201(runbook):
    client = Client()
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": str(runbook.id)},
        content_type="application/json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["status"] == "draft"
    assert "definition" in body


@pytest.mark.django_db
def test_create_workflow_invalid_runbook_returns_400():
    client = Client()
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": "00000000-0000-0000-0000-000000000000"},
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_publish_workflow_transitions_to_published(draft_workflow):
    client = Client()
    response = client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    assert response.status_code == 200
    assert response.json()["status"] == "published"


@pytest.mark.django_db
def test_publish_already_published_returns_400(draft_workflow):
    client = Client()
    client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    response = client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    assert response.status_code == 400
