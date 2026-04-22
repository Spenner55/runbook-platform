from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.organizations import services
from apps.organizations.models import Organization
from apps.organizations.serializers import OrganizationSerializer


class OrganizationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    def create(self, request):
        serializer = OrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = services.create_organization(
            name=serializer.validated_data["name"],
            slug=serializer.validated_data["slug"],
        )
        return Response(OrganizationSerializer(org).data, status=status.HTTP_201_CREATED)
