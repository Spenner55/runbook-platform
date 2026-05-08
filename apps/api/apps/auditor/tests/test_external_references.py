import pytest

from apps.audit.models import AuditEvent
from apps.audit.services import system_actor
from apps.auditor import selectors
from apps.auditor.external_clients import ExternalSnapshot
from apps.auditor.models import ExternalReferenceType, ExternalSystem
from apps.auditor.services import (
    link_external_change_reference,
    refresh_external_change_reference,
)
from apps.changes.models import ChangeRecord, ChangeTarget, OperationProfile
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.organizations.models import Membership, MembershipRole
from apps.runbooks.models import Runbook
from apps.users.models import User
from apps.workflows.models import Workflow


def _user(email):
    return User.objects.create_user(email=email, password="s3cr3tpass!")


def _change(org, *, title="Reference change"):
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
        risk_level="high",
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
        target_identifier="payments-prod",
        normalized_identifier="payments-prod",
        environment="production",
    )
    return change


@pytest.mark.django_db
def test_link_external_reference_sanitizes_bounded_snapshot(org):
    change = _change(org)

    reference = link_external_change_reference(
        change_record=change,
        system=ExternalSystem.JIRA,
        reference_type=ExternalReferenceType.TICKET,
        external_id="10001",
        external_key="PROJ-123",
        external_url="https://jira.example.com/browse/PROJ-123",
        snapshot={
            "title": "Production ticket",
            "authorization": "Bearer secret",
            "comments": ["do not store"],
            "attachments": [{"name": "secret.txt"}],
            "source_fields": {"state": "Done", "api_token": "secret"},
        },
        actor=system_actor("external reference test"),
    )

    assert reference.snapshot == {
        "title": "Production ticket",
        "source_fields": {"state": "Done"},
    }
    assert len(reference.snapshot_sha256) == 64
    assert reference.snapshot_taken_at is not None
    event = AuditEvent.objects.get(
        event_type="external_change_reference.linked",
        object_type=AuditEvent.ObjectType.EXTERNAL_CHANGE_REFERENCE,
        object_id=reference.id,
    )
    assert event.metadata == {
        "change_record_id": str(change.id),
        "system": "jira",
        "reference_type": "ticket",
        "external_key": "PROJ-123",
        "snapshot_sha256": reference.snapshot_sha256,
    }


@pytest.mark.django_db
def test_link_external_reference_rejects_duplicate_reference(org):
    change = _change(org)
    kwargs = {
        "change_record": change,
        "system": ExternalSystem.SERVICENOW,
        "reference_type": ExternalReferenceType.TICKET,
        "external_id": "CHG001",
        "external_key": "CHG001",
    }
    link_external_change_reference(**kwargs)

    with pytest.raises(DomainConflictError):
        link_external_change_reference(**kwargs)


@pytest.mark.django_db
def test_link_external_reference_rejects_unsafe_urls_and_unsupported_types(org):
    change = _change(org)

    with pytest.raises(DomainValidationError):
        link_external_change_reference(
            change_record=change,
            system=ExternalSystem.JIRA,
            reference_type=ExternalReferenceType.TICKET,
            external_id="10001",
            external_url="https://user:password@jira.example.com/browse/PROJ-123",
        )

    with pytest.raises(DomainValidationError):
        link_external_change_reference(
            change_record=change,
            system="github",
            reference_type=ExternalReferenceType.TICKET,
            external_id="10002",
        )

    with pytest.raises(DomainValidationError):
        link_external_change_reference(
            change_record=change,
            system=ExternalSystem.JIRA,
            reference_type="pull_request",
            external_id="10003",
        )


@pytest.mark.django_db
def test_refresh_is_explicit_only_and_selectors_do_not_call_external_clients(
    org,
    monkeypatch,
):
    auditor = _user("reference-auditor@example.com")
    Membership.objects.create(
        organization=org, user=auditor, role=MembershipRole.VIEWER
    )
    change = _change(org)
    reference = link_external_change_reference(
        change_record=change,
        system=ExternalSystem.JIRA,
        reference_type=ExternalReferenceType.TICKET,
        external_id="10001",
        external_key="PROJ-123",
        snapshot={"title": "Initial"},
    )
    from apps.auditor.models import AuditorAccessGrant

    AuditorAccessGrant.objects.create(
        organization=org, user=auditor, scope={"all": True}
    )

    def fail_refresh(*, system):
        raise AssertionError("search must not refresh external references")

    monkeypatch.setattr(
        "apps.auditor.external_clients.get_refresh_client", fail_refresh
    )

    rows = selectors.list_audit_changes(organization=org, user=auditor)

    assert rows[0]["external_references"][0]["external_key"] == "PROJ-123"

    class Client:
        def fetch_snapshot(self, *, reference):
            return ExternalSnapshot(snapshot={"title": "Refreshed"})

    refreshed = refresh_external_change_reference(
        reference=reference,
        client=Client(),
        actor=system_actor("external reference refresh test"),
    )

    assert refreshed.snapshot == {"title": "Refreshed"}
    event = AuditEvent.objects.get(
        event_type="external_change_reference.refreshed",
        object_type=AuditEvent.ObjectType.EXTERNAL_CHANGE_REFERENCE,
        object_id=reference.id,
    )
    assert event.metadata["snapshot_sha256"] == refreshed.snapshot_sha256
