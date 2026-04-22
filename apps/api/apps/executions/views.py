from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.executions import services
from apps.executions.models import Execution
from apps.executions.serializers import (
    ClaimNextRequestSerializer,
    ClaimedExecutionSerializer,
    CompleteExecutionRequestSerializer,
    ExecutionCreateSerializer,
    ExecutionDetailSerializer,
    ExecutionListSerializer,
    ExecutionStepSerializer,
    HeartbeatRequestSerializer,
    StepUpdateRequestSerializer,
)
from apps.workflows.models import Workflow


# ---------------------------------------------------------------------------
# Public viewset
# ---------------------------------------------------------------------------

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

        workflow = get_object_or_404(Workflow, pk=serializer.validated_data["workflow_id"])
        execution = services.create_execution(workflow=workflow)

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


# ---------------------------------------------------------------------------
# Internal runner views
# ---------------------------------------------------------------------------

@api_view(["POST"])
def claim_next(request):
    """POST /api/v1/internal/executions/claim-next/"""
    serializer = ClaimNextRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    runner_id = serializer.validated_data["runner_id"]

    result = services.claim_next_execution(runner_id=runner_id)
    if result is None:
        return Response({"execution": None, "poll_after_seconds": 5})

    execution = result["execution"]
    data = ClaimedExecutionSerializer(execution).data
    return Response({"execution": data, "poll_after_seconds": 5})


@api_view(["POST"])
def heartbeat(request, execution_id):
    """POST /api/v1/internal/executions/<execution_id>/heartbeat/"""
    execution = get_object_or_404(Execution, pk=execution_id)
    serializer = HeartbeatRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    try:
        services.heartbeat_execution(
            execution=execution,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response({"status": "ok"})


@api_view(["POST"])
def step_update(request, execution_id, step_id):
    """POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/update/"""
    execution = get_object_or_404(Execution, pk=execution_id)
    serializer = StepUpdateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    try:
        step = services.update_execution_step(
            execution=execution,
            step_id=str(step_id),
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            new_status=d["status"],
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            exit_code=d.get("exit_code"),
            error_message=d.get("error_message", ""),
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(ExecutionStepSerializer(step).data)


@api_view(["POST"])
def complete(request, execution_id):
    """POST /api/v1/internal/executions/<execution_id>/complete/"""
    execution = get_object_or_404(Execution, pk=execution_id)
    serializer = CompleteExecutionRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    try:
        execution = services.complete_execution(
            execution=execution,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            outcome=d["outcome"],
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(ExecutionDetailSerializer(execution).data)
