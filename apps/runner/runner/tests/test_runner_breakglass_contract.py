"""
Phase 11.4 Batch 3: Runner breakglass contract tests.

Covers:
- ClaimedExecution accepts optional breakglass facts
- Runner does not treat breakglass facts as credentials
- Runner continues to call Django step-start gates regardless of breakglass
- Runner handles Django blocked response after breakglass expiry
- BreakglassHeartbeatRequest rejects extra fields (extra="forbid")
- BreakglassSessionFacts carries only scope/expiry metadata
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from runner.schemas import (
    BreakglassHeartbeatRequest,
    BreakglassHeartbeatResponse,
    BreakglassSessionFacts,
    ClaimedExecution,
    StepStartResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow():
    return datetime.now(tz=UTC)


def _future(seconds=3600):
    return _utcnow() + timedelta(seconds=seconds)


def _minimal_step(position=1) -> dict:
    return {
        "id": str(uuid4()),
        "position": position,
        "step_key": f"step-{position}",
        "name": f"Step {position}",
        "step_type": "command",
        "risk_level": "low",
        "status": "pending",
    }


def _claimed_execution_payload(*, breakglass=None) -> dict:
    payload = {
        "id": str(uuid4()),
        "status": "claimed",
        "workflow_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workflow_version": 1,
        "workflow_snapshot": {"name": "test", "steps": []},
        "steps": [_minimal_step()],
    }
    if breakglass is not None:
        payload["breakglass"] = breakglass
    return payload


def _breakglass_facts() -> dict:
    return {
        "breakglass_session_id": str(uuid4()),
        "scope_sha256": "a" * 64,
        "scope_summary": "actions=dispatch gates=window_overrun targets=1",
        "started_at": _utcnow().isoformat(),
        "expires_at": _future(1800).isoformat(),
        "review_due_at": _future(86400).isoformat(),
    }


# ---------------------------------------------------------------------------
# Schema: ClaimedExecution accepts optional breakglass facts
# ---------------------------------------------------------------------------


def test_claimed_execution_without_breakglass():
    exe = ClaimedExecution.model_validate(_claimed_execution_payload())
    assert exe.breakglass is None


def test_claimed_execution_with_breakglass_facts():
    payload = _claimed_execution_payload(breakglass=_breakglass_facts())
    exe = ClaimedExecution.model_validate(payload)
    assert exe.breakglass is not None
    assert isinstance(exe.breakglass.breakglass_session_id, UUID)
    assert exe.breakglass.scope_sha256 == "a" * 64
    assert exe.breakglass.scope_summary != ""


def test_breakglass_facts_extra_ignored():
    """BreakglassSessionFacts uses extra='ignore' so unknown fields are silently dropped."""
    facts = _breakglass_facts()
    facts["unexpected_field"] = "should_be_ignored"
    exe = ClaimedExecution.model_validate(_claimed_execution_payload(breakglass=facts))
    assert exe.breakglass is not None
    assert not hasattr(exe.breakglass, "unexpected_field")


# ---------------------------------------------------------------------------
# Schema: BreakglassSessionFacts carries only metadata, no credential fields
# ---------------------------------------------------------------------------


def test_breakglass_session_facts_no_credential_fields():
    """BreakglassSessionFacts must not have fields that look like credentials."""

    field_names = set(BreakglassSessionFacts.model_fields.keys())
    credential_like = {
        "ssh_key",
        "api_key",
        "token",
        "password",
        "secret",
        "iam_role",
        "cloud_role",
        "kubeconfig",
        "dispatch_token",
    }
    overlap = field_names & credential_like
    assert not overlap, f"BreakglassSessionFacts has credential-like fields: {overlap}"


# ---------------------------------------------------------------------------
# Schema: BreakglassHeartbeatRequest rejects extra fields
# ---------------------------------------------------------------------------


def test_breakglass_heartbeat_request_rejects_extra_fields():
    """extra='forbid' means extra keys raise a ValidationError."""
    with pytest.raises(ValidationError):
        BreakglassHeartbeatRequest(
            runner_id="runner-1",
            claim_token=uuid4(),
            breakglass_session_id=uuid4(),
            scope_sha256="a" * 64,
            unexpected_privilege_escalation_field="do_not_allow",
        )


def test_breakglass_heartbeat_request_valid():
    req = BreakglassHeartbeatRequest(
        runner_id="runner-1",
        claim_token=uuid4(),
        breakglass_session_id=uuid4(),
        scope_sha256="a" * 64,
    )
    assert req.runner_id == "runner-1"
    assert req.observed_at is None


# ---------------------------------------------------------------------------
# Executor: continues calling Django step-start gate regardless of breakglass
# ---------------------------------------------------------------------------


def test_executor_calls_start_step_gate_with_active_breakglass():
    """Runner must call Django step-start for every step even when breakglass is active."""
    from runner.executor import Executor

    step_id = uuid4()
    execution_id = uuid4()
    claim_token = uuid4()

    facts = BreakglassSessionFacts.model_validate(_breakglass_facts())
    exe = ClaimedExecution.model_validate(
        {
            **_claimed_execution_payload(breakglass=facts.model_dump(mode="json")),
            "id": str(execution_id),
            "status": "claimed",
            "steps": [
                {
                    "id": str(step_id),
                    "position": 1,
                    "step_key": "step-1",
                    "name": "Step 1",
                    "step_type": "command",
                    "risk_level": "low",
                    "status": "pending",
                }
            ],
        }
    )

    client = MagicMock()
    # Django returns "run" immediately
    client.start_step.return_value = StepStartResponse(
        execution_id=execution_id,
        execution_status="running",
        step={"id": str(step_id), "status": "running"},
        runner_action="run",
        poll_after_seconds=0,
    )
    client.update_step.return_value = MagicMock()
    client.complete_execution.return_value = MagicMock()
    client.upload_artifact = MagicMock(return_value=None)

    executor = Executor(client)
    executor.run(exe, claim_token)

    # The runner MUST call start_step — breakglass does not bypass it
    client.start_step.assert_called_once_with(execution_id, step_id, claim_token)


def test_executor_does_not_alter_permissions_from_breakglass_facts():
    """Breakglass facts must not cause the runner to skip Django gates or modify permissions."""
    from runner.executor import Executor

    step_id = uuid4()
    execution_id = uuid4()
    claim_token = uuid4()

    facts = BreakglassSessionFacts.model_validate(_breakglass_facts())
    exe = ClaimedExecution.model_validate(
        {
            **_claimed_execution_payload(breakglass=facts.model_dump(mode="json")),
            "id": str(execution_id),
            "status": "claimed",
            "steps": [
                {
                    "id": str(step_id),
                    "position": 1,
                    "step_key": "step-1",
                    "name": "Step 1",
                    "step_type": "command",
                    "risk_level": "high",
                    "requires_approval": True,
                    "status": "pending",
                }
            ],
        }
    )

    client = MagicMock()
    # Django blocks the step (breakglass expired or out of scope server-side)
    client.start_step.return_value = StepStartResponse(
        execution_id=execution_id,
        execution_status="failed",
        step={"id": str(step_id), "status": "failed"},
        runner_action="blocked",
        poll_after_seconds=0,
    )
    client.complete_execution.return_value = MagicMock()

    executor = Executor(client)
    executor.run(exe, claim_token)

    # Runner must call start_step and respect the blocked response
    client.start_step.assert_called_once()
    complete_calls = client.complete_execution.call_args_list
    assert len(complete_calls) == 1
    _, kwargs = complete_calls[0]
    # The runner should complete as failed when Django blocks a step
    # (Executor passes final_status positionally)
    assert "failed" in str(complete_calls[0])


def test_executor_handles_blocked_response_after_breakglass_expiry():
    """When Django returns 'blocked' (e.g. breakglass expired), runner fails gracefully."""
    from runner.executor import Executor

    step_id = uuid4()
    execution_id = uuid4()
    claim_token = uuid4()

    # Execution has breakglass facts, but Django's gate says blocked
    facts = BreakglassSessionFacts.model_validate(_breakglass_facts())
    exe = ClaimedExecution.model_validate(
        {
            **_claimed_execution_payload(breakglass=facts.model_dump(mode="json")),
            "id": str(execution_id),
            "status": "claimed",
            "steps": [
                {
                    "id": str(step_id),
                    "position": 1,
                    "step_key": "step-1",
                    "name": "Step 1",
                    "step_type": "command",
                    "risk_level": "low",
                    "status": "pending",
                }
            ],
        }
    )

    client = MagicMock()
    client.start_step.return_value = StepStartResponse(
        execution_id=execution_id,
        execution_status="failed",
        step={"id": str(step_id), "status": "failed"},
        runner_action="blocked",
        poll_after_seconds=0,
    )
    client.complete_execution.return_value = MagicMock()

    executor = Executor(client)
    executor.run(exe, claim_token)

    # Runner must complete the execution, not hang or skip completion
    client.complete_execution.assert_called_once()


# ---------------------------------------------------------------------------
# BreakglassHeartbeatResponse schema
# ---------------------------------------------------------------------------


def test_breakglass_heartbeat_response_valid():
    resp = BreakglassHeartbeatResponse.model_validate(
        {
            "status": "active",
            "expires_at": _future(1800).isoformat(),
            "server_time": _utcnow().isoformat(),
        }
    )
    assert resp.status == "active"
    assert resp.expires_at is not None


def test_breakglass_heartbeat_response_expired_session():
    resp = BreakglassHeartbeatResponse.model_validate(
        {"status": "expired", "expires_at": None, "server_time": _utcnow().isoformat()}
    )
    assert resp.status == "expired"
    assert resp.expires_at is None
