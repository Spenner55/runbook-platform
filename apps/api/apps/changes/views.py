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
    ChangeClosureCreateSerializer,
    ChangeClosureDetailSerializer,
    ChangeRecordDetailSerializer,
    ChangeWindowInputSerializer,
    ChangeWindowOutputSerializer,
    CreateChangeRecordSerializer,
    CreateFreezeRuleSerializer,
    DispatchEligibilityCheckSerializer,
    ExecutionTimingCallbackSerializer,
    FreezeRuleSerializer,
    InternalRunnerVerificationResultSerializer,
    OperationProfileSerializer,
    SubmitChangeRecordSerializer,
    UpdateFreezeRuleSerializer,
    VerificationPlanDetailSerializer,
    VerificationResultCreateSerializer,
    VerificationResultDetailSerializer,
)
from apps.changes.models import VerificationPlan
from apps.common.authentication import RunnerBearerTokenAuthentication
from apps.common.exceptions import (
    DomainConflictError,
    DomainValidationError,
    InvalidStateTransitionError,
)
from apps.common.org_context import require_organization_id
from apps.common.permissions import (
    ADMIN_ROLES,
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


class ChangeVerificationPlanView(APIView):
    """GET /api/v1/changes/{id}/verification-plan/"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
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

        plan = (
            VerificationPlan.objects.filter(change_record=change, organization=org)
            .prefetch_related("checks", "checks__last_result")
            .first()
        )
        if plan is None:
            return Response(
                {
                    "errors": [
                        {"code": "not_found", "detail": "Verification plan not found."}
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(VerificationPlanDetailSerializer(plan).data)


class ChangeVerificationResultCreateView(APIView):
    """POST /api/v1/changes/{id}/verification-results/"""

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

        serializer = VerificationResultCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.submit_user_verification_result(
                change=change,
                check_key=d["check_key"],
                user=request.user,
                outcome=d["outcome"],
                verification_key=d.get("verification_key", ""),
                source_step_key=d.get("source_step_key", ""),
                artifact_id=str(d["artifact_id"]) if d.get("artifact_id") else None,
                artifact_checksum_sha256=d.get("artifact_checksum_sha256", ""),
                external_reference=d.get("external_reference", ""),
                api_assertion_snapshot=d.get("api_assertion_snapshot", {}),
                manual_attestation_text=d.get("manual_attestation_text", ""),
                observed_value=d.get("observed_value", {}),
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        result = result.__class__.objects.select_related("verification_check").get(
            pk=result.pk
        )
        return Response(
            VerificationResultDetailSerializer(result).data,
            status=http_status.HTTP_201_CREATED,
        )


class ChangeCloseView(APIView):
    """POST /api/v1/changes/{id}/close/"""

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

        serializer = ChangeClosureCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        independent_reviewer = None
        if d.get("independent_reviewer_id"):
            from apps.users.models import User

            independent_reviewer = User.objects.filter(
                pk=d["independent_reviewer_id"],
                memberships__organization=org,
            ).first()
            if independent_reviewer is None:
                return Response(
                    {
                        "errors": [
                            {
                                "code": "independent_reviewer_not_found",
                                "detail": "Independent reviewer was not found in this organization.",
                            }
                        ]
                    },
                    status=http_status.HTTP_400_BAD_REQUEST,
                )

        actor = actor_from_request(request)
        try:
            closure = services.close_change(
                change=change,
                outcome=d.get("outcome") or "success",
                summary=d["summary"],
                actor=actor,
                closed_by=request.user,
                independent_reviewer=independent_reviewer,
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        return Response(
            ChangeClosureDetailSerializer(closure).data,
            status=http_status.HTTP_201_CREATED,
        )


class ChangeWindowView(APIView):
    """PATCH /api/v1/changes/{change_id}/window/ — create or update the execution window."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, change_id):
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

        serializer = ChangeWindowInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        actor = actor_from_request(request)
        try:
            window = services.create_or_update_change_window(
                change=change,
                starts_at=d["starts_at"],
                ends_at=d["ends_at"],
                timezone_name=d.get("timezone", ""),
                reason=d.get("reason", ""),
                actor=actor,
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        return Response(ChangeWindowOutputSerializer(window).data)


class FreezeRuleListCreateView(APIView):
    """
    GET  /api/v1/freeze-rules/ — list all freeze rules for the org
    POST /api/v1/freeze-rules/ — create a new freeze rule (admin only)
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
        org = Organization.objects.get(pk=organization_id)

        rules = selectors.list_freeze_rules_for_org(organization=org)
        return Response({"results": FreezeRuleSerializer(rules, many=True).data})

    def post(self, request):
        organization_id = require_organization_id(request)
        assert_organization_role(
            user=request.user, organization_id=organization_id, roles=ADMIN_ROLES
        )
        org = Organization.objects.get(pk=organization_id)

        serializer = CreateFreezeRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        actor = actor_from_request(request)
        try:
            rule = services.create_freeze_rule(
                organization=org,
                name=d["name"],
                description=d.get("description", ""),
                behavior=d["behavior"],
                starts_at=d["starts_at"],
                ends_at=d["ends_at"],
                scope_type=d["scope_type"],
                target_type=d.get("target_type", ""),
                target_identifier=d.get("target_identifier", ""),
                requires_exception_reference=d.get(
                    "requires_exception_reference", False
                ),
                actor=actor,
            )
        except (DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)

        return Response(
            FreezeRuleSerializer(rule).data, status=http_status.HTTP_201_CREATED
        )


class FreezeRuleDetailView(APIView):
    """
    GET   /api/v1/freeze-rules/{id}/ — retrieve a freeze rule
    PATCH /api/v1/freeze-rules/{id}/ — update a freeze rule (admin only)
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def _get_rule(self, request, rule_id):
        organization_id = require_organization_id(request)
        org = Organization.objects.get(pk=organization_id)
        rule = selectors.get_freeze_rule(rule_id=rule_id, organization=org)
        if rule is None:
            return None, None, org
        return rule, organization_id, org

    def get(self, request, rule_id):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
        org = Organization.objects.get(pk=organization_id)
        rule = selectors.get_freeze_rule(rule_id=rule_id, organization=org)
        if rule is None:
            return Response(
                {"errors": [{"code": "not_found", "detail": "Freeze rule not found."}]},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(FreezeRuleSerializer(rule).data)

    def patch(self, request, rule_id):
        organization_id = require_organization_id(request)
        assert_organization_role(
            user=request.user, organization_id=organization_id, roles=ADMIN_ROLES
        )
        org = Organization.objects.get(pk=organization_id)
        rule = selectors.get_freeze_rule(rule_id=rule_id, organization=org)
        if rule is None:
            return Response(
                {"errors": [{"code": "not_found", "detail": "Freeze rule not found."}]},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        serializer = UpdateFreezeRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        actor = actor_from_request(request)
        try:
            rule = services.update_freeze_rule(
                rule=rule,
                actor=actor,
                **d,
            )
        except (DomainValidationError, DomainConflictError) as exc:
            return _error_response(exc)

        return Response(FreezeRuleSerializer(rule).data)


class FreezeRuleDeactivateView(APIView):
    """POST /api/v1/freeze-rules/{id}/deactivate/ — deactivate a freeze rule (admin only)"""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, rule_id):
        organization_id = require_organization_id(request)
        assert_organization_role(
            user=request.user, organization_id=organization_id, roles=ADMIN_ROLES
        )
        org = Organization.objects.get(pk=organization_id)
        rule = selectors.get_freeze_rule(rule_id=rule_id, organization=org)
        if rule is None:
            return Response(
                {"errors": [{"code": "not_found", "detail": "Freeze rule not found."}]},
                status=http_status.HTTP_404_NOT_FOUND,
            )

        actor = actor_from_request(request)
        rule = services.deactivate_freeze_rule(rule=rule, actor=actor)
        return Response(FreezeRuleSerializer(rule).data)


class DispatchChangeView(APIView):
    """POST /api/v1/changes/{change_id}/dispatch/ — dispatch a change for execution."""

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

        actor = actor_from_request(request)
        try:
            services.make_dispatchable(change=change, actor=actor)
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        change = selectors.get_change_record_with_binding(
            change_id=change_id, organization=org
        )
        return Response(
            ChangeRecordDetailSerializer(change).data,
            status=http_status.HTTP_202_ACCEPTED,
        )


class DispatchPreflightRunView(APIView):
    """POST /api/v1/changes/{change_id}/preflight/ — run dispatch preflight checks."""

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

        actor = actor_from_request(request)
        try:
            check = services.run_dispatch_preflight(change=change, actor=actor)
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        return Response(
            DispatchEligibilityCheckSerializer(check).data,
            status=http_status.HTTP_201_CREATED,
        )


class DispatchPreflightLatestView(APIView):
    """GET /api/v1/changes/{change_id}/preflight/latest/ — retrieve the most recent preflight check."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, change_id):
        organization_id = require_organization_id(request)
        assert_organization_member(user=request.user, organization_id=organization_id)
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

        check = selectors.get_latest_dispatch_preflight(
            change_id=change_id, organization=org
        )
        if check is None:
            return Response(
                {
                    "errors": [
                        {
                            "code": "not_found",
                            "detail": "No preflight check found for this change.",
                        }
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )

        return Response(DispatchEligibilityCheckSerializer(check).data)


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


class ExecutionAcceptedView(APIView):
    """POST /api/v1/internal/changes/{change_id}/execution-accepted/"""

    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    def post(self, request, change_id):
        serializer = ExecutionTimingCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.record_execution_accepted(
                change_id=str(change_id),
                runner_id=d["runner_id"],
                execution_id=str(d["execution_id"]),
                observed_at=d.get("observed_at"),
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        return Response(result)


class ExecutionStartedView(APIView):
    """POST /api/v1/internal/changes/{change_id}/execution-started/"""

    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    def post(self, request, change_id):
        serializer = ExecutionTimingCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.record_execution_started(
                change_id=str(change_id),
                runner_id=d["runner_id"],
                execution_id=str(d["execution_id"]),
                observed_at=d.get("observed_at"),
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        return Response(result)


class ExecutionFinishedView(APIView):
    """POST /api/v1/internal/changes/{change_id}/execution-finished/"""

    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    def post(self, request, change_id):
        serializer = ExecutionTimingCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.record_execution_finished(
                change_id=str(change_id),
                runner_id=d["runner_id"],
                execution_id=str(d["execution_id"]),
                observed_at=d.get("observed_at"),
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            return _error_response(exc)

        return Response(result)


class InternalRunnerVerificationResultView(APIView):
    """POST /api/v1/internal/changes/{change_id}/verification-results/"""

    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]

    def post(self, request, change_id):
        serializer = InternalRunnerVerificationResultSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = services.record_runner_verification_result(
                change_id=str(change_id),
                runner_id=d["runner_id"],
                claim_token=d["claim_token"],
                execution_id=str(d["execution_id"]),
                check_key=d["check_key"],
                outcome=d["outcome"],
                verification_key=d.get("verification_key", ""),
                step_key=d.get("step_key", ""),
                artifact_ids=d.get("artifact_ids", []),
                artifact_checksums=d.get("artifact_checksums", {}),
                observed_value=d.get("observed_value", {}),
                metadata=d.get("metadata", {}),
                submitted_at=d.get("sent_at"),
            )
        except (
            DomainValidationError,
            DomainConflictError,
            InvalidStateTransitionError,
        ) as exc:
            code_map = {
                "change_not_found": http_status.HTTP_404_NOT_FOUND,
                "binding_not_found": http_status.HTTP_404_NOT_FOUND,
                "runner_ownership_mismatch": http_status.HTTP_409_CONFLICT,
                "claim_token_mismatch": http_status.HTTP_409_CONFLICT,
                "execution_id_mismatch": http_status.HTTP_409_CONFLICT,
                "execution_not_bound": http_status.HTTP_409_CONFLICT,
            }
            http_code = code_map.get(exc.code, http_status.HTTP_400_BAD_REQUEST)
            return Response(
                {"errors": [{"code": exc.code, "detail": exc.detail}]},
                status=http_code,
            )
        except Exception as exc:
            from django.core.exceptions import ObjectDoesNotExist

            if isinstance(exc, ObjectDoesNotExist):
                return Response(
                    {
                        "errors": [
                            {
                                "code": "change_or_check_not_found",
                                "detail": "Change or verification check not found.",
                            }
                        ]
                    },
                    status=http_status.HTTP_404_NOT_FOUND,
                )
            raise

        status_code = (
            http_status.HTTP_201_CREATED
            if result["accepted"]
            else http_status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return Response(result, status=status_code)
