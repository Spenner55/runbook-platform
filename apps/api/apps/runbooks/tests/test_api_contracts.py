import pytest
from django.test import Client

from apps.runbooks import services


@pytest.mark.django_db
def test_create_runbook_returns_201(org):
    client = Client()
    payload = {
        "organization_id": str(org.id),
        "title": "Deploy Service",
        "slug": "deploy-service",
        "raw_content": "## Steps",
    }
    response = client.post(
        "/api/v1/runbooks/",
        data=payload,
        content_type="application/json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "deploy-service"
    assert body["status"] == "draft"
    assert "id" in body


@pytest.mark.django_db
def test_create_runbook_missing_title_returns_400_with_envelope(org):
    client = Client()
    payload = {
        "organization_id": str(org.id),
        "slug": "no-title",
    }
    response = client.post(
        "/api/v1/runbooks/",
        data=payload,
        content_type="application/json",
    )
    assert response.status_code == 400
    body = response.json()
    assert "errors" in body
    attrs = [e["attr"] for e in body["errors"]]
    assert "title" in attrs


@pytest.mark.django_db
def test_create_runbook_invalid_org_returns_404():
    client = Client()
    payload = {
        "organization_id": "00000000-0000-0000-0000-000000000000",
        "title": "Ghost Runbook",
        "slug": "ghost",
    }
    response = client.post(
        "/api/v1/runbooks/",
        data=payload,
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_create_runbook_slug_conflict_returns_409_with_envelope(org):
    services.create_runbook(organization=org, title="First", slug="conflict-slug", raw_content="")
    client = Client()
    payload = {
        "organization_id": str(org.id),
        "title": "Second",
        "slug": "conflict-slug",
    }
    response = client.post(
        "/api/v1/runbooks/",
        data=payload,
        content_type="application/json",
    )
    assert response.status_code == 409
    body = response.json()
    assert "errors" in body
    error = body["errors"][0]
    assert error["code"] == "runbook_slug_conflict"
    assert error["attr"] == "slug"
