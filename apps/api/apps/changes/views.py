"""Views for the changes app."""

import logging

from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.audit.services import actor_from_request
from apps.changes import selectors, services
from apps.changes.serializers import (
    BindChangeExecutionSerializer,
    ChangeRecordDetailSerializer,
    CreateChangeRecordSerializer,
    OperationProfileSerializer,
    SubmitChangeRecordSerializer,
)
from apps.common.authentication import RunnerBearerTokenAuthentication
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)
from apps.common.org_context import require_organization_id
from apps.common.permissions import (
    OPERATOR_ROLES,
    IsRunnerAuthenticated,
    assert_organization_member,
    assert_organization_role,
)
from apps.organizations.models import Organization

logger = logging.getLogger(__name__)

_DOMAIN_ERROR_STATUS = {
    DomainValidationError: http_status.HTTP_400_BAD_REQUEST,
    DomainConflictError: http_status.HTTP_409_CONFLICT,
    InvalidStateTransitionError: http_status.HTTP_409_CONFLICT,
}


def _error_response(exc):
    http_code = _DOMAIN_ERROR_STATUS.get(type(exc), http_status.HTTP_400_BAD_REQUEST)
    return Response(
        {"errors": [{"code": exc.code, "detail": exc.detail}]},
        status=http_code,
    )


class OperationProfileListView(APIView):
    """GET /api/v1/changes/operation-profiles/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
        org = Organization.objects.get(pk=organization_id)
        profiles = selectors.get_active_profiles_for_org(organization=org)
        data = OperationProfileSerializer(profiles, many=True).data
        return Response({"results": data})


class ChangeRecordListCreateView(APIView):
    """
    GET /api/v1/changes/ - List organization-scoped changes
    POST /api/v1/changes/ - Create a draft change
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
        org = Organization.objects.get(pk=organization_id)

        changes = selectors.list_change_records_for_org(organization=org)
        return Response(
            {"results": ChangeRecordDetailSerializer(changes, many=True).data}
        )

    def post(self, request):
        organization_id = require_organization_id(request)
        assert_organization_role(
            user=request.user, organization_id=organization_id, roles=OPERATOR_ROLES
        )
        org = Organization.objects.get(pk=organization_id)

        serializer = CreateChangeRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        actor = actor_from_request(request)
        try:
            change = services.create_change_record(
                organization=org,
                operation_profile_key=d["operation_profile_key"],
                workflow_id=str(d["workflow_id"]),
                title=d["title"],
                summary=d.get("summary", ""),
                justification=d.get("justification", ""),
                requested_inputs=d.get("requested_inputs", {}),
                scheduled_for=d.get("scheduled_for"),
                targets=d.get("targets", []),
                actor=actor,
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        change = selectors.get_change_record_with_binding(
            change_id=change.id, organization=org
        )
        return Response(
            ChangeRecordDetailSerializer(change).data,
            status=http_status.HTTP_201_CREATED,
        )


class ChangeRecordDetailView(APIView):
    """GET /api/v1/changes/{id}/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
        org = Organization.objects.get(pk=organization_id)

        change = selectors.get_change_record_with_binding(
            change_id=change_id, organization=org
        )
        if change is None:
            return Response(
                {
                    "errors": [
                        {"code": "not_found", "detail": "Change record not found."}
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(ChangeRecordDetailSerializer(change).data)


class ChangeRecordSubmitView(APIView):
    """POST /api/v1/changes/{id}/submit/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, change_id):
        organization_id = require_organization_id(request)
        assert_organization_role(
            user=request.user, organization_id=organization_id, roles=OPERATOR_ROLES
        )
        org = Organization.objects.get(pk=organization_id)

        change = selectors.get_change_record(change_id=change_id, organization=org)
        if change is None:
            return Response(
                {
                    "errors": [
                        {"code": "not_found", "detail": "Change record not found."}
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )

        serializer = SubmitChangeRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        actor = actor_from_request(request)
        try:
            change = services.submit_change_record(change=change, actor=actor)
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        change = selectors.get_change_record_with_binding(
            change_id=change.id, organization=org
        )
        return Response(ChangeRecordDetailSerializer(change).data)


class BindChangeExecutionView(APIView):
    """POST /api/v1/internal/changes/{change_id}/bind-execution/"""

    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    def post(self, request, change_id):
        serializer = BindChangeExecutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.bind_execution(
                change_id=str(change_id),
                runner_id=d["runner_id"],
                claim_token=str(d["claim_token"]),
                execution_id=str(d["execution_id"]),
                dispatch_token=d["dispatch_token"],
                requested_inputs_sha256=d["requested_inputs_sha256"],
                operation_profile_key=d["operation_profile_key"],
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            code_map = {
                "dispatch_token_expired": http_status.HTTP_410_GONE,
                "change_not_dispatchable": http_status.HTTP_409_CONFLICT,
                "execution_binding_conflict": http_status.HTTP_409_CONFLICT,
                "runner_ownership_mismatch": http_status.HTTP_409_CONFLICT,
                "claim_token_mismatch": http_status.HTTP_409_CONFLICT,
                "dispatch_token_invalid": http_status.HTTP_400_BAD_REQUEST,
                "requested_inputs_hash_mismatch": http_status.HTTP_400_BAD_REQUEST,
                "operation_profile_key_mismatch": http_status.HTTP_400_BAD_REQUEST,
                "change_not_found": http_status.HTTP_404_NOT_FOUND,
                "execution_not_found": http_status.HTTP_404_NOT_FOUND,
            }
            http_code = code_map.get(exc.code, http_status.HTTP_400_BAD_REQUEST)
            return Response(
                {"errors": [{"code": exc.code, "detail": exc.detail}]},
                status=http_code,
            )

        return Response(result)
