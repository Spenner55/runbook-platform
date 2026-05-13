"""Schema validation tests for runner.schemas."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from runner.schemas import (
    ActionSnapshot,
    ArtifactDeclaration,
    ClaimedExecution,
    ClaimedStep,
    ClaimNextResponse,
    CompleteExecutionRequest,
    CompleteExecutionResponse,
    HeartbeatRequest,
    IdempotencySpec,
    RetrySpec,
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


def test_claimed_v2_execution_fixture_round_trips():
    fixture = Path(__file__).parent / "fixtures" / "claimed_execution_v2.json"
    data = json.loads(fixture.read_text())

    exe = ClaimedExecution.model_validate(data)

    assert exe.execution_mode == "live"
    assert exe.steps[0].action_snapshot is not None
    assert exe.steps[0].action_snapshot.type == "shell_command"
    assert exe.steps[0].action_snapshot.version == "pilot.v1"
    assert exe.steps[0].action_snapshot.params["command"].startswith("printf")


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


# ---------------------------------------------------------------------------
# v2 action / metadata sub-model contracts
# ---------------------------------------------------------------------------


def test_retry_spec_parses_camelcase():
    spec = RetrySpec.model_validate(
        {"maxAttempts": 3, "backoffSeconds": 5, "retryOn": ["timeout"]}
    )
    assert spec.max_attempts == 3
    assert spec.backoff_seconds == 5
    assert spec.retry_on == ["timeout"]


def test_retry_spec_defaults():
    spec = RetrySpec.model_validate({"maxAttempts": 1})
    assert spec.backoff_seconds == 0
    assert spec.retry_on == []


def test_retry_spec_unknown_fields_ignored():
    spec = RetrySpec.model_validate({"maxAttempts": 2, "futureField": "ignored"})
    assert spec.max_attempts == 2


def test_idempotency_spec_parses():
    spec = IdempotencySpec.model_validate(
        {"mode": "keyed", "key": "deploy-abc", "reason": "safe"}
    )
    assert spec.mode == "keyed"
    assert spec.key == "deploy-abc"


def test_idempotency_spec_defaults():
    spec = IdempotencySpec.model_validate({"mode": "none"})
    assert spec.key == ""
    assert spec.reason == ""


def test_artifact_declaration_parses_camelcase():
    decl = ArtifactDeclaration.model_validate(
        {
            "key": "output",
            "kind": "file",
            "path": "/tmp/out.txt",
            "mimeType": "text/plain",
            "maxBytes": 1048576,
            "contentDisposition": "attachment",
            "evidenceRole": "primary",
        }
    )
    assert decl.key == "output"
    assert decl.mime_type == "text/plain"
    assert decl.max_bytes == 1048576
    assert decl.content_disposition == "attachment"
    assert decl.evidence_role == "primary"


def test_artifact_declaration_defaults():
    decl = ArtifactDeclaration.model_validate({"key": "report"})
    assert decl.mime_type == ""
    assert decl.max_bytes is None
    assert decl.required is False


def test_action_snapshot_parses():
    snap = ActionSnapshot.model_validate(
        {"type": "shell_command", "params": {"command": "echo hi"}}
    )
    assert snap.type == "shell_command"
    assert snap.params == {"command": "echo hi"}


def test_action_snapshot_defaults():
    snap = ActionSnapshot.model_validate({"type": "manual_task"})
    assert snap.params == {}
    assert snap.version == ""


# ---------------------------------------------------------------------------
# ClaimedStep v1 / v2 contract
# ---------------------------------------------------------------------------


def _v1_step_dict(**overrides) -> dict:
    d = {
        "id": str(uuid4()),
        "position": 1,
        "step_key": "step-1",
        "name": "Step 1",
        "step_type": "shell",
        "risk_level": "low",
        "command": "echo hello",
        "requires_approval": False,
        "status": "pending",
        "step_snapshot": {
            "id": "step-1",
            "name": "Step 1",
            "type": "shell",
            "risk": "low",
            "command": "echo hello",
        },
    }
    d.update(overrides)
    return d


def _v2_step_dict(**overrides) -> dict:
    d = {
        "id": str(uuid4()),
        "position": 1,
        "step_key": "run",
        "name": "Run command",
        "step_type": "shell_command",
        "risk_level": "low",
        "command": "echo hello",
        "requires_approval": False,
        "status": "pending",
        "step_snapshot": {
            "id": "run",
            "name": "Run command",
            "type": "shell_command",
            "risk": "low",
            "action": {"type": "shell_command", "params": {"command": "echo hello"}},
            "timeoutSeconds": 120,
            "retry": {"maxAttempts": 2, "backoffSeconds": 3},
            "idempotency": {"mode": "natural"},
            "artifacts": [{"key": "stdout", "kind": "stdout"}],
        },
        "action_snapshot": {
            "type": "shell_command",
            "params": {"command": "echo hello"},
        },
        "timeout_seconds": 120,
        "retry": {"maxAttempts": 2, "backoffSeconds": 3},
        "idempotency": {"mode": "natural"},
        "artifacts": [{"key": "stdout", "kind": "stdout"}],
    }
    d.update(overrides)
    return d


def test_v1_claimed_step_parses_unchanged():
    step = ClaimedStep.model_validate(_v1_step_dict())
    assert step.action_snapshot is None
    assert step.timeout_seconds is None
    assert step.retry is None
    assert step.idempotency is None
    assert step.artifacts == []


def test_v2_claimed_step_parses_with_action_snapshot():
    step = ClaimedStep.model_validate(_v2_step_dict())
    assert step.action_snapshot is not None
    assert step.action_snapshot.type == "shell_command"
    assert step.action_snapshot.params == {"command": "echo hello"}
    assert step.timeout_seconds == 120
    assert step.retry is not None
    assert step.retry.max_attempts == 2
    assert step.retry.backoff_seconds == 3
    assert step.idempotency is not None
    assert step.idempotency.mode == "natural"
    assert len(step.artifacts) == 1
    assert step.artifacts[0].key == "stdout"


def test_v2_claimed_step_missing_action_snapshot_is_none():
    """A v2 step payload with action_snapshot omitted must not fail."""
    d = _v2_step_dict()
    d.pop("action_snapshot")
    step = ClaimedStep.model_validate(d)
    assert step.action_snapshot is None


def test_claimed_step_unknown_extra_fields_still_ignored():
    """Forward-compatible: unknown fields from a future API version are dropped."""
    d = _v1_step_dict()
    d["from_future"] = "new_field"
    step = ClaimedStep.model_validate(d)
    assert step.step_key == "step-1"


# ---------------------------------------------------------------------------
# ClaimedExecution execution_mode
# ---------------------------------------------------------------------------


def test_claimed_execution_includes_execution_mode():
    data = {
        "id": str(uuid4()),
        "status": "claimed",
        "workflow_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workflow_version": 1,
        "workflow_snapshot": {},
        "execution_mode": "dry_run",
        "steps": [_v1_step_dict()],
    }
    exe = ClaimedExecution.model_validate(data)
    assert exe.execution_mode == "dry_run"


def test_claimed_execution_execution_mode_defaults_to_live():
    data = {
        "id": str(uuid4()),
        "status": "claimed",
        "workflow_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workflow_version": 1,
        "workflow_snapshot": {},
        "steps": [],
    }
    exe = ClaimedExecution.model_validate(data)
    assert exe.execution_mode == "live"
