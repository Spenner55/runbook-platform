from django.db.models import F, Prefetch, Window
from django.db.models.functions import RowNumber
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.executions.serializers import (
    ExecutionCancelSerializer,
    ExecutionCreateSerializer,
    ExecutionDetailSerializer,
    ExecutionListSerializer,
)
from apps.workflows.models import Workflow


def _build_detail_queryset():
    from apps.policies.models import PolicyEvaluation

    latest_eval_qs = (
        PolicyEvaluation.objects.select_related("policy", "rule")
        .annotate(
            _latest_rank=Window(
                expression=RowNumber(),
                partition_by=[F("step_id")],
                order_by=F("evaluated_at").desc(),
            )
        )
        .filter(_latest_rank=1)
        .order_by("-evaluated_at")
    )

    steps_prefetch = Prefetch(
        "steps",
        queryset=ExecutionStep.objects.prefetch_related(
            Prefetch(
                "policy_evaluations",
                queryset=latest_eval_qs,
                to_attr="latest_policy_evaluation",
            )
        ),
    )
    return Execution.objects.select_related(
        "workflow", "organization"
    ).prefetch_related(steps_prefetch)


class ExecutionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        Execution.objects.select_related("workflow", "organization")
        .prefetch_related("steps")
        .all()
    )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ExecutionDetailSerializer
        if self.action == "cancel":
            return ExecutionCancelSerializer
        return ExecutionListSerializer

    def retrieve(self, request, *args, **kwargs):
        execution = get_object_or_404(_build_detail_queryset(), pk=kwargs["pk"])
        return Response(ExecutionDetailSerializer(execution).data)

    def create(self, request):
        serializer = ExecutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workflow = get_object_or_404(
            Workflow, pk=serializer.validated_data["workflow_id"]
        )
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

    @action(detail=True, methods=["get"], url_path="policy-evaluations")
    def policy_evaluations(self, request, pk=None):
        from apps.policies.models import PolicyEvaluation
        from apps.policies.serializers import PolicyEvaluationDetailSerializer

        org_id = request.query_params.get("organization_id")
        if not org_id:
            return Response(
                {
                    "errors": [
                        {
                            "code": "invalid_query_params",
                            "detail": "organization_id is required.",
                            "attr": "organization_id",
                        }
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        execution = get_object_or_404(Execution, pk=pk, organization_id=org_id)
        qs = (
            PolicyEvaluation.objects.filter(execution=execution)
            .select_related("policy", "rule", "step")
            .order_by("step__position", "-evaluated_at")
        )
        return Response(
            {"results": PolicyEvaluationDetailSerializer(qs, many=True).data}
        )
