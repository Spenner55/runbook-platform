from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from apps.organizations.models import Membership, MembershipRole, Organization
from apps.users.models import User


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme Corp", slug="acme")


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="user@example.com",
        password="s3cr3tpass!",
        first_name="Test",
        last_name="User",
    )


@pytest.fixture
def api_client_for_org(db):
    def _make_client(organization, *, role=MembershipRole.OPERATOR, user=None):
        if user is None:
            user = User.objects.create_user(
                email=f"{organization.slug}-{role}-{uuid4()}@example.com",
                password="s3cr3tpass!",
            )
        Membership.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": role},
        )
        client = APIClient()
        client.force_authenticate(user=user)
        client.defaults["HTTP_X_ORGANIZATION_ID"] = str(organization.id)
        return client

    return _make_client
