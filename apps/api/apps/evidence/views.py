"""Public evidence bundle API views."""

from django.core.exceptions import ValidationError
from django.http import FileResponse
from rest_framework import status as http_status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import actor_from_request
from apps.changes.models import ChangeRecord
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.common.org_context import require_organization_id
from apps.common.permissions import (
    OPERATOR_ROLES,
    assert_organization_member,
    assert_organization_role,
)
from apps.evidence import services
from apps.evidence.models import (
    EvidenceBundle,
    EvidenceExport,
    EvidenceRedactionPolicy,
    LegalHold,
)
from apps.evidence.serializers import (
    EvidenceBundleCompletenessSerializer,
    EvidenceBundleCreateSerializer,
    EvidenceBundleInvalidateSerializer,
    EvidenceBundleManifestSerializer,
    EvidenceBundleSealSerializer,
    EvidenceBundleSerializer,
    EvidenceBundleSummarySerializer,
    EvidenceExportCreateSerializer,
    EvidenceExportSerializer,
    LegalHoldCreateSerializer,
    LegalHoldReleaseSerializer,
    LegalHoldSerializer,
)
from apps.evidence.storage import EvidenceStorage
from apps.organizations.models import Organization


def _error_response(exc, *, status=None):
    if isinstance(exc, ValidationError):
        code = getattr(exc, "code", None) or "invalid"
        detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return Response(
            {"errors": [{"code": code, "detail": detail}]},
            status=status or http_status.HTTP_400_BAD_REQUEST,
        )
    http_code = status or getattr(exc, "http_status", http_status.HTTP_400_BAD_REQUEST)
    return Response(
        {"errors": [{"code": exc.code, "detail": exc.detail}]},
        status=http_code,
    )


def _get_org(request):
    organization_id = require_organization_id(request)
    return get_object_or_404(Organization, pk=organization_id)


def _get_change(change_id, org):
    return get_object_or_404(ChangeRecord, pk=change_id, organization=org)


def _get_bundle(bundle_id, org):
    return get_object_or_404(
        EvidenceBundle.objects.select_related("change_record", "organization"),
        pk=bundle_id,
        organization=org,
    )


class ChangeEvidenceBundleListCreateView(APIView):
    """GET/POST /api/v1/changes/{change_id}/evidence-bundles/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        change = _get_change(change_id, org)
        bundles = EvidenceBundle.objects.filter(
            organization=org,
            change_record=change,
        ).order_by("-version", "-created_at")
        return Response(
            {"results": EvidenceBundleSummarySerializer(bundles, many=True).data}
        )

    def post(self, request, change_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        change = _get_change(change_id, org)

        serializer = EvidenceBundleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            bundle = services.create_evidence_bundle_for_change(
                change_record=change,
                created_by=request.user,
                actor=actor_from_request(request),
            )
        except (ValidationError, DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)

        bundle.refresh_from_db()
        return Response(
            EvidenceBundleSerializer(bundle).data,
            status=http_status.HTTP_201_CREATED,
        )


class ChangeEvidenceBundleLatestView(APIView):
    """GET /api/v1/changes/{change_id}/evidence-bundles/latest/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        change = _get_change(change_id, org)
        base_qs = EvidenceBundle.objects.filter(
            organization=org,
            change_record=change,
        )
        bundle = (
            base_qs.exclude(status=EvidenceBundle.Status.INVALIDATED)
            .order_by("-version", "-created_at")
            .first()
        )
        if bundle is None:
            bundle = base_qs.order_by("-version", "-created_at").first()
        if bundle is None:
            return Response(
                {
                    "errors": [
                        {
                            "code": "not_found",
                            "detail": "Evidence bundle not found.",
                        }
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(EvidenceBundleSerializer(bundle).data)


class EvidenceBundleDetailView(APIView):
    """GET /api/v1/evidence-bundles/{bundle_id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        bundle = _get_bundle(bundle_id, org)
        return Response(EvidenceBundleSerializer(bundle).data)


class EvidenceBundleManifestView(APIView):
    """GET /api/v1/evidence-bundles/{bundle_id}/manifest/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        bundle = _get_bundle(bundle_id, org)
        return Response(EvidenceBundleManifestSerializer(bundle).data)


class EvidenceBundleCompletenessView(APIView):
    """GET /api/v1/evidence-bundles/{bundle_id}/completeness/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        bundle = _get_bundle(bundle_id, org)
        return Response(EvidenceBundleCompletenessSerializer(bundle).data)


class EvidenceBundleSealView(APIView):
    """POST /api/v1/evidence-bundles/{bundle_id}/seal/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        bundle = _get_bundle(bundle_id, org)

        serializer = EvidenceBundleSealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            sealed = services.seal_bundle(
                bundle,
                actor=actor_from_request(request),
                sealed_by=request.user,
            )
        except (ValidationError, DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)

        sealed.refresh_from_db()
        return Response(EvidenceBundleSerializer(sealed).data)


class EvidenceBundleInvalidateView(APIView):
    """POST /api/v1/evidence-bundles/{bundle_id}/invalidate/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        bundle = _get_bundle(bundle_id, org)

        serializer = EvidenceBundleInvalidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            invalidated = services.invalidate_bundle(
                bundle,
                reason=d["reason"],
                actor=actor_from_request(request),
                invalidated_by=request.user,
            )
        except (ValidationError, DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)

        invalidated.refresh_from_db()
        return Response(EvidenceBundleSerializer(invalidated).data)


class EvidenceBundleDownloadView(APIView):
    """POST /api/v1/evidence-bundles/{bundle_id}/download/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        bundle = _get_bundle(bundle_id, org)
        try:
            result = services.create_bundle_download_url(
                bundle=bundle,
                actor=actor_from_request(request),
            )
        except (ValidationError, DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)
        return Response(result)


class EvidenceBundleContentView(APIView):
    """GET /api/v1/evidence-bundles/{bundle_id}/content/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        bundle = _get_bundle(bundle_id, org)
        token = request.query_params.get("token")
        if not token:
            raise DomainValidationError(
                code="evidence_bundle_download_token_required",
                detail="Evidence bundle download token is required.",
            )
        if bundle.status != EvidenceBundle.Status.SEALED:
            raise DomainValidationError(
                code="evidence_bundle_not_sealed",
                detail="Only sealed evidence bundles can be downloaded.",
            )
        services.validate_bundle_download_token(bundle=bundle, token=token)
        storage = EvidenceStorage()
        if bundle.storage_deleted_at is not None or not storage.exists(
            bundle.storage_key
        ):
            return Response(
                {
                    "errors": [
                        {
                            "code": "evidence_bundle_storage_missing",
                            "detail": "Evidence bundle storage is not available.",
                        }
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )

        file_obj = storage.open(bundle.storage_key)
        response = FileResponse(file_obj, content_type=bundle.mime_type)
        filename = f"evidence-bundle-{bundle.change_record_id}-v{bundle.version}.zip"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


def _get_export(export_id, org):
    return get_object_or_404(
        EvidenceExport.objects.select_related("bundle", "organization"),
        pk=export_id,
        organization=org,
    )


class EvidenceBundleExportListCreateView(APIView):
    """GET/POST /api/v1/evidence-bundles/{bundle_id}/exports/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        bundle = _get_bundle(bundle_id, org)
        exports = EvidenceExport.objects.filter(
            organization=org,
            bundle=bundle,
        ).order_by("-requested_at")
        return Response({"results": EvidenceExportSerializer(exports, many=True).data})

    def post(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        bundle = _get_bundle(bundle_id, org)

        serializer = EvidenceExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        redaction_policy = None
        policy_id = d.get("redaction_policy_id")
        if policy_id:
            redaction_policy = get_object_or_404(
                EvidenceRedactionPolicy,
                pk=policy_id,
                organization=org,
            )

        try:
            export = services.create_export(
                bundle,
                redaction_policy=redaction_policy,
                actor=actor_from_request(request),
                requested_by=request.user,
            )
        except (ValidationError, DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)

        export.refresh_from_db()
        return Response(
            EvidenceExportSerializer(export).data,
            status=http_status.HTTP_201_CREATED,
        )


class EvidenceExportDetailView(APIView):
    """GET /api/v1/evidence-exports/{export_id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, export_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        export = _get_export(export_id, org)
        return Response(EvidenceExportSerializer(export).data)


class EvidenceExportReceiptView(APIView):
    """GET /api/v1/evidence-exports/{export_id}/receipt/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, export_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        export = _get_export(export_id, org)
        return Response(
            {
                "id": export.id,
                "bundle_id": export.bundle_id,
                "status": export.status,
                "receipt": export.receipt,
                "receipt_sha256": export.receipt_sha256,
                "source_manifest_sha256": export.source_manifest_sha256,
                "source_bundle_content_sha256": export.source_bundle_content_sha256,
                "redaction_summary": export.redaction_summary,
            }
        )


class EvidenceExportDownloadView(APIView):
    """GET /api/v1/evidence-exports/{export_id}/download/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, export_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        export = _get_export(export_id, org)

        if export.status != EvidenceExport.Status.READY:
            return _error_response(
                DomainValidationError(
                    code="export_not_ready", detail="Export is not ready."
                ),
                status=http_status.HTTP_409_CONFLICT,
            )
        if export.storage_deleted_at is not None or not export.storage_key:
            return _error_response(
                DomainValidationError(
                    code="export_storage_missing",
                    detail="Export storage is not available.",
                ),
                status=http_status.HTTP_409_CONFLICT,
            )

        try:
            export_bytes = services.download_export(
                export,
                actor=actor_from_request(request),
            )
        except (ValidationError, DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc, status=http_status.HTTP_409_CONFLICT)

        import io

        file_obj = io.BytesIO(export_bytes)
        filename = f"evidence-export-{export.bundle.change_record_id}-{export.id}.zip"
        response = FileResponse(file_obj, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class EvidenceBundleLegalHoldView(APIView):
    """POST /api/v1/evidence-bundles/{bundle_id}/legal-hold/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, bundle_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        bundle = _get_bundle(bundle_id, org)

        serializer = LegalHoldCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            hold = services.create_legal_hold(
                bundle,
                reason=d["reason"],
                external_reference=d.get("external_reference", ""),
                actor=actor_from_request(request),
                placed_by=request.user,
            )
        except (ValidationError, DomainValidationError) as exc:
            return _error_response(exc)
        except DomainConflictError as exc:
            return _error_response(exc, status=http_status.HTTP_409_CONFLICT)

        return Response(
            LegalHoldSerializer(hold).data,
            status=http_status.HTTP_201_CREATED,
        )


def _get_legal_hold(hold_id, org):
    return get_object_or_404(LegalHold, pk=hold_id, organization=org)


class LegalHoldReleaseView(APIView):
    """POST /api/v1/legal-holds/{hold_id}/release/ — admin-only."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, hold_id):
        from apps.common.permissions import ADMIN_ROLES, assert_organization_role

        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=ADMIN_ROLES
        )
        hold = _get_legal_hold(hold_id, org)

        serializer = LegalHoldReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            released = services.release_legal_hold(
                hold,
                released_by=request.user,
                release_reason=d["release_reason"],
                actor=actor_from_request(request),
            )
        except (ValidationError, DomainValidationError) as exc:
            return _error_response(exc)

        return Response(LegalHoldSerializer(released).data)
