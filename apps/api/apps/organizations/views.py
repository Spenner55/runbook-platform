from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.org_context import require_matching_organization_id
from apps.common.permissions import (
    IsOrganizationAdminOrOwner,
    IsReadOnlyOrganizationMember,
)
from apps.organizations import services
from apps.organizations.models import Organization
from apps.organizations.serializers import (
    MembershipCreateSerializer,
    MembershipRoleUpdateSerializer,
    MembershipSerializer,
    OrganizationCreateSerializer,
    OrganizationDetailSerializer,
    OrganizationListSerializer,
)
from apps.users.models import User


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Organization.objects.all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return Organization.objects.none()
        return Organization.objects.filter(memberships__user=user).distinct()

    def get_permissions(self):
        if self.action in {"members", "member_detail"}:
            if self.request.method in {"GET", "HEAD", "OPTIONS"}:
                return [IsReadOnlyOrganizationMember()]
            return [IsOrganizationAdminOrOwner()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return OrganizationDetailSerializer
        return OrganizationListSerializer

    def create(self, request):
        serializer = OrganizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = services.create_organization(
            name=serializer.validated_data["name"],
            slug=serializer.validated_data["slug"],
        )
        services.create_membership(
            organization=org, user=request.user, role=services.MembershipRole.OWNER
        )
        return Response(
            OrganizationDetailSerializer(org).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get", "post"], url_path="members")
    def members(self, request, pk=None):
        require_matching_organization_id(request, pk)
        organization = self.get_object()
        if request.method == "GET":
            memberships = services.list_members(organization=organization)
            return Response(MembershipSerializer(memberships, many=True).data)

        serializer = MembershipCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        membership = services.create_membership(
            organization=organization,
            user=user,
            role=serializer.validated_data["role"],
        )
        return Response(
            MembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get", "patch", "delete"],
        url_path=r"members/(?P<membership_id>[^/.]+)",
    )
    def member_detail(self, request, pk=None, membership_id=None):
        require_matching_organization_id(request, pk)
        organization = self.get_object()
        membership = get_object_or_404(
            services.list_members(organization=organization), pk=membership_id
        )

        if request.method == "GET":
            return Response(MembershipSerializer(membership).data)

        if request.method == "PATCH":
            serializer = MembershipRoleUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            membership = services.update_member_role(
                membership=membership,
                role=serializer.validated_data["role"],
            )
            return Response(MembershipSerializer(membership).data)

        services.remove_membership(membership=membership)
        return Response(status=status.HTTP_204_NO_CONTENT)
