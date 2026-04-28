from django.urls import path

from apps.integrations.views import (
    IntegrationConnectionDetailView,
    IntegrationConnectionListCreateView,
    IntegrationDeactivateView,
    IntegrationDeliveryAttemptListView,
)

urlpatterns = [
    path("", IntegrationConnectionListCreateView.as_view(), name="integration-list"),
    path(
        "<uuid:integration_id>/",
        IntegrationConnectionDetailView.as_view(),
        name="integration-detail",
    ),
    path(
        "<uuid:integration_id>/deactivate/",
        IntegrationDeactivateView.as_view(),
        name="integration-deactivate",
    ),
    path(
        "<uuid:integration_id>/delivery-attempts/",
        IntegrationDeliveryAttemptListView.as_view(),
        name="integration-delivery-attempt-list",
    ),
]
