from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.runners.internal_views import RunnerHeartbeatView, RunnerRegisterView
from apps.runners.views import (
    RunnerPoolViewSet,
    RunnerViewSet,
    TargetConnectivityRouteViewSet,
)

internal_urlpatterns = [
    path("register/", RunnerRegisterView.as_view(), name="runner-register"),
    path("heartbeat/", RunnerHeartbeatView.as_view(), name="runner-heartbeat"),
]

_router = SimpleRouter()
_router.register("runner-pools", RunnerPoolViewSet, basename="runner-pool")
_router.register("runners", RunnerViewSet, basename="runner")
_router.register(
    "target-connectivity-routes",
    TargetConnectivityRouteViewSet,
    basename="target-connectivity-route",
)

public_urlpatterns = _router.urls
