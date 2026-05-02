"""Step executor — processes steps sequentially and reports status to Django."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx

from runner.artifact_uploader import ArtifactUploader
from runner.client import ApiClient
from runner.schemas import ClaimedExecution, ClaimedStep

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 10
_FAIL_STEP_MARKER = "FAIL_STEP"
_APPROVAL_POLL_INTERVAL_SECONDS = 5


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


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
        self._observed_status = "claimed"

    def set_observed_status(self, status: str) -> None:
        self._observed_status = status

    def run(self) -> None:
        logger.debug("Heartbeat thread started for execution %s", self._execution_id)
        while not self._stop_event.wait(self._interval):
            try:
                self._client.heartbeat(
                    self._execution_id,
                    self._claim_token,
                    observed_status=self._observed_status,
                )
                logger.debug("Heartbeat sent for execution %s", self._execution_id)
            except httpx.HTTPError as exc:
                logger.warning(
                    "Heartbeat failed for execution %s: %s", self._execution_id, exc
                )

    def stop(self) -> None:
        self._stop_event.set()


class Executor:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def _make_uploader(self, execution_id: UUID, claim_token: UUID) -> ArtifactUploader:
        return ArtifactUploader(self._client, execution_id, claim_token)

    def run(self, execution: ClaimedExecution, claim_token: UUID) -> None:
        """Execute all steps of a claimed execution sequentially."""
        execution_id = execution.id

        logger.info(
            "Starting execution %s with %d step(s)",
            execution_id,
            len(execution.steps),
        )

        # For change-bound executions, bind before entering the step loop.
        # A bind failure is fatal — refuse to execute and abort early.
        if execution.is_change_bound:
            if not self._bind_change_execution(execution, claim_token):
                logger.error(
                    "Aborting execution %s: change binding failed", execution_id
                )
                try:
                    self._client.complete_execution(
                        execution_id,
                        claim_token,
                        final_status="failed",
                        error_message="Change binding failed — aborting execution.",
                    )
                except httpx.HTTPError as exc:
                    logger.error(
                        "Failed to mark execution %s failed: %s", execution_id, exc
                    )
                return

        heartbeat = _HeartbeatThread(self._client, execution_id, claim_token)
        heartbeat.start()
        uploader = self._make_uploader(execution_id, claim_token)

        outcome = "succeeded"
        try:
            for step in sorted(execution.steps, key=lambda s: s.position):
                if step.status in {"succeeded", "skipped"}:
                    logger.info(
                        "Step %d/%s '%s': already %s — skipping",
                        step.position,
                        step.id,
                        step.name,
                        step.status,
                    )
                    continue
                if step.status == "failed":
                    logger.info(
                        "Step %d/%s '%s': already failed",
                        step.position,
                        step.id,
                        step.name,
                    )
                    outcome = "failed"
                    break
                step_failed = self._run_step(
                    execution_id, claim_token, step, heartbeat, uploader
                )
                if step_failed:
                    outcome = "failed"
                    break
        except Exception as exc:
            logger.error(
                "Unexpected error during execution %s: %s",
                execution_id,
                exc,
                exc_info=True,
            )
            outcome = "failed"
        finally:
            heartbeat.stop()
            heartbeat.join(timeout=5)

        try:
            self._client.complete_execution(
                execution_id, claim_token, final_status=outcome
            )
            logger.info(
                "Execution %s completed with outcome: %s", execution_id, outcome
            )
        except httpx.HTTPError as exc:
            logger.error("Failed to mark execution %s complete: %s", execution_id, exc)

    def _bind_change_execution(
        self, execution: ClaimedExecution, claim_token: UUID
    ) -> bool:
        """Call Django's bind-execution endpoint. Returns True on success, False on failure.
        Never logs the dispatch token."""
        missing = [
            f
            for f in (
                "change_record_id",
                "dispatch_token",
                "requested_inputs_sha256",
                "operation_profile_key",
            )
            if getattr(execution, f) is None
        ]
        if missing:
            logger.error(
                "Change-bound execution %s is missing required fields: %s — aborting",
                execution.id,
                missing,
            )
            return False

        try:
            self._client.bind_change_execution(
                change_record_id=execution.change_record_id,
                execution_id=execution.id,
                claim_token=claim_token,
                dispatch_token=execution.dispatch_token.get_secret_value(),
                requested_inputs_sha256=execution.requested_inputs_sha256,
                operation_profile_key=execution.operation_profile_key,
            )
            logger.info(
                "Change execution binding confirmed for change %s / execution %s",
                execution.change_record_id,
                execution.id,
            )
            return True
        except httpx.HTTPError as exc:
            logger.error(
                "Change binding failed for change %s / execution %s: %s",
                execution.change_record_id,
                execution.id,
                exc,
            )
            return False

    def _run_step(
        self,
        execution_id: UUID,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        uploader: ArtifactUploader,
    ) -> bool:
        """
        Run a single step. Returns True if the step failed, False if it succeeded.

        All steps call Django's /start/ endpoint first. Django determines whether
        the step can run immediately (runner_action="run") or must wait for approval
        (runner_action="wait_for_approval"). The runner never inspects requires_approval
        locally and never executes a command before receiving runner_action="run".
        """
        logger.info("Step %d/%s '%s': starting", step.position, step.id, step.name)

        try:
            start_resp = self._client.start_step(execution_id, step.id, claim_token)
        except httpx.HTTPError as exc:
            logger.error("Failed to start step %s: %s", step.id, exc)
            return True

        if start_resp.runner_action == "run":
            logger.info(
                "Step %d '%s': approved to run immediately", step.position, step.name
            )
            heartbeat.set_observed_status("running")
            return self._execute_command(
                execution_id, claim_token, step, heartbeat, uploader
            )

        if start_resp.runner_action == "wait_for_approval":
            logger.info("Step %d '%s': waiting for approval", step.position, step.name)
            return self._wait_for_approval(
                execution_id, claim_token, step, heartbeat, start_resp, uploader
            )

        # runner_action == "blocked" or unexpected
        logger.warning(
            "Step %d '%s': blocked by Django (runner_action=%s)",
            step.position,
            step.name,
            start_resp.runner_action,
        )
        return True

    def _wait_for_approval(
        self,
        execution_id: UUID,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        start_resp,
        uploader: ArtifactUploader,
    ) -> bool:
        """Poll Django until the approval is decided. Returns True if step failed."""
        poll_interval = (
            start_resp.poll_after_seconds
            if start_resp.poll_after_seconds > 0
            else _APPROVAL_POLL_INTERVAL_SECONDS
        )

        while True:
            time.sleep(poll_interval)

            try:
                status_resp = self._client.get_step_approval_status(
                    execution_id, step.id, claim_token
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Approval status poll failed for step %s: %s — retrying",
                    step.id,
                    exc,
                )
                continue

            poll_interval = (
                status_resp.poll_after_seconds
                if status_resp.poll_after_seconds > 0
                else _APPROVAL_POLL_INTERVAL_SECONDS
            )

            if status_resp.runner_action == "wait":
                logger.debug(
                    "Step %d '%s': approval still pending", step.position, step.name
                )
                continue

            if status_resp.runner_action == "run":
                logger.info(
                    "Step %d '%s': approval granted — executing",
                    step.position,
                    step.name,
                )
                heartbeat.set_observed_status("running")
                return self._execute_command(
                    execution_id, claim_token, step, heartbeat, uploader
                )

            # runner_action == "fail"
            logger.info(
                "Step %d '%s': approval denied (action=%s)",
                step.position,
                step.name,
                status_resp.runner_action,
            )
            return True

    def _execute_command(
        self,
        execution_id: UUID,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        uploader: ArtifactUploader,
    ) -> bool:
        """
        Execute the step command. Django has already set the step to running.
        Returns True if the step failed, False if it succeeded.

        Artifacts are uploaded BEFORE the terminal step status is reported so
        that evidence is preserved even if the runner crashes after uploading.
        """
        started_at = _utcnow()

        # Simulate execution — check for deliberate failure marker
        should_fail = _FAIL_STEP_MARKER in (step.command or "")

        if should_fail:
            logger.info(
                "Step %d '%s': deliberate failure (FAIL_STEP marker detected)",
                step.position,
                step.name,
            )
            finished_at = _utcnow()
            stderr_content = b"Intentional failure triggered by FAIL_STEP token.\n"
            stdout_content = b""
            # Upload artifacts before reporting terminal status
            self._upload_step_outputs(uploader, step, stdout_content, stderr_content)
            try:
                self._client.update_step(
                    execution_id,
                    step.id,
                    claim_token,
                    status="failed",
                    started_at=started_at,
                    finished_at=finished_at,
                    exit_code=1,
                    error_message="Intentional failure triggered by FAIL_STEP token.",
                )
            except httpx.HTTPError as exc:
                logger.error("Failed to mark step %s failed: %s", step.id, exc)
            return True

        # Happy path: brief placeholder work, then succeed
        time.sleep(0.5)
        finished_at = _utcnow()
        stdout_content = f"Step '{step.name}' executed successfully.\n".encode()
        stderr_content = b""
        # Upload artifacts before reporting terminal status
        self._upload_step_outputs(uploader, step, stdout_content, stderr_content)

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

    def _upload_step_outputs(
        self,
        uploader: ArtifactUploader,
        step: ClaimedStep,
        stdout: bytes,
        stderr: bytes,
    ) -> None:
        """Upload stdout and stderr artifacts. Failures are logged but do not affect step outcome."""
        if stdout:
            result = uploader.upload_stdout(step.id, stdout)
            if result is None:
                logger.warning("stdout artifact upload failed for step %s", step.id)
        if stderr:
            result = uploader.upload_stderr(step.id, stderr)
            if result is None:
                logger.warning("stderr artifact upload failed for step %s", step.id)
