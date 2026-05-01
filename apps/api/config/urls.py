from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.common.health import detailed_health_view, live_view, readiness_view
from apps.common.metrics import metrics_view


def build_urlpatterns(admin_enabled: bool | None = None):
    if admin_enabled is None:
        admin_enabled = getattr(settings, "DJANGO_ADMIN_ENABLED", True)

    patterns = []
    if admin_enabled:
        patterns.append(path("admin/", admin.site.urls))

    patterns.extend(
        [
            path("health/live", live_view),
            path("health/ready/", readiness_view),
            path("health/", detailed_health_view),
            path("metrics/", metrics_view, name="prometheus-django-metrics"),
            path("api/v1/", include(("config.api_v1_urls", "api_v1"), namespace="v1")),
        ]
    )
    return patterns


urlpatterns = build_urlpatterns()
