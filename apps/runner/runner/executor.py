"""Step executor — processes steps sequentially and reports status to Django."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx

from runner.artifact_uploader import ArtifactUploader
from runner.client import ApiClient
from runner.sandbox import (
    SandboxError,
    SandboxExecutionSpec,
    SandboxLimits,
    SandboxValidationError,
    get_provider,
)
from runner.sandbox.workspace import WorkspaceManager
from runner.schemas import (
    ArtifactUploadResponse,
    ClaimedExecution,
    ClaimedStep,
    RunnerSettings,
)

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_SECONDS = 10
_FAIL_STEP_MARKER = "FAIL_STEP"
_APPROVAL_POLL_INTERVAL_SECONDS = 5
_SUPPORTED_SANDBOX_STEP_TYPES = frozenset({"command", "shell"})


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
        cancellation_event: threading.Event | None = None,
    ) -> None:
        super().__init__(daemon=True, name="heartbeat")
        self._client = client
        self._execution_id = execution_id
        self._claim_token = claim_token
        self._interval = interval
        self._stop_event = threading.Event()
        self._observed_status = "claimed"
        self._cancellation_event = (
            cancellation_event if cancellation_event is not None else threading.Event()
        )
        self._cancel_reason = ""

    @property
    def cancel_reason(self) -> str:
        return self._cancel_reason

    def set_observed_status(self, status: str) -> None:
        self._observed_status = status

    def run(self) -> None:
        logger.debug("Heartbeat thread started for execution %s", self._execution_id)
        while not self._stop_event.wait(self._interval):
            try:
                resp = self._client.heartbeat(
                    self._execution_id,
                    self._claim_token,
                    observed_status=self._observed_status,
                )
                logger.debug("Heartbeat sent for execution %s", self._execution_id)
                if resp.cancel_requested and not self._cancellation_event.is_set():
                    self._cancel_reason = resp.cancel_reason or ""
                    logger.info(
                        "Cancellation requested for execution %s: %s",
                        self._execution_id,
                        self._cancel_reason,
                    )
                    self._cancellation_event.set()
            except httpx.HTTPError as exc:
                logger.warning(
                    "Heartbeat failed for execution %s: %s", self._execution_id, exc
                )

    def stop(self) -> None:
        self._stop_event.set()


class Executor:
    def __init__(
        self, client: ApiClient, settings: RunnerSettings | None = None
    ) -> None:
        self._client = client
        self._settings = settings

    def _make_uploader(self, execution_id: UUID, claim_token: UUID) -> ArtifactUploader:
        return ArtifactUploader(self._client, execution_id, claim_token)

    def _observe_breakglass(
        self, execution: ClaimedExecution, claim_token: UUID
    ) -> None:
        if execution.breakglass is None or execution.change_record_id is None:
            return
        self._client.breakglass_heartbeat(
            execution.change_record_id,
            claim_token,
            execution.breakglass.breakglass_session_id,
            execution.breakglass.scope_sha256,
        )

    def run(self, execution: ClaimedExecution, claim_token: UUID) -> None:
        """Execute all steps of a claimed execution sequentially."""
        execution_id = execution.id

        logger.info(
            "Starting execution %s with %d step(s)",
            execution_id,
            len(execution.steps),
        )

        if execution.breakglass is not None:
            bg = execution.breakglass
            logger.info(
                "Breakglass session active for execution %s: session=%s scope=%s expires_at=%s. "
                "Django remains authoritative — runner will call step-start gates as normal.",
                execution_id,
                bg.breakglass_session_id,
                bg.scope_summary,
                bg.expires_at,
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
            self._notify_execution_started(execution)
            self._observe_breakglass(execution, claim_token)

        cancellation_event = threading.Event()
        heartbeat = _HeartbeatThread(
            self._client,
            execution_id,
            claim_token,
            cancellation_event=cancellation_event,
        )
        heartbeat.start()
        uploader = self._make_uploader(execution_id, claim_token)

        outcome = "succeeded"
        try:
            for step in sorted(execution.steps, key=lambda s: s.position):
                if cancellation_event.is_set():
                    logger.info(
                        "Execution %s: cancellation requested before step %d '%s' — stopping",
                        execution_id,
                        step.position,
                        step.name,
                    )
                    outcome = "cancelled"
                    break
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
                    execution,
                    claim_token,
                    step,
                    heartbeat,
                    uploader,
                    cancellation_event,
                )
                if step_failed:
                    outcome = "failed"
                    break
            if outcome == "failed" and cancellation_event.is_set():
                outcome = "cancelled"
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

        if execution.is_change_bound:
            self._notify_execution_finished(execution)

    def _notify_execution_started(self, execution: ClaimedExecution) -> None:
        """POST execution-started to Django. Non-fatal on error."""
        try:
            self._client.execution_started(
                execution.change_record_id,
                execution.id,
                observed_at=_utcnow(),
            )
            logger.info(
                "execution-started notified for change %s / execution %s",
                execution.change_record_id,
                execution.id,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "execution-started callback failed for change %s / execution %s: %s",
                execution.change_record_id,
                execution.id,
                exc,
            )

    def _notify_execution_finished(self, execution: ClaimedExecution) -> None:
        """POST execution-finished to Django. Non-fatal on error."""
        try:
            self._client.execution_finished(
                execution.change_record_id,
                execution.id,
                observed_at=_utcnow(),
            )
            logger.info(
                "execution-finished notified for change %s / execution %s",
                execution.change_record_id,
                execution.id,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "execution-finished callback failed for change %s / execution %s: %s",
                execution.change_record_id,
                execution.id,
                exc,
            )

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
        execution: ClaimedExecution,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        uploader: ArtifactUploader,
        cancellation_event: threading.Event,
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
            start_resp = self._client.start_step(execution.id, step.id, claim_token)
        except httpx.HTTPError as exc:
            logger.error("Failed to start step %s: %s", step.id, exc)
            return True

        if start_resp.runner_action == "run":
            logger.info(
                "Step %d '%s': approved to run immediately", step.position, step.name
            )
            heartbeat.set_observed_status("running")
            return self._execute_command(
                execution, claim_token, step, heartbeat, uploader, cancellation_event
            )

        if start_resp.runner_action == "wait_for_approval":
            logger.info("Step %d '%s': waiting for approval", step.position, step.name)
            return self._wait_for_approval(
                execution,
                claim_token,
                step,
                heartbeat,
                start_resp,
                uploader,
                cancellation_event,
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
        execution: ClaimedExecution,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        start_resp,
        uploader: ArtifactUploader,
        cancellation_event: threading.Event,
    ) -> bool:
        """Poll Django until the approval is decided. Returns True if step failed."""
        poll_interval = (
            start_resp.poll_after_seconds
            if start_resp.poll_after_seconds > 0
            else _APPROVAL_POLL_INTERVAL_SECONDS
        )

        while True:
            time.sleep(poll_interval)

            if cancellation_event.is_set():
                logger.info(
                    "Step %d '%s': cancellation received while waiting for approval — aborting",
                    step.position,
                    step.name,
                )
                return True

            try:
                status_resp = self._client.get_step_approval_status(
                    execution.id, step.id, claim_token
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
                    execution,
                    claim_token,
                    step,
                    heartbeat,
                    uploader,
                    cancellation_event,
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
        execution: ClaimedExecution,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        uploader: ArtifactUploader,
        cancellation_event: threading.Event,
    ) -> bool:
        """Dispatch to sandboxed or simulated execution based on settings."""
        if self._settings is not None and self._settings.execution_mode == "sandboxed":
            return self._execute_sandboxed(
                execution, claim_token, step, heartbeat, uploader, cancellation_event
            )
        return self._execute_simulated(
            execution, claim_token, step, heartbeat, uploader
        )

    def _execute_simulated(
        self,
        execution: ClaimedExecution,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        uploader: ArtifactUploader,
    ) -> bool:
        """
        Simulate step execution (test fixture behavior only — not for production use).
        Returns True if the step failed, False if it succeeded.

        Artifacts are uploaded BEFORE the terminal step status is reported so
        that evidence is preserved even if the runner crashes after uploading.
        """
        started_at = _utcnow()

        # Deliberate failure marker — test fixture only
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
            artifacts = self._upload_step_outputs(
                uploader, step, stdout_content, stderr_content
            )
            try:
                self._client.update_step(
                    execution.id,
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
            else:
                self._emit_step_verification_facts(
                    execution=execution,
                    claim_token=claim_token,
                    step=step,
                    outcome="failed",
                    exit_code=1,
                    artifacts=artifacts,
                )
            return True

        # Happy path: brief placeholder work, then succeed
        time.sleep(0.5)
        finished_at = _utcnow()
        stdout_content = f"Step '{step.name}' executed successfully.\n".encode()
        stderr_content = b""
        artifacts = self._upload_step_outputs(
            uploader, step, stdout_content, stderr_content
        )

        try:
            self._client.update_step(
                execution.id,
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

        self._emit_step_verification_facts(
            execution=execution,
            claim_token=claim_token,
            step=step,
            outcome="passed",
            exit_code=0,
            artifacts=artifacts,
        )
        return False

    @staticmethod
    def _build_sandbox_env(settings: RunnerSettings) -> dict[str, str]:
        """Build the subprocess environment from allowed names/prefixes in settings."""
        import os

        allowed_names = set(settings.sandbox_allowed_env_names)
        allowed_prefixes = tuple(settings.sandbox_allowed_env_prefixes)
        return {
            k: v
            for k, v in os.environ.items()
            if k in allowed_names
            or (allowed_prefixes and k.startswith(allowed_prefixes))
        }

    def _execute_sandboxed(
        self,
        execution: ClaimedExecution,
        claim_token: UUID,
        step: ClaimedStep,
        heartbeat: _HeartbeatThread,
        uploader: ArtifactUploader,
        cancellation_event: threading.Event,
    ) -> bool:
        """Execute step via the configured sandbox provider. Returns True if failed."""
        settings = self._settings
        assert settings is not None  # only called when execution_mode == "sandboxed"

        if step.step_type not in _SUPPORTED_SANDBOX_STEP_TYPES:
            logger.error(
                "Step %d '%s': step_type=%r is not supported in sandboxed mode — failing closed",
                step.position,
                step.name,
                step.step_type,
            )
            try:
                self._client.update_step(
                    execution.id,
                    step.id,
                    claim_token,
                    status="failed",
                    error_message=(
                        f"Unsupported step_type {step.step_type!r}"
                        " for sandboxed execution."
                    ),
                    failure_kind="unsupported_step_type",
                )
            except httpx.HTTPError as exc:
                logger.error("Failed to mark step %s failed: %s", step.id, exc)
            return True

        wm = WorkspaceManager(Path(settings.sandbox_workspace_root))
        ws_path = wm.build_workspace_path(
            execution.id, step.position, step.step_key, step.id
        )

        # Use workflow-declared timeout when present; clamp to runner default max.
        timeout_seconds = settings.sandbox_default_timeout_seconds
        raw_timeout = (
            step.step_snapshot.get("timeoutSeconds") if step.step_snapshot else None
        )
        if isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
            timeout_seconds = min(
                int(raw_timeout), settings.sandbox_default_timeout_seconds
            )

        limits = SandboxLimits(
            timeout_seconds=timeout_seconds,
            stdout_max_bytes=settings.sandbox_stdout_max_bytes,
            stderr_max_bytes=settings.sandbox_stderr_max_bytes,
            artifact_max_bytes=settings.sandbox_artifact_max_bytes,
            max_artifacts=settings.sandbox_max_artifacts_per_step,
        )
        spec = SandboxExecutionSpec(
            execution_id=execution.id,
            step_id=step.id,
            step_key=step.step_key,
            step_type=step.step_type,
            command=[step.command],
            display_command=step.command,
            workspace_root=ws_path,
            environment=self._build_sandbox_env(settings),
            limits=limits,
        )

        provider = get_provider(settings.sandbox_provider)

        try:
            provider.validate(spec)
        except SandboxValidationError as exc:
            logger.error(
                "Step %d '%s': sandbox validation failed: %s",
                step.position,
                step.name,
                exc,
            )
            try:
                self._client.update_step(
                    execution.id,
                    step.id,
                    claim_token,
                    status="failed",
                    error_message=str(exc),
                    failure_kind="validation_error",
                )
            except httpx.HTTPError as http_exc:
                logger.error("Failed to mark step %s failed: %s", step.id, http_exc)
            return True

        result = None
        try:
            result = provider.execute(spec, cancellation_event)
        except SandboxError as exc:
            logger.error(
                "Step %d '%s': sandbox infrastructure error: %s",
                step.position,
                step.name,
                exc,
            )
            try:
                self._client.update_step(
                    execution.id,
                    step.id,
                    claim_token,
                    status="failed",
                    error_message=str(exc),
                    failure_kind="sandbox_error",
                )
            except httpx.HTTPError as http_exc:
                logger.error("Failed to mark step %s failed: %s", step.id, http_exc)
            provider.cleanup(spec, None)
            return True

        # Determine outcome
        if result.timed_out:
            step_status = "failed"
            failure_kind = "timeout"
            error_message = (
                result.error_message or f"Step timed out after {timeout_seconds}s"
            )
        elif result.cancelled:
            step_status = "failed"
            failure_kind = "cancelled"
            error_message = result.error_message or "Step was cancelled"
        elif result.failure_kind:
            step_status = "failed"
            failure_kind = result.failure_kind
            error_message = result.error_message
        elif result.exit_code is not None and result.exit_code != 0:
            step_status = "failed"
            failure_kind = ""
            error_message = f"Command exited with code {result.exit_code}"
        else:
            step_status = "succeeded"
            failure_kind = ""
            error_message = ""

        step_failed = step_status == "failed"
        exit_code = result.exit_code

        # Upload stdout/stderr BEFORE terminal step update
        artifacts = self._upload_step_outputs(
            uploader, step, result.stdout.content, result.stderr.content
        )
        # Upload declared file artifacts BEFORE terminal step update
        for collected in result.artifacts:
            file_result = uploader.upload_file(
                step.id,
                collected,
                sandbox_provider=result.provider,
                sandbox_run_id=result.sandbox_run_id,
                step_key=step.step_key,
            )
            if file_result is None:
                logger.warning(
                    "File artifact upload failed for step %s: %s",
                    step.id,
                    collected.spec.name,
                )
            else:
                artifacts.append(file_result)

        # Cleanup workspace per policy
        cleanup_policy = settings.sandbox_cleanup_policy
        if cleanup_policy == "always" or (
            cleanup_policy == "on_success" and not step_failed
        ):
            provider.cleanup(spec, result)

        # Report terminal step update
        try:
            self._client.update_step(
                execution.id,
                step.id,
                claim_token,
                status=step_status,
                started_at=result.started_at,
                finished_at=result.finished_at,
                exit_code=exit_code,
                error_message=error_message,
                failure_kind=failure_kind,
                timed_out=result.timed_out,
                cancelled=result.cancelled,
                sandbox_provider=result.provider,
                sandbox_run_id=result.sandbox_run_id,
            )
            if step_failed:
                logger.info(
                    "Step %d '%s': failed (failure_kind=%s, exit_code=%s)",
                    step.position,
                    step.name,
                    failure_kind,
                    exit_code,
                )
            else:
                logger.info("Step %d '%s': succeeded", step.position, step.name)
        except httpx.HTTPError as exc:
            logger.error("Failed to mark step %s %s: %s", step.id, step_status, exc)
            return True

        self._emit_step_verification_facts(
            execution=execution,
            claim_token=claim_token,
            step=step,
            outcome="passed" if not step_failed else "failed",
            exit_code=exit_code
            if exit_code is not None
            else (0 if not step_failed else 1),
            artifacts=artifacts,
        )
        return step_failed

    def _upload_step_outputs(
        self,
        uploader: ArtifactUploader,
        step: ClaimedStep,
        stdout: bytes,
        stderr: bytes,
    ) -> list[ArtifactUploadResponse]:
        """Upload stdout and stderr artifacts. Failures are logged but do not affect step outcome."""
        artifacts: list[ArtifactUploadResponse] = []
        if stdout:
            result = uploader.upload_stdout(step.id, stdout)
            if result is None:
                logger.warning("stdout artifact upload failed for step %s", step.id)
            else:
                artifacts.append(result)
        if stderr:
            result = uploader.upload_stderr(step.id, stderr)
            if result is None:
                logger.warning("stderr artifact upload failed for step %s", step.id)
            else:
                artifacts.append(result)
        return artifacts

    def _emit_step_verification_facts(
        self,
        *,
        execution: ClaimedExecution,
        claim_token: UUID,
        step: ClaimedStep,
        outcome: str,
        exit_code: int,
        artifacts: list[ArtifactUploadResponse],
    ) -> None:
        if not execution.is_change_bound or execution.change_record_id is None:
            return

        matching_keys = [
            item
            for item in execution.verification_keys
            if item.step_key and item.step_key == step.step_key
        ]
        if not matching_keys:
            return

        artifact_ids = [artifact.id for artifact in artifacts]
        artifact_checksums = {
            str(artifact.id): artifact.checksum_sha256 for artifact in artifacts
        }
        for item in matching_keys:
            try:
                response = self._client.submit_verification_result(
                    execution.change_record_id,
                    execution.id,
                    claim_token,
                    check_key=item.check_key,
                    outcome=outcome,
                    verification_key=item.verification_key,
                    step_key=step.step_key,
                    artifact_ids=artifact_ids,
                    artifact_checksums=artifact_checksums,
                    observed_value={
                        "status": outcome,
                        "exit_code": exit_code,
                        "source_step_key": step.step_key,
                    },
                    metadata={"check_type": item.check_type},
                )
                logger.info(
                    "verification fact submitted for change %s check %s: %s",
                    execution.change_record_id,
                    item.check_key,
                    response.validation_status,
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "verification fact callback failed for change %s check %s: %s",
                    execution.change_record_id,
                    item.check_key,
                    exc,
                )
