from django.urls import path

from apps.artifacts.internal_views import (
    InternalExecutionArtifactUploadView,
    InternalStepArtifactUploadView,
)
from apps.artifacts.views import (
    ArtifactContentView,
    ArtifactDownloadView,
    ExecutionArtifactListView,
)

# Public artifact URL patterns — included from api_v1_urls.py
public_urlpatterns = [
    path(
        "executions/<uuid:execution_id>/artifacts/",
        ExecutionArtifactListView.as_view(),
        name="execution-artifact-list",
    ),
    path(
        "artifacts/<uuid:artifact_id>/download/",
        ArtifactDownloadView.as_view(),
        name="artifact-download",
    ),
    path(
        "artifacts/<uuid:artifact_id>/content/",
        ArtifactContentView.as_view(),
        name="artifact-content",
    ),
]

# Internal runner URL patterns — included from api_v1_urls.py under /internal/
internal_urlpatterns = [
    path(
        "executions/<uuid:execution_id>/steps/<uuid:step_id>/artifacts/",
        InternalStepArtifactUploadView.as_view(),
        name="internal-step-artifact-upload",
    ),
    path(
        "executions/<uuid:execution_id>/artifacts/",
        InternalExecutionArtifactUploadView.as_view(),
        name="internal-execution-artifact-upload",
    ),
]
