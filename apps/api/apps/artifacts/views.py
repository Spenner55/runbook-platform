"""
Public artifact API views for the frontend.

Never exposes storage_key or claim tokens.
"""

import logging

from django.http import FileResponse
from rest_framework import status as http_status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.artifacts import services as artifact_services
from apps.artifacts.models import Artifact
from apps.artifacts.serializers import ArtifactSerializer
from apps.artifacts.storage import ArtifactStorage
from apps.audit.services import actor_from_request
from apps.common.exceptions import DomainValidationError
from apps.executions.models import Execution

logger = logging.getLogger(__name__)


class ExecutionArtifactListView(APIView):
    """GET /api/v1/executions/{execution_id}/artifacts/"""

    def get(self, request, execution_id):
        execution = get_object_or_404(Execution, pk=execution_id)

        step_id = request.query_params.get("step_id")
        kind = request.query_params.get("kind")

        try:
            limit = min(int(request.query_params.get("limit", 50)), 200)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            limit, offset = 50, 0

        if kind is not None and kind not in Artifact.Kind.values:
            raise DomainValidationError(
                code="artifact_invalid_kind",
                detail=f"Invalid kind '{kind}'. Allowed: {', '.join(Artifact.Kind.values)}.",
            )

        total, artifacts = artifact_services.list_for_execution(
            execution=execution,
            step_id=step_id,
            kind=kind,
            limit=limit,
            offset=offset,
        )

        next_offset = offset + limit if offset + limit < total else None
        prev_offset = offset - limit if offset > 0 else None

        return Response(
            {
                "count": total,
                "next": next_offset,
                "previous": prev_offset,
                "results": ArtifactSerializer(artifacts, many=True).data,
            }
        )


class ArtifactDownloadView(APIView):
    """POST /api/v1/artifacts/{artifact_id}/download/"""

    def post(self, request, artifact_id):
        artifact = get_object_or_404(
            Artifact, pk=artifact_id, upload_status=Artifact.UploadStatus.AVAILABLE
        )
        actor = actor_from_request(request)
        result = artifact_services.create_download_url(artifact=artifact, actor=actor)
        return Response(result, status=http_status.HTTP_200_OK)


class ArtifactContentView(APIView):
    """
    GET /api/v1/artifacts/{artifact_id}/content/

    Streams artifact bytes through Django for local dev.
    In production this endpoint could be replaced by S3 presigned URLs and
    disabled or restricted to internal use only.
    """

    def get(self, request, artifact_id):
        artifact = get_object_or_404(
            Artifact, pk=artifact_id, upload_status=Artifact.UploadStatus.AVAILABLE
        )
        storage = ArtifactStorage()
        if not storage.exists(artifact.storage_key):
            return Response(
                {"errors": [{"code": "artifact_not_found", "detail": "Artifact file not found in storage."}]},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        file_obj = storage.open(artifact.storage_key)
        response = FileResponse(
            file_obj,
            content_type=artifact.mime_type,
        )
        disposition = artifact.content_disposition
        response["Content-Disposition"] = f'{disposition}; filename="{artifact.name}"'
        return response
