"""Unit tests for runner.poller — client and executor are mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from runner.poller import Poller
from runner.schemas import ClaimedExecution, ClaimedStep, ClaimNextResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_claimed_execution() -> ClaimedExecution:
    step = ClaimedStep(
        id=uuid4(),
        position=1,
        step_key="step-1",
        name="Step 1",
        step_type="manual",
        risk_level="low",
        command="",
        requires_approval=False,
        status="pending",
    )
    return ClaimedExecution(
        id=uuid4(),
        status="claimed",
        workflow_id=uuid4(),
        organization_id=uuid4(),
        workflow_version=1,
        workflow_snapshot={},
        steps=[step],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("runner.poller.time.sleep")
def test_no_work_sleeps_for_poll_interval(mock_sleep):
    client = MagicMock()
    executor = MagicMock()
    poller = Poller(client, executor)

    client.claim_next.return_value = ClaimNextResponse(
        execution=None, poll_after_seconds=5
    )

    poller._poll_once()

    mock_sleep.assert_called_once_with(5)
    executor.run.assert_not_called()


@patch("runner.poller.time.sleep")
def test_work_claimed_calls_executor_run(mock_sleep):
    client = MagicMock()
    executor = MagicMock()
    poller = Poller(client, executor)

    claimed = make_claimed_execution()
    token = uuid4()
    client.claim_next.return_value = ClaimNextResponse(
        execution=claimed, claim_token=token, poll_after_seconds=5
    )

    poller._poll_once()

    executor.run.assert_called_once_with(claimed, token)
    mock_sleep.assert_not_called()


@patch("runner.poller.time.sleep")
def test_poll_does_not_double_execute(mock_sleep):
    client = MagicMock()
    executor = MagicMock()
    poller = Poller(client, executor)

    claimed = make_claimed_execution()
    client.claim_next.return_value = ClaimNextResponse(
        execution=claimed, claim_token=uuid4(), poll_after_seconds=5
    )

    poller._poll_once()

    assert executor.run.call_count == 1


@patch("runner.poller.time.sleep")
def test_http_error_sleeps_and_returns(mock_sleep):
    import httpx

    client = MagicMock()
    executor = MagicMock()
    poller = Poller(client, executor)

    client.claim_next.side_effect = httpx.HTTPError("connection refused")

    poller._poll_once()

    mock_sleep.assert_called_once_with(5)
    executor.run.assert_not_called()


@patch("runner.poller.time.sleep")
def test_missing_claim_token_skips_execution(mock_sleep):
    """If claim-next returns an execution but no claim_token, skip it."""
    client = MagicMock()
    executor = MagicMock()
    poller = Poller(client, executor)

    claimed = make_claimed_execution()
    client.claim_next.return_value = ClaimNextResponse(
        execution=claimed, claim_token=None, poll_after_seconds=5
    )

    poller._poll_once()

    executor.run.assert_not_called()
