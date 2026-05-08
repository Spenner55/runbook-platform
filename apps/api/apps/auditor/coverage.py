from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.auditor.models import (
    ChangeControlCoverage,
    ControlCoverageStatus,
    canonical_json_sha256,
)
from apps.common.exceptions import DomainValidationError
from apps.evidence.models import EvidenceBundle


@dataclass(frozen=True)
class CoverageResult:
    control_id: str
    control_title: str
    coverage_status: str
    matched_sections: list[str]
    missing_sections: list[str]
    evidence_paths: list[str]
    coverage_fingerprint_sha256: str


def compute_coverage_results(
    *, evidence_bundle, mapping_profile
) -> list[CoverageResult]:
    _validate_inputs(evidence_bundle=evidence_bundle, mapping_profile=mapping_profile)
    items = list(
        evidence_bundle.items.filter(
            organization=evidence_bundle.organization
        ).order_by(
            "item_type",
            "position",
            "canonical_path",
            "item_key",
        )
    )
    manifest_paths = _manifest_paths(evidence_bundle.manifest)
    complete = (
        evidence_bundle.completeness_status
        == EvidenceBundle.CompletenessStatus.COMPLETE
    )

    results = []
    for rule in _ordered_rules(mapping_profile.mapping_rules):
        control_id = str(rule["control_id"]).strip()
        control_title = str(rule.get("control_title", "")).strip()[:255]
        if not _rule_applies(rule, evidence_bundle.change_record):
            result = CoverageResult(
                control_id=control_id,
                control_title=control_title,
                coverage_status=ControlCoverageStatus.NOT_APPLICABLE,
                matched_sections=[],
                missing_sections=[],
                evidence_paths=[],
                coverage_fingerprint_sha256="",
            )
        elif not complete:
            result = CoverageResult(
                control_id=control_id,
                control_title=control_title,
                coverage_status=ControlCoverageStatus.NOT_COVERED,
                matched_sections=[],
                missing_sections=["bundle:complete"],
                evidence_paths=[],
                coverage_fingerprint_sha256="",
            )
        else:
            result = _compute_rule_result(
                rule=rule,
                items=items,
                manifest_paths=manifest_paths,
            )
        results.append(
            _with_fingerprint(
                result=result,
                evidence_bundle=evidence_bundle,
                mapping_profile=mapping_profile,
            )
        )
    return results


@transaction.atomic
def recompute_control_coverage(*, evidence_bundle, mapping_profile, computed_by=None):
    results = compute_coverage_results(
        evidence_bundle=evidence_bundle,
        mapping_profile=mapping_profile,
    )
    now = timezone.now()
    controls_in_profile = {result.control_id for result in results}
    coverages = []
    for result in results:
        coverage, _created = ChangeControlCoverage.objects.update_or_create(
            evidence_bundle=evidence_bundle,
            mapping_profile=mapping_profile,
            control_id=result.control_id,
            defaults={
                "organization": evidence_bundle.organization,
                "change_record": evidence_bundle.change_record,
                "standard": mapping_profile.standard,
                "control_title": result.control_title,
                "coverage_status": result.coverage_status,
                "matched_sections": result.matched_sections,
                "missing_sections": result.missing_sections,
                "evidence_paths": result.evidence_paths,
                "coverage_fingerprint_sha256": result.coverage_fingerprint_sha256,
                "computed_at": now,
                "computed_by": computed_by,
            },
        )
        coverages.append(coverage)

    stale_qs = ChangeControlCoverage.objects.filter(
        evidence_bundle=evidence_bundle,
        mapping_profile=mapping_profile,
    ).exclude(control_id__in=controls_in_profile)
    stale_qs.update(
        coverage_status=ControlCoverageStatus.STALE,
        computed_at=now,
        computed_by=computed_by,
    )
    return coverages


def _validate_inputs(*, evidence_bundle, mapping_profile) -> None:
    if evidence_bundle.organization_id != mapping_profile.organization_id:
        raise DomainValidationError(
            code="cross_org_mapping_profile",
            detail="Mapping profile must belong to the evidence bundle organization.",
            attr="mapping_profile",
        )
    if evidence_bundle.status != EvidenceBundle.Status.SEALED:
        raise DomainValidationError(
            code="sealed_bundle_required",
            detail="Control coverage requires a sealed evidence bundle.",
            attr="evidence_bundle",
        )
    if not mapping_profile.is_active:
        raise DomainValidationError(
            code="active_mapping_profile_required",
            detail="Control coverage requires an active mapping profile.",
            attr="mapping_profile",
        )


def _ordered_rules(rules) -> list[dict]:
    return sorted(
        [rule for rule in rules if isinstance(rule, dict) and rule.get("control_id")],
        key=lambda rule: str(rule["control_id"]),
    )


def _rule_applies(rule: dict, change) -> bool:
    applicability = rule.get("applicability") or {}
    if not isinstance(applicability, dict):
        return True
    risks = applicability.get("risk")
    if risks and change.operation_profile.risk_level not in risks:
        return False
    change_types = applicability.get("change_type")
    if change_types:
        change_type = "emergency" if change.is_emergency else "standard"
        if change_type not in change_types:
            return False
    return True


def _compute_rule_result(*, rule: dict, items: list, manifest_paths: set[str]):
    required_sections = sorted(
        {
            str(section).strip()
            for section in rule.get("required_sections", [])
            if section
        }
    )
    required_item_types = sorted(
        {
            str(item_type).strip()
            for item_type in rule.get("required_item_types", [])
            if item_type
        }
    )
    requirements = [f"section:{section}" for section in required_sections] + [
        f"item_type:{item_type}" for item_type in required_item_types
    ]
    matched = []
    evidence_paths = set()

    for section in required_sections:
        section_items = [
            item
            for item in items
            if _item_is_eligible(item, manifest_paths)
            and _section_from_path(item.canonical_path) == section
        ]
        if section_items:
            matched.append(f"section:{section}")
            evidence_paths.update(_item_evidence_path(item) for item in section_items)

    for item_type in required_item_types:
        type_items = [
            item
            for item in items
            if _item_is_eligible(item, manifest_paths) and item.item_type == item_type
        ]
        if type_items:
            matched.append(f"item_type:{item_type}")
            evidence_paths.update(_item_evidence_path(item) for item in type_items)

    missing = sorted(set(requirements) - set(matched))
    matched = sorted(set(matched))
    if not requirements:
        status = ControlCoverageStatus.NOT_COVERED
    elif not missing:
        status = ControlCoverageStatus.COVERED
    elif matched:
        status = ControlCoverageStatus.PARTIALLY_COVERED
    else:
        status = ControlCoverageStatus.NOT_COVERED

    return CoverageResult(
        control_id=str(rule["control_id"]).strip(),
        control_title=str(rule.get("control_title", "")).strip()[:255],
        coverage_status=status,
        matched_sections=matched,
        missing_sections=missing,
        evidence_paths=sorted(evidence_paths),
        coverage_fingerprint_sha256="",
    )


def _item_is_eligible(item, manifest_paths: set[str]) -> bool:
    if not item.present or not item.valid:
        return False
    if not item.canonical_path:
        return False
    if manifest_paths and item.canonical_path not in manifest_paths:
        return False
    return True


def _section_from_path(path: str) -> str:
    return str(path).strip("/").split("/", 1)[0]


def _item_evidence_path(item) -> str:
    if item.json_pointer:
        return f"{item.canonical_path}#{item.json_pointer}"
    return item.canonical_path


def _manifest_paths(manifest) -> set[str]:
    paths = set()
    _collect_manifest_paths(manifest, paths)
    return paths


def _collect_manifest_paths(value, paths: set[str]) -> None:
    if isinstance(value, dict):
        for key in ("canonical_path", "path"):
            path = value.get(key)
            if isinstance(path, str) and path.strip():
                paths.add(path.strip())
        for child in value.values():
            _collect_manifest_paths(child, paths)
    elif isinstance(value, list):
        for child in value:
            _collect_manifest_paths(child, paths)


def _with_fingerprint(*, result, evidence_bundle, mapping_profile) -> CoverageResult:
    fingerprint = canonical_json_sha256(
        {
            "organization_id": str(evidence_bundle.organization_id),
            "change_id": str(evidence_bundle.change_record_id),
            "evidence_bundle_id": str(evidence_bundle.id),
            "bundle_content_sha256": evidence_bundle.content_sha256,
            "mapping_profile_id": str(mapping_profile.id),
            "mapping_profile_version": mapping_profile.version,
            "control_id": result.control_id,
            "coverage_status": result.coverage_status,
            "matched_sections": result.matched_sections,
            "missing_sections": result.missing_sections,
            "evidence_paths": result.evidence_paths,
        }
    )
    return CoverageResult(
        control_id=result.control_id,
        control_title=result.control_title,
        coverage_status=result.coverage_status,
        matched_sections=result.matched_sections,
        missing_sections=result.missing_sections,
        evidence_paths=result.evidence_paths,
        coverage_fingerprint_sha256=fingerprint,
    )
