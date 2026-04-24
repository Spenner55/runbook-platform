import pytest

from apps.common.exceptions import DomainConflictError
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
def test_create_runbook_slug_conflict_raises_domain_error(org):
    services.create_runbook(
        organization=org, title="First", slug="dup-slug", raw_content=""
    )
    with pytest.raises(DomainConflictError) as exc_info:
        services.create_runbook(
            organization=org, title="Second", slug="dup-slug", raw_content=""
        )
    assert exc_info.value.code == "runbook_slug_conflict"
    assert exc_info.value.attr == "slug"


@pytest.mark.django_db
def test_create_runbook_slug_conflict_does_not_persist_second_row(org):
    services.create_runbook(
        organization=org, title="First", slug="dup-slug", raw_content=""
    )
    try:
        services.create_runbook(
            organization=org, title="Second", slug="dup-slug", raw_content=""
        )
    except DomainConflictError:
        pass
    assert Runbook.objects.filter(organization=org, slug="dup-slug").count() == 1


@pytest.mark.django_db
def test_create_runbook_same_slug_different_org_is_allowed(org, db):
    from apps.organizations.models import Organization

    other_org = Organization.objects.create(name="Other Org", slug="other-org")
    services.create_runbook(
        organization=org, title="First", slug="shared-slug", raw_content=""
    )
    rb2 = services.create_runbook(
        organization=other_org, title="Second", slug="shared-slug", raw_content=""
    )
    assert rb2.pk is not None
