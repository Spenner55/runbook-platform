"""
Internal runner API views.

These views are intentionally separate from the public ExecutionViewSet.
They accept runner-owned requests only and must not be registered on the
public router.
"""

import logging

from django.db import transaction
from rest_framework import status as http_status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.approvals import services as approval_services
from apps.approvals.models import ApprovalRequest
from apps.common.authentication import RunnerBearerTokenAuthentication
from apps.common.exceptions import DomainValidationError, InvalidStateTransitionError
from apps.common.permissions import IsRunnerAuthenticated
from apps.executions import services
from apps.executions.internal_serializers import (
    ApprovalStatusRequestSerializer,
    ClaimedExecutionSerializer,
    ClaimNextRequestSerializer,
    ExecutionCompleteSerializer,
    HeartbeatSerializer,
    InternalApprovalRequestSerializer,
    StepStartSerializer,
    StepUpdateSerializer,
)
from apps.executions.models import Execution, ExecutionStep
from apps.executions.serializers import ExecutionStepSerializer
from apps.policies import services as policy_services

logger = logging.getLogger(__name__)


def _assert_change_bound_execution_ready(
    execution, runner_id: str, claim_token: str
) -> Response | None:
    """Return a 403 Response if execution is change-bound but not yet bound/running,
    or if the requesting runner does not match the confirmed binding, or if the
    claim token is stale.

    Returns None when the execution may proceed (not change-bound, or properly bound).
    """
    try:
        from apps.changes import services as change_services  # avoid circular

        change_services.assert_execution_change_binding_ready(
            execution,
            runner_id=runner_id,
            claim_token=claim_token,
        )
    except InvalidStateTransitionError as exc:
        return Response(
            {
                "errors": [
                    {
                        "code": exc.code,
                        "detail": exc.detail,
                    }
                ]
            },
            status=http_status.HTTP_403_FORBIDDEN,
        )
    return None


def _get_change_for_execution(execution):
    try:
        return execution.change_binding.change_record
    except Exception:
        return None


def _change_has_active_breakglass(change) -> bool:
    if change is None:
        return False
    return change.breakglass_sessions.filter(status="active").exists()


def _breakglass_execution_gate_decision(
    *, execution, gate_type: str, action: str
) -> tuple[bool, Response | None]:
    change = _get_change_for_execution(execution)
    if change is None:
        return False, None
    try:
        from apps.changes import services as change_services

        target_ids = [str(tid) for tid in change.targets.values_list("id", flat=True)]
        change_services.assert_breakglass_allows(
            change=change,
            gate_type=gate_type,
            action=action,
            target_ids=target_ids,
        )
    except DomainValidationError as exc:
        if exc.code == "no_active_breakglass_session":
            return False, None
        return False, Response(
            {"errors": [{"code": exc.code, "detail": exc.detail}]},
            status=http_status.HTTP_403_FORBIDDEN,
        )
    return True, None


class RunnerInternalAPIView(APIView):
    authentication_classes = [RunnerBearerTokenAuthentication]
    permission_classes = [IsRunnerAuthenticated]


class ClaimNextExecutionView(RunnerInternalAPIView):
    """POST /api/v1/internal/executions/claim-next/"""

    def post(self, request):
        serializer = ClaimNextRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        runner_id = serializer.validated_data["runner_id"]

        try:
            from apps.changes import services as change_services

            change_services.promote_due_scheduled_changes()
        except Exception:
            logger.exception("promote_due_scheduled_changes failed during claim-next")

        result = services.claim_next_execution(runner_id=runner_id)
        if result is None:
            return Response({"execution": None, "poll_after_seconds": 5})

        execution = result["execution"]
        return Response(
            {
                "execution": ClaimedExecutionSerializer(execution).data,
                "claim_token": result["claim_token"],
                "poll_after_seconds": 5,
            }
        )


class ExecutionHeartbeatView(RunnerInternalAPIView):
    """POST /api/v1/internal/executions/<execution_id>/heartbeat/"""

    def post(self, request, execution_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = HeartbeatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        services.heartbeat_execution(
            execution=execution,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
        )
        execution.refresh_from_db(
            fields=[
                "last_heartbeat_at",
                "status",
                "cancel_requested_at",
                "cancel_reason",
            ]
        )
        return Response(
            {
                "execution_id": str(execution.id),
                "status": execution.status,
                "last_heartbeat_at": execution.last_heartbeat_at,
                "cancel_requested": execution.cancel_requested_at is not None,
                "cancel_reason": execution.cancel_reason or "",
            }
        )


class ExecutionStepUpdateView(RunnerInternalAPIView):
    """POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/update/"""

    def post(self, request, execution_id, step_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = StepUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        guard = _assert_change_bound_execution_ready(
            execution, d["runner_id"], str(d["claim_token"])
        )
        if guard is not None:
            return guard

        step = services.update_execution_step(
            execution=execution,
            step_id=str(step_id),
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            new_status=d["status"],
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
            exit_code=d.get("exit_code"),
            error_message=d.get("error_message", ""),
            failure_kind=d.get("failure_kind", ""),
            timed_out=d.get("timed_out", False),
            cancelled=d.get("cancelled", False),
            sandbox_provider=d.get("sandbox_provider", ""),
            sandbox_run_id=d.get("sandbox_run_id", ""),
            command_sha256=d.get("command_sha256", ""),
            result_metadata=d.get("result_metadata") or {},
        )
        execution.refresh_from_db(fields=["status"])
        return Response(
            {
                "execution_id": str(execution.id),
                "step": ExecutionStepSerializer(step).data,
                "execution_status": execution.status,
            }
        )


class ExecutionCompleteView(RunnerInternalAPIView):
    """POST /api/v1/internal/executions/<execution_id>/complete/"""

    def post(self, request, execution_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = ExecutionCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        guard = _assert_change_bound_execution_ready(
            execution, d["runner_id"], str(d["claim_token"])
        )
        if guard is not None:
            return guard

        execution = services.complete_execution(
            execution=execution,
            runner_id=d["runner_id"],
            claim_token=str(d["claim_token"]),
            outcome=d["final_status"],
        )
        return Response(
            {
                "id": str(execution.id),
                "status": execution.status,
                "finished_at": execution.finished_at,
            }
        )


class ExecutionStepStartView(RunnerInternalAPIView):
    """
    POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/start/

    The runner calls this for every step before executing any command.
    Django evaluates policies and returns a runner_action:
      - "run"               → step transitioned to running; runner may execute
      - "wait_for_approval" → step transitioned to waiting_for_approval; runner polls
      - "blocked"           → policy blocked the step; step transitioned to failed; runner must not execute
    """

    def post(self, request, execution_id, step_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = StepStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        runner_id = d["runner_id"]
        claim_token = str(d["claim_token"])
        guard = _assert_change_bound_execution_ready(execution, runner_id, claim_token)
        if guard is not None:
            return guard

        step = get_object_or_404(ExecutionStep, pk=step_id, execution=execution)

        # Idempotent: if step already waiting for approval, return existing state.
        if step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL:
            try:
                ar = step.approval_request
                ar = approval_services.get_approval_status(approval_request=ar)
                return Response(
                    _build_start_approval_response(execution, step, ar),
                    status=http_status.HTTP_200_OK,
                )
            except ApprovalRequest.DoesNotExist:
                pass

        with transaction.atomic():
            try:
                evaluation = policy_services.evaluate_step_policy(
                    execution=execution,
                    step=step,
                )
            except Exception as exc:
                logger.error(
                    "Policy evaluation raised unexpectedly for step %s on execution %s: %s",
                    step_id,
                    execution_id,
                    str(exc),
                )
                evaluation = None
                try:
                    evaluation = policy_services.persist_policy_evaluation_error(
                        execution=execution,
                        step=step,
                        error_code="policy_evaluation_error",
                        error_message=str(exc),
                    )
                except Exception:
                    logger.exception(
                        "Could not persist fail-closed policy evaluation for step %s on execution %s",
                        step_id,
                        execution_id,
                    )
                step = services.update_execution_step(
                    execution=execution,
                    step_id=str(step_id),
                    runner_id=runner_id,
                    claim_token=claim_token,
                    new_status=ExecutionStep.Status.FAILED,
                    error_message="policy_evaluation_error",
                )
                execution.refresh_from_db()
                return Response(
                    _build_blocked_response(execution, step, evaluation),
                    status=http_status.HTTP_200_OK,
                )

            # Evaluation failed closed — error_code is set
            if evaluation.error_code:
                step = services.update_execution_step(
                    execution=execution,
                    step_id=str(step_id),
                    runner_id=runner_id,
                    claim_token=claim_token,
                    new_status=ExecutionStep.Status.FAILED,
                    error_message="policy_evaluation_error",
                )
                execution.refresh_from_db()
                return Response(
                    _build_blocked_response(execution, step, evaluation),
                    status=http_status.HTTP_200_OK,
                )

            effective_outcome = evaluation.effective_outcome

            if effective_outcome == "approval_required":
                change = _get_change_for_execution(execution)
                if _change_has_active_breakglass(change):
                    breakglass_allowed, breakglass_guard = (
                        _breakglass_execution_gate_decision(
                            execution=execution,
                            gate_type="policy_override",
                            action="continue_running",
                        )
                    )
                    if breakglass_guard is not None:
                        return breakglass_guard
                    if breakglass_allowed:
                        step = services.update_execution_step(
                            execution=execution,
                            step_id=str(step_id),
                            runner_id=runner_id,
                            claim_token=claim_token,
                            new_status=ExecutionStep.Status.RUNNING,
                            _allow_running=True,
                        )
                        execution.refresh_from_db()
                        return Response(
                            {
                                "execution_id": str(execution.id),
                                "execution_status": execution.status,
                                "step": {"id": str(step.id), "status": step.status},
                                "runner_action": "run",
                                "poll_after_seconds": 0,
                            }
                        )
                ar, created = approval_services.request_step_approval(
                    execution=execution,
                    step=step,
                    runner_id=runner_id,
                    claim_token=claim_token,
                    policy_driven=True,
                    policy_evaluation=evaluation,
                )
                step.refresh_from_db()
                execution.refresh_from_db()
                response_status = (
                    http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
                )
                return Response(
                    _build_start_approval_response(execution, step, ar),
                    status=response_status,
                )

            if effective_outcome == "block":
                change = _get_change_for_execution(execution)
                if _change_has_active_breakglass(change):
                    breakglass_allowed, breakglass_guard = (
                        _breakglass_execution_gate_decision(
                            execution=execution,
                            gate_type="policy_override",
                            action="continue_running",
                        )
                    )
                    if breakglass_guard is not None:
                        return breakglass_guard
                    if breakglass_allowed:
                        step = services.update_execution_step(
                            execution=execution,
                            step_id=str(step_id),
                            runner_id=runner_id,
                            claim_token=claim_token,
                            new_status=ExecutionStep.Status.RUNNING,
                            _allow_running=True,
                        )
                        execution.refresh_from_db()
                        return Response(
                            {
                                "execution_id": str(execution.id),
                                "execution_status": execution.status,
                                "step": {"id": str(step.id), "status": step.status},
                                "runner_action": "run",
                                "poll_after_seconds": 0,
                            }
                        )
                step = services.update_execution_step(
                    execution=execution,
                    step_id=str(step_id),
                    runner_id=runner_id,
                    claim_token=claim_token,
                    new_status=ExecutionStep.Status.FAILED,
                    error_message="policy_blocked",
                    failure_kind="policy_blocked",
                )
                execution.refresh_from_db()
                return Response(
                    _build_blocked_response(execution, step, evaluation),
                    status=http_status.HTTP_200_OK,
                )

            # auto_approve: transition step to running — only valid after policy evaluation
            step = services.update_execution_step(
                execution=execution,
                step_id=str(step_id),
                runner_id=runner_id,
                claim_token=claim_token,
                new_status=ExecutionStep.Status.RUNNING,
                _allow_running=True,
            )
            execution.refresh_from_db()
            return Response(
                {
                    "execution_id": str(execution.id),
                    "execution_status": execution.status,
                    "step": {"id": str(step.id), "status": step.status},
                    "runner_action": "run",
                    "poll_after_seconds": 0,
                }
            )


class ApprovalStatusView(RunnerInternalAPIView):
    """
    POST /api/v1/internal/executions/<execution_id>/steps/<step_id>/approval-status/

    The runner polls this while a step is in waiting_for_approval.
    Django resolves timeout and returns runner_action:
      - "wait" → keep polling
      - "run"  → approval granted; step transitioned to running; runner may execute
      - "fail" → approval denied or timed out; step transitioned to failed; runner should complete as failed
    """

    def post(self, request, execution_id, step_id):
        execution = get_object_or_404(Execution, pk=execution_id)
        serializer = ApprovalStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        runner_id = d["runner_id"]
        claim_token = str(d["claim_token"])

        guard = _assert_change_bound_execution_ready(execution, runner_id, claim_token)
        if guard is not None:
            return guard

        # Validate ownership before any step inspection.
        services._validate_runner_ownership(execution, runner_id, claim_token)

        step = get_object_or_404(ExecutionStep, pk=step_id, execution=execution)

        # Idempotent: already transitioned by a prior poll response.
        if step.status == ExecutionStep.Status.RUNNING:
            try:
                ar = step.approval_request
            except ApprovalRequest.DoesNotExist:
                ar = None
            return Response(_build_approval_status_response(execution, step, ar, "run"))
        if step.status == ExecutionStep.Status.FAILED:
            try:
                ar = step.approval_request
            except ApprovalRequest.DoesNotExist:
                ar = None
            return Response(
                _build_approval_status_response(execution, step, ar, "fail")
            )

        if step.status != ExecutionStep.Status.WAITING_FOR_APPROVAL:
            return Response(
                {
                    "errors": [
                        {
                            "code": "invalid_state_transition",
                            "detail": f"Step is not in waiting_for_approval state (current: {step.status}).",
                        }
                    ]
                },
                status=http_status.HTTP_409_CONFLICT,
            )

        try:
            ar = step.approval_request
        except ApprovalRequest.DoesNotExist:
            return Response(
                {
                    "errors": [
                        {
                            "code": "approval_request_not_found",
                            "detail": "No approval request for this step.",
                        }
                    ]
                },
                status=http_status.HTTP_404_NOT_FOUND,
            )

        with transaction.atomic():
            ar = approval_services.get_approval_status(approval_request=ar)

            if ar.status == ApprovalRequest.Status.PENDING:
                return Response(
                    _build_approval_status_response(execution, step, ar, "wait")
                )

            if ar.status == ApprovalRequest.Status.APPROVED:
                change = _get_change_for_execution(execution)
                if _change_has_active_breakglass(change):
                    _, breakglass_guard = _breakglass_execution_gate_decision(
                        execution=execution,
                        gate_type="policy_override",
                        action="continue_running",
                    )
                    if breakglass_guard is not None:
                        return breakglass_guard
                step = services.update_execution_step(
                    execution=execution,
                    step_id=str(step_id),
                    runner_id=runner_id,
                    claim_token=claim_token,
                    new_status=ExecutionStep.Status.RUNNING,
                    _allow_running=True,
                )
                execution.refresh_from_db()
                return Response(
                    _build_approval_status_response(execution, step, ar, "run")
                )

            # Rejected or timed out → fail the step.
            error_msg = (
                "Approval rejected."
                if ar.status == ApprovalRequest.Status.REJECTED
                else "Approval timed out."
            )
            step = services.update_execution_step(
                execution=execution,
                step_id=str(step_id),
                runner_id=runner_id,
                claim_token=claim_token,
                new_status=ExecutionStep.Status.FAILED,
                error_message=error_msg,
            )
            execution.refresh_from_db()
            return Response(
                _build_approval_status_response(execution, step, ar, "fail")
            )


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _build_start_approval_response(execution, step, ar):
    return {
        "execution_id": str(execution.id),
        "execution_status": execution.status,
        "step": {"id": str(step.id), "status": step.status},
        "approval_request": InternalApprovalRequestSerializer().to_representation(ar),
        "runner_action": "wait_for_approval",
        "poll_after_seconds": 5,
    }


def _build_blocked_response(execution, step, evaluation):
    policy_eval_data = None
    if evaluation is not None:
        policy_eval_data = {
            "id": str(evaluation.id),
            "outcome": evaluation.outcome,
            "effective_outcome": evaluation.effective_outcome,
            "reason": evaluation.reason,
        }
    return {
        "execution_id": str(execution.id),
        "execution_status": execution.status,
        "step": {"id": str(step.id), "status": step.status},
        "runner_action": "blocked",
        "policy_evaluation": policy_eval_data,
        "poll_after_seconds": 0,
    }


def _build_approval_status_response(execution, step, ar, runner_action):
    poll = 5 if runner_action == "wait" else 0
    return {
        "execution_id": str(execution.id),
        "execution_status": execution.status,
        "step_id": str(step.id),
        "step_status": step.status,
        "approval_request": InternalApprovalRequestSerializer().to_representation(ar)
        if ar
        else None,
        "runner_action": runner_action,
        "poll_after_seconds": poll,
    }
