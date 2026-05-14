"""Poll loop — continuously asks Django for queued executions and hands them off."""

from __future__ import annotations

import logging
import threading
import time

import httpx

from runner.client import ApiClient
from runner.executor import Executor

logger = logging.getLogger(__name__)


class Poller:
    _MIN_EMPTY_BACKOFF: float = 2.0
    _MIN_ERROR_BACKOFF: float = 5.0
    _MAX_ERROR_BACKOFF: float = 60.0

    def __init__(
        self,
        client: ApiClient,
        executor: Executor,
        *,
        poll_interval_seconds: int = 5,
        shutdown_event: threading.Event | None = None,
        runner_heartbeat_interval_seconds: int = 30,
    ) -> None:
        self._client = client
        self._executor = executor
        self._max_empty_backoff = float(poll_interval_seconds)
        self._shutdown_event = shutdown_event
        self._empty_backoff = self._MIN_EMPTY_BACKOFF
        self._error_backoff = self._MIN_ERROR_BACKOFF
        self._runner_heartbeat_interval_seconds = runner_heartbeat_interval_seconds

    def _sleep(self, duration: float) -> None:
        """Sleep for duration, but wake early if shutdown is requested."""
        if self._shutdown_event is not None:
            self._shutdown_event.wait(timeout=duration)
        else:
            time.sleep(duration)

    def _run_heartbeat_loop(self) -> None:
        """Background thread: send runner-level heartbeats to Django."""
        while True:
            if self._shutdown_event is not None and self._shutdown_event.is_set():
                break
            time.sleep(self._runner_heartbeat_interval_seconds)
            if self._shutdown_event is not None and self._shutdown_event.is_set():
                break
            try:
                self._client.runner_heartbeat()
            except Exception as exc:
                logger.warning("runner_heartbeat call failed: %s", exc)

    def run_forever(self) -> None:
        """Poll indefinitely, executing one queued execution at a time."""
        logger.info("Poller started — waiting for queued executions")

        # Start background runner heartbeat thread if the client supports it.
        hb_thread = threading.Thread(
            target=self._run_heartbeat_loop,
            daemon=True,
            name="runner-heartbeat",
        )
        hb_thread.start()

        while True:
            if self._shutdown_event is not None and self._shutdown_event.is_set():
                logger.info("Shutdown requested — poller exiting cleanly")
                break
            try:
                self._poll_once()
            except KeyboardInterrupt:
                logger.info("Poller interrupted, shutting down")
                break
            except Exception as exc:
                logger.error("Unexpected error in poll loop: %s", exc, exc_info=True)
                time.sleep(5)

    def _poll_once(self) -> None:
        try:
            response = self._client.claim_next()
        except httpx.HTTPError as exc:
            logger.warning(
                "claim-next request failed: %s — retrying in %.0fs",
                exc,
                self._error_backoff,
            )
            self._sleep(self._error_backoff)
            self._error_backoff = min(self._error_backoff * 2, self._MAX_ERROR_BACKOFF)
            return

        # Successful HTTP call — reset error backoff
        self._error_backoff = self._MIN_ERROR_BACKOFF

        if response.execution is None:
            # Check for drain action.
            if response.runner_action == "drain":
                logger.info(
                    "Drain requested by server (reason: %s) — stopping poll",
                    response.drain_reason,
                )
                if self._shutdown_event is not None:
                    self._shutdown_event.set()
                return

            logger.debug("No queued executions; sleeping %.0fs", self._empty_backoff)
            self._sleep(self._empty_backoff)
            self._empty_backoff = min(self._empty_backoff * 2, self._max_empty_backoff)
            return

        # Work found — reset empty backoff
        self._empty_backoff = self._MIN_EMPTY_BACKOFF

        execution = response.execution
        claim_token = response.claim_token

        if claim_token is None:
            logger.error(
                "Claim-next returned execution %s but no claim_token — skipping",
                execution.id,
            )
            return

        logger.info(
            "Claimed execution %s (workflow_version=%d, steps=%d)",
            execution.id,
            execution.workflow_version,
            len(execution.steps),
        )
        # Block until execution is finished before polling again
        self._executor.run(execution, claim_token)
