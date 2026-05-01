"""Tests for SIGTERM-aware graceful shutdown behaviour."""

from __future__ import annotations

import signal
import threading
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

from runner.main import _install_sigterm_handler
from runner.poller import Poller
from runner.schemas import ClaimedExecution, ClaimedStep, ClaimNextResponse

# ---------------------------------------------------------------------------
# _install_sigterm_handler
# ---------------------------------------------------------------------------


def test_sigterm_sets_shutdown_event():
    shutdown = threading.Event()
    _install_sigterm_handler(shutdown)

    assert not shutdown.is_set()
    signal.raise_signal(signal.SIGTERM)
    assert shutdown.is_set()

    # Restore default SIGTERM handler
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


@patch("runner.main.time.sleep")
@patch("runner.main.os._exit")
def test_sigterm_starts_hard_timeout_watchdog(mock_exit, mock_sleep):
    """After SIGTERM, a watchdog thread calls os._exit(1) after the hard timeout."""
    shutdown = threading.Event()
    _install_sigterm_handler(shutdown)

    signal.raise_signal(signal.SIGTERM)

    # Give the daemon watchdog thread a moment to start
    time.sleep(0.05)

    # The watchdog calls time.sleep(_HARD_SHUTDOWN_TIMEOUT_SECONDS) — verify it started
    mock_sleep.assert_called()

    # Restore default SIGTERM handler
    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def test_sigterm_handler_is_idempotent():
    """Sending SIGTERM twice must not crash or raise."""
    shutdown = threading.Event()
    _install_sigterm_handler(shutdown)

    signal.raise_signal(signal.SIGTERM)
    signal.raise_signal(signal.SIGTERM)

    assert shutdown.is_set()

    signal.signal(signal.SIGTERM, signal.SIG_DFL)


def test_shutdown_event_prevents_new_poll_after_current_finishes():
    """Simulate: runner receives SIGTERM mid-execution and stops after executor.run()."""
    shutdown = threading.Event()
    client = MagicMock()
    executor = MagicMock()

    polls = []

    def fake_claim_next():
        polls.append(len(polls) + 1)
        if len(polls) == 1:
            # First poll: return work, set shutdown during "execution"
            step = ClaimedStep(
                id=uuid4(),
                position=1,
                step_key="s",
                name="S",
                step_type="manual",
                risk_level="low",
                status="pending",
            )
            exe = ClaimedExecution(
                id=uuid4(),
                status="claimed",
                workflow_id=uuid4(),
                organization_id=uuid4(),
                workflow_version=1,
                workflow_snapshot={},
                steps=[step],
            )
            return ClaimNextResponse(
                execution=exe, claim_token=uuid4(), poll_after_seconds=5
            )
        return ClaimNextResponse(execution=None, poll_after_seconds=5)

    def fake_executor_run(execution, claim_token):
        # Simulate SIGTERM arriving during step execution
        shutdown.set()

    client.claim_next.side_effect = fake_claim_next
    executor.run.side_effect = fake_executor_run

    poller = Poller(client, executor, shutdown_event=shutdown)
    poller.run_forever()

    # Only one poll should have run (executor ran once, then shutdown detected)
    assert len(polls) == 1
    executor.run.assert_called_once()
