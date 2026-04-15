"""Step executor — processes steps sequentially and reports status to Django."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx

from runner.client import ApiClient
from runner.schemas import ClaimedExecution

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 10
_FAIL_STEP_MARKER = "FAIL_STEP"


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class _HeartbeatThread(threading.Thread):
    """Background thread that sends periodic heartbeats while an execution is active."""

    def __init__(
        self,
        client: ApiClient,
        execution_id: UUID,
        claim_token: UUID,
        interval: float = _HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        super().__init__(daemon=True, name="heartbeat")
        self._client = client
        self._execution_id = execution_id
        self._claim_token = claim_token
        self._interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.debug("Heartbeat thread started for execution %s", self._execution_id)
        while not self._stop_event.wait(self._interval):
            try:
                self._client.heartbeat(self._execution_id, self._claim_token)
                logger.debug("Heartbeat sent for execution %s", self._execution_id)
            except httpx.HTTPError as exc:
                logger.warning("Heartbeat failed for execution %s: %s", self._execution_id, exc)

    def stop(self) -> None:
        self._stop_event.set()


class Executor:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def run(self, execution: ClaimedExecution) -> None:
        """Execute all steps of a claimed execution sequentially."""
        execution_id = execution.id
        claim_token = execution.claim_token

        logger.info(
            "Starting execution %s with %d step(s)",
            execution_id,
            len(execution.steps),
        )

        heartbeat = _HeartbeatThread(self._client, execution_id, claim_token)
        heartbeat.start()

        outcome = "succeeded"
        try:
            for step in sorted(execution.steps, key=lambda s: s.position):
                step_failed = self._run_step(execution_id, claim_token, step)
                if step_failed:
                    outcome = "failed"
                    break
        except Exception as exc:
            logger.error(
                "Unexpected error during execution %s: %s", execution_id, exc, exc_info=True
            )
            outcome = "failed"
        finally:
            heartbeat.stop()
            heartbeat.join(timeout=5)

        try:
            self._client.complete_execution(execution_id, claim_token, outcome)
            logger.info("Execution %s completed with outcome: %s", execution_id, outcome)
        except httpx.HTTPError as exc:
            logger.error(
                "Failed to mark execution %s complete: %s", execution_id, exc
            )

    def _run_step(self, execution_id: UUID, claim_token: UUID, step) -> bool:
        """
        Run a single step. Returns True if the step failed, False if it succeeded.

        A step with 'FAIL_STEP' in its command is treated as a deliberate failure path.
        """
        logger.info(
            "Step %d/%s '%s': starting", step.position, step.id, step.name
        )
        started_at = _utcnow()

        # Mark step as running
        try:
            self._client.update_step(
                execution_id,
                step.id,
                claim_token,
                status="running",
                started_at=started_at,
            )
        except httpx.HTTPError as exc:
            logger.error("Failed to mark step %s running: %s", step.id, exc)
            return True  # treat as failure

        # Simulate execution — check for deliberate failure marker
        should_fail = _FAIL_STEP_MARKER in (step.command or "")

        if should_fail:
            logger.info(
                "Step %d '%s': deliberate failure (FAIL_STEP marker detected)",
                step.position,
                step.name,
            )
            finished_at = _utcnow()
            try:
                self._client.update_step(
                    execution_id,
                    step.id,
                    claim_token,
                    status="failed",
                    started_at=started_at,
                    finished_at=finished_at,
                    exit_code=1,
                    error_message="Step failed: FAIL_STEP marker in command.",
                )
            except httpx.HTTPError as exc:
                logger.error("Failed to mark step %s failed: %s", step.id, exc)
            return True

        # Happy path: brief placeholder work, then succeed
        time.sleep(0.5)
        finished_at = _utcnow()

        try:
            self._client.update_step(
                execution_id,
                step.id,
                claim_token,
                status="succeeded",
                started_at=started_at,
                finished_at=finished_at,
                exit_code=0,
            )
            logger.info("Step %d '%s': succeeded", step.position, step.name)
        except httpx.HTTPError as exc:
            logger.error("Failed to mark step %s succeeded: %s", step.id, exc)
            return True

        return False
