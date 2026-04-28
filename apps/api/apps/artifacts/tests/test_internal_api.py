"""Tests for the internal runner artifact upload API."""

import io

import pytest
from django.test import Client


def _upload_url(execution_id, step_id):
    return f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/"


def _make_multipart(
    runner_id,
    claim_token,
    kind="stdout",
    name="stdout.txt",
    content=b"output data",
    checksum_sha256="",
    metadata="{}",
    file_name="stdout.txt",
):
    return {
        "runner_id": runner_id,
        "claim_token": str(claim_token),
        "kind": kind,
        "name": name,
        "checksum_sha256": checksum_sha256,
        "metadata": metadata,
        "file": io.BytesIO(content),
    }


@pytest.mark.django_db
def test_upload_success_returns_201(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("runner-test", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "stdout"
    assert body["name"] == "stdout.txt"
    assert "storage_key" not in body
    assert "claim_token" not in body


@pytest.mark.django_db
def test_upload_missing_file_returns_400(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data={
            "runner_id": "runner-test",
            "claim_token": claim_token,
            "kind": "stdout",
            "name": "stdout.txt",
        },
        format="multipart",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_upload_invalid_claim_token_returns_409(
    claimed_execution, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("runner-test", "00000000-0000-0000-0000-000000000000")
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_upload_wrong_runner_id_returns_409(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("wrong-runner", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_upload_oversize_file_returns_413(
    claimed_execution, claim_token, step, artifact_media_root, settings
):
    settings.ARTIFACT_MAX_UPLOAD_BYTES = 5
    client = Client()
    data = _make_multipart("runner-test", claim_token, content=b"x" * 6)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 413


@pytest.mark.django_db
def test_upload_checksum_mismatch_returns_400(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("runner-test", claim_token, content=b"hello", checksum_sha256="a" * 64)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "checksum_mismatch"


@pytest.mark.django_db
def test_upload_invalid_kind_returns_400(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("runner-test", claim_token, kind="unknown-kind")
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_upload_response_omits_storage_key(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("runner-test", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 201
    body = response.json()
    assert "storage_key" not in body
