from django.db import IntegrityError

from apps.common.exceptions import DomainConflictError
from apps.organizations.models import Membership, MembershipRole, Organization


def create_organization(*, name: str, slug: str) -> Organization:
    """Create a new organization."""
    return Organization.objects.create(name=name, slug=slug)


def create_membership(
    *, organization: Organization, user, role: str = MembershipRole.OPERATOR
) -> Membership:
    """Add a user to an organization."""
    if Membership.objects.filter(organization=organization, user=user).exists():
        raise DomainConflictError(
            code="membership_exists",
            detail="User is already a member of this organization.",
            attr="user_id",
        )
    try:
        return Membership.objects.create(
            organization=organization,
            user=user,
            role=role,
        )
    except IntegrityError as exc:
        raise DomainConflictError(
            code="membership_exists",
            detail="User is already a member of this organization.",
            attr="user_id",
        ) from exc


def get_membership(*, organization: Organization, user=None, membership_id=None):
    """Return one membership scoped to the given organization, or None."""
    queryset = Membership.objects.select_related("organization", "user").filter(
        organization=organization
    )
    if membership_id is not None:
        return queryset.filter(pk=membership_id).first()
    if user is not None:
        return queryset.filter(user=user).first()
    raise ValueError("Either user or membership_id is required.")


def list_members(*, organization: Organization):
    """List memberships for one organization."""
    return (
        Membership.objects.select_related("organization", "user")
        .filter(organization=organization)
        .order_by("user__email")
    )


def update_member_role(*, membership: Membership, role: str) -> Membership:
    _assert_not_removing_last_owner(membership=membership, next_role=role)
    membership.role = role
    membership.save(update_fields=["role", "updated_at"])
    return membership


def remove_membership(*, membership: Membership) -> None:
    _assert_not_removing_last_owner(membership=membership, next_role=None)
    membership.delete()


def _assert_not_removing_last_owner(
    *, membership: Membership, next_role: str | None
) -> None:
    if membership.role != MembershipRole.OWNER or next_role == MembershipRole.OWNER:
        return
    owner_count = Membership.objects.filter(
        organization=membership.organization, role=MembershipRole.OWNER
    ).count()
    if owner_count <= 1:
        raise DomainConflictError(
            code="last_owner_required",
            detail="An organization must retain at least one owner.",
            attr="role",
        )
