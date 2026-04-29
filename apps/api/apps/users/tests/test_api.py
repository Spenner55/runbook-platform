import pytest
from rest_framework.test import APIClient

from apps.users import services


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def user(db):
    return services.create_user(email="alice@example.com", password="s3cr3tpass!")


@pytest.mark.django_db
def test_login_success(client, user):
    resp = client.post("/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"})
    assert resp.status_code == 200
    assert "access" in resp.data
    assert resp.data["user"]["email"] == "alice@example.com"
    assert "refresh_token" in resp.cookies


@pytest.mark.django_db
def test_login_bad_credentials(client, user):
    resp = client.post("/api/v1/auth/login/", {"email": "alice@example.com", "password": "wrong!"})
    assert resp.status_code == 401


@pytest.mark.django_db
def test_refresh_success(client, user):
    login = client.post("/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"})
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
def test_logout(client, user):
    login = client.post("/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"})
    refresh_cookie = login.cookies["refresh_token"].value
    client.cookies["refresh_token"] = refresh_cookie
    resp = client.post("/api/v1/auth/logout/")
    assert resp.status_code == 204


@pytest.mark.django_db
def test_me_authenticated(client, user):
    login = client.post("/api/v1/auth/login/", {"email": "alice@example.com", "password": "s3cr3tpass!"})
    token = login.data["access"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert resp.data["email"] == "alice@example.com"


@pytest.mark.django_db
def test_me_unauthenticated(client):
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_register(client):
    resp = client.post(
        "/api/v1/auth/register/",
        {"email": "newuser@example.com", "password": "s3cur3pass!", "first_name": "New"},
    )
    assert resp.status_code == 201
    assert resp.data["user"]["email"] == "newuser@example.com"
    assert "access" in resp.data
    assert "refresh_token" in resp.cookies


@pytest.mark.django_db
def test_register_duplicate_email(client, user):
    resp = client.post(
        "/api/v1/auth/register/",
        {"email": "alice@example.com", "password": "s3cur3pass!"},
    )
    assert resp.status_code == 400
