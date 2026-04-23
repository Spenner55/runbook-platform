from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.executions import services
from apps.executions.models import Execution
from apps.executions.serializers import (
    ExecutionCancelSerializer,
    ExecutionCreateSerializer,
    ExecutionDetailSerializer,
    ExecutionListSerializer,
)
from apps.workflows.models import Workflow


class ExecutionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Execution.objects.select_related("workflow", "organization").prefetch_related("steps").all()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ExecutionDetailSerializer
        if self.action == "cancel":
            return ExecutionCancelSerializer
        return ExecutionListSerializer

    def create(self, request):
        serializer = ExecutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workflow = get_object_or_404(Workflow, pk=serializer.validated_data["workflow_id"])
        execution = services.create_execution(workflow=workflow)

        return Response(
            ExecutionDetailSerializer(execution).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        execution = self.get_object()
        execution = services.cancel_execution(execution=execution)
        return Response(ExecutionDetailSerializer(execution).data)
