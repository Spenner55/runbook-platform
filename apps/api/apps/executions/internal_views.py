"""
Internal runner API views.

These views are intentionally separate from the public ExecutionViewSet.
They accept runner-owned requests only and must not be registered on the
public router.
"""

from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.executions import services
from apps.executions.internal_serializers import (
    ClaimedExecutionSerializer,
    ClaimNextRequestSerializer,
    ExecutionCompleteSerializer,
    HeartbeatSerializer,
    StepUpdateSerializer,
)
from apps.executions.models import Execution
from apps.executions.serializers import ExecutionStepSerializer


class ClaimNextExecutionView(APIView):
    """POST /api/v1/internal/executions/claim-next/"""

    def post(self, request):
        serializer = ClaimNextRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        runner_id = serializer.validated_data["runner_id"]

        result = services.claim_next_execution(runner_id=runner_id)
        if result is None:
            return Response({"execution": None, "poll_after_seconds": 5})

        execution = result["execution"]
        return Response(
            {
                "execution": ClaimedExecutionSerializer(execution).data,
                "claim_token": result["claim_token"],
                "poll_after_seconds": 5,
            }
        )


class ExecutionHeartbeatView(APIView):
    """POST /api/v1/internal/executions/<execution_id>/heartbeat/"""

    def post(self, request, execution_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = HeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        services.heartbeat_execution(
            execution=execution,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
        )
        execution.refresh_from_db(fields=["last_heartbeat_at", "status"])
        return Response(
            {
                "execution_id": str(execution.id),
                "status": execution.status,
                "last_heartbeat_at": execution.last_heartbeat_at,
            }
        )


class ExecutionStepUpdateView(APIView):
    """POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/update/"""

    def post(self, request, execution_id, step_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = StepUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

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
        execution.refresh_from_db(fields=["status"])
        return Response(
            {
                "execution_id": str(execution.id),
                "step": ExecutionStepSerializer(step).data,
                "execution_status": execution.status,
            }
        )


class ExecutionCompleteView(APIView):
    """POST /api/v1/internal/executions/<execution_id>/complete/"""

    def post(self, request, execution_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = ExecutionCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        execution = services.complete_execution(
            execution=execution,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            outcome=d["final_status"],
        )
        return Response(
            {
                "id": str(execution.id),
                "status": execution.status,
                "finished_at": execution.finished_at,
            }
        )
