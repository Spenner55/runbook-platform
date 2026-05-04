"""Tests for change execution binding in the runner executor."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from runner.executor import Executor
from runner.schemas import (
    BindChangeExecutionRequest,
    BindChangeExecutionResponse,
    ClaimedExecution,
    ClaimedStep,
    CompleteExecutionResponse,
    StepStartResponse,
    StepUpdateResponse,
)


def make_step(position: int, command: str = "") -> ClaimedStep:
    return ClaimedStep(
        id=uuid4(),
        position=position,
        step_key=f"step-{position}",
        name=f"Step {position}",
        step_type="manual",
        risk_level="low",
        command=command,
        requires_approval=False,
        status="pending",
    )


def make_execution(steps, *, change_bound: bool = False):
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


def _step_start_run(execution_id=None, step_id=None):
    return StepStartResponse(
        execution_id=execution_id or uuid4(),
        execution_status="running",
        step={"id": str(step_id or uuid4()), "status": "running"},
        runner_action="run",
        poll_after_seconds=0,
    )


def _step_update_ok(execution_id, step_id):
    return StepUpdateResponse(
        execution_id=execution_id,
        step={"id": str(step_id), "status": "succeeded", "exit_code": 0},
        execution_status="running",
    )


class TestIsChangeBound:
    def test_not_change_bound_by_default(self):
        ex = make_execution([make_step(1)])
        assert ex.is_change_bound is False

    def test_change_bound_when_fields_present(self):
        ex = make_execution([make_step(1)], change_bound=True)
        assert ex.is_change_bound is True

    def test_dispatch_token_is_redacted_in_model_repr_and_dump(self):
        ex = make_execution([make_step(1)], change_bound=True)

        assert "secret-token" not in repr(ex)
        assert "secret-token" not in str(ex.model_dump(mode="json"))


class TestExecutorChangeBound:
    def _mock_client(self, bind_ok=True):
        client = MagicMock()
        if bind_ok:
            client.bind_change_execution.return_value = BindChangeExecutionResponse(
                change_record_id=uuid4(),
                execution_id=uuid4(),
            )
        else:
            client.bind_change_execution.side_effect = httpx.HTTPStatusError(
                "403",
                request=MagicMock(),
                response=MagicMock(status_code=403),
            )
        client.complete_execution.return_value = CompleteExecutionResponse(
            id=uuid4(), status="failed"
        )
        return client

    def test_bind_called_before_steps_for_change_bound_execution(self):
        step = make_step(1)
        execution = make_execution([step], change_bound=True)
        claim_token = uuid4()

        client = self._mock_client(bind_ok=True)
        client.start_step.return_value = _step_start_run(execution.id, step.id)
        client.update_step.return_value = _step_update_ok(execution.id, step.id)
        client.complete_execution.return_value = CompleteExecutionResponse(
            id=execution.id, status="succeeded"
        )
        client.heartbeat.return_value = MagicMock()

        executor = Executor(client)
        executor.run(execution, claim_token)

        client.bind_change_execution.assert_called_once_with(
            change_record_id=execution.change_record_id,
            execution_id=execution.id,
            claim_token=claim_token,
            dispatch_token=execution.dispatch_token.get_secret_value(),
            requested_inputs_sha256=execution.requested_inputs_sha256,
            operation_profile_key=execution.operation_profile_key,
        )
        # Steps should have been executed
        client.start_step.assert_called()

    def test_bind_failure_aborts_execution_without_running_steps(self):
        step = make_step(1)
        execution = make_execution([step], change_bound=True)
        claim_token = uuid4()

        client = self._mock_client(bind_ok=False)

        executor = Executor(client)
        executor.run(execution, claim_token)

        # Bind was attempted
        client.bind_change_execution.assert_called_once()
        # No steps run
        client.start_step.assert_not_called()
        # Execution marked failed
        client.complete_execution.assert_called_once()
        call_kwargs = client.complete_execution.call_args
        assert (
            call_kwargs.kwargs.get("final_status") == "failed"
            or call_kwargs.args[2] == "failed"
        )

    def test_non_change_bound_execution_does_not_call_bind(self):
        step = make_step(1)
        execution = make_execution([step], change_bound=False)
        claim_token = uuid4()

        client = MagicMock()
        client.start_step.return_value = _step_start_run(execution.id, step.id)
        client.update_step.return_value = _step_update_ok(execution.id, step.id)
        client.complete_execution.return_value = CompleteExecutionResponse(
            id=execution.id, status="succeeded"
        )
        client.heartbeat.return_value = MagicMock()

        executor = Executor(client)
        executor.run(execution, claim_token)

        client.bind_change_execution.assert_not_called()
        client.start_step.assert_called()

    def test_dispatch_token_not_logged(self, caplog):
        """Dispatch token must never appear in log output."""
        import logging

        step = make_step(1)
        execution = make_execution([step], change_bound=True)
        claim_token = uuid4()

        client = self._mock_client(bind_ok=True)
        client.start_step.return_value = _step_start_run(execution.id, step.id)
        client.update_step.return_value = _step_update_ok(execution.id, step.id)
        client.complete_execution.return_value = CompleteExecutionResponse(
            id=execution.id, status="succeeded"
        )
        client.heartbeat.return_value = MagicMock()

        with caplog.at_level(logging.DEBUG, logger="runner.executor"):
            executor = Executor(client)
            executor.run(execution, claim_token)

        for record in caplog.records:
            assert "secret-token" not in record.getMessage()


# ---------------------------------------------------------------------------
# C5: BindChangeExecutionRequest dispatch_token secret handling
# ---------------------------------------------------------------------------


class TestBindChangeExecutionRequestSecret:
    """dispatch_token in BindChangeExecutionRequest must be treated as a secret."""

    def _make_request(self) -> BindChangeExecutionRequest:
        return BindChangeExecutionRequest(
            runner_id="r1",
            claim_token=uuid4(),
            execution_id=uuid4(),
            dispatch_token="super-secret-dispatch-token",
            requested_inputs_sha256="a" * 64,
            operation_profile_key="prod-maintenance",
        )

    def test_dispatch_token_not_in_repr(self):
        req = self._make_request()
        assert "super-secret-dispatch-token" not in repr(req)

    def test_dispatch_token_not_in_str(self):
        req = self._make_request()
        assert "super-secret-dispatch-token" not in str(req)

    def test_dispatch_token_not_in_python_model_dump(self):
        req = self._make_request()
        dumped = str(req.model_dump())
        assert "super-secret-dispatch-token" not in dumped

    def test_dispatch_token_revealed_in_json_model_dump_for_http_body(self):
        """JSON dump must include the actual token so it can be sent to Django."""
        req = self._make_request()
        dumped = req.model_dump(mode="json")
        assert dumped["dispatch_token"] == "super-secret-dispatch-token"


# ---------------------------------------------------------------------------
# C4: Partial change metadata raises validation error
# ---------------------------------------------------------------------------


class TestPartialChangeMetadataValidation:
    """ClaimedExecution validator must reject partial (some-but-not-all) change fields."""

    def _make_step_dict(self):
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

    def test_partial_change_fields_raise_validation_error(self):
        from pydantic import ValidationError

        from runner.schemas import ClaimedExecution

        with pytest.raises(ValidationError) as exc_info:
            ClaimedExecution(
                id=uuid4(),
                status="claimed",
                workflow_id=uuid4(),
                organization_id=uuid4(),
                workflow_version=1,
                workflow_snapshot={},
                steps=[],
                change_record_id=uuid4(),
                # dispatch_token absent — partial change fields
                requested_inputs_sha256="a" * 64,
                operation_profile_key="prod-maintenance",
            )
        errors = exc_info.value.errors()
        assert any("missing" in str(e).lower() for e in errors)

    def test_all_change_fields_none_is_valid_non_change_bound(self):
        from runner.schemas import ClaimedExecution

        execution = ClaimedExecution(
            id=uuid4(),
            status="claimed",
            workflow_id=uuid4(),
            organization_id=uuid4(),
            workflow_version=1,
            workflow_snapshot={},
            steps=[],
            change_record_id=None,
            dispatch_token=None,
            requested_inputs_sha256=None,
            operation_profile_key=None,
        )
        assert execution.is_change_bound is False

    def test_all_change_fields_present_is_valid_change_bound(self):
        from runner.schemas import ClaimedExecution

        execution = ClaimedExecution(
            id=uuid4(),
            status="claimed",
            workflow_id=uuid4(),
            organization_id=uuid4(),
            workflow_version=1,
            workflow_snapshot={},
            steps=[],
            change_record_id=uuid4(),
            dispatch_token="some-token",
            requested_inputs_sha256="a" * 64,
            operation_profile_key="prod-maintenance",
        )
        assert execution.is_change_bound is True
