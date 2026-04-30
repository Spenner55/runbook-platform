from django.contrib import admin
from django.urls import include, path
from django_prometheus.exports import ExportToDjangoView

from apps.common.health import detailed_health_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", detailed_health_view),
    path("metrics/", ExportToDjangoView, name="prometheus-django-metrics"),
    path("api/v1/", include(("config.api_v1_urls", "api_v1"), namespace="v1")),
]
