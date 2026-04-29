import pytest
from rest_framework.test import APIClient

from apps.organizations import services as organization_services
from apps.organizations.models import MembershipRole
from apps.users import services as user_services


def _user(email):
    return user_services.create_user(email=email, password="s3cr3tpass!")


def _client(user, organization=None):
    client = APIClient()
    client.force_authenticate(user=user)
    if organization is not None:
        client.defaults["HTTP_X_ORGANIZATION_ID"] = str(organization.id)
    return client


@pytest.mark.django_db
def test_admin_can_create_list_update_and_remove_membership(org):
    owner = _user("owner@example.com")
    member = _user("new-member@example.com")
    organization_services.create_membership(
        organization=org, user=owner, role=MembershipRole.OWNER
    )
    client = _client(owner, org)

    create_response = client.post(
        f"/api/v1/organizations/{org.id}/members/",
        {"user_id": str(member.id), "role": MembershipRole.OPERATOR},
        format="json",
    )
    assert create_response.status_code == 201
    membership_id = create_response.data["id"]
    assert create_response.data["user"]["email"] == "new-member@example.com"
    assert create_response.data["role"] == MembershipRole.OPERATOR

    list_response = client.get(f"/api/v1/organizations/{org.id}/members/")
    assert list_response.status_code == 200
    assert {entry["user"]["email"] for entry in list_response.data} == {
        "owner@example.com",
        "new-member@example.com",
    }

    update_response = client.patch(
        f"/api/v1/organizations/{org.id}/members/{membership_id}/",
        {"role": MembershipRole.VIEWER},
        format="json",
    )
    assert update_response.status_code == 200
    assert update_response.data["role"] == MembershipRole.VIEWER

    delete_response = client.delete(
        f"/api/v1/organizations/{org.id}/members/{membership_id}/"
    )
    assert delete_response.status_code == 204


@pytest.mark.django_db
def test_viewer_has_read_only_membership_access(org):
    owner = _user("owner-readonly@example.com")
    viewer = _user("viewer@example.com")
    target = _user("target@example.com")
    organization_services.create_membership(
        organization=org, user=owner, role=MembershipRole.OWNER
    )
    viewer_membership = organization_services.create_membership(
        organization=org, user=viewer, role=MembershipRole.VIEWER
    )
    client = _client(viewer, org)

    list_response = client.get(f"/api/v1/organizations/{org.id}/members/")
    assert list_response.status_code == 200

    detail_response = client.get(
        f"/api/v1/organizations/{org.id}/members/{viewer_membership.id}/"
    )
    assert detail_response.status_code == 200

    create_response = client.post(
        f"/api/v1/organizations/{org.id}/members/",
        {"user_id": str(target.id), "role": MembershipRole.OPERATOR},
        format="json",
    )
    assert create_response.status_code == 403

    update_response = client.patch(
        f"/api/v1/organizations/{org.id}/members/{viewer_membership.id}/",
        {"role": MembershipRole.ADMIN},
        format="json",
    )
    assert update_response.status_code == 403


@pytest.mark.django_db
def test_operator_can_read_but_not_manage_memberships(org):
    member = _user("operator-access@example.com")
    target = _user("operator-target@example.com")
    membership = organization_services.create_membership(
        organization=org, user=member, role=MembershipRole.OPERATOR
    )
    client = _client(member, org)

    read_response = client.get(
        f"/api/v1/organizations/{org.id}/members/{membership.id}/"
    )
    assert read_response.status_code == 200

    create_response = client.post(
        f"/api/v1/organizations/{org.id}/members/",
        {"user_id": str(target.id), "role": MembershipRole.VIEWER},
        format="json",
    )
    assert create_response.status_code == 403


@pytest.mark.django_db
def test_non_member_cannot_read_memberships(org):
    user = _user("outsider@example.com")
    client = _client(user, org)

    response = client.get(f"/api/v1/organizations/{org.id}/members/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_member_detail_does_not_cross_organization_boundaries(org):
    user = _user("scoped-user@example.com")
    other_org = organization_services.create_organization(
        name="Other Org", slug="other-org"
    )
    org_membership = organization_services.create_membership(
        organization=org, user=user, role=MembershipRole.VIEWER
    )
    organization_services.create_membership(
        organization=other_org, user=user, role=MembershipRole.VIEWER
    )
    client = _client(user, other_org)

    response = client.get(
        f"/api/v1/organizations/{other_org.id}/members/{org_membership.id}/"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_cannot_demote_or_remove_last_owner(org):
    owner = _user("single-owner@example.com")
    membership = organization_services.create_membership(
        organization=org, user=owner, role=MembershipRole.OWNER
    )
    client = _client(owner, org)

    update_response = client.patch(
        f"/api/v1/organizations/{org.id}/members/{membership.id}/",
        {"role": MembershipRole.ADMIN},
        format="json",
    )
    assert update_response.status_code == 409
    assert update_response.data["errors"][0]["code"] == "last_owner_required"

    delete_response = client.delete(
        f"/api/v1/organizations/{org.id}/members/{membership.id}/"
    )
    assert delete_response.status_code == 409
    assert delete_response.data["errors"][0]["code"] == "last_owner_required"
