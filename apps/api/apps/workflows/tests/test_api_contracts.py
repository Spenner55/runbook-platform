from unittest.mock import patch

import pytest

from apps.common.exceptions import ConcurrencyConflictError
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Deploy", slug="deploy", raw_content="Do the thing"
    )


@pytest.fixture
def draft_workflow(runbook):
    """Create a draft workflow using the stub (no AI service call)."""
    return workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
    )


@pytest.fixture
def pending_review_workflow(runbook):
    """Create an AI-style pending-review workflow without calling the AI service."""
    return workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
        requires_review=True,
        parse_source="ai_parse",
    )


def _client_for_runbook(api_client_for_org, runbook):
    return api_client_for_org(runbook.organization)


def _client_for_workflow(api_client_for_org, workflow):
    return api_client_for_org(workflow.organization)


# ---------------------------------------------------------------------------
# Create endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_workflow_returns_201(runbook, api_client_for_org):
    """POST /api/v1/workflows/ creates a workflow via the AI boundary (mocked)."""
    stub_workflow = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
    )
    with patch(
        "apps.workflows.views.services.create_workflow_from_runbook",
        return_value=stub_workflow,
    ):
        client = _client_for_runbook(api_client_for_org, runbook)
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
def test_create_workflow_invalid_runbook_returns_404(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/workflows/",
        data={"runbook_id": "00000000-0000-0000-0000-000000000000"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_create_workflow_missing_runbook_id_returns_400(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/workflows/",
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_create_workflow_version_conflict_returns_409(runbook, api_client_for_org):
    with patch(
        "apps.workflows.views.services.create_workflow_from_runbook",
        side_effect=ConcurrencyConflictError(
            code="workflow_version_conflict",
            detail="Workflow version allocation conflicted with another request.",
        ),
    ):
        client = _client_for_runbook(api_client_for_org, runbook)
        response = client.post(
            "/api/v1/workflows/",
            data={"runbook_id": str(runbook.id)},
            content_type="application/json",
        )
    assert response.status_code == 409
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_version_conflict"


# ---------------------------------------------------------------------------
# AI error propagation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_workflow_ai_unavailable_surfaces_as_503(runbook, api_client_for_org):
    from apps.workflows.internal_clients import AiServiceUnavailableError

    with patch(
        "apps.workflows.views.services.create_workflow_from_runbook",
        side_effect=AiServiceUnavailableError("ai unavailable"),
    ):
        client = _client_for_runbook(api_client_for_org, runbook)
        response = client.post(
            "/api/v1/workflows/",
            data={"runbook_id": str(runbook.id)},
            content_type="application/json",
        )
    assert response.status_code == 503
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_ai_unavailable"


@pytest.mark.django_db
def test_create_workflow_ai_timeout_surfaces_as_503(runbook, api_client_for_org):
    from apps.workflows.internal_clients import AiServiceTimeoutError

    with patch(
        "apps.workflows.views.services.create_workflow_from_runbook",
        side_effect=AiServiceTimeoutError("timed out"),
    ):
        client = _client_for_runbook(api_client_for_org, runbook)
        response = client.post(
            "/api/v1/workflows/",
            data={"runbook_id": str(runbook.id)},
            content_type="application/json",
        )
    assert response.status_code == 503
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_ai_unavailable"


@pytest.mark.django_db
def test_create_workflow_ai_bad_response_surfaces_as_503(runbook, api_client_for_org):
    from apps.workflows.internal_clients import AiServiceBadResponseError

    with patch(
        "apps.workflows.views.services.create_workflow_from_runbook",
        side_effect=AiServiceBadResponseError("bad body"),
    ):
        client = _client_for_runbook(api_client_for_org, runbook)
        response = client.post(
            "/api/v1/workflows/",
            data={"runbook_id": str(runbook.id)},
            content_type="application/json",
        )
    assert response.status_code == 503
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_ai_bad_response"


@pytest.mark.django_db
def test_create_workflow_ai_contract_error_surfaces_as_503(runbook, api_client_for_org):
    from apps.workflows.internal_clients import AiServiceContractError

    with patch(
        "apps.workflows.views.services.create_workflow_from_runbook",
        side_effect=AiServiceContractError("missing field"),
    ):
        client = _client_for_runbook(api_client_for_org, runbook)
        response = client.post(
            "/api/v1/workflows/",
            data={"runbook_id": str(runbook.id)},
            content_type="application/json",
        )
    assert response.status_code == 503
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "workflow_ai_bad_response"


# ---------------------------------------------------------------------------
# Publish action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_workflow_transitions_to_published(draft_workflow, api_client_for_org):
    client = _client_for_workflow(api_client_for_org, draft_workflow)
    response = client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    assert response.status_code == 200
    assert response.json()["status"] == "published"


@pytest.mark.django_db
def test_publish_already_published_returns_409(draft_workflow, api_client_for_org):
    client = _client_for_workflow(api_client_for_org, draft_workflow)
    client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    response = client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    assert response.status_code == 409
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "invalid_state_transition"


@pytest.mark.django_db
def test_publish_requires_review_returns_409(
    pending_review_workflow, api_client_for_org
):
    client = _client_for_workflow(api_client_for_org, pending_review_workflow)
    response = client.post(f"/api/v1/workflows/{pending_review_workflow.id}/publish/")
    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["code"] == "workflow_requires_review"


@pytest.mark.django_db
def test_accept_review_clears_requires_review(
    pending_review_workflow, api_client_for_org
):
    client = _client_for_workflow(api_client_for_org, pending_review_workflow)
    response = client.post(
        f"/api/v1/workflows/{pending_review_workflow.id}/accept-review/"
    )
    assert response.status_code == 200
    assert response.json()["requires_review"] is False
    assert response.json()["status"] == "draft"


@pytest.mark.django_db
def test_accept_review_allows_publish(pending_review_workflow, api_client_for_org):
    client = _client_for_workflow(api_client_for_org, pending_review_workflow)
    accept_response = client.post(
        f"/api/v1/workflows/{pending_review_workflow.id}/accept-review/"
    )
    assert accept_response.status_code == 200

    publish_response = client.post(
        f"/api/v1/workflows/{pending_review_workflow.id}/publish/"
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["status"] == "published"


@pytest.mark.django_db
def test_reject_review_archives_workflow(pending_review_workflow, api_client_for_org):
    client = _client_for_workflow(api_client_for_org, pending_review_workflow)
    response = client.post(
        f"/api/v1/workflows/{pending_review_workflow.id}/reject-review/"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# Publish supersede behavior
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_supersedes_existing_published_workflow(runbook, api_client_for_org):
    """Publishing a new version must supersede the previously published one."""
    stub = StubWorkflowTransformClient()
    wf1 = workflow_services.create_workflow(runbook=runbook, transform_client=stub)
    wf2 = workflow_services.create_workflow(runbook=runbook, transform_client=stub)

    client = _client_for_runbook(api_client_for_org, runbook)
    client.post(f"/api/v1/workflows/{wf1.id}/publish/")
    client.post(f"/api/v1/workflows/{wf2.id}/publish/")

    wf1.refresh_from_db()
    wf2.refresh_from_db()
    assert wf1.status == "superseded"
    assert wf2.status == "published"


# ---------------------------------------------------------------------------
# Archive action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_archive_draft_workflow_transitions_to_archived(
    draft_workflow, api_client_for_org
):
    client = _client_for_workflow(api_client_for_org, draft_workflow)
    response = client.post(f"/api/v1/workflows/{draft_workflow.id}/archive/")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


@pytest.mark.django_db
def test_archive_published_workflow_returns_409(draft_workflow, api_client_for_org):
    client = _client_for_workflow(api_client_for_org, draft_workflow)
    client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/")
    response = client.post(f"/api/v1/workflows/{draft_workflow.id}/archive/")
    assert response.status_code == 409


@pytest.mark.django_db
def test_non_member_cannot_read_or_publish_workflow(
    draft_workflow, org, api_client_for_org
):
    other_org = type(org).objects.create(name="Other Corp", slug="other-corp")
    client = api_client_for_org(other_org)

    assert client.get("/api/v1/workflows/").json() == []
    assert client.get(f"/api/v1/workflows/{draft_workflow.id}/").status_code == 404
    assert (
        client.post(f"/api/v1/workflows/{draft_workflow.id}/publish/").status_code
        == 404
    )
