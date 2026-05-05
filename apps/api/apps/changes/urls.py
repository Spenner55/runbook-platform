from django.urls import path

from apps.changes.views import (
    BindChangeExecutionView,
    ChangeRecordDetailView,
    ChangeRecordListCreateView,
    ChangeRecordSubmitView,
    ChangeWindowView,
    DispatchPreflightLatestView,
    DispatchPreflightRunView,
    ExecutionAcceptedView,
    ExecutionFinishedView,
    ExecutionStartedView,
    FreezeRuleDeactivateView,
    FreezeRuleDetailView,
    FreezeRuleListCreateView,
    OperationProfileListView,
)

public_urlpatterns = [
    path(
        "operation-profiles/",
        OperationProfileListView.as_view(),
        name="change-operation-profile-list",
    ),
    path("", ChangeRecordListCreateView.as_view(), name="change-record-list-create"),
    path(
        "<uuid:change_id>/",
        ChangeRecordDetailView.as_view(),
        name="change-record-detail",
    ),
    path(
        "<uuid:change_id>/submit/",
        ChangeRecordSubmitView.as_view(),
        name="change-record-submit",
    ),
    path(
        "<uuid:change_id>/window/",
        ChangeWindowView.as_view(),
        name="change-record-window",
    ),
    path(
        "<uuid:change_id>/preflight/",
        DispatchPreflightRunView.as_view(),
        name="change-record-preflight-run",
    ),
    path(
        "<uuid:change_id>/preflight/latest/",
        DispatchPreflightLatestView.as_view(),
        name="change-record-preflight-latest",
    ),
]

freeze_rule_urlpatterns = [
    path(
        "",
        FreezeRuleListCreateView.as_view(),
        name="freeze-rule-list-create",
    ),
    path(
        "<uuid:rule_id>/",
        FreezeRuleDetailView.as_view(),
        name="freeze-rule-detail",
    ),
    path(
        "<uuid:rule_id>/deactivate/",
        FreezeRuleDeactivateView.as_view(),
        name="freeze-rule-deactivate",
    ),
]

internal_urlpatterns = [
    path(
        "<uuid:change_id>/bind-execution/",
        BindChangeExecutionView.as_view(),
        name="internal-change-bind-execution",
    ),
    path(
        "<uuid:change_id>/execution-accepted/",
        ExecutionAcceptedView.as_view(),
        name="internal-change-execution-accepted",
    ),
    path(
        "<uuid:change_id>/execution-started/",
        ExecutionStartedView.as_view(),
        name="internal-change-execution-started",
    ),
    path(
        "<uuid:change_id>/execution-finished/",
        ExecutionFinishedView.as_view(),
        name="internal-change-execution-finished",
    ),
]
