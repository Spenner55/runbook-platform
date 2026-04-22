from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.workflows.internal_clients import (
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
    StubWorkflowTransformClient,
)
from apps.runbooks.models import Runbook
from apps.workflows import services
from apps.workflows.models import Workflow
from apps.workflows.serializers import (
    WorkflowCreateSerializer,
    WorkflowDetailSerializer,
    WorkflowListSerializer,
)


class WorkflowViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Workflow.objects.select_related("runbook", "organization").all()

    def get_serializer_class(self):
        return WorkflowListSerializer

    def create(self, request):
        serializer = WorkflowCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        runbook = get_object_or_404(Runbook, pk=serializer.validated_data["runbook_id"])

        try:
            workflow = services.create_workflow(
                runbook=runbook,
                transform_client=StubWorkflowTransformClient(),
            )
        except AiServiceUnavailableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except AiServiceTimeoutError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except (AiServiceBadResponseError, AiServiceContractError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(WorkflowDetailSerializer(workflow).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        workflow = self.get_object()
        return Response(WorkflowDetailSerializer(workflow).data)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        workflow = self.get_object()
        try:
            workflow = services.publish_workflow(workflow=workflow)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WorkflowDetailSerializer(workflow).data)
