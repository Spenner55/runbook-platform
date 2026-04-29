"""Thin HTTP client for the Django internal runner API."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx

from runner.schemas import (
    ApprovalStatusRequest,
    ApprovalStatusResponse,
    ArtifactUploadResponse,
    ClaimNextRequest,
    ClaimNextResponse,
    CompleteExecutionRequest,
    CompleteExecutionResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    StepStartRequest,
    StepStartResponse,
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
        runner_token: str,
        runner_version: str = "0.1.0",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._runner_id = runner_id
        self._auth_headers = {"Authorization": f"Bearer {runner_token}"}
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
        response = self._http.post(url, json=payload, headers=self._auth_headers)
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
        url = (
            f"{self._base}/api/v1/internal/executions/{execution_id}"
            f"/steps/{step_id}/artifacts/"
        )
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
        timeout = httpx.Timeout(30.0)
        response = self._http.post(
            url,
            data=fields,
            files=files,
            headers=self._auth_headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return ArtifactUploadResponse.model_validate(response.json())

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()
