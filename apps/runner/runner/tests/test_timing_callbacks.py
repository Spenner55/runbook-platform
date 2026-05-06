"""Tests for runner execution-started / execution-finished timing callbacks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from runner.client import ApiClient
from runner.executor import Executor
from runner.schemas import (
    BindChangeExecutionResponse,
    ClaimedExecution,
    ClaimedStep,
    CompleteExecutionResponse,
    ExecutionFinishedResponse,
    ExecutionStartedResponse,
    ExecutionTimingCallbackRequest,
    StepStartResponse,
    StepUpdateResponse,
)

# ---------------------------------------------------------------------------
# Shared helpers
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


def _make_execution(steps, *, change_bound: bool = False) -> ClaimedExecution:
    extra = {}
    if change_bound:
        extra = {
            "change_record_id": uuid4(),
            "dispatch_token": "secret-token",
            "requested_inputs_sha256": "a" * 64,
            "operation_profile_key": "prod-maintenance",
        }
    return ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=steps,
        **extra,
    )


def _bind_ok(execution_id=None, change_record_id=None) -> BindChangeExecutionResponse:
    return BindChangeExecutionResponse(
        change_record_id=change_record_id or uuid4(),
        execution_id=execution_id or uuid4(),
    )


def _step_start_run(execution_id, step_id) -> StepStartResponse:
    return StepStartResponse(
        execution_id=execution_id,
        execution_status="running",
        step={"id": str(step_id), "status": "running"},
        runner_action="run",
        poll_after_seconds=0,
    )


def _step_update_ok(execution_id, step_id) -> StepUpdateResponse:
    return StepUpdateResponse(
        execution_id=execution_id,
        step={"id": str(step_id), "status": "succeeded", "exit_code": 0},
        execution_status="running",
    )


def _complete_ok(execution_id) -> CompleteExecutionResponse:
    return CompleteExecutionResponse(id=execution_id, status="succeeded")


def _started_ok(change_record_id, execution_id) -> ExecutionStartedResponse:
    return ExecutionStartedResponse(
        change_record_id=change_record_id,
        execution_started_at=datetime.now(tz=UTC),
    )


def _finished_ok(change_record_id, execution_id) -> ExecutionFinishedResponse:
    return ExecutionFinishedResponse(
        change_record_id=change_record_id,
        execution_finished_at=datetime.now(tz=UTC),
        locks_released=1,
    )


def _mock_client_for_change_execution(execution: ClaimedExecution):
    """Return a MagicMock client wired for a successful change-bound execution."""
    client = MagicMock()
    step = execution.steps[0]

    client.bind_change_execution.return_value = _bind_ok(
        execution_id=execution.id,
        change_record_id=execution.change_record_id,
    )
    client.execution_started.return_value = _started_ok(
        execution.change_record_id, execution.id
    )
    client.execution_finished.return_value = _finished_ok(
        execution.change_record_id, execution.id
    )
    client.start_step.return_value = _step_start_run(execution.id, step.id)
    client.update_step.return_value = _step_update_ok(execution.id, step.id)
    client.complete_execution.return_value = _complete_ok(execution.id)
    client.heartbeat.return_value = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Executor: execution-started called after bind, before steps
# ---------------------------------------------------------------------------


class TestExecutionStartedCallback:
    def test_execution_started_called_for_change_bound_execution(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)

        Executor(client).run(execution, claim_token)

        client.execution_started.assert_called_once_with(
            execution.change_record_id,
            execution.id,
            observed_at=client.execution_started.call_args.kwargs["observed_at"],
        )

    def test_execution_started_called_before_first_step(self):
        """execution_started must be called before start_step."""
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)

        call_order = []
        client.execution_started.side_effect = lambda *a, **kw: (
            call_order.append("started")
            or _started_ok(execution.change_record_id, execution.id)
        )
        client.start_step.side_effect = lambda *a, **kw: (
            call_order.append("step") or _step_start_run(execution.id, step.id)
        )

        Executor(client).run(execution, claim_token)

        assert call_order.index("started") < call_order.index("step")

    def test_execution_started_not_called_for_plain_execution(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=False)
        claim_token = uuid4()

        client = MagicMock()
        client.start_step.return_value = _step_start_run(execution.id, step.id)
        client.update_step.return_value = _step_update_ok(execution.id, step.id)
        client.complete_execution.return_value = _complete_ok(execution.id)
        client.heartbeat.return_value = MagicMock()

        Executor(client).run(execution, claim_token)

        client.execution_started.assert_not_called()

    def test_execution_started_not_called_when_bind_fails(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()

        client = MagicMock()
        client.bind_change_execution.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock(status_code=403)
        )
        client.complete_execution.return_value = _complete_ok(execution.id)

        Executor(client).run(execution, claim_token)

        client.execution_started.assert_not_called()

    def test_execution_started_failure_is_non_fatal(self):
        """A failed execution-started callback must not abort the execution."""
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)
        client.execution_started.side_effect = httpx.HTTPStatusError(
            "409", request=MagicMock(), response=MagicMock(status_code=409)
        )

        Executor(client).run(execution, claim_token)

        # Steps still ran
        client.start_step.assert_called()
        client.complete_execution.assert_called()

    def test_execution_started_passes_observed_at_timestamp(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)

        Executor(client).run(execution, claim_token)

        kwargs = client.execution_started.call_args.kwargs
        assert kwargs.get("observed_at") is not None
        assert isinstance(kwargs["observed_at"], datetime)


# ---------------------------------------------------------------------------
# Executor: execution-finished called after complete_execution
# ---------------------------------------------------------------------------


class TestExecutionFinishedCallback:
    def test_execution_finished_called_after_complete_execution(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)

        Executor(client).run(execution, claim_token)

        client.execution_finished.assert_called_once_with(
            execution.change_record_id,
            execution.id,
            observed_at=client.execution_finished.call_args.kwargs["observed_at"],
        )

    def test_execution_finished_called_after_complete_execution_order(self):
        """complete_execution must be called before execution_finished."""
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)

        call_order = []
        client.complete_execution.side_effect = lambda *a, **kw: (
            call_order.append("complete") or _complete_ok(execution.id)
        )
        client.execution_finished.side_effect = lambda *a, **kw: (
            call_order.append("finished")
            or _finished_ok(execution.change_record_id, execution.id)
        )

        Executor(client).run(execution, claim_token)

        assert call_order.index("complete") < call_order.index("finished")

    def test_execution_finished_not_called_for_plain_execution(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=False)
        claim_token = uuid4()

        client = MagicMock()
        client.start_step.return_value = _step_start_run(execution.id, step.id)
        client.update_step.return_value = _step_update_ok(execution.id, step.id)
        client.complete_execution.return_value = _complete_ok(execution.id)
        client.heartbeat.return_value = MagicMock()

        Executor(client).run(execution, claim_token)

        client.execution_finished.assert_not_called()

    def test_execution_finished_called_even_when_steps_fail(self):
        step = _make_step(1, command="FAIL_STEP")
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)
        client.update_step.return_value = StepUpdateResponse(
            execution_id=execution.id,
            step={"id": str(step.id), "status": "failed", "exit_code": 1},
            execution_status="failed",
        )
        client.complete_execution.return_value = CompleteExecutionResponse(
            id=execution.id, status="failed"
        )

        Executor(client).run(execution, claim_token)

        client.execution_finished.assert_called_once()

    def test_execution_finished_called_even_when_complete_execution_raises(self):
        """execution_finished should still be attempted if complete_execution HTTP fails."""
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)
        client.complete_execution.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=MagicMock(status_code=503)
        )

        Executor(client).run(execution, claim_token)

        client.execution_finished.assert_called_once()

    def test_execution_finished_failure_is_non_fatal(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)
        client.execution_finished.side_effect = httpx.HTTPStatusError(
            "410", request=MagicMock(), response=MagicMock(status_code=410)
        )

        # Should not raise
        Executor(client).run(execution, claim_token)

    def test_execution_finished_not_called_when_bind_fails(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()

        client = MagicMock()
        client.bind_change_execution.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock(status_code=403)
        )
        client.complete_execution.return_value = _complete_ok(execution.id)

        Executor(client).run(execution, claim_token)

        client.execution_finished.assert_not_called()

    def test_execution_finished_passes_observed_at_timestamp(self):
        step = _make_step(1)
        execution = _make_execution([step], change_bound=True)
        claim_token = uuid4()
        client = _mock_client_for_change_execution(execution)

        Executor(client).run(execution, claim_token)

        kwargs = client.execution_finished.call_args.kwargs
        assert kwargs.get("observed_at") is not None
        assert isinstance(kwargs["observed_at"], datetime)


# ---------------------------------------------------------------------------
# Client: HTTP contract for execution_started / execution_finished
# ---------------------------------------------------------------------------


def _make_transport(status_code: int, body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"Content-Type": "application/json"},
            content=json.dumps(body).encode(),
        )

    return httpx.MockTransport(handler)


def _make_client(transport: httpx.MockTransport) -> ApiClient:
    return ApiClient(
        base_url="http://api:8000",
        runner_id="test-runner",
        runner_token="test-token",
        runner_version="0.1.0",
        http_client=httpx.Client(transport=transport),
        api_retries_enabled=False,
    )


class TestClientExecutionStarted:
    def test_execution_started_posts_to_correct_url(self):
        change_id = uuid4()
        execution_id = uuid4()
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps(
                    {
                        "change_record_id": str(change_id),
                        "execution_started_at": "2026-01-01T00:00:00Z",
                    }
                ).encode(),
            )

        client = _make_client(httpx.MockTransport(handler))
        observed = datetime(2026, 1, 1, tzinfo=UTC)
        resp = client.execution_started(change_id, execution_id, observed_at=observed)

        assert (
            captured["path"]
            == f"/api/v1/internal/changes/{change_id}/execution-started/"
        )
        assert captured["body"]["runner_id"] == "test-runner"
        assert captured["body"]["execution_id"] == str(execution_id)
        assert resp.change_record_id == change_id
        assert resp.execution_started_at is not None

    def test_execution_started_4xx_raises_http_status_error(self):
        change_id = uuid4()
        execution_id = uuid4()
        transport = _make_transport(
            409, {"errors": [{"code": "runner_ownership_mismatch"}]}
        )
        client = _make_client(transport)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            client.execution_started(change_id, execution_id)

        assert exc_info.value.response.status_code == 409

    def test_execution_started_without_observed_at(self):
        change_id = uuid4()
        execution_id = uuid4()
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps(
                    {"change_record_id": str(change_id), "execution_started_at": None}
                ).encode(),
            )

        client = _make_client(httpx.MockTransport(handler))
        client.execution_started(change_id, execution_id)

        assert captured["body"]["observed_at"] is None


class TestClientExecutionFinished:
    def test_execution_finished_posts_to_correct_url(self):
        change_id = uuid4()
        execution_id = uuid4()
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps(
                    {
                        "change_record_id": str(change_id),
                        "execution_finished_at": "2026-01-01T01:00:00Z",
                        "locks_released": 2,
                    }
                ).encode(),
            )

        client = _make_client(httpx.MockTransport(handler))
        observed = datetime(2026, 1, 1, 1, tzinfo=UTC)
        resp = client.execution_finished(change_id, execution_id, observed_at=observed)

        assert (
            captured["path"]
            == f"/api/v1/internal/changes/{change_id}/execution-finished/"
        )
        assert captured["body"]["runner_id"] == "test-runner"
        assert captured["body"]["execution_id"] == str(execution_id)
        assert resp.change_record_id == change_id
        assert resp.locks_released == 2

    def test_execution_finished_4xx_raises_http_status_error(self):
        change_id = uuid4()
        execution_id = uuid4()
        transport = _make_transport(
            410, {"errors": [{"code": "dispatch_token_expired"}]}
        )
        client = _make_client(transport)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            client.execution_finished(change_id, execution_id)

        assert exc_info.value.response.status_code == 410


# ---------------------------------------------------------------------------
# Schema: ExecutionTimingCallbackRequest
# ---------------------------------------------------------------------------


class TestExecutionTimingCallbackRequestSchema:
    def test_serializes_without_observed_at(self):
        req = ExecutionTimingCallbackRequest(
            runner_id="r1",
            execution_id=uuid4(),
        )
        data = req.model_dump(mode="json")
        assert data["runner_id"] == "r1"
        assert data["observed_at"] is None

    def test_serializes_with_observed_at(self):
        ts = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        req = ExecutionTimingCallbackRequest(
            runner_id="r1",
            execution_id=uuid4(),
            observed_at=ts,
        )
        data = req.model_dump(mode="json")
        assert data["observed_at"] is not None

    def test_rejects_extra_fields(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExecutionTimingCallbackRequest(
                runner_id="r1",
                execution_id=uuid4(),
                extra_field="unexpected",
            )
