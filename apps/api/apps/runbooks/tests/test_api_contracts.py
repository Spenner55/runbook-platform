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
    services.create_runbook(
        organization=org, title="First", slug="conflict-slug", raw_content=""
    )
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


# ---------------------------------------------------------------------------
# Status transition actions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_ready_transitions_draft_to_ready(org):
    runbook = services.create_runbook(
        organization=org, title="T", slug="t", raw_content="x"
    )
    client = Client()
    response = client.post(f"/api/v1/runbooks/{runbook.id}/mark-ready/")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.django_db
def test_mark_ready_on_archived_returns_409(org):
    runbook = services.create_runbook(
        organization=org, title="T", slug="t", raw_content="x"
    )
    services.archive_runbook(runbook=runbook)
    client = Client()
    response = client.post(f"/api/v1/runbooks/{runbook.id}/mark-ready/")
    assert response.status_code == 409
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "invalid_state_transition"


@pytest.mark.django_db
def test_archive_transitions_draft_to_archived(org):
    runbook = services.create_runbook(
        organization=org, title="T2", slug="t2", raw_content="x"
    )
    client = Client()
    response = client.post(f"/api/v1/runbooks/{runbook.id}/archive/")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


@pytest.mark.django_db
def test_archive_already_archived_returns_409(org):
    runbook = services.create_runbook(
        organization=org, title="T3", slug="t3", raw_content="x"
    )
    services.archive_runbook(runbook=runbook)
    client = Client()
    response = client.post(f"/api/v1/runbooks/{runbook.id}/archive/")
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# List + detail payload discipline
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_runbooks_excludes_raw_content(org):
    services.create_runbook(
        organization=org, title="T", slug="t-list", raw_content="secret content"
    )
    client = Client()
    response = client.get("/api/v1/runbooks/")
    assert response.status_code == 200
    for item in response.json():
        assert "raw_content" not in item


@pytest.mark.django_db
def test_retrieve_runbook_includes_raw_content(org):
    runbook = services.create_runbook(
        organization=org, title="T", slug="t-detail", raw_content="the content"
    )
    client = Client()
    response = client.get(f"/api/v1/runbooks/{runbook.id}/")
    assert response.status_code == 200
    assert response.json()["raw_content"] == "the content"
