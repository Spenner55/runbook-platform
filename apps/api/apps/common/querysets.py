from django.db.models import Exists, OuterRef

from apps.organizations.models import Membership


def org_scoped(queryset, *, organization):
    """Filter a queryset to one organization."""
    return queryset.filter(organization=organization)


def org_id_scoped(queryset, *, organization_id):
    """Filter a queryset to one organization_id."""
    return queryset.filter(organization_id=organization_id)


def user_organization_scoped(queryset, *, user):
    """Filter organization-owned rows to organizations the user belongs to."""
    if not user or not user.is_authenticated:
        return queryset.none()
    membership = Membership.objects.filter(
        organization_id=OuterRef("organization_id"),
        user=user,
    )
    return queryset.filter(Exists(membership))


def user_active_organization_scoped(queryset, *, user, organization_id):
    """Filter organization-owned rows to the active org if the user belongs to it."""
    if not user or not user.is_authenticated or not organization_id:
        return queryset.none()
    membership = Membership.objects.filter(
        organization_id=organization_id,
        user=user,
    )
    return queryset.filter(organization_id=organization_id).filter(Exists(membership))
