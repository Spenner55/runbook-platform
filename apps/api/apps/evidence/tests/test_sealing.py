import io
import zipfile
from datetime import UTC, datetime, timedelta
from datetime import timezone as datetime_timezone

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.evidence.models import EvidenceBundle, EvidenceBundleItem
from apps.evidence.services import (
    build_sealed_bundle_package,
    canonical_checksums_bytes,
    canonical_json_bytes,
    canonical_ndjson_bytes,
    create_evidence_bundle_for_change,
    seal_bundle,
    sha256_hexdigest,
)
from apps.evidence.storage import EvidenceStorage
from apps.evidence.tests.test_materialization import _complete_closed_change


@pytest.fixture
def evidence_storage_root(tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    return settings.ARTIFACT_MEDIA_ROOT


def test_canonical_json_stable_across_dict_insertion_order():
    first = {"b": 2, "a": {"d": 4, "c": 3}}
    second = {"a": {"c": 3, "d": 4}, "b": 2}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_bytes(first) == b'{"a":{"c":3,"d":4},"b":2}'


def test_utc_timestamp_format_is_stable_for_equivalent_datetimes():
    utc_value = datetime(2026, 5, 7, 12, 34, 56, 789, tzinfo=UTC)
    offset_value = datetime(
        2026,
        5,
        7,
        6,
        34,
        56,
        789,
        tzinfo=datetime_timezone(timedelta(hours=-6)),
    )

    expected = b'{"ts":"2026-05-07T12:34:56.000789Z"}'
    assert canonical_json_bytes({"ts": utc_value}) == expected
    assert canonical_json_bytes({"ts": offset_value}) == expected


def test_ndjson_has_one_trailing_lf_when_non_empty():
    assert canonical_ndjson_bytes([{"b": 2, "a": 1}]) == b'{"a":1,"b":2}\n'
    assert canonical_ndjson_bytes([]) == b""


def test_checksums_are_lexicographic_and_exclude_self():
    entries = {
        "z/file.txt": b"z",
        "checksums.sha256": b"recursive",
        "a/file.txt": b"a",
        "manifest.json": b"manifest",
    }

    checksum_lines = canonical_checksums_bytes(entries).decode("utf-8").splitlines()

    assert [line.split("  ", 1)[1] for line in checksum_lines] == [
        "a/file.txt",
        "manifest.json",
        "z/file.txt",
    ]
    assert "checksums.sha256" not in "\n".join(checksum_lines)


@pytest.mark.django_db
def test_repeated_package_generation_for_same_projection_has_same_hash(
    evidence_change,
    user,
    evidence_storage_root,
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(
        change_record=evidence_change,
        created_by=user,
    )
    bundle.sealed_at = timezone.make_aware(datetime(2026, 5, 7, 12, 0, 0), UTC)
    bundle.save(update_fields=["sealed_at", "updated_at"])

    first = build_sealed_bundle_package(bundle, storage=EvidenceStorage())
    second = build_sealed_bundle_package(bundle, storage=EvidenceStorage())

    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["content_sha256"] == second["content_sha256"]


@pytest.mark.django_db
def test_seal_generates_deterministic_zip_and_persists_hashes(
    evidence_change,
    user,
    evidence_storage_root,
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(
        change_record=evidence_change,
        created_by=user,
    )

    sealed = seal_bundle(bundle, sealed_by=user, storage=EvidenceStorage())

    assert sealed.status == EvidenceBundle.Status.SEALED
    assert sealed.manifest_sha256 == sha256_hexdigest(
        canonical_json_bytes(sealed.manifest)
    )
    assert sealed.payload_checksums_sha256
    assert sealed.content_sha256
    assert sealed.content_size_bytes > 0
    assert sealed.storage_key
    storage = EvidenceStorage()
    assert storage.exists(sealed.storage_key)
    assert storage.size(sealed.storage_key) == sealed.content_size_bytes

    zip_bytes = storage.read_bytes(sealed.storage_key)
    assert sha256_hexdigest(zip_bytes) == sealed.content_sha256
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "manifest.json" in names
        assert "checksums.sha256" in names
        checksum_text = archive.read("checksums.sha256").decode("utf-8")
        assert "checksums.sha256" not in checksum_text
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_STORED
            assert (info.external_attr >> 16) & 0o777 == 0o644


@pytest.mark.django_db
def test_sealed_bundle_and_item_mutation_are_blocked(
    evidence_change,
    user,
    evidence_storage_root,
):
    _complete_closed_change(evidence_change, user)
    bundle = create_evidence_bundle_for_change(
        change_record=evidence_change,
        created_by=user,
    )
    sealed = seal_bundle(bundle, sealed_by=user, storage=EvidenceStorage())

    sealed.content_sha256 = "f" * 64
    with pytest.raises(ValidationError) as bundle_error:
        sealed.save()
    assert bundle_error.value.code == "evidence_bundle_immutable"

    item = EvidenceBundleItem.objects.filter(bundle=sealed).first()
    item.source_metadata = {"changed": True}
    with pytest.raises(ValidationError) as item_error:
        item.save()
    assert item_error.value.code == "evidence_bundle_immutable"
