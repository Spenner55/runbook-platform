from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.auditor import selectors
from apps.auditor.access import assert_auditor_read_only_method
from apps.auditor.models import (
    AuditorAccessGrant,
    AuditorGrantStatus,
    ServiceCatalogEntry,
)
from apps.changes.models import ChangeRecord, ChangeTarget, OperationProfile
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.runbooks.models import Runbook
from apps.users.models import User
from apps.workflows.models import Workflow


def _user(email):
    return User.objects.create_user(email=email, password="s3cr3tpass!")


def _change(org, *, title, status="closed", risk="high", target="prod-api"):
    runbook = Runbook.objects.create(
        organization=org,
        title=f"{title} runbook",
        slug=f"{org.slug}-{title.lower().replace(' ', '-')}",
        raw_content="Deploy safely",
    )
    workflow = Workflow.objects.create(
        organization=org,
        runbook=runbook,
        name=f"{title} workflow",
        version=1,
        status=Workflow.Status.PUBLISHED,
    )
    profile = OperationProfile.objects.create(
        organization=org,
        key=f"{title.lower().replace(' ', '-')}-profile",
        name=f"{title} profile",
        risk_level=risk,
    )
    change = ChangeRecord.objects.create(
        organization=org,
        operation_profile=profile,
        workflow=workflow,
        title=title,
        summary="Production maintenance",
        justification="Required",
    )
    ChangeTarget.objects.create(
        organization=org,
        change_record=change,
        position=1,
        target_type="service",
        target_identifier=target,
        normalized_identifier=target,
        display_name=target,
        environment="production",
    )
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=status,
        closed_at=timezone.now() if status == "closed" else None,
        verified_at=timezone.now() if status == "verified" else None,
    )
    change.refresh_from_db()
    return change


def _grant(org, user, scope, **kwargs):
    return AuditorAccessGrant.objects.create(
        organization=org,
        user=user,
        scope=scope,
        reason="audit sample",
        **kwargs,
    )


@pytest.mark.django_db
def test_active_grant_intersects_with_membership_and_scope(org):
    auditor = _user("scoped-auditor@example.com")
    Membership.objects.create(
        organization=org, user=auditor, role=MembershipRole.VIEWER
    )
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="payments-api",
        name="Payments API",
        target_patterns=["payments-prod"],
    )
    allowed = _change(
        org, title="Payments closed", status="closed", target="payments-prod"
    )
    _change(org, title="Search closed", status="closed", target="search-prod")
    _grant(
        org,
        auditor,
        {"service_keys": ["payments-api"], "statuses": ["closed"]},
    )

    rows = list(selectors.audit_change_queryset(organization=org, user=auditor))

    assert [row.id for row in rows] == [allowed.id]


@pytest.mark.django_db
def test_grant_without_org_membership_does_not_authorize(org):
    auditor = _user("outsider-auditor@example.com")
    _change(
        org, title="Visible only to members", status="closed", target="payments-prod"
    )
    _grant(org, auditor, {"all": True})

    rows = list(selectors.audit_change_queryset(organization=org, user=auditor))

    assert rows == []


@pytest.mark.django_db
def test_expired_and_revoked_grants_do_not_authorize(org):
    auditor = _user("expired-auditor@example.com")
    Membership.objects.create(
        organization=org, user=auditor, role=MembershipRole.VIEWER
    )
    _change(org, title="Closed change", status="closed", target="payments-prod")
    _grant(
        org,
        auditor,
        {"all": True},
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    _grant(
        org,
        auditor,
        {"all": True},
        status=AuditorGrantStatus.REVOKED,
        revoked_at=timezone.now(),
    )

    rows = list(selectors.audit_change_queryset(organization=org, user=auditor))

    assert rows == []


@pytest.mark.django_db
def test_combined_filters_never_widen_grant_scope(org):
    auditor = _user("filtered-auditor@example.com")
    Membership.objects.create(
        organization=org, user=auditor, role=MembershipRole.VIEWER
    )
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="payments-api",
        name="Payments API",
        target_patterns=["payments-prod"],
    )
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="search-api",
        name="Search API",
        target_patterns=["search-prod"],
    )
    _change(org, title="Payments closed", status="closed", target="payments-prod")
    _change(org, title="Search closed", status="closed", target="search-prod")
    _grant(org, auditor, {"service_keys": ["payments-api"], "statuses": ["closed"]})

    rows = list(
        selectors.audit_change_queryset(
            organization=org,
            user=auditor,
            filters={"service": "search-api"},
        )
    )

    assert rows == []


@pytest.mark.django_db
def test_multiple_grants_are_union_without_dimension_widening(org):
    auditor = _user("union-auditor@example.com")
    Membership.objects.create(
        organization=org, user=auditor, role=MembershipRole.VIEWER
    )
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="payments-api",
        name="Payments API",
        target_patterns=["payments-prod"],
    )
    ServiceCatalogEntry.objects.create(
        organization=org,
        service_key="search-api",
        name="Search API",
        target_patterns=["search-prod"],
    )
    allowed_payment = _change(
        org,
        title="Payments closed",
        status="closed",
        target="payments-prod",
    )
    allowed_search = _change(
        org,
        title="Search verified",
        status="verified",
        target="search-prod",
    )
    _change(org, title="Payments verified", status="verified", target="payments-prod")
    _change(org, title="Search closed", status="closed", target="search-prod")
    _grant(org, auditor, {"service_keys": ["payments-api"], "statuses": ["closed"]})
    _grant(org, auditor, {"service_keys": ["search-api"], "statuses": ["verified"]})

    rows = list(selectors.audit_change_queryset(organization=org, user=auditor))

    assert {row.id for row in rows} == {allowed_payment.id, allowed_search.id}


@pytest.mark.django_db
def test_grants_are_org_scoped(org):
    other_org = Organization.objects.create(name="Other", slug="other-auditor")
    auditor = _user("org-scope-auditor@example.com")
    Membership.objects.create(
        organization=org, user=auditor, role=MembershipRole.VIEWER
    )
    Membership.objects.create(
        organization=other_org,
        user=auditor,
        role=MembershipRole.VIEWER,
    )
    _change(org, title="Primary org", status="closed", target="payments-prod")
    other_change = _change(
        other_org,
        title="Other org",
        status="closed",
        target="payments-prod",
    )
    _grant(other_org, auditor, {"all": True})

    rows = list(selectors.audit_change_queryset(organization=other_org, user=auditor))
    primary_rows = list(selectors.audit_change_queryset(organization=org, user=auditor))

    assert [row.id for row in rows] == [other_change.id]
    assert primary_rows == []


def test_auditor_read_only_method_guard():
    assert_auditor_read_only_method("GET")
    with pytest.raises(PermissionDenied):
        assert_auditor_read_only_method("POST")
