import logging

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authentication import RunnerBearerTokenAuthentication
from apps.common.exceptions import DomainValidationError
from apps.common.permissions import IsRunnerAuthenticated
from apps.runners.internal_serializers import (
    RunnerHeartbeatRequestSerializer,
    RunnerRegisterRequestSerializer,
)
from apps.runners.services import register_runner, update_runner_heartbeat

logger = logging.getLogger(__name__)


class RunnerInternalAPIView(APIView):
    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]


class RunnerRegisterView(RunnerInternalAPIView):
    """POST /api/v1/internal/runners/register/"""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RunnerRegisterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            runner, clear_token = register_runner(
                registration_token=d["registration_token"],
                display_name=d["display_name"],
                runner_version=d["runner_version"],
                fingerprint_sha256=d["fingerprint_sha256"],
                hostname=d["hostname"],
                labels=d["labels"],
                capabilities=d["capabilities"],
                organization_id=str(d["organization_id"] or ""),
                pool_key=d["pool_key"],
            )
        except DomainValidationError as exc:
            return Response(
                {"detail": exc.detail, "code": exc.code},
                status=400,
            )

        metadata = runner.metadata or {}
        accepted_labels = metadata.get("accepted_labels", {})
        accepted_capabilities = metadata.get("accepted_capabilities", [])

        return Response(
            {
                "runner_id": str(runner.id),
                "runner_bearer_token": clear_token,
                "pool_key": runner.pool.key,
                "accepted_labels": accepted_labels,
                "accepted_capabilities": accepted_capabilities,
                "heartbeat_interval_seconds": 30,
                "poll_interval_seconds": 5,
            },
            status=201,
        )


class RunnerHeartbeatView(RunnerInternalAPIView):
    """POST /api/v1/internal/runners/heartbeat/"""

    def post(self, request):
        serializer = RunnerHeartbeatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # request.user is the RunnerPrincipal when using RunnerBearerTokenAuthentication
        auth_principal = request.user

        runner_id = getattr(auth_principal, "runner_id", None)
        if runner_id is None:
            return Response(
                {"detail": "Runner ID not resolved; use per-runner bearer token for heartbeat."},
                status=400,
            )
        supplied_runner_id = d.get("runner_id")
        header_runner_id = request.headers.get("X-Runner-ID", "")
        if supplied_runner_id and str(supplied_runner_id) != str(runner_id):
            return Response(
                {"detail": "runner_id does not match authenticated runner."},
                status=403,
            )
        if header_runner_id and header_runner_id != str(runner_id):
            return Response(
                {"detail": "X-Runner-ID does not match authenticated runner."},
                status=403,
            )

        from apps.runners.models import Runner

        try:
            runner = Runner.objects.select_related("pool").get(pk=runner_id)
        except Runner.DoesNotExist:
            return Response({"detail": "Runner not found."}, status=404)

        if runner.status in (Runner.Status.REVOKED, Runner.Status.DISABLED):
            return Response(
                {"detail": f"Runner is {runner.status}."},
                status=403,
            )

        runner = update_runner_heartbeat(
            runner=runner,
            runner_version=d.get("runner_version", ""),
            hostname=d.get("hostname", ""),
            current_execution_count=d.get("current_execution_count", 0),
            observed_pool_key=d.get("observed_pool_key", ""),
            capabilities_checksum=d.get("capabilities_checksum", ""),
        )

        runner_action = "continue"
        if runner.status == Runner.Status.DRAINING or runner.pool.status == "draining":
            runner_action = "drain"

        return Response(
            {
                "runner_id": str(runner.id),
                "status": runner.status,
                "last_heartbeat_at": runner.last_heartbeat_at,
                "runner_action": runner_action,
                "poll_interval_seconds": 5,
            }
        )
