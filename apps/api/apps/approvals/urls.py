from django.urls import path

from apps.approvals.views import (
    ApprovalRequestDetailView,
    ApprovalRequestListView,
    DecideApprovalView,
)

urlpatterns = [
    path("", ApprovalRequestListView.as_view(), name="approval-request-list"),
    path(
        "<uuid:approval_request_id>/",
        ApprovalRequestDetailView.as_view(),
        name="approval-request-detail",
    ),
    path(
        "<uuid:approval_request_id>/decide/",
        DecideApprovalView.as_view(),
        name="approval-request-decide",
    ),
]
