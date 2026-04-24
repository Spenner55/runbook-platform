from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.common.exceptions import ExternalDependencyError
from apps.workflows.internal_clients import (
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
)
from apps.runbooks.models import Runbook
from apps.workflows import services
from apps.workflows.models import Workflow
from apps.workflows.serializers import (
    WorkflowArchiveSerializer,
    WorkflowCreateSerializer,
    WorkflowDetailSerializer,
    WorkflowListSerializer,
    WorkflowPublishSerializer,
)


class WorkflowViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Workflow.objects.select_related("runbook", "organization").all()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return WorkflowDetailSerializer
        if self.action == "publish":
            return WorkflowPublishSerializer
        if self.action == "archive":
            return WorkflowArchiveSerializer
        return WorkflowListSerializer

    def create(self, request):
        serializer = WorkflowCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        runbook = get_object_or_404(Runbook, pk=serializer.validated_data["runbook_id"])

        try:
            workflow = services.create_workflow_from_runbook(runbook=runbook)
        except (AiServiceUnavailableError, AiServiceTimeoutError) as exc:
            raise ExternalDependencyError(
                code="workflow_ai_unavailable",
                detail=str(exc),
            ) from exc
        except (AiServiceBadResponseError, AiServiceContractError) as exc:
            raise ExternalDependencyError(
                code="workflow_ai_bad_response",
                detail=str(exc),
            ) from exc

        return Response(WorkflowDetailSerializer(workflow).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        workflow = self.get_object()
        workflow = services.publish_workflow(workflow=workflow)
        return Response(WorkflowDetailSerializer(workflow).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        workflow = self.get_object()
        workflow = services.archive_workflow(workflow=workflow)
        return Response(WorkflowDetailSerializer(workflow).data)
