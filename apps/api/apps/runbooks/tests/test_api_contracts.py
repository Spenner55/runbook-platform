import pytest
from django.test import Client


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
def test_create_runbook_missing_title_returns_400(org):
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
    assert "title" in response.json()


@pytest.mark.django_db
def test_create_runbook_invalid_org_returns_400():
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
    assert response.status_code == 400
