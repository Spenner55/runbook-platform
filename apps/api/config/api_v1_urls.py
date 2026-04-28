"""
Versioned API route tree.

Public product endpoints are registered on the router. Runner-only endpoints
stay as explicit `/internal/` paths so their serializers and ownership rules do
not leak into public viewsets.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.executions.internal_views import (
    ApprovalStatusView,
    ClaimNextExecutionView,
    ExecutionCompleteView,
    ExecutionHeartbeatView,
    ExecutionStepStartView,
    ExecutionStepUpdateView,
)
from apps.executions.views import ExecutionViewSet
from apps.organizations.views import OrganizationViewSet
from apps.runbooks.views import RunbookViewSet
from apps.workflows.views import WorkflowViewSet

router = SimpleRouter()
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("runbooks", RunbookViewSet, basename="runbook")
router.register("workflows", WorkflowViewSet, basename="workflow")
router.register("executions", ExecutionViewSet, basename="execution")

urlpatterns = [
    path("", include(router.urls)),
    path("approvals/", include("apps.approvals.urls")),
    path("policies/", include("apps.policies.urls")),
    path(
        "internal/executions/claim-next/",
        ClaimNextExecutionView.as_view(),
        name="internal-execution-claim-next",
    ),
    path(
        "internal/executions/<uuid:execution_id>/heartbeat/",
        ExecutionHeartbeatView.as_view(),
        name="internal-execution-heartbeat",
    ),
    path(
        "internal/executions/<uuid:execution_id>/steps/<uuid:step_id>/start/",
        ExecutionStepStartView.as_view(),
        name="internal-execution-step-start",
    ),
    path(
        "internal/executions/<uuid:execution_id>/steps/<uuid:step_id>/approval-status/",
        ApprovalStatusView.as_view(),
        name="internal-execution-approval-status",
    ),
    path(
        "internal/executions/<uuid:execution_id>/steps/<uuid:step_id>/update/",
        ExecutionStepUpdateView.as_view(),
        name="internal-execution-step-update",
    ),
    path(
        "internal/executions/<uuid:execution_id>/complete/",
        ExecutionCompleteView.as_view(),
        name="internal-execution-complete",
    ),
]
