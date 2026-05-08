from __future__ import annotations

from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.utils.dateparse import parse_datetime

from apps.auditor.access import apply_auditor_access_scope
from apps.auditor.models import (
    ChangeControlCoverage,
    ExternalChangeReference,
    ServiceCatalogEntry,
)
from apps.changes.models import ChangeRecord, ChangeTarget
from apps.evidence.models import EvidenceBundle

ALLOWED_ORDERINGS = {
    "-submitted_at",
    "submitted_at",
    "-closed_at",
    "closed_at",
    "-created_at",
    "created_at",
    "risk",
    "-risk",
}


def audit_change_queryset(
    *,
    organization,
    user,
    filters: dict | None = None,
    allow_admin_bypass: bool = False,
):
    queryset = (
        ChangeRecord.objects.select_related(
            "operation_profile", "workflow", "requested_by"
        )
        .prefetch_related(
            Prefetch(
                "targets",
                queryset=ChangeTarget.objects.order_by("position"),
            ),
            Prefetch(
                "evidence_bundles",
                queryset=EvidenceBundle.objects.order_by("-version", "-created_at"),
            ),
            Prefetch(
                "external_references",
                queryset=ExternalChangeReference.objects.order_by(
                    "system", "external_key"
                ),
            ),
            Prefetch(
                "control_coverages",
                queryset=ChangeControlCoverage.objects.order_by(
                    "standard", "control_id"
                ),
            ),
            "exceptions",
        )
        .filter(organization=organization)
    )
    queryset = apply_auditor_access_scope(
        queryset,
        user=user,
        organization=organization,
        allow_admin_bypass=allow_admin_bypass,
    )
    queryset = apply_search_filters(
        queryset, organization=organization, filters=filters or {}
    )
    ordering = (filters or {}).get("ordering") or "-created_at"
    if ordering not in ALLOWED_ORDERINGS:
        ordering = "-created_at"
    if ordering in {"risk", "-risk"}:
        ordering = ordering.replace("risk", "operation_profile__risk_level")
    return queryset.order_by(ordering, "id").distinct()


def get_audit_change_detail(*, organization, user, change_id, allow_admin_bypass=False):
    change = (
        audit_change_queryset(
            organization=organization,
            user=user,
            filters={},
            allow_admin_bypass=allow_admin_bypass,
        )
        .filter(pk=change_id)
        .first()
    )
    if change is None:
        raise Http404("Change not found.")
    return change


def list_audit_changes(
    *,
    organization,
    user,
    filters: dict | None = None,
    limit: int = 50,
    offset: int = 0,
    allow_admin_bypass: bool = False,
):
    queryset = audit_change_queryset(
        organization=organization,
        user=user,
        filters=filters,
        allow_admin_bypass=allow_admin_bypass,
    )
    return [_change_projection(change) for change in queryset[offset : offset + limit]]


def apply_search_filters(queryset, *, organization, filters: dict):
    if service := filters.get("service"):
        queryset = queryset.filter(
            _service_filter_q([service], organization=organization)
        )
    if target := filters.get("target"):
        queryset = queryset.filter(
            Q(targets__target_identifier=target)
            | Q(targets__normalized_identifier=target)
            | Q(targets__display_name=target)
        )
    if risk := filters.get("risk"):
        queryset = queryset.filter(operation_profile__risk_level=risk)
    if status := filters.get("status"):
        queryset = queryset.filter(status=status)
    if change_type := filters.get("change_type"):
        queryset = queryset.filter(is_emergency=(change_type == "emergency"))
    if bundle_status := filters.get("bundle_status"):
        queryset = queryset.filter(evidence_bundles__status=bundle_status)
    if control_id := filters.get("control_id"):
        queryset = queryset.filter(control_coverages__control_id=control_id)
    if coverage_status := filters.get("coverage_status"):
        queryset = queryset.filter(control_coverages__coverage_status=coverage_status)
    if external_system := filters.get("external_system"):
        queryset = queryset.filter(external_references__system=external_system)
    if start_date := _parse_filter_datetime(filters.get("start_date")):
        queryset = queryset.filter(created_at__gte=start_date)
    if end_date := _parse_filter_datetime(filters.get("end_date")):
        queryset = queryset.filter(created_at__lte=end_date)
    return queryset


def service_catalog_queryset(*, organization, include_inactive: bool = False):
    queryset = ServiceCatalogEntry.objects.filter(organization=organization)
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return queryset.order_by("service_key")


def external_references_for_change(*, organization, change_record):
    return ExternalChangeReference.objects.filter(
        organization=organization,
        change_record=change_record,
    ).order_by("system", "reference_type", "external_key", "external_id")


def coverage_for_change(*, organization, change_record):
    return ChangeControlCoverage.objects.filter(
        organization=organization,
        change_record=change_record,
    ).order_by("standard", "control_id")


def coverage_summary_for_change(*, organization, change_record) -> dict:
    rows = (
        ChangeControlCoverage.objects.filter(
            organization=organization,
            change_record=change_record,
        )
        .values("standard", "coverage_status")
        .annotate(count=Count("id"))
        .order_by("standard", "coverage_status")
    )
    summary = {}
    for row in rows:
        summary.setdefault(row["standard"], {})[row["coverage_status"]] = row["count"]
    return summary


def _change_projection(change) -> dict:
    targets = list(change.targets.all())
    latest_bundle = next(iter(change.evidence_bundles.all()), None)
    return {
        "id": str(change.id),
        "title": change.title,
        "status": change.status,
        "risk": change.operation_profile.risk_level,
        "change_type": "emergency" if change.is_emergency else "standard",
        "targets": [
            {
                "id": str(target.id),
                "label": target.display_name or target.target_identifier,
                "type": target.target_type,
                "identifier": target.normalized_identifier,
            }
            for target in targets
        ],
        "submitted_at": change.submitted_at,
        "approved_at": change.approved_at,
        "closed_at": change.closed_at,
        "has_exception": bool(change.freeze_exception_reference)
        or getattr(change, "exceptions", None).all().exists(),
        "bundle": _bundle_projection(latest_bundle),
        "external_references": [
            {
                "system": reference.system,
                "reference_type": reference.reference_type,
                "external_key": reference.external_key,
                "snapshot_status": reference.snapshot_status,
            }
            for reference in change.external_references.all()
        ],
        "coverage_summary": _coverage_summary_from_prefetch(change),
    }


def _bundle_projection(bundle) -> dict | None:
    if bundle is None:
        return None
    return {
        "id": str(bundle.id),
        "status": bundle.status,
        "completeness_status": bundle.completeness_status,
        "version": bundle.version,
        "manifest_sha256": bundle.manifest_sha256,
        "content_sha256": bundle.content_sha256,
    }


def _coverage_summary_from_prefetch(change) -> dict:
    summary = {}
    for coverage in change.control_coverages.all():
        standard_counts = summary.setdefault(coverage.standard, {})
        standard_counts[coverage.coverage_status] = (
            standard_counts.get(coverage.coverage_status, 0) + 1
        )
    return summary


def _service_filter_q(values: list[str], *, organization) -> Q:
    from apps.auditor.access import _service_scope_q

    return _service_scope_q(values, organization=organization)


def _parse_filter_datetime(value):
    if not value:
        return None
    return parse_datetime(str(value))
