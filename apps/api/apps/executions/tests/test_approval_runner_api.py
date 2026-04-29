"""
Tests for internal runner approval endpoints:
  POST /api/v1/internal/executions/<id>/steps/<id>/start/
  POST /api/v1/internal/executions/<id>/steps/<id>/approval-status/
"""

import pytest
from django.test import Client

from apps.approvals import services as approval_services
from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Approval Runner Test",
        slug="approval-runner-test",
        raw_content="Deploy service\nVerify health",
    )


@pytest.fixture
def _base_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def claimed_no_approval(_base_workflow):
    """Execution where no step requires approval."""
    execution_services.create_execution(workflow=_base_workflow)
    return execution_services.claim_next_execution(runner_id="runner-1")


@pytest.fixture
def claimed_with_approval(_base_workflow):
    """Execution where the first step requires approval."""
    execution = execution_services.create_execution(workflow=_base_workflow)
    # Patch first step to require approval.
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.step_snapshot = {**step.step_snapshot, "requiresApproval": True}
    step.save()
    return execution_services.claim_next_execution(runner_id="runner-1")


# ---------------------------------------------------------------------------
# /start/ — non-approval step
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_start_no_approval_returns_run(claimed_no_approval):
    result = claimed_no_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runner_action"] == "run"
    assert body["step"]["status"] == "running"


@pytest.mark.django_db
def test_step_start_non_approval_transitions_execution_to_running(claimed_no_approval):
    result = claimed_no_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )

    execution.refresh_from_db()
    assert execution.status == "running"


# ---------------------------------------------------------------------------
# /start/ — approval step
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_step_start_with_approval_returns_wait(claimed_with_approval):
    result = claimed_with_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["runner_action"] == "wait_for_approval"
    assert body["step"]["status"] == "waiting_for_approval"
    assert "approval_request" in body
    assert body["approval_request"]["status"] == "pending"
    assert body["poll_after_seconds"] == 5


@pytest.mark.django_db
def test_step_start_approval_is_idempotent(claimed_with_approval):
    result = claimed_with_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    url = f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/"
    payload = {"runner_id": "runner-1", "claim_token": claim_token}

    r1 = client.post(url, data=payload, content_type="application/json")
    r2 = client.post(url, data=payload, content_type="application/json")

    assert r1.status_code == 201
    assert r2.status_code == 200
    # Same approval request returned.
    assert r1.json()["approval_request"]["id"] == r2.json()["approval_request"]["id"]


@pytest.mark.django_db
def test_step_start_wrong_runner_returns_409(claimed_with_approval):
    result = claimed_with_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "wrong-runner", "claim_token": claim_token},
        content_type="application/json",
    )

    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["code"] == "runner_ownership_mismatch"


# ---------------------------------------------------------------------------
# Phase 10.2 compatibility: policy can force wait_for_approval on any step
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_policy_forced_approval_on_schema_non_approval_step(claimed_no_approval):
    """
    A step whose workflow schema has requiresApproval=false can still receive
    runner_action=wait_for_approval when Django (Phase 10.2 policy engine) sets
    requires_approval=True on the model. The runner must not branch locally on
    schema fields — it defers entirely to Django's start response.
    """
    result = claimed_no_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    # Confirm schema says no approval required.
    assert not step.step_snapshot.get("requiresApproval", False)

    # Simulate Phase 10.2 policy engine flagging the step.
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["runner_action"] == "wait_for_approval", (
        "Django must return wait_for_approval even when schema says requiresApproval=false"
    )
    assert body["step"]["status"] == "waiting_for_approval"
    assert body["approval_request"]["status"] == "pending"


# ---------------------------------------------------------------------------
# /approval-status/ — polling
# ---------------------------------------------------------------------------


@pytest.fixture
def waiting_step_data(claimed_with_approval):
    result = claimed_with_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()
    ar, _ = approval_services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )
    return {"execution": execution, "step": step, "claim_token": claim_token, "ar": ar}


@pytest.mark.django_db
def test_approval_status_pending_returns_wait(waiting_step_data):
    d = waiting_step_data
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{d['execution'].id}/steps/{d['step'].id}/approval-status/",
        data={"runner_id": "runner-1", "claim_token": d["claim_token"]},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runner_action"] == "wait"
    assert body["poll_after_seconds"] == 5


@pytest.mark.django_db
def test_approval_status_approved_returns_run(waiting_step_data):
    d = waiting_step_data
    approval_services.decide_approval(
        approval_request=d["ar"],
        decision="approved",
        actor_label="Test Op",
    )

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{d['execution'].id}/steps/{d['step'].id}/approval-status/",
        data={"runner_id": "runner-1", "claim_token": d["claim_token"]},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runner_action"] == "run"
    assert body["step_status"] == "running"


@pytest.mark.django_db
def test_approval_status_rejected_returns_fail(waiting_step_data):
    d = waiting_step_data
    approval_services.decide_approval(
        approval_request=d["ar"],
        decision="rejected",
        actor_label="Test Op",
    )

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{d['execution'].id}/steps/{d['step'].id}/approval-status/",
        data={"runner_id": "runner-1", "claim_token": d["claim_token"]},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runner_action"] == "fail"
    assert body["step_status"] == "failed"


@pytest.mark.django_db
def test_approval_status_timed_out_returns_fail(waiting_step_data):
    from datetime import timedelta

    from django.utils import timezone

    d = waiting_step_data
    d["ar"].expires_at = timezone.now() - timedelta(seconds=1)
    d["ar"].save(update_fields=["expires_at", "updated_at"])

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{d['execution'].id}/steps/{d['step'].id}/approval-status/",
        data={"runner_id": "runner-1", "claim_token": d["claim_token"]},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["runner_action"] == "fail"


@pytest.mark.django_db
def test_approval_status_wrong_runner_returns_409(waiting_step_data):
    d = waiting_step_data
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{d['execution'].id}/steps/{d['step'].id}/approval-status/",
        data={"runner_id": "wrong-runner", "claim_token": d["claim_token"]},
        content_type="application/json",
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_approval_status_step_not_in_approval_flow_returns_409(claimed_no_approval):
    result = claimed_no_approval
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/approval-status/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    assert response.status_code == 409
