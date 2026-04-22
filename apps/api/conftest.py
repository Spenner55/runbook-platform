import pytest

from apps.organizations.models import Organization


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme Corp", slug="acme")
