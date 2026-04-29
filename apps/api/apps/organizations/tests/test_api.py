import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_create_organization_returns_201(user):
    client = APIClient()
    client.force_authenticate(user=user)
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
def test_create_organization_missing_slug_returns_400(user):
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/v1/organizations/",
        data={"name": "No Slug"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "errors" in response.json()


@pytest.mark.django_db
def test_list_organizations_returns_200(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.get("/api/v1/organizations/")
    assert response.status_code == 200
    ids = [o["id"] for o in response.json()]
    assert str(org.id) in ids


@pytest.mark.django_db
def test_retrieve_organization_returns_detail(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.get(f"/api/v1/organizations/{org.id}/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(org.id)
    assert body["slug"] == org.slug


@pytest.mark.django_db
def test_non_member_cannot_retrieve_organization(org, api_client_for_org):
    other_org = type(org).objects.create(name="Other Corp", slug="other-corp")
    client = api_client_for_org(other_org)

    ids = [o["id"] for o in client.get("/api/v1/organizations/").json()]
    assert str(org.id) not in ids
    assert client.get(f"/api/v1/organizations/{org.id}/").status_code == 404
