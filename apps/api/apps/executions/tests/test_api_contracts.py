import pytest
from django.test import Client

from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Deploy Service",
        slug="deploy-service",
        raw_content="Verify prerequisites\nExecute deployment",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow_from_runbook(runbook=runbook)
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def execution(published_workflow):
    return execution_services.create_execution(workflow=published_workflow)


# ---------------------------------------------------------------------------
# Create endpoint
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_execution_returns_201(published_workflow):
    client = Client()
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": str(published_workflow.id)},
        content_type="application/json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert "steps" in body
    assert len(body["steps"]) > 0


@pytest.mark.django_db
def test_create_execution_response_includes_snapshot(published_workflow):
    client = Client()
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": str(published_workflow.id)},
        content_type="application/json",
    )
    body = response.json()
    assert body["workflow_version"] == published_workflow.version
    assert "workflow_snapshot" in body


@pytest.mark.django_db
def test_create_execution_missing_workflow_id_returns_400():
    client = Client()
    response = client.post(
        "/api/v1/executions/",
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_create_execution_unknown_workflow_returns_404():
    client = Client()
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": "00000000-0000-0000-0000-000000000000"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_create_execution_draft_workflow_returns_400_with_envelope(runbook):
    draft_wf = workflow_services.create_workflow_from_runbook(runbook=runbook)
    client = Client()
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": str(draft_wf.id)},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_not_published"


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_get_execution_returns_steps(execution):
    client = Client()
    response = client.get(f"/api/v1/executions/{execution.id}/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(execution.id)
    assert "steps" in body
    assert len(body["steps"]) > 0
    step = body["steps"][0]
    assert "position" in step
    assert "name" in step
    assert "status" in step


# ---------------------------------------------------------------------------
# Cancel action
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cancel_execution_returns_cancelled_status(execution):
    client = Client()
    response = client.post(f"/api/v1/executions/{execution.id}/cancel/")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
