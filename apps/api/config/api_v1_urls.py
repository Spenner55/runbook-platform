"""
Versioned API route tree.

Public product endpoints are registered on the router. Runner-only endpoints
stay as explicit `/internal/` paths so their serializers and ownership rules do
not leak into public viewsets.
"""

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from apps.artifacts.urls import internal_urlpatterns as artifact_internal_urlpatterns
from apps.artifacts.urls import public_urlpatterns as artifact_public_urlpatterns
from apps.audit.views import ExecutionAuditEventListView
from apps.auditor.urls import urlpatterns as auditor_public_urlpatterns
from apps.changes.urls import (
    freeze_rule_urlpatterns as change_freeze_rule_urlpatterns,
)
from apps.changes.urls import (
    internal_urlpatterns as change_internal_urlpatterns,
)
from apps.changes.urls import (
    public_urlpatterns as change_public_urlpatterns,
)
from apps.evidence.urls import urlpatterns as evidence_public_urlpatterns
from apps.executions.internal_views import (
    ApprovalStatusView,
    ClaimNextExecutionView,
    ExecutionCompleteView,
    ExecutionHeartbeatView,
    ExecutionStepStartView,
    ExecutionStepUpdateView,
)
from apps.executions.stream_views import StreamExecutionView
from apps.executions.views import ExecutionViewSet
from apps.organizations.views import OrganizationViewSet
from apps.runbooks.views import RunbookViewSet
from apps.runners.urls import internal_urlpatterns as runner_internal_urlpatterns
from apps.runners.urls import public_urlpatterns as runner_public_urlpatterns
from apps.runners.views import ChangeRunnerEligibilityView
from apps.workflows.views import WorkflowViewSet

router = SimpleRouter()
router.register("organizations", OrganizationViewSet, basename="organization")
router.register("runbooks", RunbookViewSet, basename="runbook")
router.register("workflows", WorkflowViewSet, basename="workflow")
router.register("executions", ExecutionViewSet, basename="execution")

urlpatterns = [
    path("auth/", include("apps.users.urls")),
    path("", include(router.urls)),
    path("approvals/", include("apps.approvals.urls")),
    path("policies/", include("apps.policies.urls")),
    path("audit/", include("apps.audit.urls")),
    path("integrations/", include("apps.integrations.urls")),
    path("changes/", include((change_public_urlpatterns, "changes"))),
    path("", include((evidence_public_urlpatterns, "evidence"))),
    path("", include((auditor_public_urlpatterns, "auditor"))),
    path("freeze-rules/", include((change_freeze_rule_urlpatterns, "freeze-rules"))),
    *artifact_public_urlpatterns,
    path(
        "executions/<uuid:execution_id>/audit/",
        ExecutionAuditEventListView.as_view(),
        name="execution-audit-event-list",
    ),
    path(
        "executions/<uuid:execution_id>/stream/",
        StreamExecutionView.as_view(),
        name="execution-stream",
    ),
    path("", include((runner_public_urlpatterns, "runners"))),
    path(
        "changes/<uuid:change_id>/runner-eligibility/",
        ChangeRunnerEligibilityView.as_view(),
        name="change-runner-eligibility",
    ),
    path("internal/", include(artifact_internal_urlpatterns)),
    path(
        "internal/runners/", include((runner_internal_urlpatterns, "runners-internal"))
    ),
    path(
        "internal/changes/", include((change_internal_urlpatterns, "changes-internal"))
    ),
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
