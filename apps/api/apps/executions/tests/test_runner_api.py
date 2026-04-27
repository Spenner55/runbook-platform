"""
Tests for internal runner endpoints via the new internal_views.py.

These tests exercise the full HTTP path through /api/v1/internal/...
"""

import pytest
from django.test import Client

from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Runner Test Runbook",
        slug="runner-test",
        raw_content="Verify prerequisites\nExecute deployment",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow(runbook=runbook, transform_client=StubWorkflowTransformClient())
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def queued_execution(published_workflow):
    return execution_services.create_execution(workflow=published_workflow)


# ---------------------------------------------------------------------------
# claim-next
# ---------------------------------------------------------------------------

CLAIM_NEXT_URL = "/api/v1/internal/executions/claim-next/"


@pytest.mark.django_db
def test_claim_next_empty_queue_returns_200_with_null_execution():
    client = Client()
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["execution"] is None
    assert "poll_after_seconds" in body


@pytest.mark.django_db
def test_claim_next_claims_queued_execution(queued_execution):
    client = Client()
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["execution"] is not None
    assert body["execution"]["status"] == "claimed"
    assert body["execution"]["id"] == str(queued_execution.id)
    assert "claim_token" in body
    assert body["claim_token"] is not None


@pytest.mark.django_db
def test_claim_next_response_includes_steps(queued_execution):
    client = Client()
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    body = response.json()
    assert "steps" in body["execution"]
    assert len(body["execution"]["steps"]) > 0


@pytest.mark.django_db
def test_claim_next_missing_runner_id_returns_400():
    client = Client()
    response = client.post(
        CLAIM_NEXT_URL,
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_heartbeat_updates_last_heartbeat_at(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["execution_id"] == str(execution.id)
    assert "last_heartbeat_at" in body


@pytest.mark.django_db
def test_heartbeat_wrong_runner_returns_409(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={"runner_id": "wrong-runner", "claim_token": claim_token},
        content_type="application/json",
    )
    assert response.status_code == 409
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "runner_ownership_mismatch"


@pytest.mark.django_db
def test_heartbeat_wrong_token_returns_409(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={
            "runner_id": "runner-1",
            "claim_token": "00000000-0000-0000-0000-000000000000",
        },
        content_type="application/json",
    )
    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["code"] == "claim_token_mismatch"


# ---------------------------------------------------------------------------
# step-update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_update_transitions_pending_to_running(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "running",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["step"]["status"] == "running"
    assert body["execution_status"] == "running"


@pytest.mark.django_db
def test_step_update_invalid_transition_returns_409(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",  # pending -> succeeded is not allowed
        },
        content_type="application/json",
    )
    assert response.status_code == 409
    assert "errors" in response.json()


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_complete_marks_execution_succeeded(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/complete/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "final_status": "succeeded",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["id"] == str(execution.id)


@pytest.mark.django_db
def test_complete_wrong_runner_returns_409(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/complete/",
        data={
            "runner_id": "wrong-runner",
            "claim_token": claim_token,
            "final_status": "succeeded",
        },
        content_type="application/json",
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_complete_invalid_final_status_returns_400(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    client = Client()
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/complete/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "final_status": "cancelled",  # not a valid final_status
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()
