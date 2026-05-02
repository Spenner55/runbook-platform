"""Tests for execution binding constraint and bind endpoint validation."""

import pytest
from django.db import IntegrityError

from apps.changes import services as change_services
from apps.changes.models import ChangeExecutionBinding, ChangeRecord


@pytest.mark.django_db
class TestChangeExecutionBindingConstraints:
    def _make_dispatchable(self, draft_change, operation_profile):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()
        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)
            change.refresh_from_db()
        return change

    def test_one_binding_per_change_record(self, draft_change, operation_profile):
        change = self._make_dispatchable(draft_change, operation_profile)
        assert change.status == ChangeRecord.Status.DISPATCHABLE
        binding = change.execution_binding
        assert binding is not None

        with pytest.raises(IntegrityError):
            from django.db import transaction
            from django.utils import timezone

            with transaction.atomic():
                ChangeExecutionBinding.objects.create(
                    organization=change.organization,
                    change_record=change,
                    execution=binding.execution,
                    operation_profile_key=change.operation_profile.key,
                    requested_inputs_sha256=change.requested_inputs_sha256,
                    dispatch_token_nonce="dup-nonce",
                    dispatch_token_hash="dup-hash",
                    dispatch_token_expires_at=timezone.now(),
                    reserved_at=timezone.now(),
                )

    def test_binding_references_correct_execution(
        self, draft_change, operation_profile
    ):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        assert binding.execution is not None
        assert binding.execution.workflow == draft_change.workflow

    def test_dispatch_token_hash_stored_not_cleartext(
        self, draft_change, operation_profile
    ):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        clear_token = change_services.generate_dispatch_token(binding)
        assert binding.dispatch_token_hash != clear_token
        assert len(binding.dispatch_token_hash) > 0

    def test_generate_dispatch_token_is_deterministic_for_same_nonce(
        self, draft_change, operation_profile
    ):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        t1 = change_services.generate_dispatch_token(binding)
        t2 = change_services.generate_dispatch_token(binding)
        assert t1 == t2

    def test_verify_dispatch_token_correct(self, draft_change, operation_profile):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        token = change_services.generate_dispatch_token(binding)
        assert change_services.verify_dispatch_token(binding, token) is True

    def test_verify_dispatch_token_wrong(self, draft_change, operation_profile):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        assert change_services.verify_dispatch_token(binding, "wrong") is False

    def test_verify_dispatch_token_empty(self, draft_change, operation_profile):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        assert change_services.verify_dispatch_token(binding, "") is False

    def test_verify_dispatch_token_detects_tampered_stored_hash(
        self, draft_change, operation_profile
    ):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        token = change_services.generate_dispatch_token(binding)
        binding.dispatch_token_hash = change_services.hash_dispatch_token(
            "attacker-token"
        )
        binding.save(update_fields=["dispatch_token_hash"])

        assert change_services.verify_dispatch_token(binding, token) is False


@pytest.mark.django_db
class TestBindChangeExecutionEndpoint:
    def _make_dispatchable(self, draft_change, operation_profile):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()
        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)
            change.refresh_from_db()
        return change

    def test_bind_missing_fields_returns_400(
        self, draft_change, operation_profile, runner_client
    ):
        change = self._make_dispatchable(draft_change, operation_profile)
        # Send an empty body — serializer should reject it with 400
        response = runner_client.post(
            f"/api/v1/internal/changes/{change.id}/bind-execution/",
            {},
            format="json",
        )
        assert response.status_code == 400

    def test_bind_nonexistent_change_returns_404(self, runner_client):
        import uuid

        response = runner_client.post(
            f"/api/v1/internal/changes/{uuid.uuid4()}/bind-execution/",
            {
                "runner_id": "test-runner",
                "claim_token": "tok",
                "execution_id": str(uuid.uuid4()),
                "dispatch_token": "tok",
                "operation_profile_key": "k",
                "requested_inputs_sha256": "a" * 64,
            },
            format="json",
        )
        assert response.status_code == 404

    def test_bind_unauthenticated_rejected(
        self, draft_change, operation_profile, api_client
    ):
        change = self._make_dispatchable(draft_change, operation_profile)
        import uuid

        response = api_client.post(
            f"/api/v1/internal/changes/{change.id}/bind-execution/",
            {
                "runner_id": "runner",
                "claim_token": "tok",
                "execution_id": str(uuid.uuid4()),
                "dispatch_token": "tok",
                "operation_profile_key": "k",
                "requested_inputs_sha256": "a" * 64,
            },
            format="json",
        )
        assert response.status_code == 401

    def test_bind_wrong_dispatch_token_returns_error(
        self, draft_change, operation_profile, runner_client
    ):
        """Verifies dispatch token is validated — wrong token should produce an error."""
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        import uuid

        response = runner_client.post(
            f"/api/v1/internal/changes/{change.id}/bind-execution/",
            {
                "runner_id": "test-runner",
                "claim_token": str(uuid.uuid4()),
                "execution_id": str(binding.execution_id),
                "dispatch_token": "clearly-wrong-token",
                "operation_profile_key": operation_profile.key,
                "requested_inputs_sha256": change.requested_inputs_sha256,
            },
            format="json",
        )
        # Should fail — either ownership mismatch or dispatch token invalid
        assert response.status_code in (400, 403, 409)


@pytest.mark.django_db
class TestChangeLifecycleInvariantFixes:
    """Tests for C1–C6 critical invariant fixes."""

    def _make_dispatchable(self, draft_change, operation_profile):
        operation_profile.requires_approval = False
        operation_profile.save()
        change = change_services.submit_change_record(change=draft_change)
        change.refresh_from_db()
        if change.status == ChangeRecord.Status.APPROVED:
            change_services.make_dispatchable(change=change)
            change.refresh_from_db()
        return change

    def _claim_execution(self, execution):
        """Simulate a runner claiming the execution."""
        from apps.executions import services as execution_services

        result = execution_services.claim_next_execution(runner_id="test-runner-1")
        assert result is not None
        return result

    # C1: Complete before bind is blocked
    def test_complete_before_bind_is_rejected(
        self, draft_change, operation_profile, runner_client
    ):
        """ExecutionCompleteView must reject completion of change-bound execution that hasn't been bound yet."""
        change = self._make_dispatchable(draft_change, operation_profile)
        assert change.status == ChangeRecord.Status.DISPATCHABLE

        binding = change.execution_binding
        execution = binding.execution

        # Claim the execution
        from apps.executions import services as execution_services

        result = execution_services.claim_next_execution(runner_id="test-runner-1")
        assert result is not None
        claim_token = result["claim_token"]

        # Attempt to complete without binding first
        response = runner_client.post(
            f"/api/v1/internal/executions/{execution.id}/complete/",
            {
                "runner_id": "test-runner-1",
                "claim_token": claim_token,
                "final_status": "failed",
            },
            format="json",
        )
        assert response.status_code == 403
        # Change must still be dispatchable (not stranded)
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.DISPATCHABLE

    # C2: Watchdog recovery calls change hook
    def test_watchdog_recovery_closes_running_change(
        self, draft_change, operation_profile
    ):
        """Watchdog recovery of a stale change-bound execution must close the change."""
        change = self._make_dispatchable(draft_change, operation_profile)
        assert change.status == ChangeRecord.Status.DISPATCHABLE

        binding = change.execution_binding
        execution = binding.execution

        # Claim and bind the execution, then make its heartbeat stale.
        from apps.executions import services as execution_services

        claim_result = execution_services.claim_next_execution(
            runner_id="test-runner-1"
        )
        assert claim_result is not None
        claim_token = claim_result["claim_token"]
        execution.refresh_from_db()

        # Bind the execution to move change to running
        dispatch_token = change_services.generate_dispatch_token(binding)
        change_services.bind_execution(
            change_id=str(change.id),
            runner_id="test-runner-1",
            claim_token=claim_token,
            execution_id=str(execution.id),
            dispatch_token=dispatch_token,
            requested_inputs_sha256=binding.requested_inputs_sha256,
            operation_profile_key=binding.operation_profile_key,
        )
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.RUNNING

        # Make the heartbeat stale
        from datetime import timedelta

        from django.utils import timezone

        execution.refresh_from_db()
        execution.last_heartbeat_at = timezone.now() - timedelta(seconds=600)
        execution.save(update_fields=["last_heartbeat_at"])

        # Run watchdog
        recovered = execution_services.recover_stuck_executions(
            stuck_threshold_seconds=300
        )
        assert str(execution.id) in recovered

        # Change must be closed (not stuck in running)
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.CLOSED

    # C2: Approval timeout calls change hook
    def test_approval_timeout_closes_running_change(
        self, draft_change, operation_profile
    ):
        """Approval timeout on a change-bound execution step must close the change."""
        from apps.approvals.models import ApprovalRequest
        from apps.executions import services as execution_services
        from apps.executions.models import ExecutionStep

        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        execution = binding.execution

        # Claim and bind
        claim_result = execution_services.claim_next_execution(
            runner_id="test-runner-1"
        )
        assert claim_result is not None
        claim_token = claim_result["claim_token"]
        execution.refresh_from_db()

        dispatch_token = change_services.generate_dispatch_token(binding)
        change_services.bind_execution(
            change_id=str(change.id),
            runner_id="test-runner-1",
            claim_token=claim_token,
            execution_id=str(execution.id),
            dispatch_token=dispatch_token,
            requested_inputs_sha256=binding.requested_inputs_sha256,
            operation_profile_key=binding.operation_profile_key,
        )
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.RUNNING

        # Set up a fake expired approval request on a step
        from datetime import timedelta

        from django.utils import timezone

        step = execution.steps.first()
        step.status = ExecutionStep.Status.WAITING_FOR_APPROVAL
        step.save(update_fields=["status"])

        ar = ApprovalRequest.objects.create(
            organization=execution.organization,
            execution=execution,
            step=step,
            subject_type="execution_step",
            subject_id=str(step.id),
            status=ApprovalRequest.Status.PENDING,
            requested_at=timezone.now() - timedelta(hours=2),
            expires_at=timezone.now() - timedelta(hours=1),
            timeout_seconds=3600,
        )
        execution.status = "running"
        execution.save(update_fields=["status"])

        result = execution_services.fail_execution_for_approval_timeout(
            execution=execution,
            step=step,
            approval_request=ar,
        )
        assert result is True

        # Change must be closed
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.CLOSED

    # C4: Expired dispatch token transitions change to expired
    def test_expired_dispatch_token_transitions_change_to_expired(
        self, draft_change, operation_profile
    ):
        """bind_execution with expired token must transition change to expired status."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.common.exceptions import InvalidStateTransitionError
        from apps.executions import services as execution_services

        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        execution = binding.execution

        # Claim the execution
        claim_result = execution_services.claim_next_execution(
            runner_id="test-runner-1"
        )
        assert claim_result is not None
        claim_token = claim_result["claim_token"]
        execution.refresh_from_db()

        # Expire the binding
        binding.dispatch_token_expires_at = timezone.now() - timedelta(seconds=1)
        binding.save(update_fields=["dispatch_token_expires_at"])

        dispatch_token = change_services.generate_dispatch_token(binding)

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            change_services.bind_execution(
                change_id=str(change.id),
                runner_id="test-runner-1",
                claim_token=claim_token,
                execution_id=str(execution.id),
                dispatch_token=dispatch_token,
                requested_inputs_sha256=binding.requested_inputs_sha256,
                operation_profile_key=binding.operation_profile_key,
            )
        assert exc_info.value.code == "dispatch_token_expired"

        # Change must be expired (not stuck in dispatchable)
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.EXPIRED
        assert change.terminal_reason == "dispatch_token_expired"

    def test_claim_next_expires_dispatch_before_runner_receives_partial_claim(
        self, draft_change, operation_profile
    ):
        from datetime import timedelta

        from django.utils import timezone

        from apps.executions import services as execution_services
        from apps.executions.models import Execution

        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        binding.dispatch_token_expires_at = timezone.now() - timedelta(seconds=1)
        binding.save(update_fields=["dispatch_token_expires_at"])

        result = execution_services.claim_next_execution(runner_id="test-runner-1")

        assert result is None
        change.refresh_from_db()
        binding.execution.refresh_from_db()
        assert change.status == ChangeRecord.Status.EXPIRED
        assert change.terminal_reason == "dispatch_token_expired"
        assert binding.execution.status == Execution.Status.CANCELLED

    def test_different_runner_cannot_start_after_successful_bind(
        self, draft_change, operation_profile, runner_client
    ):
        from apps.executions import services as execution_services

        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        execution = binding.execution
        claim_result = execution_services.claim_next_execution(runner_id="runner-1")
        claim_token = claim_result["claim_token"]

        change_services.bind_execution(
            change_id=str(change.id),
            runner_id="runner-1",
            claim_token=claim_token,
            execution_id=str(execution.id),
            dispatch_token=change_services.generate_dispatch_token(binding),
            requested_inputs_sha256=binding.requested_inputs_sha256,
            operation_profile_key=binding.operation_profile_key,
        )

        execution.refresh_from_db()
        execution.claimed_by_runner_id = "runner-2"
        execution.save(update_fields=["claimed_by_runner_id"])
        step = execution.steps.order_by("position").first()

        response = runner_client.post(
            f"/api/v1/internal/executions/{execution.id}/steps/{step.id}/start/",
            {
                "runner_id": "runner-2",
                "claim_token": claim_token,
            },
            format="json",
        )

        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == "change_binding_runner_mismatch"

    # C3: Bind idempotency revalidates payload
    def test_bind_idempotency_rejects_mismatched_profile_key(
        self, draft_change, operation_profile
    ):
        """Second bind call with wrong operation_profile_key must be rejected even on idempotent path."""
        from apps.common.exceptions import DomainValidationError
        from apps.executions import services as execution_services

        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        execution = binding.execution

        claim_result = execution_services.claim_next_execution(
            runner_id="test-runner-1"
        )
        assert claim_result is not None
        claim_token = claim_result["claim_token"]
        execution.refresh_from_db()

        dispatch_token = change_services.generate_dispatch_token(binding)

        # First bind — success
        change_services.bind_execution(
            change_id=str(change.id),
            runner_id="test-runner-1",
            claim_token=claim_token,
            execution_id=str(execution.id),
            dispatch_token=dispatch_token,
            requested_inputs_sha256=binding.requested_inputs_sha256,
            operation_profile_key=binding.operation_profile_key,
        )
        change.refresh_from_db()
        assert change.status == ChangeRecord.Status.RUNNING

        # Second bind with wrong profile key — must be rejected
        with pytest.raises(DomainValidationError) as exc_info:
            change_services.bind_execution(
                change_id=str(change.id),
                runner_id="test-runner-1",
                claim_token=claim_token,
                execution_id=str(execution.id),
                dispatch_token=dispatch_token,
                requested_inputs_sha256=binding.requested_inputs_sha256,
                operation_profile_key="wrong-profile-key",
            )
        assert exc_info.value.code == "operation_profile_key_mismatch"

    # C6: draft -> pending_approval emits status_changed
    def test_submit_with_approval_emits_status_changed(
        self, draft_change, operation_profile
    ):
        """Submitting a change that requires approval must emit change.status_changed."""
        from apps.audit.models import AuditEvent

        assert operation_profile.requires_approval is True

        change_services.submit_change_record(change=draft_change)

        status_changed_events = AuditEvent.objects.filter(
            event_type="change.status_changed",
            object_id=draft_change.id,
        )
        assert status_changed_events.exists()
        event = status_changed_events.order_by("created_at").first()
        data = event.metadata
        assert data.get("previous_status") == ChangeRecord.Status.DRAFT
        assert data.get("new_status") == ChangeRecord.Status.PENDING_APPROVAL
