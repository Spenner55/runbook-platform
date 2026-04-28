from django.urls import path

from apps.policies.views import (
    PolicyListCreateView,
    PolicyRetrieveUpdateView,
    PolicyRuleCreateView,
    PolicyRuleUpdateDeactivateView,
)

urlpatterns = [
    path("", PolicyListCreateView.as_view(), name="policy-list-create"),
    path("<uuid:policy_id>/", PolicyRetrieveUpdateView.as_view(), name="policy-detail"),
    path(
        "<uuid:policy_id>/rules/",
        PolicyRuleCreateView.as_view(),
        name="policy-rule-create",
    ),
    path(
        "<uuid:policy_id>/rules/<uuid:rule_id>/",
        PolicyRuleUpdateDeactivateView.as_view(),
        name="policy-rule-detail",
    ),
]
