from urllib.parse import urlencode

from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditEvent
from apps.audit.serializers import AuditEventListQuerySerializer, AuditEventSerializer
from apps.common.org_context import require_organization_id
from apps.common.permissions import assert_organization_member


class AuditEventListView(APIView):
    """GET /api/v1/audit/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        query_data = request.query_params.copy()
        query_data["organization_id"] = require_organization_id(request)
        serializer = AuditEventListQuerySerializer(data=query_data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        assert_organization_member(
            user=request.user, organization_id=params["organization_id"]
        )
        qs = build_audit_queryset(params)
        count = qs.count()
        results = list(qs[offset : offset + limit])

        return Response(
            {
                "count": count,
                "next": _page_url(request, count, limit, offset + limit),
                "previous": _page_url(request, count, limit, offset - limit)
                if offset > 0
                else None,
                "results": AuditEventSerializer(results, many=True).data,
            }
        )


class ExecutionAuditEventListView(APIView):
    """GET /api/v1/executions/<execution_id>/audit/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, execution_id):
        query_data = request.query_params.copy()
        query_data["organization_id"] = require_organization_id(request)
        query_data["object_type"] = AuditEvent.ObjectType.EXECUTION
        query_data["object_id"] = str(execution_id)
        serializer = AuditEventListQuerySerializer(data=query_data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        limit = params.get("limit", 50)
        offset = params.get("offset", 0)
        organization_id = params["organization_id"]
        assert_organization_member(
            user=request.user, organization_id=organization_id
        )
        qs = execution_audit_queryset(
            organization_id=organization_id,
            execution_id=execution_id,
            event_type=params.get("event_type"),
            actor_type=params.get("actor_type"),
            occurred_after=params.get("occurred_after"),
            occurred_before=params.get("occurred_before"),
        )
        count = qs.count()
        results = list(qs[offset : offset + limit])

        return Response(
            {
                "count": count,
                "next": _page_url(request, count, limit, offset + limit),
                "previous": _page_url(request, count, limit, offset - limit)
                if offset > 0
                else None,
                "results": AuditEventSerializer(results, many=True).data,
            },
            status=status.HTTP_200_OK,
        )


def build_audit_queryset(params):
    qs = AuditEvent.objects.filter(organization_id=params["organization_id"])

    if params.get("object_type"):
        qs = qs.filter(object_type=params["object_type"], object_id=params["object_id"])
    if params.get("event_type"):
        qs = qs.filter(event_type=params["event_type"])
    if params.get("actor_type"):
        qs = qs.filter(actor_type=params["actor_type"])
    if params.get("occurred_after"):
        qs = qs.filter(occurred_at__gte=params["occurred_after"])
    if params.get("occurred_before"):
        qs = qs.filter(occurred_at__lte=params["occurred_before"])

    return qs.order_by("-occurred_at", "-id")


def execution_audit_queryset(
    *,
    organization_id,
    execution_id,
    event_type=None,
    actor_type=None,
    occurred_after=None,
    occurred_before=None,
):
    related_event_filter = Q(
        object_type=AuditEvent.ObjectType.EXECUTION, object_id=execution_id
    ) | Q(metadata__execution_id=str(execution_id))
    qs = AuditEvent.objects.filter(
        organization_id=organization_id,
    ).filter(related_event_filter)

    if event_type:
        qs = qs.filter(event_type=event_type)
    if actor_type:
        qs = qs.filter(actor_type=actor_type)
    if occurred_after:
        qs = qs.filter(occurred_at__gte=occurred_after)
    if occurred_before:
        qs = qs.filter(occurred_at__lte=occurred_before)

    return qs.order_by("-occurred_at", "-id")


def _page_url(request, count: int, limit: int, offset: int):
    if offset < 0 or offset >= count:
        return None
    params = request.query_params.copy()
    params["limit"] = str(limit)
    params["offset"] = str(offset)
    return f"{request.path}?{urlencode(params, doseq=True)}"
