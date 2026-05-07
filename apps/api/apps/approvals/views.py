from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.approvals import services
from apps.approvals.models import ApprovalRequest
from apps.approvals.serializers import (
    ApprovalRequestSerializer,
    DecideApprovalSerializer,
)
from apps.audit.services import actor_from_request
from apps.common.org_context import require_organization_id
from apps.common.permissions import (
    assert_organization_member,
    assert_organization_operator,
)
from apps.common.querysets import user_active_organization_scoped
from apps.organizations.models import Organization


class ApprovalRequestListView(APIView):
    """GET /api/v1/approvals/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org_id = require_organization_id(request)
        org = get_object_or_404(Organization, pk=org_id)
        assert_organization_member(user=request.user, organization_id=org.id)
        status_filter = request.query_params.get("status")
        execution_id = request.query_params.get("execution_id")

        qs = services.list_approvals(
            organization=org, status=status_filter, execution_id=execution_id
        )
        resolved = [services.get_approval_status(approval_request=ar) for ar in qs]
        return Response(
            {"results": ApprovalRequestSerializer(resolved, many=True).data}
        )


class ApprovalRequestDetailView(APIView):
    """GET /api/v1/approvals/<approval_request_id>/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, approval_request_id):
        ar = get_object_or_404(
            user_active_organization_scoped(
                ApprovalRequest.objects.select_related("organization").all(),
                user=request.user,
                organization_id=require_organization_id(request),
            ),
            pk=approval_request_id,
        )
        ar = services.get_approval_status(approval_request=ar)
        return Response(ApprovalRequestSerializer(ar).data)


class DecideApprovalView(APIView):
    """POST /api/v1/approvals/<approval_request_id>/decide/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, approval_request_id):
        ar = get_object_or_404(
            user_active_organization_scoped(
                ApprovalRequest.objects.select_related("organization").all(),
                user=request.user,
                organization_id=require_organization_id(request),
            ),
            pk=approval_request_id,
        )
        assert_organization_operator(
            user=request.user, organization_id=ar.organization_id
        )
        serializer = DecideApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        services.decide_approval(
            approval_request=ar,
            decision=d["decision"],
            notes=d.get("notes", ""),
            actor=actor_from_request(request),
            actor_user=request.user,
        )

        ar.refresh_from_db()
        return Response(ApprovalRequestSerializer(ar).data)
