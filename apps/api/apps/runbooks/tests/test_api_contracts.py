import pytest
from rest_framework.test import APIClient

from apps.runbooks import services


@pytest.mark.django_db
def test_runbook_list_requires_authentication():
    response = APIClient().get("/api/v1/runbooks/")
    assert response.status_code == 401


@pytest.mark.django_db
def test_create_runbook_returns_201(org, api_client_for_org):
    client = api_client_for_org(org)
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
def test_runbook_list_requires_organization_header(org, api_client_for_org):
    client = api_client_for_org(org)
    client.defaults.pop("HTTP_X_ORGANIZATION_ID")

    response = client.get("/api/v1/runbooks/")

    assert response.status_code == 400
    body = response.json()
    assert body["errors"][0]["code"] == "organization_id_required"
    assert body["errors"][0]["attr"] == "X-Organization-Id"


@pytest.mark.django_db
def test_create_runbook_rejects_header_body_org_mismatch(org, api_client_for_org):
    client = api_client_for_org(org)
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
    assert response.json()["errors"][0]["code"] == "org_id_mismatch"


@pytest.mark.django_db
def test_create_runbook_missing_title_returns_400_with_envelope(org, api_client_for_org):
    client = api_client_for_org(org)
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
def test_create_runbook_slug_conflict_returns_409_with_envelope(
    org, api_client_for_org
):
    services.create_runbook(
        organization=org, title="First", slug="conflict-slug", raw_content=""
    )
    client = api_client_for_org(org)
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
def test_mark_ready_transitions_draft_to_ready(org, api_client_for_org):
    runbook = services.create_runbook(
        organization=org, title="T", slug="t", raw_content="x"
    )
    client = api_client_for_org(org)
    response = client.post(f"/api/v1/runbooks/{runbook.id}/mark-ready/")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.django_db
def test_mark_ready_on_archived_returns_409(org, api_client_for_org):
    runbook = services.create_runbook(
        organization=org, title="T", slug="t", raw_content="x"
    )
    services.archive_runbook(runbook=runbook)
    client = api_client_for_org(org)
    response = client.post(f"/api/v1/runbooks/{runbook.id}/mark-ready/")
    assert response.status_code == 409
    body = response.json()
    assert "errors" in body
    assert body["errors"][0]["code"] == "invalid_state_transition"


@pytest.mark.django_db
def test_archive_transitions_draft_to_archived(org, api_client_for_org):
    runbook = services.create_runbook(
        organization=org, title="T2", slug="t2", raw_content="x"
    )
    client = api_client_for_org(org)
    response = client.post(f"/api/v1/runbooks/{runbook.id}/archive/")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"


@pytest.mark.django_db
def test_archive_already_archived_returns_409(org, api_client_for_org):
    runbook = services.create_runbook(
        organization=org, title="T3", slug="t3", raw_content="x"
    )
    services.archive_runbook(runbook=runbook)
    client = api_client_for_org(org)
    response = client.post(f"/api/v1/runbooks/{runbook.id}/archive/")
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# List + detail payload discipline
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_runbooks_excludes_raw_content(org, api_client_for_org):
    services.create_runbook(
        organization=org, title="T", slug="t-list", raw_content="secret content"
    )
    client = api_client_for_org(org)
    response = client.get("/api/v1/runbooks/")
    assert response.status_code == 200
    for item in response.json():
        assert "raw_content" not in item


@pytest.mark.django_db
def test_retrieve_runbook_includes_raw_content(org, api_client_for_org):
    runbook = services.create_runbook(
        organization=org, title="T", slug="t-detail", raw_content="the content"
    )
    client = api_client_for_org(org)
    response = client.get(f"/api/v1/runbooks/{runbook.id}/")
    assert response.status_code == 200
    assert response.json()["raw_content"] == "the content"


@pytest.mark.django_db
def test_non_member_cannot_read_or_mutate_runbook(org, api_client_for_org):
    runbook = services.create_runbook(
        organization=org, title="Private", slug="private", raw_content="secret"
    )
    other_org = type(org).objects.create(name="Other Corp", slug="other-corp")
    client = api_client_for_org(other_org)

    assert client.get("/api/v1/runbooks/").json() == []
    assert client.get(f"/api/v1/runbooks/{runbook.id}/").status_code == 404
    assert client.post(f"/api/v1/runbooks/{runbook.id}/mark-ready/").status_code == 404
