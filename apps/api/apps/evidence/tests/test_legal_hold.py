"""Tests for legal hold behavior: create, release, cleanup blocking, cross-tenant isolation."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.changes.models import ChangeRecord
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.evidence.models import EvidenceBundle, EvidenceExport, LegalHold
from apps.evidence.services import (
    assert_no_active_legal_hold,
    cleanup_expired_bundle_storage,
    cleanup_expired_export_storage,
    create_evidence_bundle_for_change,
    create_legal_hold,
    release_legal_hold,
)
from apps.evidence.tests.test_materialization import (
    _complete_closed_change,
)
from apps.organizations.models import Organization

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_closed_change(org, operation_profile, workflow, user):
    change = ChangeRecord.objects.create(
        organization=org,
        operation_profile=operation_profile,
        workflow=workflow,
        title="Test change for legal hold",
        summary="Legal hold test",
        justification="Required",
    )
    _complete_closed_change(change, user)
    return change


def _seal_bundle(bundle, *, tmp_path, settings, user):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    from apps.evidence.services import seal_bundle

    return seal_bundle(bundle, sealed_by=user)


def _make_expired_bundle(bundle, days_past=1):
    past = timezone.now() - timedelta(days=days_past)
    EvidenceBundle.objects.filter(pk=bundle.pk).update(
        retention_expires_at=past,
    )
    bundle.refresh_from_db()
    return bundle


def _make_expired_export(export, days_past=1):
    past = timezone.now() - timedelta(days=days_past)
    EvidenceExport.objects.filter(pk=export.pk).update(expires_at=past)
    export.refresh_from_db()
    return export


# ---------------------------------------------------------------------------
# create_legal_hold
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_legal_hold_returns_active_hold(
    evidence_change, user, evidence_operation_profile, evidence_workflow
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    hold = create_legal_hold(bundle, reason="Audit matter 1234", placed_by=user)

    assert hold.status == LegalHold.Status.ACTIVE
    assert hold.change_record_id == evidence_change.id
    assert hold.evidence_bundle_id == bundle.id
    assert hold.organization_id == evidence_change.organization_id
    assert hold.placed_by_id == user.id


@pytest.mark.django_db
def test_create_legal_hold_requires_reason(evidence_change, user):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    with pytest.raises(DomainValidationError) as exc_info:
        create_legal_hold(bundle, reason="   ")

    assert exc_info.value.code == "legal_hold_reason_required"


@pytest.mark.django_db
def test_create_legal_hold_duplicate_rejected(evidence_change, user):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    create_legal_hold(bundle, reason="First hold")

    with pytest.raises(DomainConflictError) as exc_info:
        create_legal_hold(bundle, reason="Second hold")

    assert exc_info.value.code == "legal_hold_already_active"


@pytest.mark.django_db
def test_create_legal_hold_emits_audit_event(
    evidence_change, user, django_capture_on_commit_callbacks
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    with django_capture_on_commit_callbacks(execute=True):
        hold = create_legal_hold(bundle, reason="Audit hold")

    events = AuditEvent.objects.filter(
        event_type="legal_hold.created",
        object_id=hold.id,
    )
    assert events.exists()
    event = events.first()
    assert event.organization_id == evidence_change.organization_id
    assert str(evidence_change.id) in event.metadata.get("change_record_id", "")


# ---------------------------------------------------------------------------
# release_legal_hold
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_release_legal_hold_succeeds_with_actor_and_reason(evidence_change, user):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    hold = create_legal_hold(bundle, reason="Hold for release test")

    released = release_legal_hold(hold, released_by=user, release_reason="Matter resolved.")

    assert released.status == LegalHold.Status.RELEASED
    assert released.released_by_id == user.id
    assert released.released_at is not None
    assert released.release_reason == "Matter resolved."


@pytest.mark.django_db
def test_release_legal_hold_requires_nonblank_reason(evidence_change, user):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    hold = create_legal_hold(bundle, reason="Hold to fail release")

    with pytest.raises(DomainValidationError) as exc_info:
        release_legal_hold(hold, released_by=user, release_reason="  ")

    assert exc_info.value.code == "release_reason_required"
    hold.refresh_from_db()
    assert hold.status == LegalHold.Status.ACTIVE


@pytest.mark.django_db
def test_release_already_released_hold_rejected(evidence_change, user):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    hold = create_legal_hold(bundle, reason="Hold")
    release_legal_hold(hold, released_by=user, release_reason="Released.")

    with pytest.raises(DomainValidationError) as exc_info:
        release_legal_hold(hold, released_by=user, release_reason="Released again.")

    assert exc_info.value.code == "legal_hold_not_active"


@pytest.mark.django_db
def test_release_legal_hold_emits_audit_event(
    evidence_change, user, django_capture_on_commit_callbacks
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    hold = create_legal_hold(bundle, reason="Hold for release audit test")

    with django_capture_on_commit_callbacks(execute=True):
        release_legal_hold(hold, released_by=user, release_reason="Resolved.")

    events = AuditEvent.objects.filter(
        event_type="legal_hold.released",
        object_id=hold.id,
    )
    assert events.exists()


# ---------------------------------------------------------------------------
# Active legal hold blocks cleanup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_active_hold_blocks_bundle_cleanup(evidence_change, user, tmp_path, settings):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    _seal_bundle(bundle, tmp_path=tmp_path, settings=settings, user=user)
    bundle.refresh_from_db()
    _make_expired_bundle(bundle)

    create_legal_hold(bundle, reason="Legal matter in progress.")

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_bundle_storage(bundle)

    assert exc_info.value.code == "legal_hold_blocks_cleanup"
    # Storage must not be deleted
    bundle.refresh_from_db()
    assert bundle.storage_deleted_at is None


@pytest.mark.django_db
def test_active_hold_blocks_export_cleanup(evidence_change, user, tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    from apps.evidence.services import create_export, seal_bundle

    seal_bundle(bundle, sealed_by=user)
    bundle.refresh_from_db()

    export = create_export(bundle)
    _make_expired_export(export)
    create_legal_hold(bundle, reason="Hold also covers exports.")

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_export_storage(export)

    assert exc_info.value.code == "legal_hold_blocks_cleanup"
    export.refresh_from_db()
    assert export.storage_deleted_at is None


@pytest.mark.django_db
def test_active_hold_blocks_bundle_cleanup_emits_blocked_event(
    evidence_change, user, tmp_path, settings
):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    from apps.evidence.services import seal_bundle

    seal_bundle(bundle, sealed_by=user)
    bundle.refresh_from_db()
    _make_expired_bundle(bundle)
    hold = create_legal_hold(bundle, reason="Hold blocks cleanup.")

    try:
        cleanup_expired_bundle_storage(bundle)
    except DomainValidationError:
        pass

    events = AuditEvent.objects.filter(
        event_type="evidence.retention_cleanup_blocked",
        object_id=hold.id,
    )
    assert events.exists()
    meta = events.first().metadata
    assert meta["target_type"] == "evidence_bundle"
    assert meta["target_id"] == str(bundle.id)


# ---------------------------------------------------------------------------
# Released hold permits cleanup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_released_hold_permits_bundle_cleanup(evidence_change, user, tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    from apps.evidence.services import seal_bundle

    seal_bundle(bundle, sealed_by=user)
    bundle.refresh_from_db()
    _make_expired_bundle(bundle)

    hold = create_legal_hold(bundle, reason="Temporary hold.")
    release_legal_hold(hold, released_by=user, release_reason="Matter closed.")

    now = timezone.now()
    cleaned = cleanup_expired_bundle_storage(bundle, now=now)

    assert cleaned.storage_deleted_at is not None
    assert cleaned.storage_delete_reason == "retention_expired"
    # Hashes and metadata are preserved
    assert cleaned.manifest_sha256
    assert cleaned.content_sha256
    assert cleaned.storage_key


@pytest.mark.django_db
def test_released_hold_permits_export_cleanup(evidence_change, user, tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    from apps.evidence.services import create_export, seal_bundle

    seal_bundle(bundle, sealed_by=user)
    bundle.refresh_from_db()
    export = create_export(bundle)
    _make_expired_export(export)

    hold = create_legal_hold(bundle, reason="Temporary hold.")
    release_legal_hold(hold, released_by=user, release_reason="Released.")

    cleaned = cleanup_expired_export_storage(export)

    assert cleaned.storage_deleted_at is not None
    assert cleaned.content_sha256


# ---------------------------------------------------------------------------
# Cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cross_tenant_hold_does_not_block_other_org_cleanup(
    evidence_change, user, tmp_path, settings
):
    """A hold on org-A's change must not block org-B's bundle cleanup."""
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    other_org = Organization.objects.create(name="Other Org LH", slug="other-org-lh")

    # Set up org-A bundle under hold
    _complete_closed_change(evidence_change, user)
    bundle_a = create_evidence_bundle_for_change(change_record=evidence_change)
    create_legal_hold(bundle_a, reason="Hold on org A.")

    # Create org-B change and bundle
    from apps.changes.models import OperationProfile
    from apps.runbooks import services as runbook_services
    from apps.workflows import services as workflow_services
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    rb = runbook_services.create_runbook(
        organization=other_org,
        title="Other org runbook",
        slug="other-org-evidence-lh",
        raw_content="Other org runbook",
    )
    wf = workflow_services.create_workflow(
        runbook=rb, transform_client=StubWorkflowTransformClient()
    )
    wf = workflow_services.publish_workflow(workflow=wf)
    profile = OperationProfile.objects.create(
        organization=other_org,
        key="other-profile-lh",
        name="Other Profile",
        risk_level="high",
    )
    profile.allowed_workflows.add(wf)
    change_b = ChangeRecord.objects.create(
        organization=other_org,
        operation_profile=profile,
        workflow=wf,
        title="Other change",
        summary="Other org",
        justification="Required",
    )
    _complete_closed_change(change_b, user)
    bundle_b = create_evidence_bundle_for_change(change_record=change_b)

    from apps.evidence.services import seal_bundle

    seal_bundle(bundle_b, sealed_by=user)
    bundle_b.refresh_from_db()
    _make_expired_bundle(bundle_b)

    # Cleanup of org-B bundle must succeed — org-A hold is irrelevant
    cleaned = cleanup_expired_bundle_storage(bundle_b)
    assert cleaned.storage_deleted_at is not None


@pytest.mark.django_db
def test_assert_no_active_legal_hold_is_org_scoped(evidence_change, user):
    """assert_no_active_legal_hold does not cross org boundaries."""
    other_org = Organization.objects.create(name="Hold Isolation Org", slug="hold-iso-org")
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    create_legal_hold(bundle, reason="Org A hold.")

    # A change in another org should not be affected by org A's hold
    from apps.changes.models import OperationProfile
    from apps.runbooks import services as runbook_services
    from apps.workflows import services as workflow_services
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    rb = runbook_services.create_runbook(
        organization=other_org,
        title="Isolation runbook",
        slug="iso-rb-hold",
        raw_content="Isolation",
    )
    wf = workflow_services.create_workflow(
        runbook=rb, transform_client=StubWorkflowTransformClient()
    )
    wf = workflow_services.publish_workflow(workflow=wf)
    profile = OperationProfile.objects.create(
        organization=other_org,
        key="iso-profile",
        name="Iso Profile",
        risk_level="high",
    )
    profile.allowed_workflows.add(wf)
    change_other = ChangeRecord.objects.create(
        organization=other_org,
        operation_profile=profile,
        workflow=wf,
        title="Iso change",
        summary="Iso",
        justification="Iso",
    )

    # assert_no_active_legal_hold for the other-org change must not raise
    assert_no_active_legal_hold(change_other)


# ---------------------------------------------------------------------------
# Legal hold public API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_legal_hold_api_creates_active_hold(
    evidence_change, user, api_client_for_org
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    client = api_client_for_org(evidence_change.organization)

    response = client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/legal-hold/",
        data={"reason": "External audit matter MATTER-9999"},
        content_type="application/json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == LegalHold.Status.ACTIVE
    assert body["evidence_bundle_id"] == str(bundle.id)


@pytest.mark.django_db
def test_legal_hold_api_rejects_duplicate(evidence_change, user, api_client_for_org):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    client = api_client_for_org(evidence_change.organization)

    client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/legal-hold/",
        data={"reason": "First hold"},
        content_type="application/json",
    )
    response = client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/legal-hold/",
        data={"reason": "Second hold"},
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "legal_hold_already_active"


@pytest.mark.django_db
def test_release_api_requires_admin_role(evidence_change, user, api_client_for_org):
    from apps.organizations.models import MembershipRole

    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    hold = create_legal_hold(bundle, reason="Release API test hold")

    # OPERATOR role — not allowed to release (release is admin-only)
    client = api_client_for_org(
        evidence_change.organization, role=MembershipRole.OPERATOR
    )

    response = client.post(
        f"/api/v1/legal-holds/{hold.id}/release/",
        data={"release_reason": "Should fail"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_release_api_succeeds_for_admin(evidence_change, user, api_client_for_org):
    from apps.organizations.models import MembershipRole

    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)
    hold = create_legal_hold(bundle, reason="Admin release test hold")

    client = api_client_for_org(
        evidence_change.organization, role=MembershipRole.ADMIN
    )

    response = client.post(
        f"/api/v1/legal-holds/{hold.id}/release/",
        data={"release_reason": "Matter resolved."},
        content_type="application/json",
    )

    assert response.status_code == 200
    hold.refresh_from_db()
    assert hold.status == LegalHold.Status.RELEASED
