import pytest
from django.utils import timezone

from apps.auditor.models import (
    ControlCoverageStatus,
    ControlMappingProfile,
    ControlStandard,
)
from apps.auditor.services import recompute_change_control_coverage
from apps.changes.models import ChangeRecord, ChangeTarget, OperationProfile
from apps.common.exceptions import DomainValidationError
from apps.evidence.models import EvidenceBundle, EvidenceBundleItem
from apps.runbooks.models import Runbook
from apps.workflows.models import Workflow


def _change(org, *, title="Coverage change", risk="high", is_emergency=False):
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
        is_emergency=is_emergency,
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


def _bundle(change, *, complete=True, seal=True, include_approval=True):
    now = timezone.now()
    bundle = EvidenceBundle.objects.create(
        organization=change.organization,
        change_record=change,
        version=1,
        status=EvidenceBundle.Status.COMPILING,
        completeness_status=(
            EvidenceBundle.CompletenessStatus.COMPLETE
            if complete
            else EvidenceBundle.CompletenessStatus.INCOMPLETE
        ),
        source_cutoff_at=now,
        manifest={
            "items": [
                {"canonical_path": "request/change_record.json"},
                {"canonical_path": "approval/approval_request.json"},
            ]
        },
        manifest_sha256="a" * 64,
        content_sha256="b" * 64,
        content_size_bytes=128,
        storage_key=f"evidence/{change.organization_id}/{change.id}/bundle.zip",
    )
    EvidenceBundleItem.objects.create(
        organization=change.organization,
        bundle=bundle,
        item_type=EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT,
        item_key="change",
        canonical_path="request/change_record.json",
        position=1,
        present=True,
        valid=True,
    )
    if include_approval:
        EvidenceBundleItem.objects.create(
            organization=change.organization,
            bundle=bundle,
            item_type=EvidenceBundleItem.ItemType.APPROVAL,
            item_key="approval",
            canonical_path="approval/approval_request.json",
            position=2,
            present=True,
            valid=True,
        )
    if seal:
        bundle.status = EvidenceBundle.Status.SEALED
        bundle.sealed_at = now
        bundle.save()
    return bundle


def _profile(org, *, active=True):
    return ControlMappingProfile.objects.create(
        organization=org,
        key="soc2-change-controls",
        name="SOC 2 change controls",
        standard=ControlStandard.SOC2,
        mapping_rules=[
            {
                "control_id": "CC8.1",
                "control_title": "Change authorization",
                "required_sections": ["request", "approval"],
                "required_item_types": ["change_snapshot", "approval"],
                "applicability": {"risk": ["high", "critical"]},
            },
            {
                "control_id": "CC8.2",
                "control_title": "Emergency change review",
                "required_sections": ["exception"],
                "applicability": {"change_type": ["emergency"]},
            },
        ],
        is_active=active,
    )


@pytest.mark.django_db
def test_recompute_control_coverage_is_deterministic_for_sealed_bundle(org):
    change = _change(org)
    bundle = _bundle(change)
    profile = _profile(org)

    first = recompute_change_control_coverage(
        change_record=change,
        evidence_bundle=bundle,
        mapping_profile=profile,
    )
    second = recompute_change_control_coverage(
        change_record=change,
        evidence_bundle=bundle,
        mapping_profile=profile,
    )

    first_payload = [
        (
            row.control_id,
            row.coverage_status,
            row.matched_sections,
            row.missing_sections,
            row.evidence_paths,
            row.coverage_fingerprint_sha256,
        )
        for row in first
    ]
    second_payload = [
        (
            row.control_id,
            row.coverage_status,
            row.matched_sections,
            row.missing_sections,
            row.evidence_paths,
            row.coverage_fingerprint_sha256,
        )
        for row in second
    ]

    assert first_payload == second_payload
    assert first[0].coverage_status == ControlCoverageStatus.COVERED
    assert first[1].coverage_status == ControlCoverageStatus.NOT_APPLICABLE


@pytest.mark.django_db
def test_recompute_rejects_unsealed_bundle(org):
    change = _change(org)
    bundle = _bundle(change, seal=False)
    profile = _profile(org)

    with pytest.raises(DomainValidationError) as exc:
        recompute_change_control_coverage(
            change_record=change,
            evidence_bundle=bundle,
            mapping_profile=profile,
        )

    assert exc.value.code == "sealed_bundle_required"


@pytest.mark.django_db
def test_incomplete_bundle_does_not_satisfy_final_coverage(org):
    change = _change(org)
    bundle = _bundle(change, complete=False)
    profile = _profile(org)

    rows = recompute_change_control_coverage(
        change_record=change,
        evidence_bundle=bundle,
        mapping_profile=profile,
    )

    covered = [row for row in rows if row.control_id == "CC8.1"][0]
    assert covered.coverage_status == ControlCoverageStatus.NOT_COVERED
    assert covered.missing_sections == ["bundle:complete"]


@pytest.mark.django_db
def test_missing_required_items_are_partial_not_covered(org):
    change = _change(org)
    bundle = _bundle(change, include_approval=False)
    profile = _profile(org)

    rows = recompute_change_control_coverage(
        change_record=change,
        evidence_bundle=bundle,
        mapping_profile=profile,
    )

    row = [item for item in rows if item.control_id == "CC8.1"][0]
    assert row.coverage_status == ControlCoverageStatus.PARTIALLY_COVERED
    assert row.matched_sections == ["item_type:change_snapshot", "section:request"]
    assert row.missing_sections == ["item_type:approval", "section:approval"]


@pytest.mark.django_db
def test_recompute_requires_matching_org_and_change(org):
    other_change = _change(org, title="Other coverage change")
    change = _change(org)
    bundle = _bundle(change)
    profile = _profile(org)

    with pytest.raises(DomainValidationError) as exc:
        recompute_change_control_coverage(
            change_record=other_change,
            evidence_bundle=bundle,
            mapping_profile=profile,
        )

    assert exc.value.code == "bundle_change_mismatch"
