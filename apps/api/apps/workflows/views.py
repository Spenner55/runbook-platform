from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.services import actor_from_request
from apps.common.exceptions import ExternalDependencyError
from apps.common.org_context import require_organization_id
from apps.common.permissions import assert_organization_operator
from apps.common.querysets import (
    user_active_organization_scoped,
    user_organization_scoped,
)
from apps.runbooks.models import Runbook
from apps.workflows import services
from apps.workflows.internal_clients import (
    AiServiceBadResponseError,
    AiServiceContractError,
    AiServiceTimeoutError,
    AiServiceUnavailableError,
)
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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        organization_id = require_organization_id(self.request)
        return user_active_organization_scoped(
            Workflow.objects.select_related("runbook", "organization").all(),
            user=self.request.user,
            organization_id=organization_id,
        )

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
        organization_id = require_organization_id(request)

        runbook = get_object_or_404(
            user_organization_scoped(
                Runbook.objects.select_related("organization").all(),
                user=request.user,
            ),
            pk=serializer.validated_data["runbook_id"],
            organization_id=organization_id,
        )
        assert_organization_operator(
            user=request.user, organization_id=runbook.organization_id
        )

        try:
            workflow = services.create_workflow_from_runbook(
                runbook=runbook, actor=actor_from_request(request)
            )
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

        return Response(
            WorkflowDetailSerializer(workflow).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        workflow = self.get_object()
        assert_organization_operator(
            user=request.user, organization_id=workflow.organization_id
        )
        workflow = services.publish_workflow(
            workflow=workflow, actor=actor_from_request(request)
        )
        return Response(WorkflowDetailSerializer(workflow).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        workflow = self.get_object()
        assert_organization_operator(
            user=request.user, organization_id=workflow.organization_id
        )
        workflow = services.archive_workflow(
            workflow=workflow, actor=actor_from_request(request)
        )
        return Response(WorkflowDetailSerializer(workflow).data)

    @action(detail=True, methods=["post"], url_path="accept-review")
    def accept_review(self, request, pk=None):
        workflow = self.get_object()
        assert_organization_operator(
            user=request.user, organization_id=workflow.organization_id
        )
        workflow = services.accept_review(
            workflow=workflow, actor=actor_from_request(request)
        )
        return Response(WorkflowDetailSerializer(workflow).data)

    @action(detail=True, methods=["post"], url_path="reject-review")
    def reject_review(self, request, pk=None):
        workflow = self.get_object()
        assert_organization_operator(
            user=request.user, organization_id=workflow.organization_id
        )
        workflow = services.reject_review(
            workflow=workflow, actor=actor_from_request(request)
        )
        return Response(WorkflowDetailSerializer(workflow).data)
