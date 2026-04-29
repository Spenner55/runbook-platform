"""
Public approval API contract tests.

Covers GET /api/v1/approvals/, GET /api/v1/approvals/<id>/, and
POST /api/v1/approvals/<id>/decide/
"""

import pytest

from apps.approvals import services
from apps.audit.models import AuditEvent


@pytest.fixture
def pending_approval_request(claimed_approval_execution):
    result = claimed_approval_execution
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()
    ar, _ = services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
    )
    return ar


def _client_for_approval(api_client_for_org, approval_request):
    return api_client_for_org(approval_request.organization)


# ---------------------------------------------------------------------------
# GET /api/v1/approvals/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_approvals_requires_organization_id(org, api_client_for_org):
    client = api_client_for_org(org)
    client.defaults.pop("HTTP_X_ORGANIZATION_ID")
    response = client.get("/api/v1/approvals/")
    assert response.status_code == 400
    body = response.json()
    assert any(e["code"] == "organization_id_required" for e in body["errors"])


@pytest.mark.django_db
def test_list_approvals_returns_pending_by_default(
    org, pending_approval_request, api_client_for_org
):
    client = api_client_for_org(org)
    response = client.get(f"/api/v1/approvals/?organization_id={org.id}")
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    ids = [r["id"] for r in body["results"]]
    assert str(pending_approval_request.id) in ids


@pytest.mark.django_db
def test_list_approvals_scoped_to_org(
    org, pending_approval_request, api_client_for_org
):
    from apps.organizations.models import Organization

    other_org = Organization.objects.create(name="Other Corp", slug="other")
    client = api_client_for_org(other_org)
    response = client.get(f"/api/v1/approvals/?organization_id={other_org.id}")
    assert response.status_code == 200
    body = response.json()
    # Should not include requests from a different org.
    ids = [r["id"] for r in body["results"]]
    assert str(pending_approval_request.id) not in ids


@pytest.mark.django_db
def test_list_approvals_includes_step_detail(
    org, pending_approval_request, api_client_for_org
):
    client = api_client_for_org(org)
    response = client.get(f"/api/v1/approvals/?organization_id={org.id}")
    body = response.json()
    item = body["results"][0]
    assert "step" in item
    assert "name" in item["step"]
    assert item["step"]["requires_approval"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/approvals/<id>/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_approval_detail_returns_200(pending_approval_request, api_client_for_org):
    client = _client_for_approval(api_client_for_org, pending_approval_request)
    response = client.get(f"/api/v1/approvals/{pending_approval_request.id}/")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(pending_approval_request.id)
    assert body["status"] == "pending"
    assert body["decision"] is None


@pytest.mark.django_db
def test_get_approval_detail_unknown_id_returns_404(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.get("/api/v1/approvals/00000000-0000-0000-0000-000000000000/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/approvals/<id>/decide/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_decide_approved_returns_200(
    pending_approval_request, api_client_for_org, user
):
    client = api_client_for_org(pending_approval_request.organization, user=user)
    response = client.post(
        f"/api/v1/approvals/{pending_approval_request.id}/decide/",
        data={
            "decision": "approved",
            "actor_display_name": "Client Supplied Name",
            "notes": "LGTM",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["decision"]["decision"] == "approved"
    assert body["decision"]["decided_by_label"] == user.email
    assert body["decision"]["decided_by_label"] != "Client Supplied Name"

    event = AuditEvent.objects.get(event_type="approval.approved")
    assert event.actor_type == AuditEvent.ActorType.USER
    assert event.actor_id == str(user.id)
    assert event.actor_label == user.email


@pytest.mark.django_db
def test_decide_rejected_returns_200(pending_approval_request, api_client_for_org):
    client = _client_for_approval(api_client_for_org, pending_approval_request)
    response = client.post(
        f"/api/v1/approvals/{pending_approval_request.id}/decide/",
        data={
            "decision": "rejected",
            "actor_display_name": "Test Operator",
            "notes": "Not approved.",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"


@pytest.mark.django_db
def test_decide_missing_actor_uses_authenticated_user(
    pending_approval_request, api_client_for_org, user
):
    client = api_client_for_org(pending_approval_request.organization, user=user)
    response = client.post(
        f"/api/v1/approvals/{pending_approval_request.id}/decide/",
        data={"decision": "approved"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["decided_by_label"] == user.email


@pytest.mark.django_db
def test_decide_second_decision_returns_409(
    pending_approval_request, api_client_for_org
):
    client = _client_for_approval(api_client_for_org, pending_approval_request)
    first = client.post(
        f"/api/v1/approvals/{pending_approval_request.id}/decide/",
        data={"decision": "approved", "actor_display_name": "Op A"},
        content_type="application/json",
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/approvals/{pending_approval_request.id}/decide/",
        data={"decision": "rejected", "actor_display_name": "Op B"},
        content_type="application/json",
    )
    assert second.status_code == 409
    body = second.json()
    assert body["errors"][0]["code"] == "approval_request_not_pending"


@pytest.mark.django_db
def test_decide_unknown_approval_returns_404(org, api_client_for_org):
    client = api_client_for_org(org)
    response = client.post(
        "/api/v1/approvals/00000000-0000-0000-0000-000000000000/decide/",
        data={"decision": "approved", "actor_display_name": "Op"},
        content_type="application/json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_non_member_cannot_read_or_decide_approval(
    org, pending_approval_request, api_client_for_org
):
    other_org = type(org).objects.create(name="Other Corp", slug="other-corp")
    client = api_client_for_org(other_org)

    assert (
        client.get(f"/api/v1/approvals/{pending_approval_request.id}/").status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/approvals/{pending_approval_request.id}/decide/",
            data={"decision": "approved", "actor_display_name": "Op"},
            content_type="application/json",
        ).status_code
        == 404
    )
