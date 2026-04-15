from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "service": "api"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("api/v1/", include("apps.organizations.urls")),
    path("api/v1/", include("apps.runbooks.urls")),
    path("api/v1/", include("apps.workflows.urls")),
    path("api/v1/", include("apps.executions.urls")),
]
