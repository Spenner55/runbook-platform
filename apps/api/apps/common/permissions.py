from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.organizations.models import Membership, MembershipRole

ADMIN_ROLES = {MembershipRole.OWNER, MembershipRole.ADMIN}
MEMBER_ROLES = {
    MembershipRole.OWNER,
    MembershipRole.ADMIN,
    MembershipRole.OPERATOR,
    MembershipRole.VIEWER,
}
OPERATOR_ROLES = {
    MembershipRole.OWNER,
    MembershipRole.ADMIN,
    MembershipRole.OPERATOR,
}


def get_organization_id_from_view(view):
    return (
        view.kwargs.get("pk")
        or view.kwargs.get("organization_pk")
        or view.kwargs.get("organization_id")
    )


def get_user_membership(*, user, organization_id):
    if not user or not user.is_authenticated or not organization_id:
        return None
    return (
        Membership.objects.filter(user=user, organization_id=organization_id)
        .select_related("organization", "user")
        .first()
    )


def is_organization_member(*, user, organization_id) -> bool:
    return get_user_membership(user=user, organization_id=organization_id) is not None


def has_organization_role(*, user, organization_id, roles) -> bool:
    membership = get_user_membership(user=user, organization_id=organization_id)
    return membership is not None and membership.role in roles


def assert_organization_role(*, user, organization_id, roles) -> Membership:
    if not user or not user.is_authenticated:
        raise NotAuthenticated()
    membership = get_user_membership(user=user, organization_id=organization_id)
    if membership is None or membership.role not in roles:
        raise PermissionDenied("You do not have access to this organization.")
    return membership


def assert_organization_member(*, user, organization_id) -> Membership:
    return assert_organization_role(
        user=user, organization_id=organization_id, roles=MEMBER_ROLES
    )


def assert_organization_operator(*, user, organization_id) -> Membership:
    return assert_organization_role(
        user=user, organization_id=organization_id, roles=OPERATOR_ROLES
    )


def assert_organization_admin(*, user, organization_id) -> Membership:
    return assert_organization_role(
        user=user, organization_id=organization_id, roles=ADMIN_ROLES
    )


class IsAuthenticatedOrganizationMember(BasePermission):
    """Allow authenticated users who belong to the organization in the URL."""

    def has_permission(self, request, view):
        organization_id = get_organization_id_from_view(view)
        return is_organization_member(
            user=request.user, organization_id=organization_id
        )


class IsOrganizationAdminOrOwner(BasePermission):
    """Allow organization admins and owners."""

    def has_permission(self, request, view):
        organization_id = get_organization_id_from_view(view)
        return has_organization_role(
            user=request.user,
            organization_id=organization_id,
            roles=ADMIN_ROLES,
        )


class IsOrganizationOperator(BasePermission):
    """Allow organization owners, admins, and operators."""

    def has_permission(self, request, view):
        organization_id = get_organization_id_from_view(view)
        return has_organization_role(
            user=request.user,
            organization_id=organization_id,
            roles=OPERATOR_ROLES,
        )


class IsReadOnlyOrganizationMember(BasePermission):
    """Allow read-only access to authenticated organization members."""

    def has_permission(self, request, view):
        if request.method not in SAFE_METHODS:
            return False
        organization_id = get_organization_id_from_view(view)
        return is_organization_member(
            user=request.user, organization_id=organization_id
        )


class IsRunnerAuthenticated(BasePermission):
    """Allow only authenticated internal runner principals."""

    def has_permission(self, request, view):
        return bool(
            getattr(request.user, "is_authenticated", False)
            and getattr(request.user, "is_runner", False)
        )
