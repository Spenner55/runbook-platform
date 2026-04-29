import pytest

from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


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
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def execution(published_workflow):
    return execution_services.create_execution(workflow=published_workflow)


def _client_for_workflow(api_client_for_org, workflow):
    return api_client_for_org(workflow.organization)


def _client_for_execution(api_client_for_org, execution):
    return api_client_for_org(execution.organization)


# ---------------------------------------------------------------------------
# Create endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_execution_returns_201(published_workflow, api_client_for_org):
    client = _client_for_workflow(api_client_for_org, published_workflow)
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
def test_create_execution_response_includes_snapshot(
    published_workflow, api_client_for_org
):
    client = _client_for_workflow(api_client_for_org, published_workflow)
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": str(published_workflow.id)},
        content_type="application/json",
    )
    body = response.json()
    assert body["workflow_version"] == published_workflow.version
    assert "workflow_snapshot" in body


@pytest.mark.django_db
def test_create_execution_missing_workflow_id_returns_400(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/executions/",
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_create_execution_unknown_workflow_returns_404(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": "00000000-0000-0000-0000-000000000000"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_create_execution_draft_workflow_returns_400_with_envelope(
    runbook, api_client_for_org
):
    draft_wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    client = api_client_for_org(runbook.organization)
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": str(draft_wf.id)},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_not_published"


@pytest.mark.django_db
def test_create_execution_requires_review_workflow_returns_400(
    runbook, api_client_for_org
):
    workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source="ai_parse",
    )
    workflow.status = "published"
    workflow.save(update_fields=["status", "updated_at"])

    client = api_client_for_org(runbook.organization)
    response = client.post(
        "/api/v1/executions/",
        data={"workflow_id": str(workflow.id)},
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert body["errors"][0]["code"] == "workflow_requires_review"


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_execution_returns_steps(execution, api_client_for_org):
    client = _client_for_execution(api_client_for_org, execution)
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
def test_cancel_execution_returns_cancelled_status(execution, api_client_for_org):
    client = _client_for_execution(api_client_for_org, execution)
    response = client.post(f"/api/v1/executions/{execution.id}/cancel/")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.django_db
def test_non_member_cannot_read_or_cancel_execution(
    execution, org, api_client_for_org
):
    other_org = type(org).objects.create(name="Other Corp", slug="other-corp")
    client = api_client_for_org(other_org)

    assert client.get("/api/v1/executions/").json() == []
    assert client.get(f"/api/v1/executions/{execution.id}/").status_code == 404
    assert client.post(f"/api/v1/executions/{execution.id}/cancel/").status_code == 404
