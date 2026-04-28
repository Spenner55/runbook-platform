from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.approvals import services
from apps.approvals.models import ApprovalRequest
from apps.approvals.serializers import (
    ApprovalRequestSerializer,
    DecideApprovalSerializer,
)
from apps.organizations.models import Organization


class ApprovalRequestListView(APIView):
    """GET /api/v1/approvals/"""

    def get(self, request):
        org_id = request.query_params.get("organization_id")
        if not org_id:
            return Response(
                {
                    "errors": [
                        {
                            "code": "invalid_query_params",
                            "detail": "organization_id is required.",
                            "attr": "organization_id",
                        }
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        org = get_object_or_404(Organization, pk=org_id)
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

    def get(self, request, approval_request_id):
        ar = get_object_or_404(ApprovalRequest, pk=approval_request_id)
        ar = services.get_approval_status(approval_request=ar)
        return Response(ApprovalRequestSerializer(ar).data)


class DecideApprovalView(APIView):
    """POST /api/v1/approvals/<approval_request_id>/decide/"""

    def post(self, request, approval_request_id):
        ar = get_object_or_404(ApprovalRequest, pk=approval_request_id)
        serializer = DecideApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        services.decide_approval(
            approval_request=ar,
            decision=d["decision"],
            notes=d.get("notes", ""),
            actor_label=d["actor_display_name"],
        )

        ar.refresh_from_db()
        return Response(ApprovalRequestSerializer(ar).data)
