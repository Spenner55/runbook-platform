"""Thin HTTP client for the Django internal runner API."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx

from runner.schemas import (
    ClaimNextRequest,
    ClaimNextResponse,
    CompleteExecutionRequest,
    CompleteExecutionResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    StepUpdateRequest,
    StepUpdateResponse,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(10.0)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ApiClient:
    def __init__(
        self,
        base_url: str,
        runner_id: str,
        runner_version: str = "0.1.0",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._runner_id = runner_id
        self._runner_version = runner_version
        self._owns_http_client = http_client is None
        self._http = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=_DEFAULT_TIMEOUT)
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base}{path}"
        response = self._http.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

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
            ).model_dump(mode="json"),
        )
        return StepUpdateResponse.model_validate(data)

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

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()
