"""Verification result submission and recomputation service tests."""

import hashlib

import pytest
from django.utils import timezone

from apps.artifacts.models import Artifact
from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor, AuditService
from apps.changes import services as change_services
from apps.changes.models import (
    ChangeRecord,
    OperationProfile,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
)
from apps.executions import services as execution_services
from apps.executions.models import Execution
from apps.organizations.models import Membership, MembershipRole
from apps.users.models import User


RUNNER_ID = "verification-runner"


def _system_actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _user_actor(user):
    return AuditActor(
        actor_type=AuditEvent.ActorType.USER,
        actor_id=str(user.id),
        actor_label=user.email,
    )


def _configure_profile(profile: OperationProfile, checks: list[dict]) -> None:
    profile.verification_mode = OperationProfile.VerificationMode.MIXED
    profile.verification_plan_template = {"checks": checks}
    profile.save(
        update_fields=["verification_mode", "verification_plan_template", "updated_at"]
    )


def _make_user(email: str, org):
    user = User.objects.create_user(email=email, password="not-used")
    Membership.objects.create(organization=org, user=user, role=MembershipRole.OPERATOR)
    return user


def _prepare_pending_change(draft_change, *, submitter=None):
    from apps.approvals import services as approval_services

    actor = _user_actor(submitter) if submitter else _system_actor()
    change = change_services.submit_change_record(change=draft_change, actor=actor)
    approval_actor = _system_actor()
    approval_services.decide_approval(
        approval_request=change.approval_request,
        decision="approved",
        actor=approval_actor,
    )
    change.refresh_from_db()
    binding = change.execution_binding
    claim = execution_services.claim_next_execution(runner_id=RUNNER_ID)
    change_services.bind_execution(
        change_id=str(change.id),
        runner_id=RUNNER_ID,
        claim_token=claim["claim_token"],
        execution_id=str(binding.execution_id),
        dispatch_token=change_services.generate_dispatch_token(binding),
        requested_inputs_sha256=binding.requested_inputs_sha256,
        operation_profile_key=binding.operation_profile_key,
    )
    binding.refresh_from_db()
    execution_services.complete_execution(
        execution=binding.execution,
        runner_id=RUNNER_ID,
        claim_token=claim["claim_token"],
        outcome=Execution.Status.SUCCEEDED,
    )
    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.VERIFICATION_PENDING
    return change, binding


def _artifact(
    *, org, execution, checksum=None, name="report.json", kind=Artifact.Kind.REPORT
):
    checksum = checksum or hashlib.sha256(b"verification artifact").hexdigest()
    return Artifact.objects.create(
        organization=org,
        execution=execution,
        kind=kind,
        name=name,
        original_name=name,
        mime_type="application/json",
        size_bytes=32,
        checksum_sha256=checksum,
        storage_key=f"test/{execution.id}/{name}/{checksum}",
        uploaded_by_runner_id=RUNNER_ID,
        upload_status=Artifact.UploadStatus.AVAILABLE,
        uploaded_at=timezone.now(),
    )


@pytest.mark.django_db
def test_required_checks_block_verified_until_passed(draft_change):
    change, _binding = _prepare_pending_change(draft_change)

    plan = change.verification_plan
    assert plan.status == VerificationPlan.Status.ACTIVE
    assert change.status == ChangeRecord.Status.VERIFICATION_PENDING

    change_services.submit_runner_verification_result(
        change=change,
        check_key="runner-health-check",
        runner_id=RUNNER_ID,
        execution_id=str(change.execution_binding.execution_id),
        outcome=VerificationResult.Outcome.PASSED,
        verification_key="postdeploy.health.ok",
        observed_value={"status": "passed"},
    )

    change.refresh_from_db()
    plan.refresh_from_db()
    assert plan.status == VerificationPlan.Status.SATISFIED
    assert change.status == ChangeRecord.Status.VERIFIED


@pytest.mark.django_db
def test_failed_required_check_causes_verification_failed(draft_change):
    change, binding = _prepare_pending_change(draft_change)

    change_services.submit_runner_verification_result(
        change=change,
        check_key="runner-health-check",
        runner_id=RUNNER_ID,
        execution_id=str(binding.execution_id),
        outcome=VerificationResult.Outcome.FAILED,
        verification_key="postdeploy.health.ok",
        observed_value={"status": "failed"},
    )

    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.VERIFICATION_FAILED
    assert change.verification_plan.status == VerificationPlan.Status.FAILED


@pytest.mark.django_db
def test_optional_failed_check_does_not_block_verified(draft_change, operation_profile):
    _configure_profile(
        operation_profile,
        [
            {
                "key": "required-runner",
                "name": "Required runner",
                "type": "runner_step",
                "required": True,
                "verification_key": "required.ok",
            },
            {
                "key": "optional-runner",
                "name": "Optional runner",
                "type": "runner_step",
                "required": False,
                "verification_key": "optional.ok",
            },
        ],
    )
    change, binding = _prepare_pending_change(draft_change)

    change_services.submit_runner_verification_result(
        change=change,
        check_key="optional-runner",
        runner_id=RUNNER_ID,
        execution_id=str(binding.execution_id),
        outcome=VerificationResult.Outcome.FAILED,
        verification_key="optional.ok",
        observed_value={"status": "failed"},
    )
    change_services.submit_runner_verification_result(
        change=change,
        check_key="required-runner",
        runner_id=RUNNER_ID,
        execution_id=str(binding.execution_id),
        outcome=VerificationResult.Outcome.PASSED,
        verification_key="required.ok",
        observed_value={"status": "passed"},
    )

    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.VERIFIED
    assert change.verification_plan.failed_required_count == 0


@pytest.mark.django_db
def test_artifact_from_another_execution_rejected(draft_change, operation_profile):
    _configure_profile(
        operation_profile,
        [
            {
                "key": "artifact-report",
                "name": "Artifact report",
                "type": "artifact_presence",
                "required": True,
                "artifact_kind": Artifact.Kind.REPORT,
            }
        ],
    )
    change, _binding = _prepare_pending_change(draft_change)
    other_execution = Execution.objects.create(
        organization=change.organization,
        workflow=change.workflow,
        workflow_version=change.workflow.version,
        workflow_snapshot={},
    )
    artifact = _artifact(org=change.organization, execution=other_execution)

    result = change_services.submit_verification_result(
        change=change,
        check_key="artifact-report",
        source=VerificationResult.Source.USER,
        outcome=VerificationResult.Outcome.PASSED,
        submitted_by=_make_user("artifact-reviewer@example.com", change.organization),
        artifact_id=str(artifact.id),
    )

    assert result.validation_status == VerificationResult.ValidationStatus.REJECTED
    assert result.validation_errors[0]["code"] == "artifact_execution_mismatch"
    change.verification_plan.checks.get().refresh_from_db()
    assert change.verification_plan.checks.get().status == VerificationCheck.Status.PENDING


@pytest.mark.django_db
def test_artifact_checksum_mismatch_rejected(draft_change, operation_profile):
    _configure_profile(
        operation_profile,
        [
            {
                "key": "artifact-report",
                "name": "Artifact report",
                "type": "artifact_presence",
                "required": True,
                "artifact_kind": Artifact.Kind.REPORT,
            }
        ],
    )
    change, binding = _prepare_pending_change(draft_change)
    artifact = _artifact(org=change.organization, execution=binding.execution)

    result = change_services.submit_verification_result(
        change=change,
        check_key="artifact-report",
        source=VerificationResult.Source.USER,
        outcome=VerificationResult.Outcome.PASSED,
        submitted_by=_make_user("checksum-reviewer@example.com", change.organization),
        artifact_id=str(artifact.id),
        artifact_checksum_sha256="0" * 64,
    )

    assert result.validation_status == VerificationResult.ValidationStatus.REJECTED
    assert {"code": "artifact_checksum_mismatch"} in result.validation_errors


@pytest.mark.django_db
def test_self_review_rejected(draft_change, operation_profile, org):
    submitter = _make_user("submitter@example.com", org)
    _configure_profile(
        operation_profile,
        [
            {
                "key": "manual-review",
                "name": "Manual review",
                "type": "manual_attestation",
                "required": True,
                "manual_attestation_config": {"requires_independent_reviewer": True},
            }
        ],
    )
    change, _binding = _prepare_pending_change(draft_change, submitter=submitter)

    result = change_services.submit_user_verification_result(
        change=change,
        check_key="manual-review",
        user=submitter,
        outcome=VerificationResult.Outcome.PASSED,
        manual_attestation_text="I reviewed the change.",
    )

    assert result.validation_status == VerificationResult.ValidationStatus.REJECTED
    assert {"code": "self_review_rejected"} in result.validation_errors


@pytest.mark.django_db
def test_mixed_manual_and_automated_checks_work(draft_change, operation_profile, org):
    reviewer = _make_user("independent-reviewer@example.com", org)
    _configure_profile(
        operation_profile,
        [
            {
                "key": "runner-check",
                "name": "Runner check",
                "type": "runner_step",
                "required": True,
                "verification_key": "runner.ok",
            },
            {
                "key": "manual-review",
                "name": "Manual review",
                "type": "manual_attestation",
                "required": True,
                "manual_attestation_config": {"requires_independent_reviewer": True},
            },
        ],
    )
    change, binding = _prepare_pending_change(draft_change)

    change_services.submit_runner_verification_result(
        change=change,
        check_key="runner-check",
        runner_id=RUNNER_ID,
        execution_id=str(binding.execution_id),
        outcome=VerificationResult.Outcome.PASSED,
        verification_key="runner.ok",
        observed_value={"status": "passed"},
    )
    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.VERIFICATION_PENDING

    change_services.submit_user_verification_result(
        change=change,
        check_key="manual-review",
        user=reviewer,
        outcome=VerificationResult.Outcome.PASSED,
        manual_attestation_text="I independently verified production health.",
    )

    change.refresh_from_db()
    assert change.status == ChangeRecord.Status.VERIFIED


@pytest.mark.django_db
def test_audit_metadata_scrubber_covers_verification_payloads(org):
    event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        actor_label="test",
        event_type="test.verification_scrub",
        object_type=AuditEvent.ObjectType.CHANGE_RECORD,
        object_id=org.id,
        metadata={
            "manual_attestation_text": "raw attestation",
            "api_assertion_response": {"authorization": "Bearer secret"},
            "safe": "kept",
        },
    )

    assert event.metadata == {"safe": "kept"}
