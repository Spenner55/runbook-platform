"""Schema validation tests for runner.schemas."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from runner.schemas import (
    ClaimedExecution,
    ClaimedStep,
    ClaimNextResponse,
    CompleteExecutionRequest,
    CompleteExecutionResponse,
    HeartbeatRequest,
    RunnerSettings,
    StepUpdateResponse,
)

# ---------------------------------------------------------------------------
# RunnerSettings
# ---------------------------------------------------------------------------


def test_runner_settings_defaults():
    s = RunnerSettings(
        api_base_url="http://api:8000",
        runner_id="r1",
        registration_token="runner-secret",
    )
    assert s.runner_version == "0.1.0"
    assert s.poll_interval_seconds == 5
    assert s.heartbeat_interval_seconds == 10
    assert s.log_level == "INFO"


def test_runner_settings_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RunnerSettings(
            api_base_url="http://x",
            runner_id="r1",
            registration_token="runner-secret",
            unknown_field="bad",
        )


@pytest.mark.parametrize("token", ["", "change-me"])
def test_runner_settings_rejects_missing_or_placeholder_registration_token(token):
    with pytest.raises(ValidationError):
        RunnerSettings(
            api_base_url="http://x",
            runner_id="r1",
            registration_token=token,
        )


def test_runner_settings_from_env(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://my-api:9000")
    monkeypatch.setenv("RUNNER_ID", "test-runner")
    monkeypatch.setenv("RUNNER_VERSION", "1.2.3")
    monkeypatch.setenv("RUNNER_REGISTRATION_TOKEN", "runner-secret")
    monkeypatch.setenv("RUNNER_POLL_INTERVAL_SECONDS", "15")
    s = RunnerSettings.from_env()
    assert s.api_base_url == "http://my-api:9000"
    assert s.runner_id == "test-runner"
    assert s.runner_version == "1.2.3"
    assert s.registration_token == "runner-secret"
    assert s.poll_interval_seconds == 15


# ---------------------------------------------------------------------------
# ClaimedStep
# ---------------------------------------------------------------------------


def test_claimed_step_valid():
    step = ClaimedStep(
        id=uuid4(),
        position=1,
        step_key="step-1",
        name="Step One",
        step_type="shell",
        risk_level="low",
        command="echo hello",
        requires_approval=False,
        status="pending",
    )
    assert step.position == 1


def test_claimed_step_ignores_extra_fields():
    step = ClaimedStep(
        id=uuid4(),
        position=1,
        step_key="s",
        name="N",
        step_type="manual",
        risk_level="low",
        status="pending",
        unknown_extra="ignored",
    )
    assert step.step_key == "s"


def test_claimed_step_invalid_status():
    with pytest.raises(ValidationError):
        ClaimedStep(
            id=uuid4(),
            position=1,
            step_key="s",
            name="N",
            step_type="manual",
            risk_level="low",
            status="invalid_status",
        )


# ---------------------------------------------------------------------------
# ClaimedExecution
# ---------------------------------------------------------------------------


def _make_step() -> dict:
    return {
        "id": str(uuid4()),
        "position": 1,
        "step_key": "step-1",
        "name": "Step 1",
        "step_type": "shell",
        "risk_level": "low",
        "command": "",
        "requires_approval": False,
        "status": "pending",
    }


def test_claimed_execution_valid():
    exe = ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={"name": "wf"},
        steps=[ClaimedStep(**_make_step())],
    )
    assert exe.status == "claimed"
    assert len(exe.steps) == 1


def test_claimed_execution_no_claim_token_field():
    """claim_token must NOT be a field on ClaimedExecution — it lives on ClaimNextResponse."""
    exe = ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=[],
    )
    assert (
        not hasattr(exe, "claim_token")
        or exe.__class__.model_fields.get("claim_token") is None
    )


def test_claimed_execution_parses_django_response_shape():
    """Simulate the dict Django actually returns in ClaimedExecutionSerializer."""
    data = {
        "id": str(uuid4()),
        "status": "claimed",
        "workflow_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workflow_version": 2,
        "workflow_snapshot": {"name": "test", "steps": []},
        "claimed_by_runner_id": "runner-dev-01",
        "claimed_at": "2026-01-01T00:00:00Z",
        "last_heartbeat_at": "2026-01-01T00:00:01Z",
        "steps": [_make_step()],
    }
    exe = ClaimedExecution.model_validate(data)
    assert exe.claimed_by_runner_id == "runner-dev-01"


# ---------------------------------------------------------------------------
# ClaimNextResponse
# ---------------------------------------------------------------------------


def test_claim_next_response_with_work():
    data = {
        "execution": {
            "id": str(uuid4()),
            "status": "claimed",
            "workflow_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "workflow_version": 1,
            "workflow_snapshot": {},
            "steps": [_make_step()],
        },
        "claim_token": str(uuid4()),
        "poll_after_seconds": 5,
    }
    resp = ClaimNextResponse.model_validate(data)
    assert resp.execution is not None
    assert resp.claim_token is not None
    assert resp.poll_after_seconds == 5


def test_claim_next_response_no_work():
    data = {"execution": None, "poll_after_seconds": 5}
    resp = ClaimNextResponse.model_validate(data)
    assert resp.execution is None
    assert resp.claim_token is None


# ---------------------------------------------------------------------------
# CompleteExecutionRequest
# ---------------------------------------------------------------------------


def test_complete_request_uses_final_status_not_outcome():
    req = CompleteExecutionRequest(
        runner_id="r1",
        claim_token=uuid4(),
        final_status="succeeded",
    )
    dumped = req.model_dump(mode="json")
    assert "final_status" in dumped
    assert "outcome" not in dumped


def test_complete_request_rejects_invalid_final_status():
    with pytest.raises(ValidationError):
        CompleteExecutionRequest(
            runner_id="r1",
            claim_token=uuid4(),
            final_status="running",  # not allowed
        )


# ---------------------------------------------------------------------------
# StepUpdateResponse
# ---------------------------------------------------------------------------


def test_step_update_response_parses_nested_django_shape():
    """Simulate the dict Django actually returns from ExecutionStepUpdateView."""
    data = {
        "execution_id": str(uuid4()),
        "step": {
            "id": str(uuid4()),
            "position": 1,
            "step_key": "s",
            "name": "N",
            "step_type": "manual",
            "risk_level": "low",
            "command": "",
            "requires_approval": False,
            "status": "running",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": None,
            "exit_code": None,
            "error_message": "",
        },
        "execution_status": "running",
    }
    resp = StepUpdateResponse.model_validate(data)
    assert resp.step.status == "running"
    assert resp.execution_status == "running"


# ---------------------------------------------------------------------------
# CompleteExecutionResponse
# ---------------------------------------------------------------------------


def test_complete_response_parses_django_shape():
    """Django's complete view does NOT return started_at — must not be required."""
    data = {
        "id": str(uuid4()),
        "status": "succeeded",
        "finished_at": "2026-01-01T00:00:00Z",
    }
    resp = CompleteExecutionResponse.model_validate(data)
    assert resp.status == "succeeded"


# ---------------------------------------------------------------------------
# HeartbeatRequest serialisation
# ---------------------------------------------------------------------------


def test_heartbeat_request_json_serialisation():
    req = HeartbeatRequest(
        runner_id="r1",
        claim_token=uuid4(),
        observed_status="running",
    )
    dumped = req.model_dump(mode="json")
    assert dumped["observed_status"] == "running"
    assert "claim_token" in dumped
