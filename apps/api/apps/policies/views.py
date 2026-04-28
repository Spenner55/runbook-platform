from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import DomainConflictError
from apps.organizations.models import Organization
from apps.policies import services
from apps.policies.models import Policy, PolicyRule
from apps.policies.serializers import (
    PolicyCreateSerializer,
    PolicyDetailSerializer,
    PolicyListSerializer,
    PolicyRuleCreateSerializer,
    PolicyRuleSerializer,
    PolicyRuleUpdateSerializer,
    PolicyUpdateSerializer,
)


def _query_param_error(attr, detail):
    return Response(
        {"errors": [{"code": "invalid_query_params", "detail": detail, "attr": attr}]},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _get_scoped_policy_or_response(request, policy_id):
    org_id = request.query_params.get("organization_id")
    if not org_id:
        return None, _query_param_error("organization_id", "organization_id is required.")

    org = get_object_or_404(Organization, pk=org_id)
    return get_object_or_404(Policy, pk=policy_id, organization=org), None


class PolicyListCreateView(APIView):
    """GET/POST /api/v1/policies/"""

    def get(self, request):
        org_id = request.query_params.get("organization_id")
        if not org_id:
            return _query_param_error("organization_id", "organization_id is required.")
        org = get_object_or_404(Organization, pk=org_id)

        is_active_param = request.query_params.get("is_active", "true")
        if is_active_param not in {"true", "false", "all"}:
            return _query_param_error("is_active", "is_active must be one of: true, false, all.")

        qs = Policy.objects.filter(organization=org)
        if is_active_param == "true":
            qs = qs.filter(is_active=True)
        elif is_active_param == "false":
            qs = qs.filter(is_active=False)
        # "all" returns everything.

        qs = qs.order_by("name")
        return Response({"results": PolicyListSerializer(qs, many=True).data})

    def post(self, request):
        serializer = PolicyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        org = get_object_or_404(Organization, pk=d["organization_id"])

        try:
            policy = services.create_policy(
                organization=org,
                name=d["name"],
                description=d.get("description", ""),
                is_active=d.get("is_active", True),
            )
        except DomainConflictError as exc:
            return Response(
                {"errors": [{"code": exc.code, "detail": exc.detail}]},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(PolicyDetailSerializer(policy).data, status=status.HTTP_201_CREATED)


class PolicyRetrieveUpdateView(APIView):
    """GET/PATCH /api/v1/policies/<policy_id>/"""

    def get(self, request, policy_id):
        policy, error = _get_scoped_policy_or_response(request, policy_id)
        if error:
            return error
        return Response(PolicyDetailSerializer(policy).data)

    def patch(self, request, policy_id):
        policy, error = _get_scoped_policy_or_response(request, policy_id)
        if error:
            return error
        serializer = PolicyUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = {k: v for k, v in serializer.validated_data.items()}

        try:
            policy = services.update_policy(policy=policy, **changes)
        except DomainConflictError as exc:
            return Response(
                {"errors": [{"code": exc.code, "detail": exc.detail}]},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(PolicyDetailSerializer(policy).data)


class PolicyRuleCreateView(APIView):
    """POST /api/v1/policies/<policy_id>/rules/"""

    def post(self, request, policy_id):
        policy, error = _get_scoped_policy_or_response(request, policy_id)
        if error:
            return error
        serializer = PolicyRuleCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            rule = services.create_rule(
                policy=policy,
                name=d["name"],
                description=d.get("description", ""),
                is_active=d.get("is_active", True),
                priority=d["priority"],
                condition_type=d["condition_type"],
                condition_params=d["condition_params"],
                outcome=d["outcome"],
                reason=d.get("reason", ""),
            )
        except DomainConflictError as exc:
            return Response(
                {"errors": [{"code": exc.code, "detail": exc.detail}]},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(PolicyRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class PolicyRuleUpdateDeactivateView(APIView):
    """PATCH/DELETE /api/v1/policies/<policy_id>/rules/<rule_id>/"""

    def _get_rule(self, request, policy_id, rule_id):
        policy, error = _get_scoped_policy_or_response(request, policy_id)
        if error:
            return None, error
        return get_object_or_404(PolicyRule, pk=rule_id, policy=policy), None

    def patch(self, request, policy_id, rule_id):
        rule, error = self._get_rule(request, policy_id, rule_id)
        if error:
            return error
        serializer = PolicyRuleUpdateSerializer(data=request.data, context={"rule": rule})
        serializer.is_valid(raise_exception=True)
        changes = {k: v for k, v in serializer.validated_data.items()}

        try:
            rule = services.update_rule(rule=rule, **changes)
        except DomainConflictError as exc:
            return Response(
                {"errors": [{"code": exc.code, "detail": exc.detail}]},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(PolicyRuleSerializer(rule).data)

    def delete(self, request, policy_id, rule_id):
        rule, error = self._get_rule(request, policy_id, rule_id)
        if error:
            return error
        # Soft-delete: set is_active=False to preserve evaluation history
        rule.is_active = False
        rule.save(update_fields=["is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
