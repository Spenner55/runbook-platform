"""Internal runner verification callback tests."""

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.approvals import services as approval_services
from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import ChangeRecord, VerificationResult
from apps.executions import services as execution_services

RUNNER_ID = "verification-runner"


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _prepare_running_change(draft_change, *, runner_id=RUNNER_ID):
    change = change_services.submit_change_record(
        change=draft_change,
        actor=_system_actor(),
    )
    approval_services.decide_approval(
        approval_request=change.approval_request,
        decision="approved",
        actor=_system_actor(),
    )
    change.refresh_from_db()

    claim = execution_services.claim_next_execution(runner_id=runner_id)
    binding = change.execution_binding
    change_services.bind_execution(
        change_id=str(change.id),
        runner_id=runner_id,
        claim_token=claim["claim_token"],
        execution_id=str(binding.execution_id),
        dispatch_token=change_services.generate_dispatch_token(binding),
        requested_inputs_sha256=binding.requested_inputs_sha256,
        operation_profile_key=binding.operation_profile_key,
    )
    change.refresh_from_db()
    binding.refresh_from_db()
    assert change.status == ChangeRecord.Status.RUNNING
    return change, binding, claim["claim_token"]


def _payload(change, binding, claim_token, *, runner_id=RUNNER_ID):
    return {
        "runner_id": runner_id,
        "claim_token": str(claim_token),
        "execution_id": str(binding.execution_id),
        "check_key": "runner-health-check",
        "verification_key": "postdeploy.health.ok",
        "outcome": VerificationResult.Outcome.PASSED,
        "step_key": "health-check",
        "artifact_ids": [],
        "artifact_checksums": {},
        "observed_value": {"status": "passed", "exit_code": 0},
        "metadata": {"source": "runner"},
        "sent_at": timezone.now().isoformat(),
    }


@pytest.mark.django_db
def test_internal_verification_callback_rejects_user_jwt(draft_change, org_user):
    change, binding, claim_token = _prepare_running_change(draft_change)
    token = AccessToken.for_user(org_user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    response = client.post(
        f"/api/v1/internal/changes/{change.id}/verification-results/",
        _payload(change, binding, claim_token),
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_internal_verification_callback_rejects_wrong_runner(draft_change, runner_client):
    change, binding, claim_token = _prepare_running_change(draft_change)

    response = runner_client.post(
        f"/api/v1/internal/changes/{change.id}/verification-results/",
        _payload(change, binding, claim_token, runner_id="wrong-runner"),
        format="json",
    )

    assert response.status_code == 409
    assert response.data["errors"][0]["code"] == "runner_ownership_mismatch"


@pytest.mark.django_db
def test_internal_verification_callback_rejects_wrong_claim_token(
    draft_change, runner_client
):
    change, binding, _claim_token = _prepare_running_change(draft_change)

    response = runner_client.post(
        f"/api/v1/internal/changes/{change.id}/verification-results/",
        _payload(change, binding, uuid.uuid4()),
        format="json",
    )

    assert response.status_code == 409
    assert response.data["errors"][0]["code"] == "claim_token_mismatch"


@pytest.mark.django_db
def test_internal_verification_callback_accepts_valid_report(
    draft_change, runner_client
):
    change, binding, claim_token = _prepare_running_change(draft_change)

    response = runner_client.post(
        f"/api/v1/internal/changes/{change.id}/verification-results/",
        _payload(change, binding, claim_token),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["accepted"] is True
    assert response.data["validation_status"] == "accepted"
    assert response.data["result_id"]

    result = VerificationResult.objects.get(pk=response.data["result_id"])
    assert result.source == VerificationResult.Source.RUNNER
    assert result.runner_id == RUNNER_ID
    assert result.change_record_id == change.id


@pytest.mark.django_db
def test_internal_verification_route_convention_rejects_internal_v1_drift(
    draft_change, runner_client
):
    change, binding, claim_token = _prepare_running_change(draft_change)

    response = runner_client.post(
        f"/internal/v1/changes/{change.id}/verification-results/",
        _payload(change, binding, claim_token),
        format="json",
    )

    assert response.status_code == 404
