from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.organizations.models import Organization
from apps.runbooks import services
from apps.runbooks.models import Runbook
from apps.runbooks.serializers import (
    RunbookArchiveSerializer,
    RunbookCreateSerializer,
    RunbookDetailSerializer,
    RunbookListSerializer,
    RunbookMarkReadySerializer,
)


class RunbookViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Runbook.objects.select_related("organization").all()

    def get_serializer_class(self):
        if self.action == "create":
            return RunbookCreateSerializer
        if self.action == "mark_ready":
            return RunbookMarkReadySerializer
        if self.action == "archive":
            return RunbookArchiveSerializer
        if self.action == "retrieve":
            return RunbookDetailSerializer
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

    @action(detail=True, methods=["post"], url_path="mark-ready")
    def mark_ready(self, request, pk=None):
        runbook = self.get_object()
        runbook = services.mark_runbook_ready(runbook=runbook)
        return Response(RunbookDetailSerializer(runbook).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        runbook = self.get_object()
        runbook = services.archive_runbook(runbook=runbook)
        return Response(RunbookDetailSerializer(runbook).data)
