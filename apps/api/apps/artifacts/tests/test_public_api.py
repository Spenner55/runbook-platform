"""Tests for the public artifact listing and download URL APIs."""

import io
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.artifacts import services as artifact_services
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization


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
    org, claimed_execution, uploaded_artifact
):
    client = Client()
    response = client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(org.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["kind"] == "stdout"
    assert result["name"] == "stdout.txt"
    assert "storage_key" not in result


@pytest.mark.django_db
def test_execution_artifact_list_empty(org, claimed_execution, artifact_media_root):
    client = Client()
    response = client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(org.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["results"] == []


@pytest.mark.django_db
def test_execution_artifact_list_filter_by_kind(
    org, claimed_execution, claim_token, step, artifact_media_root
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
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(org.id), "kind": "stdout"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["kind"] == "stdout"


@pytest.mark.django_db
@pytest.mark.django_db
def test_execution_artifact_list_filter_by_step(
    org, claimed_execution, claim_token, step, artifact_media_root
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
    client = Client()
    response = client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(org.id), "step_id": str(step.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["step_id"] == str(step.id)


@pytest.mark.django_db
def test_execution_artifact_list_requires_organization(claimed_execution):
    client = Client()
    response = client.get(f"/api/v1/executions/{claimed_execution.id}/artifacts/")
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "artifact_organization_required"


@pytest.mark.django_db
def test_execution_artifact_list_rejects_cross_tenant(claimed_execution):
    other_org = Organization.objects.create(name="Other Org", slug="other-org")
    client = Client()
    response = client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(other_org.id)},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_artifact_list_omits_storage_key(org, claimed_execution, uploaded_artifact):
    client = Client()
    response = client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(org.id)},
    )
    body = response.json()
    for result in body["results"]:
        assert "storage_key" not in result


@pytest.mark.django_db
def test_download_url_endpoint_returns_url(org, claimed_execution, uploaded_artifact):
    client = Client()
    response = client.post(
        f"/api/v1/artifacts/{uploaded_artifact.id}/download/",
        data={"organization_id": str(org.id)},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert "download_url" in body
    assert "expires_at" in body
    assert body["method"] == "GET"
    assert body["filename"] == "stdout.txt"
    assert "storage_key" not in body
    assert "token=" in body["download_url"]
    assert f"organization_id={org.id}" in body["download_url"]


@pytest.mark.django_db
def test_download_url_emits_audit_event(org, claimed_execution, uploaded_artifact):
    client = Client()
    client.post(
        f"/api/v1/artifacts/{uploaded_artifact.id}/download/",
        data={"organization_id": str(org.id)},
        content_type="application/json",
    )
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
    client.get(
        f"/api/v1/executions/{claimed_execution.id}/artifacts/",
        {"organization_id": str(claimed_execution.organization_id)},
    )
    after = AuditEvent.objects.count()
    assert after == before


@pytest.mark.django_db
def test_content_endpoint_requires_download_token(org, uploaded_artifact):
    client = Client()
    response = client.get(
        f"/api/v1/artifacts/{uploaded_artifact.id}/content/",
        {"organization_id": str(org.id)},
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "artifact_download_token_required"


@pytest.mark.django_db
def test_download_grant_allows_content_access(org, uploaded_artifact):
    client = Client()
    response = client.post(
        f"/api/v1/artifacts/{uploaded_artifact.id}/download/",
        data={"organization_id": str(org.id)},
        content_type="application/json",
    )
    assert response.status_code == 200
    content_response = client.get(response.json()["download_url"])
    assert content_response.status_code == 200
    assert b"".join(content_response.streaming_content) == b"hello world"


@pytest.mark.django_db
def test_expired_download_grant_is_rejected(org, uploaded_artifact):
    expired_at = timezone.now() - timedelta(seconds=1)
    token = artifact_services.create_download_token(
        artifact=uploaded_artifact, expires_at=expired_at
    )
    client = Client()
    response = client.get(
        f"/api/v1/artifacts/{uploaded_artifact.id}/content/",
        {"organization_id": str(org.id), "token": token},
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "artifact_download_token_expired"


@pytest.mark.django_db
def test_download_request_rejects_cross_tenant(uploaded_artifact):
    other_org = Organization.objects.create(name="Other Org", slug="other-org")
    client = Client()
    response = client.post(
        f"/api/v1/artifacts/{uploaded_artifact.id}/download/",
        data={"organization_id": str(other_org.id)},
        content_type="application/json",
    )
    assert response.status_code == 404
