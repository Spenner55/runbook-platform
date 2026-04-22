from rest_framework import mixins, status, viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.organizations.models import Organization
from apps.runbooks import services
from apps.runbooks.models import Runbook
from apps.runbooks.serializers import (
    RunbookCreateSerializer,
    RunbookDetailSerializer,
    RunbookListSerializer,
)


class RunbookViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Runbook.objects.select_related("organization").all()

    def get_serializer_class(self):
        return RunbookListSerializer

    def create(self, request):
        serializer = RunbookCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        organization = get_object_or_404(Organization, pk=data["organization_id"])

        runbook = services.create_runbook(
            organization=organization,
            title=data["title"],
            slug=data["slug"],
            raw_content=data.get("raw_content", ""),
        )
        return Response(RunbookDetailSerializer(runbook).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        runbook = self.get_object()
        return Response(RunbookDetailSerializer(runbook).data)
