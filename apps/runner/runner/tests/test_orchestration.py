"""
End-to-end orchestration tests using fake API client and controlled clock.

These tests exercise the full claim→heartbeat→execute→complete sequencing
without touching a real HTTP server or database.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID, uuid4

from runner.executor import Executor
from runner.poller import Poller
from runner.schemas import (
    ClaimedExecution,
    ClaimedStep,
    ClaimNextResponse,
    CompleteExecutionResponse,
    HeartbeatResponse,
    StepUpdateResponse,
    StepUpdateStepDetail,
)

# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakeApiClient:
    """
    Minimal fake that records calls and returns plausible responses.
    Thread-safe because heartbeat runs in a background thread.
    """

    def __init__(self, claim_response: ClaimNextResponse) -> None:
        self._claim_response = claim_response
        self.heartbeat_calls: list[tuple[UUID, UUID]] = []
        self.step_update_calls: list[dict[str, Any]] = []
        self.complete_calls: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def claim_next(self) -> ClaimNextResponse:
        return self._claim_response

    def heartbeat(
        self, execution_id: UUID, claim_token: UUID, observed_status: str = "claimed"
    ) -> HeartbeatResponse:
        with self._lock:
            self.heartbeat_calls.append((execution_id, claim_token))
        return HeartbeatResponse(status=observed_status)

    def update_step(
        self,
        execution_id: UUID,
        step_id: UUID,
        claim_token: UUID,
        *,
        status: str,
        **kwargs: Any,
    ) -> StepUpdateResponse:
        with self._lock:
            self.step_update_calls.append(
                {"step_id": step_id, "status": status, **kwargs}
            )
        return StepUpdateResponse(
            execution_id=execution_id,
            step=StepUpdateStepDetail(id=step_id, status=status),
            execution_status="running",
        )

    def complete_execution(
        self,
        execution_id: UUID,
        claim_token: UUID,
        final_status: str,
        error_message: str = "",
    ) -> CompleteExecutionResponse:
        with self._lock:
            self.complete_calls.append(
                {"execution_id": execution_id, "final_status": final_status}
            )
        return CompleteExecutionResponse(id=execution_id, status=final_status)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(position: int, command: str = "") -> ClaimedStep:
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="shell",
        risk_level="low",
        command=command,
        requires_approval=False,
        status="pending",
    )


def _make_claim_response(steps: list[ClaimedStep]) -> tuple[ClaimNextResponse, UUID]:
    token = uuid4()
    exe = ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=steps,
    )
    return ClaimNextResponse(
        execution=exe, claim_token=token, poll_after_seconds=5
    ), token


def _step_statuses(client: FakeApiClient) -> list[str]:
    return [c["status"] for c in client.step_update_calls]


# ---------------------------------------------------------------------------
# Happy path sequencing
# ---------------------------------------------------------------------------


def test_happy_path_step_order_and_statuses(monkeypatch):
    """Each step must be marked running then succeeded, in position order."""
    import runner.executor as executor_mod

    monkeypatch.setattr(executor_mod.time, "sleep", lambda _: None)

    steps = [_make_step(2), _make_step(1)]  # deliberately out of order
    resp, token = _make_claim_response(steps)
    client = FakeApiClient(resp)
    executor = Executor(client=client)

    execution = resp.execution
    executor.run(execution, token)

    # step 1 then step 2, each running then succeeded
    statuses = _step_statuses(client)
    assert statuses == ["running", "succeeded", "running", "succeeded"]

    # step IDs in position order
    step_by_id = {s.id: s for s in steps}
    running_ids = [
        c["step_id"] for c in client.step_update_calls if c["status"] == "running"
    ]
    positions = [step_by_id[sid].position for sid in running_ids]
    assert positions == sorted(positions)


def test_happy_path_complete_called_once_with_succeeded(monkeypatch):
    import runner.executor as executor_mod

    monkeypatch.setattr(executor_mod.time, "sleep", lambda _: None)

    resp, token = _make_claim_response([_make_step(1), _make_step(2)])
    client = FakeApiClient(resp)
    executor = Executor(client=client)

    executor.run(resp.execution, token)

    assert len(client.complete_calls) == 1
    assert client.complete_calls[0]["final_status"] == "succeeded"


# ---------------------------------------------------------------------------
# Failure path sequencing
# ---------------------------------------------------------------------------


def test_fail_step_marks_step_failed_then_completes_failed(monkeypatch):
    import runner.executor as executor_mod

    monkeypatch.setattr(executor_mod.time, "sleep", lambda _: None)

    steps = [_make_step(1, command="echo FAIL_STEP"), _make_step(2), _make_step(3)]
    resp, token = _make_claim_response(steps)
    client = FakeApiClient(resp)
    executor = Executor(client=client)

    executor.run(resp.execution, token)

    statuses = _step_statuses(client)
    assert statuses == ["running", "failed"]  # step 1 only; steps 2+3 never touched

    assert len(client.complete_calls) == 1
    assert client.complete_calls[0]["final_status"] == "failed"


def test_failure_leaves_later_steps_untouched(monkeypatch):
    import runner.executor as executor_mod

    monkeypatch.setattr(executor_mod.time, "sleep", lambda _: None)

    steps = [_make_step(1, command="FAIL_STEP"), _make_step(2)]
    resp, token = _make_claim_response(steps)
    client = FakeApiClient(resp)
    executor = Executor(client=client)

    executor.run(resp.execution, token)

    step_ids_touched = {c["step_id"] for c in client.step_update_calls}
    # Step 2 should not have been touched
    for s in steps:
        if s.command == "FAIL_STEP":
            continue
        assert s.id not in step_ids_touched


def test_complete_called_exactly_once_on_failure(monkeypatch):
    import runner.executor as executor_mod

    monkeypatch.setattr(executor_mod.time, "sleep", lambda _: None)

    resp, token = _make_claim_response([_make_step(1, command="FAIL_STEP")])
    client = FakeApiClient(resp)
    executor = Executor(client=client)

    executor.run(resp.execution, token)

    assert len(client.complete_calls) == 1


# ---------------------------------------------------------------------------
# Heartbeat start/stop
# ---------------------------------------------------------------------------


def test_heartbeat_is_sent_while_execution_active(monkeypatch):
    """
    Use a long fake step delay + fast heartbeat interval to guarantee
    at least one heartbeat fires during execution.
    """
    import runner.executor as executor_mod

    original_init = executor_mod._HeartbeatThread.__init__

    def patched_init(self, client, execution_id, claim_token, interval=10):
        original_init(self, client, execution_id, claim_token, interval=0.01)  # fast

    monkeypatch.setattr(executor_mod._HeartbeatThread, "__init__", patched_init)

    # Give execution real time to run (0.05s step delay) so heartbeats fire
    def fake_sleep(s: float) -> None:
        import time

        time.sleep(min(s, 0.05))

    monkeypatch.setattr(executor_mod.time, "sleep", fake_sleep)

    resp, token = _make_claim_response([_make_step(1)])
    client = FakeApiClient(resp)
    executor = Executor(client=client)

    executor.run(resp.execution, token)

    # Heartbeat must have fired at least once
    assert len(client.heartbeat_calls) >= 1


def test_no_heartbeat_without_active_execution():
    """
    Poller should not call executor (and thus no heartbeat) when claim_next
    returns no work.
    """
    from unittest.mock import MagicMock, patch

    client_mock = MagicMock()
    executor_mock = MagicMock()
    poller = Poller(client=client_mock, executor=executor_mock)

    client_mock.claim_next.return_value = ClaimNextResponse(
        execution=None, poll_after_seconds=5
    )

    with patch("runner.poller.time.sleep"):
        poller._poll_once()

    executor_mock.run.assert_not_called()


# ---------------------------------------------------------------------------
# Poller claim handoff
# ---------------------------------------------------------------------------


def test_poller_passes_claim_token_to_executor(monkeypatch):
    """Poller must pass response.claim_token as the second arg to executor.run."""
    from unittest.mock import MagicMock

    client_mock = MagicMock()
    executor_mock = MagicMock()
    poller = Poller(client=client_mock, executor=executor_mock)

    token = uuid4()
    exe = ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=[],
    )
    client_mock.claim_next.return_value = ClaimNextResponse(
        execution=exe, claim_token=token, poll_after_seconds=5
    )

    poller._poll_once()

    executor_mock.run.assert_called_once_with(exe, token)
