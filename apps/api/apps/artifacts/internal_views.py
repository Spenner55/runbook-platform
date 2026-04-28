"""
Internal runner artifact upload view.

Not registered on the public router. Only callable by runners that own
an active execution through their claim token.
"""

import logging

from rest_framework import status as http_status
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.artifacts import services as artifact_services
from apps.artifacts.serializers import ArtifactSerializer, ArtifactUploadSerializer
from apps.executions.models import Execution, ExecutionStep

logger = logging.getLogger(__name__)


class InternalStepArtifactUploadView(APIView):
    """POST /api/v1/internal/executions/{execution_id}/steps/{step_id}/artifacts/"""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, execution_id, step_id):
        serializer = ArtifactUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        execution = get_object_or_404(Execution, pk=execution_id)
        step = get_object_or_404(ExecutionStep, pk=step_id, execution=execution)

        artifact = artifact_services.create_from_runner_upload(
            execution=execution,
            step=step,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            kind=d["kind"],
            name=d["name"],
            file_obj=d["file"],
            declared_mime_type=d.get("mime_type", ""),
            declared_checksum_sha256=d.get("checksum_sha256", ""),
            metadata=d.get("metadata", {}),
        )

        return Response(
            ArtifactSerializer(artifact).data, status=http_status.HTTP_201_CREATED
        )


class InternalExecutionArtifactUploadView(APIView):
    """POST /api/v1/internal/executions/{execution_id}/artifacts/"""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, execution_id):
        serializer = ArtifactUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        execution = get_object_or_404(Execution, pk=execution_id)

        artifact = artifact_services.create_from_runner_upload(
            execution=execution,
            step=None,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            kind=d["kind"],
            name=d["name"],
            file_obj=d["file"],
            declared_mime_type=d.get("mime_type", ""),
            declared_checksum_sha256=d.get("checksum_sha256", ""),
            metadata=d.get("metadata", {}),
        )

        return Response(
            ArtifactSerializer(artifact).data, status=http_status.HTTP_201_CREATED
        )
