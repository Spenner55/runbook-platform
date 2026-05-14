"""
Tests for internal runner endpoints via the new internal_views.py.

These tests exercise the full HTTP path through /api/v1/internal/...
"""

import pytest
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.runners.models import Runner, RunnerPool
from apps.runners.services import generate_runner_token
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient
from apps.workflows.tests.fixtures.workflow_v2 import valid_v2_shell_command_workflow


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
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    body = response.json()
    assert "steps" in body["execution"]
    assert len(body["execution"]["steps"]) > 0


@pytest.mark.django_db
def test_claim_next_v2_execution_includes_action_snapshot(runbook):
    workflow = workflow_services.create_workflow_v2_draft(
        runbook=runbook,
        definition=valid_v2_shell_command_workflow(),
    )
    workflow = workflow_services.publish_workflow(workflow=workflow)
    queued = execution_services.create_execution(workflow=workflow)

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["execution"]["id"] == str(queued.id)
    step = body["execution"]["steps"][0]
    assert step["action_snapshot"] == workflow.definition["steps"][0]["action"]
    assert step["step_snapshot"] == workflow.definition["steps"][0]
    assert step["timeout_seconds"] == 30


@pytest.mark.django_db
def test_claim_next_missing_runner_id_returns_400():
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        CLAIM_NEXT_URL,
        data={},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_claim_next_without_authorization_is_rejected():
    client = Client()
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_claim_next_with_invalid_runner_token_is_rejected():
    client = Client(HTTP_AUTHORIZATION="Bearer wrong-runner-token")
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_claim_next_with_user_jwt_is_rejected(user):
    token = str(RefreshToken.for_user(user).access_token)
    client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 403


def _runner_client_with_status(org, pool, status):
    """Create a runner in the given status and return (Client, runner)."""
    from django.utils import timezone

    clear, token_hash = generate_runner_token()
    now = timezone.now()
    runner = Runner.objects.create(
        organization=org,
        pool=pool,
        display_name="test-runner",
        status=status,
        token_hash=token_hash,
        fingerprint_sha256="fp-test",
        registered_at=now,
        last_seen_at=now,
        last_heartbeat_at=now,
    )
    client = Client(HTTP_AUTHORIZATION=f"Bearer {clear}")
    return client, runner


@pytest.fixture
def runner_pool(org):

    return RunnerPool.objects.create(
        organization=org,
        key="test-pool",
        name="Test Pool",
        status=RunnerPool.Status.ACTIVE,
    )


@pytest.mark.django_db
def test_claim_next_disabled_runner_returns_401(org, runner_pool):
    client, _ = _runner_client_with_status(org, runner_pool, Runner.Status.DISABLED)
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "any"},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_claim_next_revoked_runner_returns_401(org, runner_pool):
    client, _ = _runner_client_with_status(org, runner_pool, Runner.Status.REVOKED)
    response = client.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "any"},
        content_type="application/json",
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_heartbeat_updates_last_heartbeat_at(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
def test_step_update_rejects_running_status(queued_execution):
    """Update endpoint must reject status=running — only /start/ may set a step running."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "running",
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    step.refresh_from_db()
    assert step.status == "pending"


@pytest.mark.django_db
def test_step_update_accepts_succeeded_after_start(queued_execution):
    """Update endpoint accepts terminal statuses once the step is running via /start/."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["step"]["status"] == "succeeded"


@pytest.mark.django_db
def test_step_update_invalid_transition_returns_409(queued_execution):
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = client.post(
        f"/api/v1/internal/executions/{execution.id}/complete/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "final_status": "queued",  # not a valid final_status
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


# ---------------------------------------------------------------------------
# step-update: sandbox result fields (Phase A schema prep)
# ---------------------------------------------------------------------------


def _start_step(client, execution, step, claim_token):
    """Helper: call /start/ so the step is running before /update/."""
    client.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_step_update_accepts_sandbox_result_fields(queued_execution):
    """Sandbox result fields are accepted and persisted on a terminal step update."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    _start_step(api, execution, step, claim_token)

    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",
            "exit_code": 0,
            "failure_kind": "",
            "timed_out": False,
            "cancelled": False,
            "sandbox_provider": "local_process",
            "sandbox_run_id": "run-abc123",
            "command_sha256": "a" * 64,
            "result_metadata": {"wall_seconds": 1.2},
        },
        content_type="application/json",
    )
    assert response.status_code == 200

    step.refresh_from_db()
    assert step.sandbox_provider == "local_process"
    assert step.sandbox_run_id == "run-abc123"
    assert step.command_sha256 == "a" * 64
    assert step.result_metadata == {"wall_seconds": 1.2}
    assert step.timed_out is False
    assert step.cancelled is False
    assert step.failure_kind == ""


@pytest.mark.django_db
def test_step_update_accepts_failure_kind_on_failed_step(queued_execution):
    """failure_kind and timed_out are persisted on a failed step."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    _start_step(api, execution, step, claim_token)

    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "failed",
            "exit_code": 1,
            "failure_kind": "timeout",
            "timed_out": True,
            "error_message": "Step timed out after 30 seconds.",
        },
        content_type="application/json",
    )
    assert response.status_code == 200

    step.refresh_from_db()
    assert step.failure_kind == "timeout"
    assert step.timed_out is True
    assert step.error_message == "Step timed out after 30 seconds."


@pytest.mark.django_db
def test_step_update_sandbox_fields_omitted_defaults_to_blank(queued_execution):
    """Older runners that omit sandbox fields get blank/False defaults — no error."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    _start_step(api, execution, step, claim_token)

    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",
        },
        content_type="application/json",
    )
    assert response.status_code == 200

    step.refresh_from_db()
    assert step.failure_kind == ""
    assert step.timed_out is False
    assert step.cancelled is False
    assert step.sandbox_provider == ""
    assert step.result_metadata == {}


@pytest.mark.django_db
def test_step_update_rejects_oversized_result_metadata(queued_execution):
    """result_metadata larger than 8 KB is rejected with 400."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    _start_step(api, execution, step, claim_token)

    oversized = {"k": "x" * 9000}
    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",
            "result_metadata": oversized,
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert "errors" in body


@pytest.mark.django_db
def test_step_update_rejects_non_dict_result_metadata(queued_execution):
    """result_metadata must be a JSON object; a list is rejected."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    _start_step(api, execution, step, claim_token)

    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",
            "result_metadata": [1, 2, 3],
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_step_update_rejects_invalid_command_sha256(queued_execution):
    """command_sha256 must be exactly 64 lowercase hex chars or empty."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    _start_step(api, execution, step, claim_token)

    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": claim_token,
            "status": "succeeded",
            "command_sha256": "not-a-valid-sha256",
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_step_update_stale_claim_token_rejected(queued_execution):
    """A stale/wrong claim token must still be rejected even with sandbox fields present."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    step = execution.steps.order_by("position").first()

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/update/",
        data={
            "runner_id": "runner-1",
            "claim_token": "00000000-0000-0000-0000-000000000000",
            "status": "succeeded",
            "sandbox_provider": "local_process",
            "result_metadata": {"key": "value"},
        },
        content_type="application/json",
    )
    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["code"] == "claim_token_mismatch"


# ---------------------------------------------------------------------------
# heartbeat: cancellation intent (Phase A schema prep)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_heartbeat_returns_cancel_requested_false_by_default(queued_execution):
    """Heartbeat response includes cancel_requested=false when no cancellation is pending."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cancel_requested"] is False
    assert body["cancel_reason"] == ""


@pytest.mark.django_db
def test_heartbeat_returns_cancel_requested_true_when_intent_set(queued_execution):
    """Heartbeat response reflects cancel intent written directly to the model."""
    from django.utils import timezone

    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    # Retained for backwards compatibility — tests model-layer read path
    execution.cancel_requested_at = timezone.now()
    execution.cancel_requested_by = "user:test"
    execution.cancel_reason = "user requested"
    execution.save(
        update_fields=["cancel_requested_at", "cancel_requested_by", "cancel_reason"]
    )

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cancel_requested"] is True
    assert body["cancel_reason"] == "user requested"


@pytest.mark.django_db
def test_heartbeat_returns_cancel_requested_after_cancel_execution(queued_execution):
    """cancel_execution on a claimed execution sets intent visible via heartbeat."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]
    claim_token = claim_result["claim_token"]

    execution_services.cancel_execution(execution=execution)

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={"runner_id": "runner-1", "claim_token": claim_token},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cancel_requested"] is True


@pytest.mark.django_db
def test_heartbeat_wrong_token_still_rejected_with_new_fields(queued_execution):
    """Stale token rejection is unaffected by new response fields."""
    claim_result = execution_services.claim_next_execution(runner_id="runner-1")
    execution = claim_result["execution"]

    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        f"/api/v1/internal/executions/{execution.id}/heartbeat/",
        data={
            "runner_id": "runner-1",
            "claim_token": "00000000-0000-0000-0000-000000000000",
        },
        content_type="application/json",
    )
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "claim_token_mismatch"


# ---------------------------------------------------------------------------
# step_snapshot propagation in claim payload
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_next_step_snapshot_present_in_response(queued_execution):
    """Claimed step payload must include step_snapshot so the runner can read timeoutSeconds."""
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    steps = body["execution"]["steps"]
    assert len(steps) > 0
    for step in steps:
        assert "step_snapshot" in step, "step_snapshot must be present in claimed step"
        assert isinstance(step["step_snapshot"], dict)


@pytest.mark.django_db
def test_claim_next_step_snapshot_keys_match_workflow_step(queued_execution):
    """step_snapshot keys must match the original workflow step definition."""
    from apps.executions.models import ExecutionStep

    # Get the first step's snapshot directly from the DB
    db_step = ExecutionStep.objects.filter(execution=queued_execution).first()
    assert db_step is not None
    assert isinstance(db_step.step_snapshot, dict)
    assert "id" in db_step.step_snapshot

    # Verify the same data appears in the API response
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    api_step = next(
        s for s in body["execution"]["steps"] if s["step_key"] == db_step.step_key
    )
    assert api_step["step_snapshot"]["id"] == db_step.step_snapshot["id"]


# ---------------------------------------------------------------------------
# v2 action_snapshot / timeout_seconds / execution_mode in claim payload
# ---------------------------------------------------------------------------


def _v2_shell_definition(**overrides):
    doc = {
        "schemaVersion": "2",
        "name": "V2 Runner Test Workflow",
        "steps": [
            {
                "id": "run-cmd",
                "name": "Run Command",
                "type": "shell_command",
                "risk": "low",
                "action": {"type": "shell_command", "params": {"command": "echo test"}},
                "timeoutSeconds": 90,
                "retry": {"maxAttempts": 2, "backoffSeconds": 5},
                "idempotency": {"mode": "natural"},
                "artifacts": [{"key": "out", "kind": "stdout"}],
            }
        ],
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def published_v2_workflow(runbook):
    wf = workflow_services.create_workflow_v2_draft(
        runbook=runbook,
        definition=_v2_shell_definition(),
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def queued_v2_execution(published_v2_workflow):
    return execution_services.create_execution(workflow=published_v2_workflow)


@pytest.mark.django_db
def test_claim_next_v1_step_has_null_action_snapshot(queued_execution):
    """v1 steps must have action_snapshot=null in the claim payload."""
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    steps = response.json()["execution"]["steps"]
    for step in steps:
        assert "action_snapshot" in step
        assert step["action_snapshot"] is None


@pytest.mark.django_db
def test_claim_next_v2_step_has_action_snapshot(queued_v2_execution):
    """v2 steps must include a non-null action_snapshot with type and params."""
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    step = response.json()["execution"]["steps"][0]
    assert step["action_snapshot"] is not None
    assert step["action_snapshot"]["type"] == "shell_command"
    assert step["action_snapshot"]["params"]["command"] == "echo test"


@pytest.mark.django_db
def test_claim_next_v2_step_has_timeout_seconds(queued_v2_execution):
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    step = response.json()["execution"]["steps"][0]
    assert step["timeout_seconds"] == 90


@pytest.mark.django_db
def test_claim_next_v2_step_has_retry_and_idempotency(queued_v2_execution):
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    step = response.json()["execution"]["steps"][0]
    assert step["retry"] == {"maxAttempts": 2, "backoffSeconds": 5}
    assert step["idempotency"] == {"mode": "natural"}
    assert step["artifacts"] == [{"key": "out", "kind": "stdout"}]


@pytest.mark.django_db
def test_claim_next_v1_execution_has_live_mode(queued_execution):
    api = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    response = api.post(
        CLAIM_NEXT_URL,
        data={"runner_id": "runner-1"},
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["execution"]["execution_mode"] == "live"
