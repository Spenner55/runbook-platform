from django.urls import path

from apps.changes.views import (
    BindChangeExecutionView,
    ChangeRecordDetailView,
    ChangeRecordListCreateView,
    ChangeRecordSubmitView,
    OperationProfileListView,
)

public_urlpatterns = [
    path("operation-profiles/", OperationProfileListView.as_view(), name="change-operation-profile-list"),
    path("", ChangeRecordListCreateView.as_view(), name="change-record-list-create"),
    path("<uuid:change_id>/", ChangeRecordDetailView.as_view(), name="change-record-detail"),
    path("<uuid:change_id>/submit/", ChangeRecordSubmitView.as_view(), name="change-record-submit"),
]

internal_urlpatterns = [
    path(
        "<uuid:change_id>/bind-execution/",
        BindChangeExecutionView.as_view(),
        name="internal-change-bind-execution",
    ),
]
