"""Tests for retention policy evaluation and cleanup behavior.

Hard rules verified here:
- Cleanup deletes only stored ZIP bytes; sealed manifest, hashes, and DB row survive.
- Retention cleanup never mutates sealed evidence.
- Active legal holds block cleanup.
- Released holds permit cleanup after expiry.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.common.exceptions import DomainValidationError
from apps.evidence.models import (
    EvidenceBundle,
    EvidenceExport,
    EvidenceRetentionPolicy,
)
from apps.evidence.services import (
    cleanup_expired_bundle_storage,
    cleanup_expired_export_storage,
    create_evidence_bundle_for_change,
    create_export,
    create_legal_hold,
    release_legal_hold,
    seal_bundle,
)
from apps.evidence.storage import EvidenceStorage
from apps.evidence.tests.test_materialization import _complete_closed_change

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def storage_root(tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    return settings.ARTIFACT_MEDIA_ROOT


@pytest.fixture
def default_retention_policy(org):
    return EvidenceRetentionPolicy.objects.create(
        organization=org,
        name="Default 7y",
        sealed_bundle_retention_days=2557,
        invalidated_bundle_retention_days=2557,
        export_retention_days=30,
        is_default=True,
        is_active=True,
    )


def _sealed_bundle(change, user):
    bundle = create_evidence_bundle_for_change(change_record=change)
    return seal_bundle(bundle, sealed_by=user)


def _make_bundle_expired(bundle, days=1):
    past = timezone.now() - timedelta(days=days)
    EvidenceBundle.objects.filter(pk=bundle.pk).update(retention_expires_at=past)
    bundle.refresh_from_db()
    return bundle


def _make_export_expired(export, days=1):
    past = timezone.now() - timedelta(days=days)
    EvidenceExport.objects.filter(pk=export.pk).update(expires_at=past)
    export.refresh_from_db()
    return export


# ---------------------------------------------------------------------------
# Retention policy resolution at seal time
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_seal_sets_retention_policy_and_expires_at_when_default_exists(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    sealed = seal_bundle(bundle, sealed_by=user)
    sealed.refresh_from_db()

    assert sealed.retention_policy_id == default_retention_policy.id
    assert sealed.retention_expires_at is not None
    expected = sealed.sealed_at + timedelta(days=default_retention_policy.sealed_bundle_retention_days)
    assert abs((sealed.retention_expires_at - expected).total_seconds()) < 5


@pytest.mark.django_db
def test_seal_without_retention_policy_leaves_expires_at_null(
    evidence_change, user, storage_root
):
    """When no default retention policy exists, retention_expires_at stays null."""
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    sealed = seal_bundle(bundle, sealed_by=user)
    sealed.refresh_from_db()

    assert sealed.retention_policy_id is None
    assert sealed.retention_expires_at is None


# ---------------------------------------------------------------------------
# Cleanup behavior: only bytes are deleted
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cleanup_deletes_bytes_keeps_db_row_and_hashes(
    evidence_change, user, default_retention_policy, storage_root
):
    """Retention cleanup deletes stored ZIP only; manifest hashes and DB row survive."""
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()

    original_manifest_sha256 = bundle.manifest_sha256
    original_content_sha256 = bundle.content_sha256
    original_storage_key = bundle.storage_key
    assert original_storage_key

    _make_bundle_expired(bundle)
    now = timezone.now()
    cleaned = cleanup_expired_bundle_storage(bundle, now=now)

    # Storage bytes gone
    storage = EvidenceStorage()
    assert not storage.exists(original_storage_key)

    # DB row and integrity fields preserved
    assert cleaned.storage_deleted_at is not None
    assert cleaned.storage_delete_reason == "retention_expired"
    assert cleaned.manifest_sha256 == original_manifest_sha256
    assert cleaned.content_sha256 == original_content_sha256
    assert cleaned.storage_key == original_storage_key  # key itself is preserved


@pytest.mark.django_db
def test_cleanup_never_modifies_sealed_manifest_json(
    evidence_change, user, default_retention_policy, storage_root
):
    """Cleanup must never mutate manifest, hashes, items, or any sealed fields."""
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()

    pre_manifest = bundle.manifest
    pre_items = list(bundle.items.values("id", "content_sha256", "canonical_path"))

    _make_bundle_expired(bundle)
    cleanup_expired_bundle_storage(bundle)
    bundle.refresh_from_db()

    assert bundle.manifest == pre_manifest
    post_items = list(bundle.items.values("id", "content_sha256", "canonical_path"))
    assert post_items == pre_items


@pytest.mark.django_db
def test_cleanup_export_deletes_bytes_keeps_metadata(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()

    export = create_export(bundle)
    original_content_sha256 = export.content_sha256
    original_storage_key = export.storage_key

    _make_export_expired(export)
    now = timezone.now()
    cleaned = cleanup_expired_export_storage(export, now=now)

    storage = EvidenceStorage()
    assert not storage.exists(original_storage_key)

    assert cleaned.storage_deleted_at is not None
    assert cleaned.content_sha256 == original_content_sha256
    assert cleaned.storage_key == original_storage_key


@pytest.mark.django_db
def test_cleanup_rejects_not_expired_bundle(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    # retention_expires_at is in the future after sealing with a 7-year policy

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_bundle_storage(bundle)

    assert exc_info.value.code == "retention_not_expired"
    bundle.refresh_from_db()
    assert bundle.storage_deleted_at is None


@pytest.mark.django_db
def test_cleanup_rejects_not_expired_export(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    export = create_export(bundle)
    # expires_at is in the future

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_export_storage(export)

    assert exc_info.value.code == "retention_not_expired"


@pytest.mark.django_db
def test_cleanup_bundle_idempotent_when_already_deleted(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    _make_bundle_expired(bundle)

    cleanup_expired_bundle_storage(bundle)
    bundle.refresh_from_db()
    first_deleted_at = bundle.storage_deleted_at

    result = cleanup_expired_bundle_storage(bundle)
    assert result.storage_deleted_at == first_deleted_at


# ---------------------------------------------------------------------------
# Legal hold overrides retention
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_active_change_level_hold_blocks_bundle_cleanup(
    evidence_change, user, default_retention_policy, storage_root
):
    """A hold on the change (no specific bundle) blocks all bundle cleanup for that change."""
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    _make_bundle_expired(bundle)

    # Create a hold pointing to this bundle (and thus its change record)
    create_legal_hold(bundle, reason="Change-level hold.")

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_bundle_storage(bundle)

    assert exc_info.value.code == "legal_hold_blocks_cleanup"


@pytest.mark.django_db
def test_active_bundle_hold_blocks_derived_export_cleanup(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    export = create_export(bundle)
    _make_export_expired(export)

    create_legal_hold(bundle, reason="Hold blocks export cleanup.")

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_export_storage(export)

    assert exc_info.value.code == "legal_hold_blocks_cleanup"


@pytest.mark.django_db
def test_released_hold_permits_bundle_cleanup_after_expiry(
    evidence_change, user, default_retention_policy, storage_root
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    _make_bundle_expired(bundle)

    hold = create_legal_hold(bundle, reason="Temporary hold.")
    release_legal_hold(hold, released_by=user, release_reason="Matter resolved.")

    cleaned = cleanup_expired_bundle_storage(bundle)
    assert cleaned.storage_deleted_at is not None


# ---------------------------------------------------------------------------
# Retention audit events
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bundle_cleanup_emits_retention_deleted_event(
    evidence_change, user, default_retention_policy, storage_root,
    django_capture_on_commit_callbacks,
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    original_content_sha256 = bundle.content_sha256
    _make_bundle_expired(bundle)

    with django_capture_on_commit_callbacks(execute=True):
        cleanup_expired_bundle_storage(bundle)

    events = AuditEvent.objects.filter(
        event_type="evidence_bundle.retention_deleted",
        object_id=bundle.id,
    )
    assert events.exists()
    meta = events.first().metadata
    assert meta.get("content_sha256") == original_content_sha256


@pytest.mark.django_db
def test_export_cleanup_emits_retention_deleted_event(
    evidence_change, user, default_retention_policy, storage_root,
    django_capture_on_commit_callbacks,
):
    _complete_closed_change(evidence_change, user)
    bundle = _sealed_bundle(evidence_change, user)
    bundle.refresh_from_db()
    export = create_export(bundle)
    _make_export_expired(export)

    with django_capture_on_commit_callbacks(execute=True):
        cleanup_expired_export_storage(export)

    events = AuditEvent.objects.filter(
        event_type="evidence_export.retention_deleted",
        object_id=export.id,
    )
    assert events.exists()
