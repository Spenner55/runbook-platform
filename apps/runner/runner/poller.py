"""Poll loop — continuously asks Django for queued executions and hands them off."""

from __future__ import annotations

import logging
import time

import httpx

from runner.client import ApiClient
from runner.executor import Executor

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, client: ApiClient, executor: Executor) -> None:
        self._client = client
        self._executor = executor

    def run_forever(self) -> None:
        """Poll indefinitely, executing one queued execution at a time."""
        logger.info("Poller started — waiting for queued executions")
        while True:
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
            logger.warning("claim-next request failed: %s — retrying in 5s", exc)
            time.sleep(5)
            return

        if response.execution is None:
            logger.debug("No queued executions; sleeping %ds", response.poll_after_seconds)
            time.sleep(response.poll_after_seconds)
            return

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
