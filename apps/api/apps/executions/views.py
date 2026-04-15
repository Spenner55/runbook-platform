from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.executions import services
from apps.executions.models import Execution
from apps.executions.serializers import (
    ExecutionCreateSerializer,
    ExecutionDetailSerializer,
    ExecutionListSerializer,
)
from apps.workflows.models import Workflow


class ExecutionViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Execution.objects.select_related("workflow", "organization").all()

    def get_serializer_class(self):
        return ExecutionListSerializer

    def create(self, request):
        serializer = ExecutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            workflow = Workflow.objects.get(pk=serializer.validated_data["workflow_id"])
        except Workflow.DoesNotExist:
            return Response(
                {"workflow_id": "Workflow not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            execution = services.create_execution_from_workflow(workflow=workflow)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            ExecutionDetailSerializer(execution).data,
            status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, pk=None):
        execution = self.get_object()
        return Response(ExecutionDetailSerializer(execution).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        execution = self.get_object()
        try:
            execution = services.cancel_execution(execution=execution)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExecutionDetailSerializer(execution).data)
