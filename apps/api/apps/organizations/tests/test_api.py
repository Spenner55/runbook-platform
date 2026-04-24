import pytest
from django.test import Client


@pytest.mark.django_db
def test_create_organization_returns_201():
    client = Client()
    response = client.post(
        "/api/v1/organizations/",
        data={"name": "Platform Ops", "slug": "platform-ops"},
        content_type="application/json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "platform-ops"
    assert body["name"] == "Platform Ops"
    assert "id" in body


@pytest.mark.django_db
def test_create_organization_missing_slug_returns_400():
    client = Client()
    response = client.post(
        "/api/v1/organizations/",
        data={"name": "No Slug"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_list_organizations_returns_200(org):
    client = Client()
    response = client.get("/api/v1/organizations/")
    assert response.status_code == 200
    ids = [o["id"] for o in response.json()]
    assert str(org.id) in ids


@pytest.mark.django_db
def test_retrieve_organization_returns_detail(org):
    client = Client()
    response = client.get(f"/api/v1/organizations/{org.id}/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(org.id)
    assert body["slug"] == org.slug
