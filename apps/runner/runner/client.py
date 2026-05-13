"""Thin HTTP client for the Django internal runner API."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from runner.schemas import (
    ApprovalStatusRequest,
    ApprovalStatusResponse,
    ArtifactUploadResponse,
    BindChangeExecutionRequest,
    BindChangeExecutionResponse,
    BreakglassHeartbeatRequest,
    BreakglassHeartbeatResponse,
    ClaimNextRequest,
    ClaimNextResponse,
    CompleteExecutionRequest,
    CompleteExecutionResponse,
    ExecutionFinishedResponse,
    ExecutionStartedResponse,
    ExecutionTimingCallbackRequest,
    HeartbeatRequest,
    HeartbeatResponse,
    StepStartRequest,
    StepStartResponse,
    StepUpdateRequest,
    StepUpdateResponse,
    VerificationResultRequest,
    VerificationResultResponse,
)

logger = logging.getLogger(__name__)

RUNNER_API_TIMEOUT = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=2.0)
ARTIFACT_UPLOAD_TIMEOUT = httpx.Timeout(
    connect=2.0,
    read=60.0,
    write=60.0,
    pool=2.0,
)
RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0)
_RETRYABLE_STATUS_CODES = {502, 503, 504}
_RetrySleep = Callable[[float], bool | None]


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ApiClient:
    def __init__(
        self,
        base_url: str,
        runner_id: str,
        runner_token: str,
        runner_version: str = "0.1.0",
        http_client: httpx.Client | None = None,
        api_retries_enabled: bool = True,
        retry_sleep: _RetrySleep | None = None,
        registered_runner_id: str = "",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._runner_id = registered_runner_id if registered_runner_id else runner_id
        self._auth_headers = {"Authorization": f"Bearer {runner_token}"}
        self._runner_version = runner_version
        self._api_retries_enabled = api_retries_enabled
        self._retry_sleep = retry_sleep or time.sleep
        self._owns_http_client = http_client is None
        self._http = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=RUNNER_API_TIMEOUT)
        )

    @property
    def runner_id(self) -> str:
        return self._runner_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request_headers(self, request_id: str) -> dict[str, str]:
        """Build per-request headers: auth, runner identity, and a fresh request ID."""
        return {
            **self._auth_headers,
            "X-Runner-ID": self._runner_id,
            "X-Request-ID": request_id,
        }

    def _retry_delays(self) -> tuple[float, ...]:
        if not self._api_retries_enabled:
            return ()
        return RETRY_DELAYS_SECONDS

    def _log_retry(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        attempt: int,
        delay: float,
        status_code: int | None = None,
        exception: Exception | None = None,
    ) -> None:
        logger.warning(
            "runner_api_request_retrying",
            extra={
                "request_id": request_id,
                "runner_id": self._runner_id,
                "runner_version": self._runner_version,
                "method": method,
                "path": path,
                "attempt": attempt,
                "delay_seconds": delay,
                "status_code": status_code,
                "exception_type": type(exception).__name__ if exception else "",
                "exception_message": str(exception) if exception else "",
            },
        )

    def _sleep_before_retry(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        attempt: int,
        delay: float,
    ) -> bool:
        interrupted = bool(self._retry_sleep(delay))
        if interrupted:
            logger.info(
                "runner_api_retry_sleep_interrupted",
                extra={
                    "request_id": request_id,
                    "runner_id": self._runner_id,
                    "runner_version": self._runner_version,
                    "method": method,
                    "path": path,
                    "attempt": attempt,
                    "delay_seconds": delay,
                },
            )
        return interrupted

    def _post_response(
        self,
        path: str,
        *,
        request_id: str,
        timeout: httpx.Timeout,
        retry_enabled: bool,
        **kwargs,
    ) -> httpx.Response:
        url = f"{self._base}{path}"
        method = "POST"
        retry_delays = self._retry_delays() if retry_enabled else ()
        max_attempts = len(retry_delays) + 1

        for attempt in range(1, max_attempts + 1):
            started = time.monotonic()
            status_code = None
            try:
                response = self._http.post(
                    url,
                    headers=self._request_headers(request_id),
                    timeout=timeout,
                    **kwargs,
                )
                status_code = response.status_code
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if (
                    status_code not in _RETRYABLE_STATUS_CODES
                    or attempt >= max_attempts
                ):
                    raise
                delay = retry_delays[attempt - 1]
                self._log_retry(
                    request_id=request_id,
                    method=method,
                    path=path,
                    attempt=attempt,
                    delay=delay,
                    status_code=status_code,
                )
                if self._sleep_before_retry(
                    request_id=request_id,
                    method=method,
                    path=path,
                    attempt=attempt,
                    delay=delay,
                ):
                    raise
            except httpx.TransportError as exc:
                if attempt >= max_attempts:
                    raise
                delay = retry_delays[attempt - 1]
                self._log_retry(
                    request_id=request_id,
                    method=method,
                    path=path,
                    attempt=attempt,
                    delay=delay,
                    exception=exc,
                )
                if self._sleep_before_retry(
                    request_id=request_id,
                    method=method,
                    path=path,
                    attempt=attempt,
                    delay=delay,
                ):
                    raise
            finally:
                logger.info(
                    "runner_api_request_completed",
                    extra={
                        "request_id": request_id,
                        "runner_id": self._runner_id,
                        "runner_version": self._runner_version,
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "status_code": status_code,
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    },
                )

        raise RuntimeError("unreachable retry loop exit")

    def _post(self, path: str, payload: dict) -> dict:
        request_id = str(uuid4())
        response = self._post_response(
            path,
            request_id=request_id,
            timeout=RUNNER_API_TIMEOUT,
            retry_enabled=True,
            json=payload,
        )
        return response.json()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def register(
        self,
        display_name: str,
        fingerprint_sha256: str,
        hostname: str,
        labels: dict | None = None,
        capabilities: list | None = None,
    ) -> dict:
        """Call POST /api/v1/internal/runners/register/ with the registration token."""
        data = self._post(
            "/api/v1/internal/runners/register/",
            {
                "registration_token": self._auth_headers["Authorization"].split(" ", 1)[1],
                "display_name": display_name,
                "runner_version": self._runner_version,
                "fingerprint_sha256": fingerprint_sha256,
                "hostname": hostname,
                "labels": labels or {},
                "capabilities": capabilities or [],
            },
        )
        return data

    def runner_heartbeat(
        self,
        runner_version: str = "",
        hostname: str = "",
        current_execution_count: int = 0,
        observed_pool_key: str = "",
        capabilities_checksum: str = "",
    ) -> dict:
        """Call POST /api/v1/internal/runners/heartbeat/ with the per-runner bearer token."""
        data = self._post(
            "/api/v1/internal/runners/heartbeat/",
            {
                "runner_version": runner_version,
                "hostname": hostname,
                "current_execution_count": current_execution_count,
                "observed_pool_key": observed_pool_key,
                "capabilities_checksum": capabilities_checksum,
                "sent_at": _utcnow().isoformat(),
            },
        )
        return data

    def claim_next(self) -> ClaimNextResponse:
        data = self._post(
            "/api/v1/internal/executions/claim-next/",
            ClaimNextRequest(
                runner_id=self._runner_id,
                runner_version=self._runner_version,
                requested_at=_utcnow(),
            ).model_dump(mode="json"),
        )
        return ClaimNextResponse.model_validate(data)

    def heartbeat(
        self,
        execution_id: UUID,
        claim_token: UUID,
        observed_status: str = "claimed",
    ) -> HeartbeatResponse:
        data = self._post(
            f"/api/v1/internal/executions/{execution_id}/heartbeat/",
            HeartbeatRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                observed_status=observed_status,  # type: ignore[arg-type]
                sent_at=_utcnow(),
            ).model_dump(mode="json"),
        )
        return HeartbeatResponse.model_validate(data)

    def update_step(
        self,
        execution_id: UUID,
        step_id: UUID,
        claim_token: UUID,
        *,
        status: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        exit_code: int | None = None,
        error_message: str = "",
        failure_kind: str = "",
        timed_out: bool = False,
        cancelled: bool = False,
        sandbox_provider: str = "",
        sandbox_run_id: str = "",
    ) -> StepUpdateResponse:
        data = self._post(
            f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/update/",
            StepUpdateRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                status=status,  # type: ignore[arg-type]
                started_at=started_at,
                finished_at=finished_at,
                exit_code=exit_code,
                error_message=error_message,
                failure_kind=failure_kind,
                timed_out=timed_out,
                cancelled=cancelled,
                sandbox_provider=sandbox_provider,
                sandbox_run_id=sandbox_run_id,
            ).model_dump(mode="json"),
        )
        return StepUpdateResponse.model_validate(data)

    def start_step(
        self,
        execution_id: UUID,
        step_id: UUID,
        claim_token: UUID,
    ) -> StepStartResponse:
        data = self._post(
            f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/start/",
            StepStartRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                sent_at=_utcnow(),
            ).model_dump(mode="json"),
        )
        return StepStartResponse.model_validate(data)

    def get_step_approval_status(
        self,
        execution_id: UUID,
        step_id: UUID,
        claim_token: UUID,
    ) -> ApprovalStatusResponse:
        data = self._post(
            f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/approval-status/",
            ApprovalStatusRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                sent_at=_utcnow(),
            ).model_dump(mode="json"),
        )
        return ApprovalStatusResponse.model_validate(data)

    def complete_execution(
        self,
        execution_id: UUID,
        claim_token: UUID,
        final_status: str,
        error_message: str = "",
    ) -> CompleteExecutionResponse:
        data = self._post(
            f"/api/v1/internal/executions/{execution_id}/complete/",
            CompleteExecutionRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                final_status=final_status,  # type: ignore[arg-type]
                finished_at=_utcnow(),
                error_message=error_message,
            ).model_dump(mode="json"),
        )
        return CompleteExecutionResponse.model_validate(data)

    def bind_change_execution(
        self,
        change_record_id: UUID,
        execution_id: UUID,
        claim_token: UUID,
        dispatch_token: str,
        requested_inputs_sha256: str,
        operation_profile_key: str,
    ) -> BindChangeExecutionResponse:
        data = self._post(
            f"/api/v1/internal/changes/{change_record_id}/bind-execution/",
            BindChangeExecutionRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                execution_id=execution_id,
                dispatch_token=dispatch_token,
                requested_inputs_sha256=requested_inputs_sha256,
                operation_profile_key=operation_profile_key,
                sent_at=_utcnow(),
            ).model_dump(mode="json"),
        )
        return BindChangeExecutionResponse.model_validate(data)

    def execution_started(
        self,
        change_record_id: UUID,
        execution_id: UUID,
        *,
        observed_at: datetime | None = None,
    ) -> ExecutionStartedResponse:
        data = self._post(
            f"/api/v1/internal/changes/{change_record_id}/execution-started/",
            ExecutionTimingCallbackRequest(
                runner_id=self._runner_id,
                execution_id=execution_id,
                observed_at=observed_at,
            ).model_dump(mode="json"),
        )
        return ExecutionStartedResponse.model_validate(data)

    def execution_finished(
        self,
        change_record_id: UUID,
        execution_id: UUID,
        *,
        observed_at: datetime | None = None,
    ) -> ExecutionFinishedResponse:
        data = self._post(
            f"/api/v1/internal/changes/{change_record_id}/execution-finished/",
            ExecutionTimingCallbackRequest(
                runner_id=self._runner_id,
                execution_id=execution_id,
                observed_at=observed_at,
            ).model_dump(mode="json"),
        )
        return ExecutionFinishedResponse.model_validate(data)

    def breakglass_heartbeat(
        self,
        change_record_id: UUID,
        claim_token: UUID,
        breakglass_session_id: UUID,
        scope_sha256: str,
    ) -> BreakglassHeartbeatResponse | None:
        """
        Report a breakglass session observation to Django.  Non-fatal on error.
        Returns the response or None if the call fails.
        """
        try:
            data = self._post(
                f"/api/v1/internal/changes/{change_record_id}/breakglass-heartbeat/",
                BreakglassHeartbeatRequest(
                    runner_id=self._runner_id,
                    claim_token=claim_token,
                    breakglass_session_id=breakglass_session_id,
                    scope_sha256=scope_sha256,
                    observed_at=_utcnow(),
                ).model_dump(mode="json"),
            )
            return BreakglassHeartbeatResponse.model_validate(data)
        except Exception as exc:
            logger.warning(
                "breakglass_heartbeat failed for change %s session %s: %s",
                change_record_id,
                breakglass_session_id,
                exc,
            )
            return None

    def submit_verification_result(
        self,
        change_record_id: UUID,
        execution_id: UUID,
        claim_token: UUID,
        *,
        check_key: str,
        outcome: str,
        verification_key: str = "",
        step_key: str = "",
        artifact_ids: list[UUID] | None = None,
        artifact_checksums: dict[str, str] | None = None,
        observed_value: dict | None = None,
        metadata: dict | None = None,
    ) -> VerificationResultResponse:
        data = self._post(
            f"/api/v1/internal/changes/{change_record_id}/verification-results/",
            VerificationResultRequest(
                runner_id=self._runner_id,
                claim_token=claim_token,
                execution_id=execution_id,
                check_key=check_key,
                verification_key=verification_key,
                outcome=outcome,  # type: ignore[arg-type]
                step_key=step_key,
                artifact_ids=artifact_ids or [],
                artifact_checksums=artifact_checksums or {},
                observed_value=observed_value or {},
                metadata=metadata or {},
                sent_at=_utcnow(),
            ).model_dump(mode="json"),
        )
        return VerificationResultResponse.model_validate(data)

    def upload_artifact(
        self,
        execution_id: UUID,
        step_id: UUID,
        claim_token: UUID,
        *,
        kind: str,
        name: str,
        file_obj,
        mime_type: str = "",
        checksum_sha256: str = "",
        metadata: dict | None = None,
    ) -> ArtifactUploadResponse:
        fields = {
            "runner_id": self._runner_id,
            "claim_token": str(claim_token),
            "kind": kind,
            "name": name,
            "mime_type": mime_type,
            "checksum_sha256": checksum_sha256,
            "metadata": json.dumps(metadata or {}),
        }
        files = {"file": (name, file_obj, mime_type or "application/octet-stream")}
        request_id = str(uuid4())
        path = f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/"
        response = self._post_response(
            path,
            request_id=request_id,
            timeout=ARTIFACT_UPLOAD_TIMEOUT,
            retry_enabled=False,
            data=fields,
            files=files,
        )
        return ArtifactUploadResponse.model_validate(response.json())

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()
