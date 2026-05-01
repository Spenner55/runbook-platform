import pytest
from django.core.cache import caches
from django.test import override_settings
from rest_framework.test import APIClient

from apps.organizations import services as organization_services
from apps.organizations.models import MembershipRole
from apps.users import services


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return services.create_user(email="alice@example.com", password="s3cr3tpass!")


@pytest.mark.django_db
def test_login_success(client, user):
    resp = client.post(
        "/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"}
    )
    assert resp.status_code == 200
    assert "access" in resp.data
    assert resp.data["user"]["email"] == "alice@example.com"
    assert "memberships" in resp.data["user"]
    assert "refresh_token" in resp.cookies
    assert resp.cookies["refresh_token"]["samesite"] == "Strict"


@pytest.mark.django_db
def test_login_bad_credentials(client, user):
    resp = client.post(
        "/api/v1/auth/login/", {"email": "alice@example.com", "password": "wrong!"}
    )
    assert resp.status_code == 401


@pytest.mark.django_db
@override_settings(RATELIMIT_ENABLE=True, AUTH_LOGIN_RATE_LIMIT="2/m")
def test_login_rate_limit_returns_429(client, user):
    caches["default"].clear()
    payload = {"email": "alice@example.com", "password": "wrong!"}

    assert client.post("/api/v1/auth/login/", payload).status_code == 401
    assert client.post("/api/v1/auth/login/", payload).status_code == 401
    resp = client.post("/api/v1/auth/login/", payload)

    assert resp.status_code == 429


@pytest.mark.django_db
def test_refresh_success(client, user):
    login = client.post(
        "/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"}
    )
    refresh_cookie = login.cookies["refresh_token"].value
    client.cookies["refresh_token"] = refresh_cookie
    resp = client.post("/api/v1/auth/refresh/")
    assert resp.status_code == 200
    assert "access" in resp.data


@pytest.mark.django_db
def test_refresh_missing_cookie(client):
    resp = client.post("/api/v1/auth/refresh/")
    assert resp.status_code == 401


@pytest.mark.django_db
@override_settings(RATELIMIT_ENABLE=True, AUTH_REFRESH_RATE_LIMIT="1/m")
def test_refresh_rate_limit_returns_429(client):
    caches["default"].clear()

    assert client.post("/api/v1/auth/refresh/").status_code == 401
    resp = client.post("/api/v1/auth/refresh/")

    assert resp.status_code == 429


@pytest.mark.django_db
def test_logout_requires_authentication(client):
    resp = client.post("/api/v1/auth/logout/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_logout(client, user):
    login = client.post(
        "/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"}
    )
    refresh_cookie = login.cookies["refresh_token"].value
    client.cookies["refresh_token"] = refresh_cookie
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    resp = client.post("/api/v1/auth/logout/")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_me_authenticated(client, user):
    org = organization_services.create_organization(name="Acme", slug="acme-auth")
    organization_services.create_membership(
        organization=org, user=user, role=MembershipRole.OPERATOR
    )
    login = client.post(
        "/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"}
    )
    token = login.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert resp.data["email"] == "alice@example.com"
    assert resp.data["active_organization_id"] == str(org.id)
    assert resp.data["memberships"] == [
        {
            "id": str(user.memberships.get().id),
            "role": MembershipRole.OPERATOR,
            "organization": {
                "id": str(org.id),
                "name": "Acme",
                "slug": "acme-auth",
            },
        }
    ]


@pytest.mark.django_db
def test_me_unauthenticated(client):
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_register_endpoint_is_not_exposed(client):
    resp = client.post("/api/v1/auth/register/", {})
    assert resp.status_code == 404
