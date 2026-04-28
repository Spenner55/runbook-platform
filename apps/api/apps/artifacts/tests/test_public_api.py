"""Tests for the public artifact listing and download URL APIs."""

import io

import pytest
from django.test import Client
from django.utils import timezone

from apps.artifacts import services as artifact_services
from apps.artifacts.models import Artifact
from apps.audit.models import AuditEvent


def _make_file(content: bytes, name: str = "stdout.txt"):
    f = io.BytesIO(content)
    f.name = name
    f.size = len(content)
    f.chunks = lambda: [content]
    return f


@pytest.fixture
def uploaded_artifact(org, claimed_execution, claim_token, step, artifact_media_root):
    return artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(b"hello world"),
    )


@pytest.mark.django_db
def test_execution_artifact_list_returns_results(
    claimed_execution, uploaded_artifact
):
    client = Client()
    response = client.get(f"/api/v1/executions/{claimed_execution.id}/artifacts/")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["kind"] == "stdout"
    assert result["name"] == "stdout.txt"
    assert "storage_key" not in result


@pytest.mark.django_db
def test_execution_artifact_list_empty(claimed_execution, artifact_media_root):
    client = Client()
    response = client.get(f"/api/v1/executions/{claimed_execution.id}/artifacts/")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["results"] == []


@pytest.mark.django_db
def test_execution_artifact_list_filter_by_kind(
    claimed_execution, claim_token, step, artifact_media_root
):
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stdout",
        name="stdout.txt",
        file_obj=_make_file(b"out"),
    )
    artifact_services.create_from_runner_upload(
        execution=claimed_execution,
        step=step,
        runner_id="runner-test",
        claim_token=claim_token,
        kind="stderr",
        name="stderr.txt",
        file_obj=_make_file(b"err"),
    )
    client = Client()
    response = client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/?kind=stdout"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["kind"] == "stdout"


@pytest.mark.django_db
def test_artifact_list_omits_storage_key(claimed_execution, uploaded_artifact):
    client = Client()
    response = client.get(f"/api/v1/executions/{claimed_execution.id}/artifacts/")
    body = response.json()
    for result in body["results"]:
        assert "storage_key" not in result


@pytest.mark.django_db
def test_download_url_endpoint_returns_url(claimed_execution, uploaded_artifact):
    client = Client()
    response = client.post(f"/api/v1/artifacts/{uploaded_artifact.id}/download/")
    assert response.status_code == 200
    body = response.json()
    assert "download_url" in body
    assert "expires_at" in body
    assert body["method"] == "GET"
    assert body["filename"] == "stdout.txt"
    assert "storage_key" not in body


@pytest.mark.django_db
def test_download_url_emits_audit_event(claimed_execution, uploaded_artifact):
    client = Client()
    client.post(f"/api/v1/artifacts/{uploaded_artifact.id}/download/")
    events = AuditEvent.objects.filter(
        event_type="artifact.download_url_created",
        object_id=uploaded_artifact.id,
    )
    assert events.count() == 1
    meta = events.first().metadata
    assert "expires_at" in meta
    assert "download_url" not in meta
    assert "storage_key" not in meta


@pytest.mark.django_db
def test_list_does_not_emit_audit_events(claimed_execution, uploaded_artifact):
    before = AuditEvent.objects.count()
    client = Client()
    client.get(f"/api/v1/executions/{claimed_execution.id}/artifacts/")
    after = AuditEvent.objects.count()
    assert after == before
