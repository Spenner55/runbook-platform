from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.organizations import services
from apps.organizations.models import Organization
from apps.organizations.serializers import (
    OrganizationCreateSerializer,
    OrganizationDetailSerializer,
    OrganizationListSerializer,
)


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Organization.objects.all()

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
        return Response(
            OrganizationDetailSerializer(org).data, status=status.HTTP_201_CREATED
        )
