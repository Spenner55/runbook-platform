"""
API contract tests for Phase 10.2 public policy endpoints.

Covers: CRUD, validation, conflict handling, tenant isolation.
"""

import pytest

from apps.organizations.models import MembershipRole, Organization
from apps.policies import services as policy_services


@pytest.fixture
def client(org, org2, api_client_for_org, user):
    api_client_for_org(org2, role=MembershipRole.ADMIN, user=user)
    return api_client_for_org(org, role=MembershipRole.ADMIN, user=user)


@pytest.fixture
def org2(db):
    return Organization.objects.create(name="Other Org", slug="other-org")


@pytest.fixture
def policy(org):
    return policy_services.create_policy(
        organization=org, name="Test Policy", description="Desc"
    )


@pytest.fixture
def rule(policy):
    return policy_services.create_rule(
        policy=policy,
        name="High risk rule",
        priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="approval_required",
        reason="Needs approval.",
    )


def _policy_url(policy, organization=None):
    org_id = organization.id if organization is not None else policy.organization_id
    return f"/api/v1/policies/{policy.id}/?organization_id={org_id}"


def _rules_url(policy, organization=None):
    org_id = organization.id if organization is not None else policy.organization_id
    return f"/api/v1/policies/{policy.id}/rules/?organization_id={org_id}"


def _rule_url(policy, rule, organization=None):
    org_id = organization.id if organization is not None else policy.organization_id
    return f"/api/v1/policies/{policy.id}/rules/{rule.id}/?organization_id={org_id}"


# ---------------------------------------------------------------------------
# Policy list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_policies_requires_organization_id(client):
    client.defaults.pop("HTTP_X_ORGANIZATION_ID")
    resp = client.get("/api/v1/policies/")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["code"] == "organization_id_required"


@pytest.mark.django_db
def test_list_policies_rejects_query_header_mismatch(client, org2):
    resp = client.get(f"/api/v1/policies/?organization_id={org2.id}")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["code"] == "org_id_mismatch"


@pytest.mark.django_db
def test_list_policies_returns_active_by_default(client, org, policy):
    resp = client.get(f"/api/v1/policies/?organization_id={org.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["name"] == "Test Policy"


@pytest.mark.django_db
def test_list_policies_is_active_all_includes_inactive(client, org, policy):
    policy_services.update_policy(policy=policy, is_active=False)
    resp = client.get(f"/api/v1/policies/?organization_id={org.id}&is_active=all")
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


@pytest.mark.django_db
def test_list_policies_is_active_false_filters_correctly(client, org, policy):
    policy_services.update_policy(policy=policy, is_active=False)
    resp = client.get(f"/api/v1/policies/?organization_id={org.id}&is_active=false")
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


@pytest.mark.django_db
def test_list_policies_invalid_is_active_returns_400(client, org):
    resp = client.get(f"/api/v1/policies/?organization_id={org.id}&is_active=sometimes")
    assert resp.status_code == 400
    assert resp.json()["errors"][0]["attr"] == "is_active"


@pytest.mark.django_db
def test_list_policies_excludes_other_org(client, org, org2, policy):
    policy_services.create_policy(organization=org2, name="Other Policy")
    resp = client.get(f"/api/v1/policies/?organization_id={org.id}")
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


# ---------------------------------------------------------------------------
# Policy create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_policy_returns_201(client, org):
    resp = client.post(
        "/api/v1/policies/",
        data={"organization_id": str(org.id), "name": "New Policy", "is_active": True},
        content_type="application/json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New Policy"
    assert "id" in body


@pytest.mark.django_db
def test_create_policy_duplicate_active_name_returns_409(client, org, policy):
    resp = client.post(
        "/api/v1/policies/",
        data={"organization_id": str(org.id), "name": "Test Policy"},
        content_type="application/json",
    )
    assert resp.status_code == 409
    assert resp.json()["errors"][0]["code"] == "duplicate_active_policy_name"


@pytest.mark.django_db
def test_create_policy_missing_name_returns_400(client, org):
    resp = client.post(
        "/api/v1/policies/",
        data={"organization_id": str(org.id)},
        content_type="application/json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Policy detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_get_policy_detail_includes_rules(client, org, policy, rule):
    resp = client.get(_policy_url(policy))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(policy.id)
    assert len(body["rules"]) == 1
    assert body["rules"][0]["priority"] == 10


@pytest.mark.django_db
def test_get_policy_detail_rules_ordered_by_priority(client, org, policy):
    policy_services.create_rule(
        policy=policy,
        name="Rule B",
        priority=20,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )
    policy_services.create_rule(
        policy=policy,
        name="Rule A",
        priority=5,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["low"]},
        outcome="auto_approve",
    )
    resp = client.get(_policy_url(policy))
    rules = resp.json()["rules"]
    assert [r["priority"] for r in rules] == [5, 20]


@pytest.mark.django_db
def test_get_unknown_policy_returns_404(client):
    client.defaults["HTTP_X_ORGANIZATION_ID"] = "00000000-0000-0000-0000-000000000000"
    resp = client.get(
        "/api/v1/policies/00000000-0000-0000-0000-000000000000/"
        "?organization_id=00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_get_policy_detail_requires_organization_id(client, policy):
    client.defaults.pop("HTTP_X_ORGANIZATION_ID")
    resp = client.get(f"/api/v1/policies/{policy.id}/")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_get_policy_detail_wrong_org_returns_404(client, org2, policy):
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org2.id)
    resp = client.get(_policy_url(policy, organization=org2))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Policy update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_policy_updates_fields(client, policy):
    resp = client.patch(
        _policy_url(policy),
        data={"description": "Updated desc"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated desc"


@pytest.mark.django_db
def test_patch_policy_deactivate(client, policy):
    resp = client.patch(
        _policy_url(policy),
        data={"is_active": False},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    policy.refresh_from_db()
    assert policy.is_active is False


@pytest.mark.django_db
def test_patch_policy_duplicate_name_returns_409(client, org, policy):
    policy_services.create_policy(organization=org, name="Other Policy")
    resp = client.patch(
        _policy_url(policy),
        data={"name": "Other Policy"},
        content_type="application/json",
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Rule create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_rule_returns_201(client, policy):
    resp = client.post(
        _rules_url(policy),
        data={
            "name": "High risk",
            "priority": 10,
            "condition_type": "risk_level",
            "condition_params": {"operator": "in", "values": ["high"]},
            "outcome": "approval_required",
        },
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["priority"] == 10


@pytest.mark.django_db
def test_create_rule_invalid_condition_params_returns_400(client, policy):
    resp = client.post(
        _rules_url(policy),
        data={
            "name": "Bad rule",
            "priority": 10,
            "condition_type": "risk_level",
            "condition_params": {"operator": "bad"},
            "outcome": "block",
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_create_rule_duplicate_priority_returns_409(client, policy, rule):
    resp = client.post(
        _rules_url(policy),
        data={
            "name": "Another Rule",
            "priority": 10,
            "condition_type": "risk_level",
            "condition_params": {"operator": "in", "values": ["low"]},
            "outcome": "auto_approve",
        },
        content_type="application/json",
    )
    assert resp.status_code == 409
    assert resp.json()["errors"][0]["code"] == "duplicate_rule_priority"


@pytest.mark.django_db
def test_create_rule_time_window_validates_tz(client, policy):
    resp = client.post(
        _rules_url(policy),
        data={
            "name": "Window rule",
            "priority": 10,
            "condition_type": "time_window",
            "condition_params": {
                "timezone": "Invalid/Tz",
                "days_of_week": ["mon"],
                "start_time": "09:00",
                "end_time": "17:00",
                "match_when": "inside",
            },
            "outcome": "block",
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Rule update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_rule_updates_fields(client, policy, rule):
    resp = client.patch(
        _rule_url(policy, rule),
        data={"reason": "Updated reason"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["reason"] == "Updated reason"


@pytest.mark.django_db
def test_patch_rule_deactivate(client, policy, rule):
    resp = client.patch(
        _rule_url(policy, rule),
        data={"is_active": False},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.django_db
def test_patch_rule_duplicate_priority_returns_409(client, policy, rule):
    rule2 = policy_services.create_rule(
        policy=policy,
        name="Rule 2",
        priority=20,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["low"]},
        outcome="auto_approve",
    )
    resp = client.patch(
        _rule_url(policy, rule2),
        data={"priority": 10},
        content_type="application/json",
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Rule soft-delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_rule_soft_deactivates(client, policy, rule):
    resp = client.delete(_rule_url(policy, rule))
    assert resp.status_code == 204
    rule.refresh_from_db()
    assert rule.is_active is False


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cross_tenant_policy_access_returns_404_on_rules(client, org, org2, policy):
    """Cannot create rules on another org's policy."""
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org2.id)
    resp = client.post(
        _rules_url(policy, organization=org2),
        data={
            "name": "Rule",
            "priority": 10,
            "condition_type": "risk_level",
            "condition_params": {"operator": "in", "values": ["high"]},
            "outcome": "block",
        },
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_policy_patch_returns_404(client, org2, policy):
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org2.id)
    resp = client.patch(
        _policy_url(policy, organization=org2),
        data={"description": "Wrong tenant"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cross_tenant_rule_patch_returns_404(client, org2, policy, rule):
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org2.id)
    resp = client.patch(
        _rule_url(policy, rule, organization=org2),
        data={"reason": "Wrong tenant"},
        content_type="application/json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_does_not_include_other_org_policies(client, org, org2):
    policy_services.create_policy(organization=org, name="Org1 Policy")
    policy_services.create_policy(organization=org2, name="Org2 Policy")

    resp = client.get(f"/api/v1/policies/?organization_id={org.id}")
    names = [p["name"] for p in resp.json()["results"]]
    assert "Org1 Policy" in names
    assert "Org2 Policy" not in names
