"""
Artifact uploader for the runner.

Handles checksum computation, local size enforcement, bounded retry,
and delegation to ApiClient for the actual HTTP upload.

The runner never uploads to S3 directly — all artifacts go through Django.
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from pathlib import Path
from uuid import UUID

import httpx

from runner.client import ApiClient
from runner.sandbox.base import CollectedArtifact
from runner.schemas import ArtifactUploadResponse

logger = logging.getLogger(__name__)

_DEFAULT_MAX_BYTES = 52_428_800  # 50 MB, matches Django default
_STDOUT_STDERR_MAX_BYTES = 5_242_880  # 5 MB per stream
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 1.0
_UPLOAD_METHOD = "POST"


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _truncate_output(data: bytes, max_bytes: int) -> tuple[bytes, dict]:
    """Return (truncated_bytes, metadata). metadata includes truncation info if applied."""
    if len(data) <= max_bytes:
        return data, {"truncated": False}
    return data[:max_bytes], {
        "truncated": True,
        "original_size_bytes": len(data),
        "captured_size_bytes": max_bytes,
        "truncation_reason": "stream_limit",
    }


def _request_id_from_error(exc: httpx.HTTPError) -> str:
    request = getattr(exc, "_request", None)
    if request is None:
        return ""
    return request.headers.get("X-Request-ID", "")


class ArtifactUploader:
    """
    Uploads artifacts from a runner step to Django's internal API.

    Usage:
        uploader = ArtifactUploader(client, execution_id, claim_token)
        uploader.upload_stdout(step_id, stdout_bytes)
        uploader.upload_stderr(step_id, stderr_bytes)
    """

    def __init__(
        self,
        client: ApiClient,
        execution_id: UUID,
        claim_token: UUID,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        stdout_stderr_max_bytes: int = _STDOUT_STDERR_MAX_BYTES,
    ) -> None:
        self._client = client
        self._execution_id = execution_id
        self._claim_token = claim_token
        self._max_bytes = max_bytes
        self._stdout_stderr_max = stdout_stderr_max_bytes

    def upload_stdout(
        self, step_id: UUID, content: bytes
    ) -> ArtifactUploadResponse | None:
        return self._upload_stream(step_id, content, kind="stdout", name="stdout.txt")

    def upload_stderr(
        self, step_id: UUID, content: bytes
    ) -> ArtifactUploadResponse | None:
        return self._upload_stream(step_id, content, kind="stderr", name="stderr.txt")

    def upload_file(
        self,
        step_id: UUID,
        artifact: CollectedArtifact,
        *,
        sandbox_provider: str = "",
        sandbox_run_id: str = "",
        step_key: str = "",
        redaction_applied: bool = False,
        collection_status: str = "collected",
    ) -> ArtifactUploadResponse | None:
        """Upload a collected file artifact to Django.

        artifact_source_path in metadata is the relative path from the spec, not
        the absolute host path, so host filesystem layout is never exposed.
        """
        try:
            content = Path(artifact.absolute_path).read_bytes()
        except OSError as exc:
            logger.error(
                "Failed to read artifact file %s for step %s: %s",
                artifact.spec.path,
                step_id,
                exc,
            )
            return None

        truncated = len(content) > self._max_bytes
        if truncated:
            content = content[: self._max_bytes]

        metadata: dict = {
            "truncated": truncated,
            "redaction_applied": redaction_applied,
            "collection_status": collection_status,
            "artifact_source_path": artifact.spec.path,
        }
        if sandbox_provider:
            metadata["sandbox_provider"] = sandbox_provider
        if sandbox_run_id:
            metadata["sandbox_run_id"] = sandbox_run_id
        if step_key:
            metadata["step_key"] = step_key

        return self._upload_bytes(
            step_id,
            content,
            kind=artifact.spec.kind,
            name=artifact.spec.name,
            mime_type=artifact.spec.mime_type,
            metadata=metadata,
        )

    def _upload_stream(
        self,
        step_id: UUID,
        content: bytes,
        kind: str,
        name: str,
    ) -> ArtifactUploadResponse | None:
        content, metadata = _truncate_output(content, self._stdout_stderr_max)
        return self._upload_bytes(
            step_id, content, kind=kind, name=name, metadata=metadata
        )

    def _upload_bytes(
        self,
        step_id: UUID,
        content: bytes,
        *,
        kind: str,
        name: str,
        mime_type: str = "",
        metadata: dict | None = None,
    ) -> ArtifactUploadResponse | None:
        if len(content) > self._max_bytes:
            logger.warning(
                "Artifact %s for step %s exceeds max size (%d > %d bytes) — skipping upload",
                name,
                step_id,
                len(content),
                self._max_bytes,
            )
            return None

        checksum = _compute_sha256(content)
        path = (
            f"/api/v1/internal/executions/{self._execution_id}"
            f"/steps/{step_id}/artifacts/"
        )
        runner_id = getattr(self._client, "runner_id", "")
        if not isinstance(runner_id, str):
            runner_id = ""

        for attempt in range(1, _MAX_RETRIES + 1):
            file_obj = io.BytesIO(content)
            try:
                result = self._client.upload_artifact(
                    self._execution_id,
                    step_id,
                    self._claim_token,
                    kind=kind,
                    name=name,
                    file_obj=file_obj,
                    mime_type=mime_type,
                    checksum_sha256=checksum,
                    metadata=metadata or {},
                )
                logger.info(
                    "Uploaded artifact %s (%s, %d bytes) for step %s",
                    name,
                    kind,
                    len(content),
                    step_id,
                )
                return result
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    logger.error(
                        "Artifact upload %s rejected (status %d, attempt %d/%d) — not retrying",
                        name,
                        exc.response.status_code,
                        attempt,
                        _MAX_RETRIES,
                        extra={
                            "method": _UPLOAD_METHOD,
                            "path": path,
                            "attempt": attempt,
                            "delay_seconds": 0,
                            "status_code": exc.response.status_code,
                            "exception_type": "",
                            "exception_message": "",
                            "runner_id": runner_id,
                            "request_id": _request_id_from_error(exc),
                        },
                    )
                    return None
                logger.warning(
                    "Artifact upload %s server error (status %d, attempt %d/%d)",
                    name,
                    exc.response.status_code,
                    attempt,
                    _MAX_RETRIES,
                    extra={
                        "method": _UPLOAD_METHOD,
                        "path": path,
                        "attempt": attempt,
                        "delay_seconds": (
                            _RETRY_BACKOFF_SECONDS if attempt < _MAX_RETRIES else 0
                        ),
                        "status_code": exc.response.status_code,
                        "exception_type": "",
                        "exception_message": "",
                        "runner_id": runner_id,
                        "request_id": _request_id_from_error(exc),
                    },
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "Artifact upload %s network error (attempt %d/%d): %s",
                    name,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                    extra={
                        "method": _UPLOAD_METHOD,
                        "path": path,
                        "attempt": attempt,
                        "delay_seconds": (
                            _RETRY_BACKOFF_SECONDS if attempt < _MAX_RETRIES else 0
                        ),
                        "status_code": None,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "runner_id": runner_id,
                        "request_id": _request_id_from_error(exc),
                    },
                )

            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS)

        logger.error(
            "Artifact upload %s failed after %d attempts for step %s",
            name,
            _MAX_RETRIES,
            step_id,
        )
        return None
