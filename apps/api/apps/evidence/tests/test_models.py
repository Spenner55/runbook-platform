import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.evidence.models import (
    EvidenceBundle,
    EvidenceBundleItem,
    EvidenceExport,
    EvidenceRedactionPolicy,
    EvidenceRetentionPolicy,
    LegalHold,
)
from apps.evidence.services import assert_bundle_mutable


def _bundle(change, **overrides):
    defaults = {
        "organization": change.organization,
        "change_record": change,
        "version": 1,
        "source_cutoff_at": timezone.now(),
    }
    defaults.update(overrides)
    return EvidenceBundle.objects.create(**defaults)


def _sealed_bundle(change, **overrides):
    now = timezone.now()
    defaults = {
        "status": EvidenceBundle.Status.SEALED,
        "completeness_status": EvidenceBundle.CompletenessStatus.COMPLETE,
        "sealed_at": now,
        "manifest_sha256": "a" * 64,
        "content_sha256": "b" * 64,
        "content_size_bytes": 128,
        "storage_key": f"evidence/{change.organization_id}/{change.id}/bundle.zip",
    }
    defaults.update(overrides)
    return _bundle(change, **defaults)


@pytest.mark.django_db
def test_evidence_bundle_uses_uuid_pk(evidence_change):
    bundle = _bundle(evidence_change)
    assert bundle.pk is not None
    assert len(str(bundle.pk)) == 36


@pytest.mark.django_db
def test_evidence_bundle_version_unique_per_change(evidence_change):
    _bundle(evidence_change, version=1)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _bundle(evidence_change, version=1)


@pytest.mark.django_db
def test_evidence_bundle_invalid_status_rejected(evidence_change):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _bundle(evidence_change, status="bad_status")


@pytest.mark.django_db
def test_evidence_item_invalid_type_rejected(evidence_change):
    bundle = _bundle(evidence_change)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            EvidenceBundleItem.objects.create(
                organization=evidence_change.organization,
                bundle=bundle,
                item_type="bad_type",
                item_key="change",
                canonical_path="change/change_record.json",
            )


@pytest.mark.django_db
def test_sealed_bundle_requires_storage_and_hash_fields(evidence_change):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _bundle(
                evidence_change,
                status=EvidenceBundle.Status.SEALED,
                sealed_at=timezone.now(),
            )


@pytest.mark.django_db
def test_sealed_bundle_content_fields_are_immutable(evidence_change):
    bundle = _sealed_bundle(evidence_change)
    bundle.content_sha256 = "c" * 64

    with pytest.raises(ValidationError) as exc_info:
        bundle.save()

    assert exc_info.value.code == "evidence_bundle_immutable"


@pytest.mark.django_db
def test_sealed_bundle_can_be_invalidated_with_reason(evidence_change):
    bundle = _sealed_bundle(evidence_change)
    bundle.status = EvidenceBundle.Status.INVALIDATED
    bundle.invalidated_at = timezone.now()
    bundle.invalidation_reason = "superseded"
    bundle.save()

    bundle.refresh_from_db()
    assert bundle.status == EvidenceBundle.Status.INVALIDATED


@pytest.mark.django_db
def test_sealed_bundle_items_cannot_be_added(evidence_change):
    bundle = _sealed_bundle(evidence_change)

    with pytest.raises(ValidationError) as exc_info:
        EvidenceBundleItem.objects.create(
            organization=evidence_change.organization,
            bundle=bundle,
            item_type=EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
            item_key="change",
            canonical_path="change/change_record.json",
        )

    assert exc_info.value.code == "evidence_bundle_immutable"


@pytest.mark.django_db
def test_service_guard_rejects_sealed_bundle(evidence_change):
    bundle = _sealed_bundle(evidence_change)

    with pytest.raises(ValidationError) as exc_info:
        assert_bundle_mutable(bundle)

    assert exc_info.value.code == "evidence_bundle_immutable"


@pytest.mark.django_db
def test_service_guard_allows_compiling_bundle(evidence_change):
    bundle = _bundle(evidence_change)

    assert_bundle_mutable(bundle)


@pytest.mark.django_db
def test_redaction_default_policy_unique_per_organization(org):
    EvidenceRedactionPolicy.objects.create(
        organization=org,
        name="Default",
        is_default=True,
        rules_sha256="a" * 64,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            EvidenceRedactionPolicy.objects.create(
                organization=org,
                name="Other default",
                is_default=True,
                rules_sha256="b" * 64,
            )


@pytest.mark.django_db
def test_retention_days_must_be_positive(org):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            EvidenceRetentionPolicy.objects.create(
                organization=org,
                name="Bad retention",
                sealed_bundle_retention_days=0,
                invalidated_bundle_retention_days=30,
                export_retention_days=7,
            )


@pytest.mark.django_db
def test_ready_export_requires_receipt_storage_and_hash_fields(evidence_change):
    bundle = _sealed_bundle(evidence_change)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            EvidenceExport.objects.create(
                organization=evidence_change.organization,
                bundle=bundle,
                status=EvidenceExport.Status.READY,
                ready_at=timezone.now(),
                source_manifest_sha256=bundle.manifest_sha256,
                source_bundle_content_sha256=bundle.content_sha256,
            )


@pytest.mark.django_db
def test_legal_hold_release_requires_actor_time_and_reason(evidence_change, user):
    with pytest.raises(ValidationError) as exc_info:
        LegalHold.objects.create(
            organization=evidence_change.organization,
            change_record=evidence_change,
            status=LegalHold.Status.RELEASED,
            reason="Matter hold",
            released_by=user,
            released_at=timezone.now(),
            release_reason="",
        )

    assert exc_info.value.code == "legal_hold_release_fields_required"


@pytest.mark.django_db
def test_legal_hold_invalid_status_rejected(evidence_change):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            LegalHold.objects.create(
                organization=evidence_change.organization,
                change_record=evidence_change,
                status="bad_status",
                reason="Matter hold",
            )
