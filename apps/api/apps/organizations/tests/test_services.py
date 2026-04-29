import pytest

from apps.common.exceptions import DomainConflictError
from apps.organizations import services
from apps.organizations.models import Membership, MembershipRole
from apps.users import services as user_services


def _user(email):
    return user_services.create_user(email=email, password="s3cr3tpass!")


@pytest.mark.django_db
def test_create_membership_links_user_to_organization(org):
    user = _user("member@example.com")

    membership = services.create_membership(
        organization=org, user=user, role=MembershipRole.ADMIN
    )

    assert membership.organization == org
    assert membership.user == user
    assert membership.role == MembershipRole.ADMIN


@pytest.mark.django_db
def test_create_membership_rejects_duplicate_user_in_organization(org):
    user = _user("duplicate@example.com")
    services.create_membership(organization=org, user=user)

    with pytest.raises(DomainConflictError) as exc_info:
        services.create_membership(organization=org, user=user)

    assert getattr(exc_info.value, "code", None) == "membership_exists"
    assert Membership.objects.filter(organization=org, user=user).count() == 1


@pytest.mark.django_db
def test_get_membership_is_organization_scoped(org):
    user = _user("scoped@example.com")
    other_org = services.create_organization(name="Other", slug="other")
    membership = services.create_membership(organization=org, user=user)

    assert services.get_membership(organization=org, user=user) == membership
    assert services.get_membership(organization=other_org, user=user) is None


@pytest.mark.django_db
def test_list_update_and_remove_membership(org):
    user = _user("crud@example.com")
    membership = services.create_membership(organization=org, user=user)

    assert list(services.list_members(organization=org)) == [membership]

    updated = services.update_member_role(
        membership=membership, role=MembershipRole.VIEWER
    )
    assert updated.role == MembershipRole.VIEWER

    services.remove_membership(membership=updated)
    assert not Membership.objects.filter(pk=membership.pk).exists()
