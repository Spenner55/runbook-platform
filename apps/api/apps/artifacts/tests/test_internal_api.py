"""Tests for the internal runner artifact upload API."""

import hashlib
import io

import pytest
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken


def _upload_url(execution_id, step_id):
    return f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/"


def _make_multipart(
    runner_id,
    claim_token,
    kind="stdout",
    name="stdout.txt",
    content=b"output data",
    checksum_sha256=None,
    metadata="{}",
    file_name="stdout.txt",
):
    if checksum_sha256 is None:
        checksum_sha256 = hashlib.sha256(content).hexdigest()
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    data = _make_multipart(
        "runner-test", claim_token, content=b"hello", checksum_sha256="a" * 64
    )
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
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
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    data = _make_multipart("runner-test", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 201
    body = response.json()
    assert "storage_key" not in body


@pytest.mark.django_db
def test_upload_invalid_metadata_json_returns_400(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    data = _make_multipart("runner-test", claim_token, metadata="{not-json")
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["attr"] == "metadata"


@pytest.mark.django_db
def test_upload_terminal_execution_returns_409(
    claimed_execution, claim_token, step, artifact_media_root
):
    claimed_execution.status = "succeeded"
    claimed_execution.save(update_fields=["status"])

    client = Client(HTTP_AUTHORIZATION="Bearer test-runner-token")
    data = _make_multipart("runner-test", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "artifact_execution_terminal"


@pytest.mark.django_db
def test_upload_without_runner_token_is_rejected(
    claimed_execution, claim_token, step, artifact_media_root
):
    client = Client()
    data = _make_multipart("runner-test", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_upload_with_user_jwt_is_rejected(
    user, claimed_execution, claim_token, step, artifact_media_root
):
    token = str(RefreshToken.for_user(user).access_token)
    client = Client(HTTP_AUTHORIZATION=f"Bearer {token}")
    data = _make_multipart("runner-test", claim_token)
    response = client.post(
        _upload_url(claimed_execution.id, step.id),
        data=data,
        format="multipart",
    )
    assert response.status_code == 403
