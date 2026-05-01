"""Unit tests for runner.poller — client and executor are mocked."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx

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


def make_poller(**kwargs) -> Poller:
    client = kwargs.pop("client", MagicMock())
    executor = kwargs.pop("executor", MagicMock())
    return Poller(client, executor, **kwargs)


# ---------------------------------------------------------------------------
# Empty queue — adaptive backoff
# ---------------------------------------------------------------------------


@patch("runner.poller.time.sleep")
def test_no_work_sleeps_for_min_empty_backoff(mock_sleep):
    poller = make_poller()
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=None, poll_after_seconds=5
    )

    poller._poll_once()

    mock_sleep.assert_called_once_with(Poller._MIN_EMPTY_BACKOFF)
    poller._executor.run.assert_not_called()


@patch("runner.poller.time.sleep")
def test_empty_backoff_doubles_on_repeated_empty_polls(mock_sleep):
    poller = make_poller(poll_interval_seconds=10)
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=None, poll_after_seconds=5
    )

    poller._poll_once()
    first_sleep = mock_sleep.call_args_list[-1][0][0]
    poller._poll_once()
    second_sleep = mock_sleep.call_args_list[-1][0][0]

    assert second_sleep == first_sleep * 2


@patch("runner.poller.time.sleep")
def test_empty_backoff_caps_at_poll_interval(mock_sleep):
    poller = make_poller(poll_interval_seconds=5)
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=None, poll_after_seconds=5
    )

    # Drive backoff past the cap
    for _ in range(10):
        poller._poll_once()

    last_sleep = mock_sleep.call_args_list[-1][0][0]
    assert last_sleep <= float(5)


@patch("runner.poller.time.sleep")
def test_empty_backoff_resets_when_work_found(mock_sleep):
    poller = make_poller()
    no_work = ClaimNextResponse(execution=None, poll_after_seconds=5)
    poller._client.claim_next.return_value = no_work

    # Drive up the backoff
    poller._poll_once()
    poller._poll_once()
    raised_backoff = poller._empty_backoff

    # Now return work — backoff should reset
    claimed = make_claimed_execution()
    token = uuid4()
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=claimed, claim_token=token, poll_after_seconds=5
    )
    poller._poll_once()

    assert poller._empty_backoff == Poller._MIN_EMPTY_BACKOFF
    assert raised_backoff > Poller._MIN_EMPTY_BACKOFF


# ---------------------------------------------------------------------------
# HTTP error backoff
# ---------------------------------------------------------------------------


@patch("runner.poller.time.sleep")
def test_http_error_sleeps_and_returns(mock_sleep):
    poller = make_poller()
    poller._client.claim_next.side_effect = httpx.HTTPError("connection refused")

    poller._poll_once()

    mock_sleep.assert_called_once_with(Poller._MIN_ERROR_BACKOFF)
    poller._executor.run.assert_not_called()


@patch("runner.poller.time.sleep")
def test_http_error_backoff_doubles(mock_sleep):
    poller = make_poller()
    poller._client.claim_next.side_effect = httpx.HTTPError("connection refused")

    poller._poll_once()
    first = mock_sleep.call_args_list[-1][0][0]
    poller._poll_once()
    second = mock_sleep.call_args_list[-1][0][0]

    assert second == first * 2


@patch("runner.poller.time.sleep")
def test_http_error_backoff_caps_at_max(mock_sleep):
    poller = make_poller()
    poller._client.claim_next.side_effect = httpx.HTTPError("connection refused")

    for _ in range(10):
        poller._poll_once()

    last_sleep = mock_sleep.call_args_list[-1][0][0]
    assert last_sleep <= Poller._MAX_ERROR_BACKOFF


@patch("runner.poller.time.sleep")
def test_http_error_backoff_resets_on_success(mock_sleep):
    poller = make_poller()
    poller._client.claim_next.side_effect = httpx.HTTPError("connection refused")

    # Drive up error backoff
    poller._poll_once()
    poller._poll_once()
    assert poller._error_backoff > Poller._MIN_ERROR_BACKOFF

    # Successful response resets error backoff
    poller._client.claim_next.side_effect = None
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=None, poll_after_seconds=5
    )
    poller._poll_once()
    assert poller._error_backoff == Poller._MIN_ERROR_BACKOFF


# ---------------------------------------------------------------------------
# Work claimed
# ---------------------------------------------------------------------------


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
    poller = make_poller()
    claimed = make_claimed_execution()
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=claimed, claim_token=uuid4(), poll_after_seconds=5
    )

    poller._poll_once()

    assert poller._executor.run.call_count == 1


@patch("runner.poller.time.sleep")
def test_missing_claim_token_skips_execution(mock_sleep):
    """If claim-next returns an execution but no claim_token, skip it."""
    poller = make_poller()
    claimed = make_claimed_execution()
    poller._client.claim_next.return_value = ClaimNextResponse(
        execution=claimed, claim_token=None, poll_after_seconds=5
    )

    poller._poll_once()

    poller._executor.run.assert_not_called()


# ---------------------------------------------------------------------------
# Shutdown event
# ---------------------------------------------------------------------------


def test_run_forever_exits_when_shutdown_set():
    """run_forever() must return after the current _poll_once() if shutdown is set."""
    shutdown = threading.Event()
    poller = make_poller(shutdown_event=shutdown)

    call_count = 0

    def fake_poll_once():
        nonlocal call_count
        call_count += 1
        shutdown.set()

    poller._poll_once = fake_poll_once  # type: ignore[method-assign]
    poller.run_forever()

    assert call_count == 1


def test_run_forever_checks_shutdown_before_each_poll():
    """If shutdown is already set, run_forever() must not call _poll_once() at all."""
    shutdown = threading.Event()
    shutdown.set()
    poller = make_poller(shutdown_event=shutdown)

    poller._poll_once = MagicMock()  # type: ignore[method-assign]
    poller.run_forever()

    poller._poll_once.assert_not_called()


def test_sleep_wakes_early_on_shutdown():
    """_sleep() returns promptly when shutdown_event is set mid-sleep."""
    shutdown = threading.Event()
    poller = make_poller(shutdown_event=shutdown)

    def _set_after_short_delay():
        time_module.sleep(0.05)
        shutdown.set()

    import time as time_module

    t = threading.Thread(target=_set_after_short_delay)
    t.start()

    start = time_module.monotonic()
    poller._sleep(10.0)
    elapsed = time_module.monotonic() - start

    t.join()
    assert elapsed < 1.0, f"_sleep() took {elapsed:.2f}s — should have woken early"
