"""Tests for EvidenceExport creation, receipt, and download audit logging.

Enforces:
- Export ready state requires hashes, size, receipt, and storage key.
- Redaction does not mutate canonical evidence.
- Export audit logging (created + downloaded).
- Export receipt is stable/safe.
- Redacted export omits configured sensitive fields.
"""

import json
import zipfile
from io import BytesIO

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import system_actor
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.evidence.models import (
    EvidenceBundle,
    EvidenceExport,
    EvidenceRedactionPolicy,
    LegalHold,
)
from apps.evidence.services import (
    assert_no_active_legal_hold,
    cleanup_expired_bundle_storage,
    cleanup_expired_export_storage,
    compute_redaction_policy_sha256,
    create_export,
    create_legal_hold,
    seal_bundle,
)
from apps.evidence.storage import EvidenceStorage
from apps.evidence.tests.test_materialization import _complete_closed_change


@pytest.fixture
def evidence_storage_root(tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    return settings.ARTIFACT_MEDIA_ROOT


def _make_redaction_policy(org, *, rules, name="Test Policy", user=None):
    sha256 = compute_redaction_policy_sha256(rules)
    return EvidenceRedactionPolicy.objects.create(
        organization=org,
        name=name,
        rules=rules,
        rules_sha256=sha256,
        is_active=True,
        created_by=user,
    )


def _sealed_bundle(change, user, storage):
    from apps.evidence.services import create_evidence_bundle_for_change

    _complete_closed_change(change, user)
    bundle = create_evidence_bundle_for_change(change_record=change, created_by=user)
    return seal_bundle(bundle, sealed_by=user, storage=storage)


# ---------------------------------------------------------------------------
# Export ready-state constraints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_ready_requires_all_fields(evidence_change, user, evidence_storage_root):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    export = create_export(sealed, requested_by=user, storage=storage)

    assert export.status == EvidenceExport.Status.READY
    assert export.storage_key
    assert export.content_sha256
    assert export.content_size_bytes is not None
    assert export.manifest_sha256
    assert export.receipt_sha256


@pytest.mark.django_db
def test_export_db_check_constraint_enforces_ready_fields(
    evidence_change, user, evidence_storage_root, db
):
    """Creating an export with status=ready but missing fields should fail."""
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    with pytest.raises(Exception):
        EvidenceExport.objects.create(
            organization=sealed.organization,
            bundle=sealed,
            status=EvidenceExport.Status.READY,
            source_manifest_sha256=sealed.manifest_sha256,
            source_bundle_content_sha256=sealed.content_sha256,
            requested_at=timezone.now(),
            # Missing: storage_key, content_sha256, content_size_bytes, manifest_sha256, receipt_sha256
        )


# ---------------------------------------------------------------------------
# Export receipt is stable and safe
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_receipt_contains_source_hashes(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    export = create_export(sealed, requested_by=user, storage=storage)

    receipt = export.receipt
    assert receipt["source_manifest_sha256"] == sealed.manifest_sha256
    assert receipt["source_bundle_content_sha256"] == sealed.content_sha256
    assert receipt["bundle_id"] == str(sealed.id)
    assert receipt["bundle_version"] == sealed.version
    assert receipt["change_record_id"] == str(sealed.change_record_id)
    assert receipt["receipt_type"] == "evidence_export"
    assert receipt["export_id"] == str(export.id)


@pytest.mark.django_db
def test_export_receipt_does_not_expose_raw_tokens(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    export = create_export(sealed, requested_by=user, storage=storage)
    receipt_str = json.dumps(export.receipt)
    for forbidden in ("password", "token", "secret", "dispatch_token", "claim_token"):
        assert (
            forbidden not in receipt_str.lower()
            or receipt_str.lower().count(forbidden) == 0
            or all(
                val not in receipt_str for val in [f'"{forbidden}":', f"'{forbidden}':"]
            )
        )


@pytest.mark.django_db
def test_export_receipt_sha256_matches_canonical_bytes(
    evidence_change, user, evidence_storage_root
):
    from apps.evidence.services import canonical_json_bytes, sha256_hexdigest

    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    export = create_export(sealed, requested_by=user, storage=storage)

    receipt_bytes = canonical_json_bytes(export.receipt)
    assert sha256_hexdigest(receipt_bytes) == export.receipt_sha256


# ---------------------------------------------------------------------------
# Export audit logging
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_export_creation_emits_audit_event(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    before = AuditEvent.objects.filter(event_type="evidence_export.created").count()
    create_export(sealed, requested_by=user, storage=storage)

    assert (
        AuditEvent.objects.filter(event_type="evidence_export.created").count()
        == before + 1
    )
    event = AuditEvent.objects.filter(event_type="evidence_export.created").latest(
        "occurred_at"
    )
    assert event.object_type == AuditEvent.ObjectType.EVIDENCE_EXPORT
    assert str(event.organization_id) == str(sealed.organization_id)


@pytest.mark.django_db
def test_export_download_emits_audit_event(
    evidence_change, user, evidence_storage_root
):
    from apps.evidence.services import download_export

    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    export = create_export(sealed, requested_by=user, storage=storage)

    actor = system_actor("Test download")
    before = AuditEvent.objects.filter(event_type="evidence_export.downloaded").count()
    download_export(export, actor=actor, storage=storage)
    assert (
        AuditEvent.objects.filter(event_type="evidence_export.downloaded").count()
        == before + 1
    )


@pytest.mark.django_db
def test_export_download_rejects_expired_export(
    evidence_change, user, evidence_storage_root
):
    from datetime import timedelta

    from apps.evidence.services import download_export

    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    export = create_export(sealed, requested_by=user, storage=storage)
    EvidenceExport.objects.filter(pk=export.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    export.refresh_from_db()

    with pytest.raises(DomainValidationError) as exc_info:
        download_export(export, actor=system_actor("Expired export"), storage=storage)
    assert exc_info.value.code == "export_expired"


@pytest.mark.django_db(transaction=True)
def test_export_audit_metadata_does_not_contain_redacted_values(
    evidence_change, user, evidence_storage_root, org
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    policy = _make_redaction_policy(
        org,
        rules=[
            {
                "action": "redact_ndjson_field",
                "id": "r1",
                "path": "audit/audit_trail.ndjson",
                "field": "actor_label",
            }
        ],
    )
    create_export(sealed, redaction_policy=policy, requested_by=user, storage=storage)

    event = AuditEvent.objects.filter(event_type="evidence_export.created").latest(
        "occurred_at"
    )
    meta_str = json.dumps(event.metadata)
    assert "[REDACTED]" not in meta_str
    assert "redacted_value" not in meta_str


# ---------------------------------------------------------------------------
# Redaction does not mutate canonical evidence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_redacted_export_does_not_mutate_canonical_bundle(
    evidence_change, user, evidence_storage_root, org
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    original_manifest_sha256 = sealed.manifest_sha256
    original_content_sha256 = sealed.content_sha256
    original_manifest = dict(sealed.manifest)

    policy = _make_redaction_policy(
        org,
        rules=[
            {
                "action": "redact_ndjson_field",
                "id": "r1",
                "path": "audit/audit_trail.ndjson",
                "field": "actor_label",
            }
        ],
    )
    create_export(sealed, redaction_policy=policy, requested_by=user, storage=storage)

    sealed.refresh_from_db()
    assert sealed.manifest_sha256 == original_manifest_sha256
    assert sealed.content_sha256 == original_content_sha256
    assert sealed.manifest == original_manifest

    canonical_bytes = storage.read_bytes(sealed.storage_key)
    from apps.evidence.services import sha256_hexdigest

    assert sha256_hexdigest(canonical_bytes) == original_content_sha256


@pytest.mark.django_db
def test_redacted_export_has_different_content_hash_than_canonical(
    evidence_change, user, evidence_storage_root, org
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    policy = _make_redaction_policy(
        org,
        rules=[{"action": "artifact_metadata_only", "id": "r1"}],
    )
    export = create_export(
        sealed, redaction_policy=policy, requested_by=user, storage=storage
    )

    assert export.content_sha256 != sealed.content_sha256


@pytest.mark.django_db
def test_redacted_export_omits_artifact_bytes(
    evidence_change, user, evidence_storage_root, org
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    policy = _make_redaction_policy(
        org,
        rules=[{"action": "artifact_metadata_only", "id": "r1"}],
    )
    export = create_export(
        sealed, redaction_policy=policy, requested_by=user, storage=storage
    )

    export_bytes = storage.read_bytes(export.storage_key)
    with zipfile.ZipFile(BytesIO(export_bytes)) as zf:
        artifact_file_entries = [
            n for n in zf.namelist() if n.startswith("artifacts/files/")
        ]
    assert len(artifact_file_entries) == 0


@pytest.mark.django_db
def test_unredacted_export_matches_source_structure(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    export = create_export(
        sealed, redaction_policy=None, requested_by=user, storage=storage
    )

    assert export.redaction_summary["redacted"] is False
    assert export.status == EvidenceExport.Status.READY

    export_bytes = storage.read_bytes(export.storage_key)
    with zipfile.ZipFile(BytesIO(export_bytes)) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert "checksums.sha256" in names
    assert "exports/export_receipt.json" in names


# ---------------------------------------------------------------------------
# Export receipt inside ZIP has receipt_type=evidence_export
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_export_zip_receipt_has_correct_receipt_type(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    export = create_export(sealed, requested_by=user, storage=storage)

    export_bytes = storage.read_bytes(export.storage_key)
    with zipfile.ZipFile(BytesIO(export_bytes)) as zf:
        receipt_raw = zf.read("exports/export_receipt.json")

    receipt = json.loads(receipt_raw)
    assert receipt["receipt_type"] == "evidence_export"
    assert receipt["export_id"] == str(export.id)
    assert receipt["bundle_id"] == str(sealed.id)
    assert receipt["source_manifest_sha256"] == sealed.manifest_sha256


# ---------------------------------------------------------------------------
# Export fails on unsealed bundle
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_export_rejects_unsealed_bundle(
    evidence_change, user, evidence_storage_root
):
    from apps.evidence.services import create_evidence_bundle_for_change

    storage = EvidenceStorage()
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(
        change_record=evidence_change, created_by=user
    )

    with pytest.raises(DomainValidationError) as exc_info:
        create_export(bundle, requested_by=user, storage=storage)
    assert exc_info.value.code == "bundle_not_sealed"


@pytest.mark.django_db
def test_create_export_rejects_inactive_redaction_policy(
    evidence_change, user, evidence_storage_root, org
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    policy = _make_redaction_policy(org, rules=[])
    policy.is_active = False
    policy.save(update_fields=["is_active", "updated_at"])

    with pytest.raises(DomainValidationError) as exc_info:
        create_export(
            sealed, redaction_policy=policy, requested_by=user, storage=storage
        )
    assert exc_info.value.code == "redaction_policy_inactive"


# ---------------------------------------------------------------------------
# Legal hold
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_legal_hold_creates_active_hold(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    hold = create_legal_hold(
        sealed,
        reason="External audit matter 1234",
        external_reference="MATTER-1234",
        placed_by=user,
    )

    assert hold.status == LegalHold.Status.ACTIVE
    assert hold.change_record_id == sealed.change_record_id
    assert hold.evidence_bundle_id == sealed.id


@pytest.mark.django_db
def test_create_legal_hold_rejects_duplicate(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    create_legal_hold(sealed, reason="First hold", placed_by=user)

    with pytest.raises(DomainConflictError) as exc_info:
        create_legal_hold(sealed, reason="Second hold", placed_by=user)
    assert exc_info.value.code == "legal_hold_already_active"


@pytest.mark.django_db
def test_legal_hold_blocks_bundle_cleanup(evidence_change, user, evidence_storage_root):
    from datetime import timedelta

    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)

    EvidenceBundle.objects.filter(pk=sealed.pk).update(
        retention_expires_at=timezone.now() - timedelta(days=1)
    )
    sealed.refresh_from_db()

    create_legal_hold(sealed, reason="Litigation hold", placed_by=user)

    with pytest.raises(DomainValidationError) as exc_info:
        cleanup_expired_bundle_storage(sealed, storage=storage)
    assert exc_info.value.code == "legal_hold_blocks_cleanup"


@pytest.mark.django_db
def test_assert_no_active_legal_hold_passes_when_no_hold(
    evidence_change, user, evidence_storage_root
):
    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    assert_no_active_legal_hold(sealed.change_record, bundle=sealed)


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cleanup_expired_bundle_storage_deletes_bytes(
    evidence_change, user, evidence_storage_root
):
    from datetime import timedelta

    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    EvidenceBundle.objects.filter(pk=sealed.pk).update(
        retention_expires_at=timezone.now() - timedelta(days=1)
    )
    sealed.refresh_from_db()

    assert storage.exists(sealed.storage_key)
    cleanup_expired_bundle_storage(sealed, storage=storage)
    assert not storage.exists(sealed.storage_key)

    sealed.refresh_from_db()
    assert sealed.storage_deleted_at is not None
    assert sealed.content_sha256  # hashes preserved
    assert sealed.manifest_sha256


@pytest.mark.django_db
def test_cleanup_expired_export_storage_deletes_bytes(
    evidence_change, user, evidence_storage_root
):
    from datetime import timedelta

    storage = EvidenceStorage()
    sealed = _sealed_bundle(evidence_change, user, storage)
    export = create_export(sealed, requested_by=user, storage=storage)

    EvidenceExport.objects.filter(pk=export.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    export.refresh_from_db()

    assert storage.exists(export.storage_key)
    cleanup_expired_export_storage(export, storage=storage)
    assert not storage.exists(export.storage_key)

    export.refresh_from_db()
    assert export.storage_deleted_at is not None
    assert export.content_sha256  # hashes preserved
