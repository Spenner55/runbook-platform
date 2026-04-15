import pytest
from django.db import IntegrityError

from apps.runbooks import services
from apps.runbooks.models import Runbook


@pytest.mark.django_db
def test_create_runbook_persists_row(org):
    runbook = services.create_runbook(
        organization=org, title="My Runbook", slug="my-runbook", raw_content=""
    )
    assert Runbook.objects.filter(pk=runbook.pk).exists()


@pytest.mark.django_db
def test_create_runbook_sets_fields_correctly(org):
    runbook = services.create_runbook(
        organization=org,
        title="DB Deploy",
        slug="db-deploy",
        raw_content="run migrations",
    )
    assert runbook.title == "DB Deploy"
    assert runbook.slug == "db-deploy"
    assert runbook.raw_content == "run migrations"
    assert runbook.status == Runbook.Status.DRAFT
    assert runbook.organization == org


@pytest.mark.django_db
def test_create_runbook_enforces_unique_slug_per_org(org):
    services.create_runbook(organization=org, title="First", slug="dup-slug", raw_content="")
    with pytest.raises(IntegrityError):
        services.create_runbook(organization=org, title="Second", slug="dup-slug", raw_content="")
