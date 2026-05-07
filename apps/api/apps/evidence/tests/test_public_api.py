import pytest

from apps.audit.models import AuditEvent
from apps.evidence.models import EvidenceBundle
from apps.evidence.services import create_evidence_bundle_for_change
from apps.evidence.storage import EvidenceStorage
from apps.evidence.tests.test_materialization import (
    _close_change,
    _complete_closed_change,
    _execution,
    _verification,
)
from apps.organizations.models import MembershipRole, Organization


@pytest.fixture
def evidence_storage_root(tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    return settings.ARTIFACT_MEDIA_ROOT


@pytest.fixture
def client(org, api_client_for_org):
    return api_client_for_org(org)


def _complete_bundle(change, user):
    _complete_closed_change(change, user)
    return create_evidence_bundle_for_change(change_record=change, created_by=user)


@pytest.mark.django_db
def test_list_bundles_rejects_cross_tenant(evidence_change, user, api_client_for_org):
    bundle = _complete_bundle(evidence_change, user)
    other_org = Organization.objects.create(name="Other Org", slug="other-evidence")
    other_client = api_client_for_org(other_org)

    response = other_client.get(
        f"/api/v1/changes/{evidence_change.id}/evidence-bundles/"
    )
    detail_response = other_client.get(f"/api/v1/evidence-bundles/{bundle.id}/")

    assert response.status_code == 404
    assert detail_response.status_code == 404


@pytest.mark.django_db
def test_create_bundle_rejects_non_closed_change(evidence_change, client):
    response = client.post(
        f"/api/v1/changes/{evidence_change.id}/evidence-bundles/",
        data={},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "evidence_change_not_closed"


@pytest.mark.django_db
def test_seal_rejects_incomplete_bundle(evidence_change, user, client):
    _execution(evidence_change)
    _verification(evidence_change, user)
    _close_change(evidence_change)
    bundle = create_evidence_bundle_for_change(
        change_record=evidence_change,
        created_by=user,
    )

    response = client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/seal/",
        data={},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "evidence_bundle_not_complete"


@pytest.mark.django_db
def test_sealed_detail_exposes_manifest_and_completeness_safely(
    evidence_change,
    user,
    client,
    evidence_storage_root,
):
    bundle = _complete_bundle(evidence_change, user)

    seal_response = client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/seal/",
        data={},
        content_type="application/json",
    )
    assert seal_response.status_code == 200
    body = seal_response.json()

    assert body["status"] == EvidenceBundle.Status.SEALED
    assert body["manifest_sha256"]
    assert body["manifest"]["package_type"] == "sealed_bundle"
    assert body["completeness_status"] == EvidenceBundle.CompletenessStatus.COMPLETE
    assert body["completeness_report"]["summary"]["missing_required_count"] == 0
    assert "storage_key" not in body
    assert "download_url" not in body
    assert "token" not in body

    manifest_response = client.get(f"/api/v1/evidence-bundles/{bundle.id}/manifest/")
    completeness_response = client.get(
        f"/api/v1/evidence-bundles/{bundle.id}/completeness/"
    )

    assert manifest_response.status_code == 200
    assert "storage_key" not in manifest_response.json()
    assert completeness_response.status_code == 200
    assert "source_metadata" not in str(completeness_response.json())


@pytest.mark.django_db
def test_mutation_routes_reject_viewer_role(
    evidence_change,
    user,
    api_client_for_org,
    evidence_storage_root,
):
    bundle = _complete_bundle(evidence_change, user)
    viewer_client = api_client_for_org(
        evidence_change.organization,
        role=MembershipRole.VIEWER,
    )

    create_response = viewer_client.post(
        f"/api/v1/changes/{evidence_change.id}/evidence-bundles/",
        data={},
        content_type="application/json",
    )
    seal_response = viewer_client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/seal/",
        data={},
        content_type="application/json",
    )
    invalidate_response = viewer_client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/invalidate/",
        data={"reason": "defect"},
        content_type="application/json",
    )

    assert create_response.status_code == 403
    assert seal_response.status_code == 403
    assert invalidate_response.status_code == 403


@pytest.mark.django_db
def test_audit_events_emitted_safely(
    evidence_change,
    user,
    client,
    django_capture_on_commit_callbacks,
    evidence_storage_root,
):
    _complete_closed_change(evidence_change, user)

    with django_capture_on_commit_callbacks(execute=True):
        create_response = client.post(
            f"/api/v1/changes/{evidence_change.id}/evidence-bundles/",
            data={},
            content_type="application/json",
        )
        assert create_response.status_code == 201
        bundle_id = create_response.json()["id"]

        seal_response = client.post(
            f"/api/v1/evidence-bundles/{bundle_id}/seal/",
            data={},
            content_type="application/json",
        )
        assert seal_response.status_code == 200
        download_response = client.post(
            f"/api/v1/evidence-bundles/{bundle_id}/download/",
            data={},
            content_type="application/json",
        )
        assert download_response.status_code == 200
        assert "token=" in download_response.json()["download_url"]

        invalidate_response = client.post(
            f"/api/v1/evidence-bundles/{bundle_id}/invalidate/",
            data={"reason": "source defect"},
            content_type="application/json",
        )
        assert invalidate_response.status_code == 200

    events = AuditEvent.objects.filter(
        object_id=bundle_id,
        event_type__in=[
            "evidence_bundle.materialized",
            "evidence_bundle.sealed",
            "evidence_bundle.downloaded",
            "evidence_bundle.invalidated",
        ],
    )
    assert {event.event_type for event in events} == {
        "evidence_bundle.materialized",
        "evidence_bundle.sealed",
        "evidence_bundle.downloaded",
        "evidence_bundle.invalidated",
    }
    for event in events:
        encoded = str(event.metadata)
        assert "storage_key" not in encoded
        assert "download_url" not in encoded
        assert "token" not in encoded
        assert "raw_manifest" not in encoded


@pytest.mark.django_db
def test_download_grant_allows_sealed_bundle_content(
    evidence_change,
    user,
    client,
    evidence_storage_root,
):
    bundle = _complete_bundle(evidence_change, user)
    sealed = client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/seal/",
        data={},
        content_type="application/json",
    ).json()

    grant_response = client.post(
        f"/api/v1/evidence-bundles/{bundle.id}/download/",
        data={},
        content_type="application/json",
    )
    content_response = client.get(grant_response.json()["download_url"])

    assert content_response.status_code == 200
    body = b"".join(content_response.streaming_content)
    assert len(body) == sealed["content_size_bytes"]
    assert EvidenceStorage().size(
        EvidenceBundle.objects.get(pk=bundle.id).storage_key
    ) == sealed["content_size_bytes"]
