from datetime import timedelta

import pytest
from django.utils import timezone

from apps.artifacts.models import Artifact
from apps.audit.models import AuditEvent
from apps.audit.services import AuditService, system_actor
from apps.changes.models import (
    ChangeClosure,
    ChangeExecutionBinding,
    ChangeRecord,
    VerificationCheck,
    VerificationPlan,
    VerificationResult,
)
from apps.evidence.models import EvidenceBundle, EvidenceBundleItem
from apps.evidence.services import create_evidence_bundle_for_change
from apps.executions.models import Execution, ExecutionStep
from apps.organizations.models import Organization


def _close_change(change):
    now = timezone.now()
    change.status = ChangeRecord.Status.CLOSED
    change.closed_at = now
    change.verified_at = now - timedelta(minutes=1)
    change.save(update_fields=["status", "closed_at", "verified_at", "updated_at"])
    return change


def _execution(change):
    execution = Execution.objects.create(
        organization=change.organization,
        workflow=change.workflow,
        workflow_version=change.workflow_version_snapshot or 1,
        workflow_snapshot={},
        status=Execution.Status.SUCCEEDED,
        started_at=timezone.now() - timedelta(minutes=20),
        finished_at=timezone.now() - timedelta(minutes=10),
        claimed_by_runner_id="runner-1",
        claimed_at=timezone.now() - timedelta(minutes=21),
    )
    step = ExecutionStep.objects.create(
        execution=execution,
        position=1,
        step_key="health-check",
        name="Health check",
        step_type="shell",
        risk_level="low",
        command="",
        status=ExecutionStep.Status.SUCCEEDED,
        started_at=timezone.now() - timedelta(minutes=19),
        finished_at=timezone.now() - timedelta(minutes=18),
        exit_code=0,
    )
    ChangeExecutionBinding.objects.create(
        change_record=change,
        execution=execution,
        organization=change.organization,
        operation_profile_key=change.operation_profile.key,
        requested_inputs_sha256=change.requested_inputs_sha256 or "a" * 64,
        dispatch_token_nonce="nonce",
        dispatch_token_hash="hash",
        dispatch_token_expires_at=timezone.now() + timedelta(minutes=5),
        reserved_at=timezone.now() - timedelta(minutes=25),
        bound_at=timezone.now() - timedelta(minutes=22),
        bound_by_runner_id="runner-1",
        execution_accepted_at=timezone.now() - timedelta(minutes=21),
        execution_started_at=timezone.now() - timedelta(minutes=20),
        execution_finished_at=timezone.now() - timedelta(minutes=10),
    )
    return execution, step


def _verification(change, user=None, *, with_result=True, artifact=None):
    plan = VerificationPlan.objects.create(
        organization=change.organization,
        change_record=change,
        operation_profile=change.operation_profile,
        mode=VerificationPlan.Mode.MIXED,
        status=VerificationPlan.Status.SATISFIED if with_result else VerificationPlan.Status.ACTIVE,
        generated_from_profile_snapshot={"verification_mode": "mixed"},
        generated_from_profile_sha256="a" * 64,
        required_check_count=1,
        optional_check_count=0,
        satisfied_required_count=1 if with_result else 0,
        failed_required_count=0,
        generated_at=timezone.now() - timedelta(minutes=9),
    )
    check = VerificationCheck.objects.create(
        organization=change.organization,
        plan=plan,
        change_record=change,
        position=1,
        key="runner-health-check",
        name="Runner health check",
        check_type=VerificationCheck.CheckType.RUNNER_STEP,
        required=True,
        status=VerificationCheck.Status.PASSED if with_result else VerificationCheck.Status.PENDING,
        verification_key="postdeploy.health.ok",
        source_step_key="health-check",
    )
    result = None
    if with_result:
        result = VerificationResult.objects.create(
            organization=change.organization,
            change_record=change,
            plan=plan,
            verification_check=check,
            source=VerificationResult.Source.USER,
            outcome=VerificationResult.Outcome.PASSED,
            validation_status=VerificationResult.ValidationStatus.ACCEPTED,
            submitted_by=user,
            artifact=artifact,
            artifact_checksum_sha256=artifact.checksum_sha256 if artifact else "",
            manual_attestation_text="Verified post-change health.",
            submitted_at=timezone.now() - timedelta(minutes=8),
            validated_at=timezone.now() - timedelta(minutes=7),
        )
        VerificationCheck.objects.filter(pk=check.pk).update(last_result=result)
    return plan, check, result


def _closure(change, plan, user):
    return ChangeClosure.objects.create(
        organization=change.organization,
        change_record=change,
        outcome=ChangeClosure.Outcome.SUCCESS,
        closed_by=user,
        summary="Change verified and closed.",
        verification_plan=plan,
        verification_summary={"required": 1, "satisfied": 1},
        execution_summary={"status": "succeeded"},
        closed_at=timezone.now(),
    )


def _artifact(change, execution, *, organization=None):
    return Artifact.objects.create(
        organization=organization or change.organization,
        execution=execution,
        kind=Artifact.Kind.REPORT,
        name="verification-report.json",
        mime_type="application/json",
        size_bytes=17,
        checksum_sha256="b" * 64,
        storage_key=f"artifacts/{change.id}/verification-report.json",
        uploaded_by_runner_id="runner-1",
        upload_status=Artifact.UploadStatus.AVAILABLE,
        uploaded_at=timezone.now() - timedelta(minutes=6),
    )


def _complete_closed_change(change, user, *, artifact=None):
    execution, _step = _execution(change)
    plan, _check, _result = _verification(change, user, artifact=artifact)
    _closure(change, plan, user)
    _close_change(change)
    return execution, plan


@pytest.mark.django_db
def test_closed_change_can_produce_bundle(evidence_change, user):
    _complete_closed_change(evidence_change, user)

    bundle = create_evidence_bundle_for_change(change_record=evidence_change, created_by=user)

    assert bundle.status == EvidenceBundle.Status.COMPILING
    assert bundle.completeness_status == EvidenceBundle.CompletenessStatus.COMPLETE
    assert bundle.source_snapshot_sha256
    item_types = set(bundle.items.values_list("item_type", flat=True))
    assert EvidenceBundleItem.ItemType.CHANGE_SNAPSHOT in item_types
    assert EvidenceBundleItem.ItemType.APPROVAL in item_types
    assert EvidenceBundleItem.ItemType.POLICY_DECISION in item_types
    assert EvidenceBundleItem.ItemType.EXECUTION in item_types
    assert EvidenceBundleItem.ItemType.AUDIT_EVENT in item_types
    assert EvidenceBundleItem.ItemType.ARTIFACT in item_types
    assert EvidenceBundleItem.ItemType.VERIFICATION_RESULT in item_types
    assert EvidenceBundleItem.ItemType.CLOSURE in item_types


@pytest.mark.django_db
def test_missing_closure_marks_incomplete(evidence_change, user):
    _execution(evidence_change)
    _verification(evidence_change, user)
    _close_change(evidence_change)

    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    assert bundle.completeness_status == EvidenceBundle.CompletenessStatus.INCOMPLETE
    closure_item = bundle.items.get(item_type=EvidenceBundleItem.ItemType.CLOSURE)
    assert closure_item.present is False
    assert closure_item.missing_reason == "missing_closure"


@pytest.mark.django_db
def test_missing_required_verification_result_marks_incomplete(evidence_change, user):
    _execution(evidence_change)
    plan, _check, _result = _verification(evidence_change, user, with_result=False)
    _closure(evidence_change, plan, user)
    _close_change(evidence_change)

    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    assert bundle.completeness_status == EvidenceBundle.CompletenessStatus.INCOMPLETE
    assert bundle.items.filter(
        item_type=EvidenceBundleItem.ItemType.VERIFICATION_RESULT,
        present=False,
        missing_reason="missing_required_verification_result",
    ).exists()


@pytest.mark.django_db
def test_cross_org_artifact_reference_marks_invalid(evidence_change, user):
    execution, _step = _execution(evidence_change)
    artifact = _artifact(evidence_change, execution)
    plan, _check, _result = _verification(evidence_change, user, artifact=artifact)
    _closure(evidence_change, plan, user)
    _close_change(evidence_change)
    other_org = Organization.objects.create(name="Other Org", slug="other-org")
    Artifact.objects.filter(pk=artifact.pk).update(organization=other_org)

    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    assert bundle.completeness_status == EvidenceBundle.CompletenessStatus.INVALID
    invalid_item = bundle.items.get(item_key=f"artifact:{artifact.id}")
    assert invalid_item.valid is False
    assert invalid_item.validation_errors[0]["code"] == "cross_org_artifact_reference"


@pytest.mark.django_db
def test_audit_event_order_is_preserved(evidence_change, user):
    _complete_closed_change(evidence_change, user)
    actor = system_actor("audit order test")
    base_time = timezone.now() - timedelta(minutes=5)
    for offset, event_type in enumerate(["test.first", "test.second", "test.third"]):
        AuditService.emit(
            organization_id=evidence_change.organization_id,
            actor_type=actor.actor_type,
            actor_label=actor.actor_label,
            event_type=event_type,
            object_type=AuditEvent.ObjectType.CHANGE_RECORD,
            object_id=evidence_change.id,
            occurred_at=base_time + timedelta(seconds=offset),
        )

    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    event_types = list(
        bundle.items.filter(item_type=EvidenceBundleItem.ItemType.AUDIT_EVENT)
        .exclude(item_key="audit_trail")
        .order_by("position")
        .values_list("source_metadata__event_type", flat=True)
    )
    assert event_types.index("test.first") < event_types.index("test.second")
    assert event_types.index("test.second") < event_types.index("test.third")


@pytest.mark.django_db
def test_bundle_creation_audit_event_is_excluded(evidence_change, user):
    _complete_closed_change(evidence_change, user)

    bundle = create_evidence_bundle_for_change(change_record=evidence_change)

    assert AuditEvent.objects.filter(
        object_type=AuditEvent.ObjectType.EVIDENCE_BUNDLE,
        object_id=bundle.id,
        event_type="evidence_bundle.materialized",
    ).exists()
    assert not bundle.items.filter(
        item_type=EvidenceBundleItem.ItemType.AUDIT_EVENT,
        source_metadata__event_type="evidence_bundle.materialized",
    ).exists()
