import time

from django.conf import settings
from django.core.cache import cache
from django.db.models import F, Prefetch, Window
from django.db.models.functions import RowNumber
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.services import actor_from_request
from apps.common.org_context import require_organization_id
from apps.common.permissions import (
    assert_organization_member,
    assert_organization_operator,
)
from apps.common.querysets import (
    user_active_organization_scoped,
    user_organization_scoped,
)
from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.executions.serializers import (
    ExecutionCancelSerializer,
    ExecutionCreateSerializer,
    ExecutionDetailSerializer,
    ExecutionListSerializer,
)
from apps.workflows.models import Workflow

EXECUTION_LIST_FIELDS = [
    "id",
    "status",
    "workflow_id",
    "organization_id",
    "workflow_version",
    "claimed_by_runner_id",
    "claimed_at",
    "last_heartbeat_at",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
]


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
    queryset = Execution.objects.select_related("workflow", "organization").all()
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        organization_id = require_organization_id(self.request)
        if self.action == "retrieve":
            queryset = _build_detail_queryset()
        elif self.action == "list":
            queryset = Execution.objects.only(*EXECUTION_LIST_FIELDS)
        else:
            queryset = Execution.objects.select_related(
                "workflow", "organization"
            ).all()
        return user_active_organization_scoped(
            queryset,
            user=self.request.user,
            organization_id=organization_id,
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ExecutionDetailSerializer
        if self.action == "cancel":
            return ExecutionCancelSerializer
        return ExecutionListSerializer

    def retrieve(self, request, *args, **kwargs):
        organization_id = require_organization_id(request)
        execution = get_object_or_404(
            user_active_organization_scoped(
                _build_detail_queryset(),
                user=request.user,
                organization_id=organization_id,
            ),
            pk=kwargs["pk"],
        )
        return Response(ExecutionDetailSerializer(execution).data)

    def list(self, request, *args, **kwargs):
        organization_id = require_organization_id(request)
        cache_seconds = getattr(settings, "EXECUTION_LIST_CACHE_SECONDS", 0)
        if cache_seconds <= 0:
            return super().list(request, *args, **kwargs)

        cache_key = (
            "executions:list:v1:"
            f"user:{request.user.pk}:org:{organization_id}:"
            f"query:{request.META.get('QUERY_STRING', '')}"
        )
        lock_key = f"{cache_key}:refreshing"
        now = time.time()
        cached_entry = cache.get(cache_key)
        if cached_entry is not None and cached_entry["fresh_until"] > now:
            return Response(cached_entry["data"])

        stale_seconds = getattr(settings, "EXECUTION_LIST_CACHE_STALE_SECONDS", 60)
        lock_acquired = cache.add(lock_key, "1", timeout=5)
        if cached_entry is not None and not lock_acquired:
            return Response(cached_entry["data"])

        if cached_entry is None and not lock_acquired:
            for _ in range(10):
                time.sleep(0.01)
                cached_entry = cache.get(cache_key)
                if cached_entry is not None:
                    return Response(cached_entry["data"])

        response = super().list(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            cache.set(
                cache_key,
                {
                    "data": response.data,
                    "fresh_until": time.time() + cache_seconds,
                },
                timeout=cache_seconds + stale_seconds,
            )
        if lock_acquired:
            cache.delete(lock_key)
        return response

    def create(self, request):
        serializer = ExecutionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization_id = require_organization_id(request)

        workflow = get_object_or_404(
            user_organization_scoped(
                Workflow.objects.select_related("organization").all(),
                user=request.user,
            ),
            pk=serializer.validated_data["workflow_id"],
            organization_id=organization_id,
        )
        assert_organization_operator(
            user=request.user, organization_id=workflow.organization_id
        )
        execution = services.create_execution(
            workflow=workflow, actor=actor_from_request(request)
        )

        return Response(
            ExecutionDetailSerializer(execution).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        execution = self.get_object()
        assert_organization_operator(
            user=request.user, organization_id=execution.organization_id
        )
        execution = services.cancel_execution(
            execution=execution, actor=actor_from_request(request)
        )
        return Response(ExecutionDetailSerializer(execution).data)

    @action(detail=True, methods=["get"], url_path="policy-evaluations")
    def policy_evaluations(self, request, pk=None):
        from apps.policies.models import PolicyEvaluation
        from apps.policies.serializers import PolicyEvaluationDetailSerializer

        org_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=org_id)
        execution = get_object_or_404(
            self.get_queryset(), pk=pk, organization_id=org_id
        )
        qs = (
            PolicyEvaluation.objects.filter(execution=execution)
            .select_related("policy", "rule", "step")
            .order_by("step__position", "-evaluated_at")
        )
        return Response(
            {"results": PolicyEvaluationDetailSerializer(qs, many=True).data}
        )
