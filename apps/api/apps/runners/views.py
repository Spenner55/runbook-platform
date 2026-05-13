import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.common.permissions import (
    ADMIN_ROLES,
    MEMBER_ROLES,
    assert_organization_admin,
    assert_organization_member,
)
from apps.runners.models import (
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
    TargetConnectivityRoute,
)
from apps.runners.serializers import (
    RunnerPoolSerializer,
    RunnerRegistrationTokenCreateSerializer,
    RunnerSerializer,
    TargetConnectivityRouteSerializer,
)
from apps.runners.services import generate_runner_token

logger = logging.getLogger(__name__)


def _get_org_id(request, kwargs):
    return (
        kwargs.get("organization_pk")
        or request.query_params.get("organization_id")
        or request.headers.get("X-Organization-Id")
    )


class RunnerPoolViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = RunnerPoolSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        org_id = _get_org_id(self.request, self.kwargs)
        if not org_id:
            return RunnerPool.objects.none()
        return RunnerPool.objects.filter(organization_id=org_id).select_related("organization")

    def get_permissions(self):
        return []

    def list(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_member(user=request.user, organization_id=org_id)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_member(user=request.user, organization_id=org_id)
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_admin(user=request.user, organization_id=org_id)
        from apps.organizations.models import Organization

        organization = get_object_or_404(Organization, pk=org_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pool = RunnerPool.objects.create(organization=organization, **serializer.validated_data)
        AuditService.emit(
            organization_id=org_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner_pool.created",
            object_type=AuditEvent.ObjectType.RUNNER_POOL,
            object_id=pool.id,
            metadata={"key": pool.key},
        )
        return Response(RunnerPoolSerializer(pool).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_admin(user=request.user, organization_id=org_id)
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def drain(self, request, pk=None):
        pool = self.get_object()
        org_id = _get_org_id(request, self.kwargs) or str(pool.organization_id)
        assert_organization_admin(user=request.user, organization_id=org_id)
        pool.status = RunnerPool.Status.DRAINING
        pool.save(update_fields=["status", "updated_at"])
        AuditService.emit(
            organization_id=pool.organization_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner_pool.drained",
            object_type=AuditEvent.ObjectType.RUNNER_POOL,
            object_id=pool.id,
            metadata={"key": pool.key},
        )
        return Response(RunnerPoolSerializer(pool).data)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        pool = self.get_object()
        org_id = _get_org_id(request, self.kwargs) or str(pool.organization_id)
        assert_organization_admin(user=request.user, organization_id=org_id)
        pool.status = RunnerPool.Status.DISABLED
        pool.save(update_fields=["status", "updated_at"])
        AuditService.emit(
            organization_id=pool.organization_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner_pool.disabled",
            object_type=AuditEvent.ObjectType.RUNNER_POOL,
            object_id=pool.id,
            metadata={"key": pool.key},
        )
        return Response(RunnerPoolSerializer(pool).data)

    @action(detail=True, methods=["post"], url_path="registration-tokens")
    def registration_tokens(self, request, pk=None):
        pool = self.get_object()
        org_id = _get_org_id(request, self.kwargs) or str(pool.organization_id)
        assert_organization_admin(user=request.user, organization_id=org_id)

        serializer = RunnerRegistrationTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        clear_token, token_hash = generate_runner_token()
        reg_token = RunnerRegistrationToken.objects.create(
            organization=pool.organization,
            pool=pool,
            token_hash=token_hash,
            label_policy=d.get("label_policy", []),
            capability_policy=d.get("capability_policy", []),
            expires_at=d["expires_at"],
            max_registrations=d.get("max_registrations", 1),
            created_by=request.user,
        )
        AuditService.emit(
            organization_id=pool.organization_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner_registration_token.created",
            object_type=AuditEvent.ObjectType.RUNNER_REGISTRATION_TOKEN,
            object_id=reg_token.id,
            metadata={"pool_key": pool.key, "expires_at": d["expires_at"].isoformat()},
        )
        return Response(
            {
                "id": str(reg_token.id),
                "pool_id": str(pool.id),
                "pool_key": pool.key,
                "token": clear_token,
                "expires_at": reg_token.expires_at,
                "max_registrations": reg_token.max_registrations,
                "created_at": reg_token.created_at,
            },
            status=201,
        )


class RunnerViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = RunnerSerializer

    def get_queryset(self):
        org_id = _get_org_id(self.request, self.kwargs)
        if not org_id:
            return Runner.objects.none()
        return Runner.objects.filter(organization_id=org_id).select_related(
            "organization", "pool"
        )

    def get_permissions(self):
        return []

    def list(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_member(user=request.user, organization_id=org_id)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_member(user=request.user, organization_id=org_id)
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def drain(self, request, pk=None):
        runner = self.get_object()
        org_id = _get_org_id(request, self.kwargs) or str(runner.organization_id)
        assert_organization_admin(user=request.user, organization_id=org_id)
        runner.status = Runner.Status.DRAINING
        runner.drain_requested_at = timezone.now()
        runner.save(update_fields=["status", "drain_requested_at", "updated_at"])
        AuditService.emit(
            organization_id=runner.organization_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner.drained",
            object_type=AuditEvent.ObjectType.RUNNER,
            object_id=runner.id,
            metadata={"display_name": runner.display_name},
        )
        return Response(RunnerSerializer(runner).data)

    @action(detail=True, methods=["post"])
    def disable(self, request, pk=None):
        runner = self.get_object()
        org_id = _get_org_id(request, self.kwargs) or str(runner.organization_id)
        assert_organization_admin(user=request.user, organization_id=org_id)
        runner.status = Runner.Status.DISABLED
        runner.disabled_at = timezone.now()
        runner.save(update_fields=["status", "disabled_at", "updated_at"])
        AuditService.emit(
            organization_id=runner.organization_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner.disabled",
            object_type=AuditEvent.ObjectType.RUNNER,
            object_id=runner.id,
            metadata={"display_name": runner.display_name},
        )
        return Response(RunnerSerializer(runner).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        runner = self.get_object()
        org_id = _get_org_id(request, self.kwargs) or str(runner.organization_id)
        assert_organization_admin(user=request.user, organization_id=org_id)
        runner.status = Runner.Status.REVOKED
        runner.revoked_at = timezone.now()
        runner.save(update_fields=["status", "revoked_at", "updated_at"])
        AuditService.emit(
            organization_id=runner.organization_id,
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="runner.revoked",
            object_type=AuditEvent.ObjectType.RUNNER,
            object_id=runner.id,
            metadata={"display_name": runner.display_name},
        )
        return Response(RunnerSerializer(runner).data)


class TargetConnectivityRouteViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TargetConnectivityRouteSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        org_id = _get_org_id(self.request, self.kwargs)
        if not org_id:
            return TargetConnectivityRoute.objects.none()
        return TargetConnectivityRoute.objects.filter(
            organization_id=org_id
        ).select_related("organization", "pool")

    def get_permissions(self):
        return []

    def list(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_member(user=request.user, organization_id=org_id)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_member(user=request.user, organization_id=org_id)
        return super().retrieve(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_admin(user=request.user, organization_id=org_id)
        from apps.organizations.models import Organization

        organization = get_object_or_404(Organization, pk=org_id)
        pool_id = request.data.get("pool")
        pool = get_object_or_404(RunnerPool, pk=pool_id, organization=organization)
        data = {k: v for k, v in request.data.items() if k != "pool"}
        serializer = TargetConnectivityRouteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = {k: v for k, v in serializer.validated_data.items() if k not in ("organization", "pool")}
        route = TargetConnectivityRoute.objects.create(
            organization=organization,
            pool=pool,
            **validated,
        )
        AuditService.emit(
            organization_id=str(org_id),
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(request.user.id),
            actor_label=str(request.user),
            event_type="target_connectivity_route.created",
            object_type=AuditEvent.ObjectType.TARGET_CONNECTIVITY_ROUTE,
            object_id=route.id,
            metadata={"target_type": route.target_type, "pool_key": pool.key},
        )
        return Response(TargetConnectivityRouteSerializer(route).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        org_id = _get_org_id(request, kwargs)
        assert_organization_admin(user=request.user, organization_id=org_id)
        return super().partial_update(request, *args, **kwargs)


class ChangeRunnerEligibilityView(APIView):
    """POST /api/v1/changes/{change_id}/runner-eligibility/"""

    def post(self, request, change_id):
        from apps.changes.models import ChangeRecord
        from apps.runners.models import Runner
        from apps.runners.route_matching import find_pool_for_change

        org_id = request.headers.get("X-Organization-Id")
        assert_organization_member(user=request.user, organization_id=org_id)

        change = get_object_or_404(
            ChangeRecord.objects.prefetch_related("targets"),
            pk=change_id,
            organization_id=org_id,
        )

        pool, reason = find_pool_for_change(change)

        online_runners_count = 0
        pool_status = None
        if pool:
            from django.conf import settings as _settings
            from django.utils import timezone as _tz

            online_threshold = _tz.now() - _tz.timedelta(
                seconds=getattr(_settings, "RUNNER_ONLINE_SECONDS", 30)
            )
            online_runners_count = Runner.objects.filter(
                pool=pool,
                status=Runner.Status.ACTIVE,
                last_heartbeat_at__gte=online_threshold,
            ).count()
            pool_status = pool.status

        return Response(
            {
                "eligible": pool is not None,
                "pool_key": pool.key if pool else None,
                "pool_id": str(pool.id) if pool else None,
                "pool_status": pool_status,
                "reason": reason,
                "online_runners_count": online_runners_count,
            }
        )
