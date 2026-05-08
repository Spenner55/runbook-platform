from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotAuthenticated, PermissionDenied

from apps.auditor.models import AuditorAccessGrant, AuditorGrantStatus
from apps.common.permissions import ADMIN_ROLES, get_user_membership


def assert_auditor_read_only_method(method: str) -> None:
    if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        raise PermissionDenied("Auditor access is read-only.")


def get_active_auditor_grants(*, user, organization, at=None) -> QuerySet:
    if not user or not getattr(user, "is_authenticated", False):
        raise NotAuthenticated()
    if get_user_membership(user=user, organization_id=organization.id) is None:
        return AuditorAccessGrant.objects.none()

    now = at or timezone.now()
    return (
        AuditorAccessGrant.objects.filter(
            organization=organization,
            user=user,
            status=AuditorGrantStatus.ACTIVE,
        )
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by("created_at", "id")
    )


def is_admin_member(*, user, organization) -> bool:
    membership = get_user_membership(user=user, organization_id=organization.id)
    return membership is not None and membership.role in ADMIN_ROLES


def apply_auditor_access_scope(
    queryset: QuerySet,
    *,
    user,
    organization,
    allow_admin_bypass: bool = False,
    at=None,
) -> QuerySet:
    queryset = queryset.filter(organization=organization)
    if allow_admin_bypass and is_admin_member(user=user, organization=organization):
        return queryset

    grants = list(
        get_active_auditor_grants(user=user, organization=organization, at=at)
    )
    if not grants:
        return queryset.none()

    scoped_q = None
    for grant in grants:
        grant_q = _scope_to_change_q(grant.scope, organization=organization)
        scoped_q = grant_q if scoped_q is None else scoped_q | grant_q
    if scoped_q is None:
        return queryset.none()
    return queryset.filter(scoped_q).distinct()


def _scope_to_change_q(scope: dict, *, organization) -> Q:
    q = Q()
    if not scope.get("all"):
        q &= _dimension_q(scope, "service_keys", _service_scope_q, organization)
        q &= _dimension_q(scope, "target_ids", _target_scope_q, organization)
        q &= _dimension_q(scope, "risk_levels", _risk_scope_q, organization)
        q &= _dimension_q(scope, "statuses", _status_scope_q, organization)
        q &= _dimension_q(scope, "change_types", _change_type_scope_q, organization)
        q &= _dimension_q(
            scope, "bundle_statuses", _bundle_status_scope_q, organization
        )
        q &= _dimension_q(scope, "control_ids", _control_id_scope_q, organization)
        q &= _dimension_q(
            scope,
            "coverage_statuses",
            _coverage_status_scope_q,
            organization,
        )
        q &= _dimension_q(scope, "standards", _standard_scope_q, organization)

    date_from = _parse_scope_datetime(scope.get("date_from"))
    date_to = _parse_scope_datetime(scope.get("date_to"))
    if date_from is not None:
        q &= _audit_date_gte_q(date_from)
    if date_to is not None:
        q &= _audit_date_lte_q(date_to)
    if scope.get("include_exceptions") is False:
        q &= Q(exceptions__isnull=True) & Q(freeze_exception_reference="")
    return q


def _dimension_q(scope: dict, key: str, builder, organization) -> Q:
    if key not in scope:
        return Q()
    values = scope[key]
    if values == {"all": True}:
        return Q()
    if not values:
        return Q(pk__in=[])
    return builder([str(value) for value in values], organization=organization)


def _service_scope_q(values: list[str], *, organization) -> Q:
    from apps.auditor.models import ServiceCatalogEntry

    q = (
        Q(targets__metadata__service_key__in=values)
        | Q(targets__metadata__service__in=values)
        | Q(request_snapshot__service_key__in=values)
        | Q(request_snapshot__service__in=values)
    )
    services = ServiceCatalogEntry.objects.filter(
        organization=organization,
        service_key__in=values,
        is_active=True,
    )
    for service in services:
        for pattern in service.target_patterns:
            q |= _target_pattern_q(pattern)
    return q


def _target_pattern_q(pattern) -> Q:
    if isinstance(pattern, str):
        value = pattern.strip()
        if value.endswith("*"):
            prefix = value[:-1]
            return (
                Q(targets__target_identifier__startswith=prefix)
                | Q(targets__normalized_identifier__startswith=prefix)
                | Q(targets__display_name__startswith=prefix)
            )
        return (
            Q(targets__target_identifier=value)
            | Q(targets__normalized_identifier=value)
            | Q(targets__display_name=value)
        )
    if not isinstance(pattern, dict):
        return Q(pk__in=[])

    q = Q()
    target_type = pattern.get("target_type") or pattern.get("type")
    identifier = pattern.get("target_identifier") or pattern.get("identifier")
    normalized = pattern.get("normalized_identifier")
    prefix = pattern.get("prefix")
    if target_type:
        q &= Q(targets__target_type=str(target_type))
    if identifier:
        q &= Q(targets__target_identifier=str(identifier))
    if normalized:
        q &= Q(targets__normalized_identifier=str(normalized))
    if prefix:
        q &= Q(targets__normalized_identifier__startswith=str(prefix))
    if not q:
        return Q(pk__in=[])
    return q


def _target_scope_q(values: list[str], *, organization) -> Q:
    uuid_values = [value for value in values if _is_uuid(value)]
    q = (
        Q(targets__target_identifier__in=values)
        | Q(targets__normalized_identifier__in=values)
        | Q(targets__display_name__in=values)
    )
    if uuid_values:
        q |= Q(targets__id__in=uuid_values)
    return q


def _risk_scope_q(values: list[str], *, organization) -> Q:
    return Q(operation_profile__risk_level__in=values)


def _status_scope_q(values: list[str], *, organization) -> Q:
    return Q(status__in=values)


def _change_type_scope_q(values: list[str], *, organization) -> Q:
    q = Q(pk__in=[])
    if "standard" in values:
        q |= Q(is_emergency=False)
    if "emergency" in values:
        q |= Q(is_emergency=True)
    return q


def _bundle_status_scope_q(values: list[str], *, organization) -> Q:
    return Q(evidence_bundles__status__in=values)


def _control_id_scope_q(values: list[str], *, organization) -> Q:
    return Q(control_coverages__control_id__in=values)


def _coverage_status_scope_q(values: list[str], *, organization) -> Q:
    return Q(control_coverages__coverage_status__in=values)


def _standard_scope_q(values: list[str], *, organization) -> Q:
    return Q(control_coverages__standard__in=values)


def _parse_scope_datetime(value) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, UTC)
    return parsed


def _audit_date_gte_q(value) -> Q:
    return Q(submitted_at__isnull=False, submitted_at__gte=value) | Q(
        submitted_at__isnull=True,
        created_at__gte=value,
    )


def _audit_date_lte_q(value) -> Q:
    return Q(submitted_at__isnull=False, submitted_at__lte=value) | Q(
        submitted_at__isnull=True,
        created_at__lte=value,
    )


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
