import pytest
from django.test import Client
from unittest.mock import patch

from apps.runbooks.ai_client import (
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
)
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
@patch(
    "apps.workflows.views.services.create_workflow_from_runbook",
    side_effect=AiServiceUnavailableError("ai unavailable"),
)
def test_create_workflow_ai_unavailable_returns_503(_mock_create, runbook):
    client = Client()
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": str(runbook.id)},
        content_type="application/json",
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "ai unavailable"


@pytest.mark.django_db
@patch(
    "apps.workflows.views.services.create_workflow_from_runbook",
    side_effect=AiServiceTimeoutError("ai timeout"),
)
def test_create_workflow_ai_timeout_returns_504(_mock_create, runbook):
    client = Client()
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": str(runbook.id)},
        content_type="application/json",
    )
    assert response.status_code == 504
    assert response.json()["detail"] == "ai timeout"


@pytest.mark.django_db
@patch(
    "apps.workflows.views.services.create_workflow_from_runbook",
    side_effect=AiServiceBadResponseError("ai bad response"),
)
def test_create_workflow_ai_bad_response_returns_502(_mock_create, runbook):
    client = Client()
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": str(runbook.id)},
        content_type="application/json",
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "ai bad response"


@pytest.mark.django_db
@patch(
    "apps.workflows.views.services.create_workflow_from_runbook",
    side_effect=AiServiceContractError("ai contract error"),
)
def test_create_workflow_ai_contract_error_returns_502(_mock_create, runbook):
    client = Client()
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": str(runbook.id)},
        content_type="application/json",
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "ai contract error"


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
