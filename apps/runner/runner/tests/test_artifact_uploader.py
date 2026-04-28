"""Unit tests for ArtifactUploader."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest

from runner.artifact_uploader import ArtifactUploader, _compute_sha256, _truncate_output
from runner.schemas import ArtifactUploadResponse


EXECUTION_ID = uuid4()
STEP_ID = uuid4()
CLAIM_TOKEN = uuid4()


def _make_response(kind="stdout", name="stdout.txt", size_bytes=5):
    return ArtifactUploadResponse(
        id=uuid4(),
        execution_id=EXECUTION_ID,
        step_id=STEP_ID,
        kind=kind,
        name=name,
        mime_type="text/plain; charset=utf-8",
        size_bytes=size_bytes,
        checksum_sha256="a" * 64,
        uploaded_by_runner_id="runner-test",
    )


def _make_client(return_value=None, side_effect=None):
    client = MagicMock()
    if side_effect is not None:
        client.upload_artifact.side_effect = side_effect
    else:
        client.upload_artifact.return_value = return_value or _make_response()
    return client


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_compute_sha256():
    content = b"hello"
    expected = hashlib.sha256(content).hexdigest()
    assert _compute_sha256(content) == expected
    assert len(_compute_sha256(content)) == 64


def test_truncate_output_no_truncation():
    content = b"short"
    result, meta = _truncate_output(content, 100)
    assert result == content
    assert meta == {"truncated": False}


def test_truncate_output_truncates():
    content = b"x" * 20
    result, meta = _truncate_output(content, 10)
    assert len(result) == 10
    assert meta["truncated"] is True
    assert meta["original_size_bytes"] == 20
    assert meta["captured_size_bytes"] == 10
    assert meta["truncation_reason"] == "stream_limit"


# ---------------------------------------------------------------------------
# ArtifactUploader tests
# ---------------------------------------------------------------------------


def test_upload_stdout_success():
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    result = uploader.upload_stdout(STEP_ID, b"hello output")
    assert result is not None
    client.upload_artifact.assert_called_once()
    call_kwargs = client.upload_artifact.call_args
    assert call_kwargs.kwargs["kind"] == "stdout"
    assert call_kwargs.kwargs["name"] == "stdout.txt"


def test_upload_stderr_success():
    client = _make_client(_make_response(kind="stderr", name="stderr.txt"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    result = uploader.upload_stderr(STEP_ID, b"error output")
    assert result is not None
    assert client.upload_artifact.call_args.kwargs["kind"] == "stderr"


def test_upload_checksum_is_sent():
    content = b"data"
    expected_checksum = hashlib.sha256(content).hexdigest()
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    uploader.upload_stdout(STEP_ID, content)
    assert client.upload_artifact.call_args.kwargs["checksum_sha256"] == expected_checksum


def test_upload_skips_oversize_file():
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN, max_bytes=5)
    result = uploader._upload_bytes(STEP_ID, b"x" * 6, kind="stdout", name="big.txt")
    assert result is None
    client.upload_artifact.assert_not_called()


def test_upload_truncates_stdout():
    client = _make_client()
    uploader = ArtifactUploader(
        client, EXECUTION_ID, CLAIM_TOKEN, stdout_stderr_max_bytes=5
    )
    uploader.upload_stdout(STEP_ID, b"x" * 10)
    call_kwargs = client.upload_artifact.call_args.kwargs
    # metadata should contain truncation info
    assert call_kwargs["metadata"]["truncated"] is True


def test_no_retry_on_4xx():
    error = httpx.HTTPStatusError(
        "Bad request", request=MagicMock(), response=MagicMock(status_code=400)
    )
    client = _make_client(side_effect=error)
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    result = uploader.upload_stdout(STEP_ID, b"data")
    assert result is None
    assert client.upload_artifact.call_count == 1


def test_retries_on_5xx():
    success = _make_response()
    error = httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=MagicMock(status_code=503)
    )
    client = _make_client(side_effect=[error, success])
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    with patch("runner.artifact_uploader.time.sleep"):
        result = uploader.upload_stdout(STEP_ID, b"data")
    assert result is not None
    assert client.upload_artifact.call_count == 2


def test_retries_on_network_error():
    success = _make_response()
    client = _make_client(
        side_effect=[httpx.ConnectError("Connection refused"), success]
    )
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    with patch("runner.artifact_uploader.time.sleep"):
        result = uploader.upload_stdout(STEP_ID, b"data")
    assert result is not None
    assert client.upload_artifact.call_count == 2


def test_returns_none_after_max_retries():
    error = httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=MagicMock(status_code=503)
    )
    client = _make_client(side_effect=[error, error])
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    with patch("runner.artifact_uploader.time.sleep"):
        result = uploader.upload_stdout(STEP_ID, b"data")
    assert result is None
    assert client.upload_artifact.call_count == 2


def test_upload_uses_correct_api_path():
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    uploader.upload_stdout(STEP_ID, b"data")
    # Verify upload_artifact was called with the correct execution/step IDs
    args = client.upload_artifact.call_args.args
    assert args[0] == EXECUTION_ID
    assert args[1] == STEP_ID
    assert args[2] == CLAIM_TOKEN
