from urllib.parse import urlencode

from django.http import Http404
from rest_framework import status as http_status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import actor_from_request
from apps.auditor import selectors, services
from apps.auditor.models import (
    AuditorAccessGrant,
    ControlMappingProfile,
    ExternalChangeReference,
    ServiceCatalogEntry,
)
from apps.auditor.serializers import (
    AuditChangeDetailSerializer,
    AuditChangeListQuerySerializer,
    AuditChangeSummarySerializer,
    AuditorAccessGrantSerializer,
    ChangeControlCoverageSerializer,
    ControlMappingProfileSerializer,
    CoverageRecomputeSerializer,
    ExternalChangeReferenceCreateSerializer,
    ExternalChangeReferenceSerializer,
    ServiceCatalogEntrySerializer,
)
from apps.changes.models import ChangeRecord
from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.common.org_context import require_organization_id
from apps.common.permissions import (
    ADMIN_ROLES,
    OPERATOR_ROLES,
    assert_organization_member,
    assert_organization_role,
)
from apps.evidence.models import EvidenceBundle
from apps.organizations.models import Organization
from apps.users.models import User


def _error_response(exc, *, status=None):
    http_code = status or getattr(exc, "http_status", http_status.HTTP_400_BAD_REQUEST)
    return Response(
        {"errors": [{"code": exc.code, "detail": exc.detail}]},
        status=http_code,
    )


def _not_found(detail="Not found."):
    return Response(
        {"errors": [{"code": "not_found", "detail": detail}]},
        status=http_status.HTTP_404_NOT_FOUND,
    )


def _get_org(request):
    organization_id = require_organization_id(request)
    return get_object_or_404(Organization, pk=organization_id)


def _page_url(request, count: int, limit: int, offset: int):
    if offset < 0 or offset >= count:
        return None
    params = request.query_params.copy()
    params["limit"] = str(limit)
    params["offset"] = str(offset)
    return f"{request.path}?{urlencode(params, doseq=True)}"


class AuditChangeListView(APIView):
    """GET /api/v1/audit/changes/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        serializer = AuditChangeListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        limit = params.pop("limit", 50)
        offset = params.pop("offset", 0)

        qs = selectors.audit_change_queryset(
            organization=org,
            user=request.user,
            filters=params,
            allow_admin_bypass=True,
        )
        if "has_exception" in params:
            qs = [
                change
                for change in qs
                if selectors._change_projection(change)["has_exception"]
                is params["has_exception"]
            ]
            count = len(qs)
            page = qs[offset : offset + limit]
            results = [selectors._change_projection(change) for change in page]
        else:
            count = qs.count()
            results = [
                selectors._change_projection(change)
                for change in qs[offset : offset + limit]
            ]
        return Response(
            {
                "count": count,
                "next": _page_url(request, count, limit, offset + limit),
                "previous": _page_url(request, count, limit, offset - limit)
                if offset > 0
                else None,
                "results": AuditChangeSummarySerializer(results, many=True).data,
            }
        )


class AuditChangeDetailView(APIView):
    """GET /api/v1/audit/changes/{change_id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        try:
            change = selectors.get_audit_change_detail(
                organization=org,
                user=request.user,
                change_id=change_id,
                allow_admin_bypass=True,
            )
        except Http404:
            return _not_found("Change record not found.")
        data = selectors._change_projection(change)
        data.update(
            {
                "summary": change.summary,
                "justification": change.justification,
                "external_references": list(change.external_references.all()),
                "control_coverage": list(change.control_coverages.all()),
                "created_at": change.created_at,
                "updated_at": change.updated_at,
            }
        )
        return Response(AuditChangeDetailSerializer(data).data)


class ChangeExternalReferenceListCreateView(APIView):
    """GET/POST /api/v1/changes/{change_id}/external-references/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        change = get_object_or_404(ChangeRecord, pk=change_id, organization=org)
        refs = selectors.external_references_for_change(
            organization=org, change_record=change
        )
        return Response(
            {"results": ExternalChangeReferenceSerializer(refs, many=True).data}
        )

    def post(self, request, change_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        change = get_object_or_404(ChangeRecord, pk=change_id, organization=org)
        serializer = ExternalChangeReferenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reference = services.link_external_change_reference(
                change_record=change,
                linked_by=request.user,
                actor=actor_from_request(request),
                **serializer.validated_data,
            )
        except (DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)
        return Response(
            ExternalChangeReferenceSerializer(reference).data,
            status=http_status.HTTP_201_CREATED,
        )


class ExternalReferenceDetailView(APIView):
    """GET /api/v1/external-references/{reference_id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, reference_id):
        org = _get_org(request)
        assert_organization_member(user=request.user, organization_id=org.id)
        reference = get_object_or_404(
            ExternalChangeReference, pk=reference_id, organization=org
        )
        return Response(ExternalChangeReferenceSerializer(reference).data)


class ExternalReferenceRefreshView(APIView):
    """POST /api/v1/external-references/{reference_id}/refresh/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, reference_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        reference = get_object_or_404(
            ExternalChangeReference, pk=reference_id, organization=org
        )
        try:
            reference = services.refresh_external_change_reference(
                reference=reference,
                refreshed_by=request.user,
                actor=actor_from_request(request),
            )
        except Exception:
            return Response(
                {
                    "errors": [
                        {
                            "code": "external_reference_refresh_failed",
                            "detail": "External reference refresh failed.",
                        }
                    ]
                },
                status=http_status.HTTP_502_BAD_GATEWAY,
            )
        return Response(ExternalChangeReferenceSerializer(reference).data)


class ServiceCatalogEntryListCreateView(APIView):
    """GET/POST /api/v1/audit/service-catalog/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        include_inactive = request.query_params.get("include_inactive") == "true"
        services_qs = selectors.service_catalog_queryset(
            organization=org, include_inactive=include_inactive
        )
        return Response(
            {"results": ServiceCatalogEntrySerializer(services_qs, many=True).data}
        )

    def post(self, request):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        serializer = ServiceCatalogEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            service = services.create_service_catalog_entry(
                organization=org,
                actor=actor_from_request(request),
                created_by=request.user,
                **serializer.validated_data,
            )
        except (DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)
        return Response(
            ServiceCatalogEntrySerializer(service).data,
            status=http_status.HTTP_201_CREATED,
        )


class ServiceCatalogEntryDetailView(APIView):
    """GET/PATCH/DELETE /api/v1/audit/service-catalog/{service_id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, service_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        service = get_object_or_404(ServiceCatalogEntry, pk=service_id, organization=org)
        return Response(ServiceCatalogEntrySerializer(service).data)

    def patch(self, request, service_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        service = get_object_or_404(ServiceCatalogEntry, pk=service_id, organization=org)
        serializer = ServiceCatalogEntrySerializer(
            service, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        try:
            service = services.update_service_catalog_entry(
                service=service,
                actor=actor_from_request(request),
                updated_by=request.user,
                **serializer.validated_data,
            )
        except (DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)
        return Response(ServiceCatalogEntrySerializer(service).data)

    def delete(self, request, service_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        service = get_object_or_404(ServiceCatalogEntry, pk=service_id, organization=org)
        try:
            services.update_service_catalog_entry(
                service=service,
                actor=actor_from_request(request),
                updated_by=request.user,
                is_active=False,
            )
        except (DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class ControlMappingProfileListCreateView(APIView):
    """GET/POST /api/v1/audit/control-mapping-profiles/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        qs = ControlMappingProfile.objects.filter(organization=org).order_by(
            "standard", "key", "-version"
        )
        if request.query_params.get("include_inactive") != "true":
            qs = qs.filter(is_active=True)
        return Response(
            {"results": ControlMappingProfileSerializer(qs, many=True).data}
        )

    def post(self, request):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        serializer = ControlMappingProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save(
            organization=org,
            created_by=request.user,
            updated_by=request.user,
        )
        return Response(
            ControlMappingProfileSerializer(profile).data,
            status=http_status.HTTP_201_CREATED,
        )


class ControlMappingProfileDetailView(APIView):
    """GET/PATCH/DELETE /api/v1/audit/control-mapping-profiles/{profile_id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, profile_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        profile = get_object_or_404(ControlMappingProfile, pk=profile_id, organization=org)
        return Response(ControlMappingProfileSerializer(profile).data)

    def patch(self, request, profile_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        profile = get_object_or_404(ControlMappingProfile, pk=profile_id, organization=org)
        serializer = ControlMappingProfileSerializer(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(ControlMappingProfileSerializer(profile).data)

    def delete(self, request, profile_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        profile = get_object_or_404(ControlMappingProfile, pk=profile_id, organization=org)
        profile.is_active = False
        profile.updated_by = request.user
        profile.save()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class ChangeControlCoverageRecomputeView(APIView):
    """POST /api/v1/changes/{change_id}/control-coverage/recompute/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, change_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=OPERATOR_ROLES
        )
        change = get_object_or_404(ChangeRecord, pk=change_id, organization=org)
        serializer = CoverageRecomputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = get_object_or_404(
            ControlMappingProfile,
            pk=serializer.validated_data["mapping_profile_id"],
            organization=org,
        )
        bundle = None
        if serializer.validated_data.get("evidence_bundle_id"):
            bundle = get_object_or_404(
                EvidenceBundle,
                pk=serializer.validated_data["evidence_bundle_id"],
                organization=org,
            )
        try:
            rows = services.recompute_change_control_coverage(
                change_record=change,
                mapping_profile=profile,
                evidence_bundle=bundle,
                computed_by=request.user,
                actor=actor_from_request(request),
            )
        except DomainValidationError as exc:
            return _error_response(exc)
        return Response(
            {"results": ChangeControlCoverageSerializer(rows, many=True).data}
        )


class AuditorAccessGrantListCreateView(APIView):
    """GET/POST /api/v1/audit/access-grants/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=ADMIN_ROLES
        )
        qs = AuditorAccessGrant.objects.filter(organization=org).order_by(
            "-created_at", "id"
        )
        return Response({"results": AuditorAccessGrantSerializer(qs, many=True).data})

    def post(self, request):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=ADMIN_ROLES
        )
        serializer = AuditorAccessGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        try:
            grant = services.create_auditor_access_grant(
                organization=org,
                user=target_user,
                actor=actor_from_request(request),
                created_by=request.user,
                scope=serializer.validated_data["scope"],
                reason=serializer.validated_data.get("reason", ""),
                starts_at=serializer.validated_data.get("starts_at"),
                expires_at=serializer.validated_data.get("expires_at"),
            )
        except DomainValidationError as exc:
            return _error_response(exc)
        return Response(
            AuditorAccessGrantSerializer(grant).data,
            status=http_status.HTTP_201_CREATED,
        )


class AuditorAccessGrantRevokeView(APIView):
    """POST /api/v1/audit/access-grants/{grant_id}/revoke/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, grant_id):
        org = _get_org(request)
        assert_organization_role(
            user=request.user, organization_id=org.id, roles=ADMIN_ROLES
        )
        grant = get_object_or_404(AuditorAccessGrant, pk=grant_id, organization=org)
        grant = services.revoke_auditor_access_grant(
            grant=grant,
            actor=actor_from_request(request),
            revoked_by=request.user,
        )
        return Response(AuditorAccessGrantSerializer(grant).data)
