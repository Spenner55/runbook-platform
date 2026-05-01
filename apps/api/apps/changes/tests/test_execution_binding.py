"""Tests for execution binding constraint and bind endpoint validation."""

import pytest
from django.db import IntegrityError

from apps.changes.models import ChangeExecutionBinding, ChangeRecord
from apps.changes import services as change_services


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

    def test_binding_references_correct_execution(self, draft_change, operation_profile):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        assert binding.execution is not None
        assert binding.execution.workflow == draft_change.workflow

    def test_dispatch_token_hash_stored_not_cleartext(self, draft_change, operation_profile):
        change = self._make_dispatchable(draft_change, operation_profile)
        binding = change.execution_binding
        clear_token = change_services.generate_dispatch_token(binding)
        assert binding.dispatch_token_hash != clear_token
        assert len(binding.dispatch_token_hash) > 0

    def test_generate_dispatch_token_is_deterministic_for_same_nonce(self, draft_change, operation_profile):
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

    def test_bind_missing_fields_returns_400(self, draft_change, operation_profile, runner_client):
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

    def test_bind_unauthenticated_rejected(self, draft_change, operation_profile, api_client):
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

    def test_bind_wrong_dispatch_token_returns_error(self, draft_change, operation_profile, runner_client):
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
