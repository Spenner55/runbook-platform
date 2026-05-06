"""Verification plan generation and dispatch enforcement service tests."""

import json

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import (
    ChangeRecord,
    VerificationCheck,
    VerificationPlan,
)
from apps.common.exceptions import DomainConflictError, DomainValidationError


def _actor():
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")


def _approve_without_plan(change):
    from apps.approvals.models import ApprovalRequest

    actor = _actor()
    change = change_services.submit_change_record(change=change, actor=actor)
    if change.approval_request_id:
        ApprovalRequest.objects.filter(pk=change.approval_request_id).update(
            status="approved"
        )
    ChangeRecord.objects.filter(pk=change.pk).update(
        status=ChangeRecord.Status.APPROVED,
        approved_at=timezone.now(),
    )
    change.refresh_from_db()
    return change


def _claim_dispatch_execution(change, runner_id="verification-runner"):
    from apps.executions import services as execution_services

    binding = change.execution_binding
    claim_result = execution_services.claim_next_execution(runner_id=runner_id)
    assert claim_result is not None
    binding.execution.refresh_from_db()
    return binding, claim_result["claim_token"]


@pytest.mark.django_db
def test_plan_generation_from_profile_template(draft_change):
    change = _approve_without_plan(draft_change)

    plan = change_services.ensure_verification_plan(
        change=change,
        actor=_actor(),
        activate=True,
    )

    assert plan.status == VerificationPlan.Status.ACTIVE
    assert plan.mode == VerificationPlan.Mode.AUTOMATED
    assert plan.required_check_count == 1
    assert plan.optional_check_count == 0
    assert plan.generated_from_profile_sha256

    checks = list(plan.checks.order_by("position"))
    assert [(c.position, c.key, c.check_type, c.required) for c in checks] == [
        (
            1,
            "runner-health-check",
            VerificationCheck.CheckType.RUNNER_STEP,
            True,
        )
    ]
    assert checks[0].source_step_key == "health-check"
    assert checks[0].verification_key == "postdeploy.health.ok"


@pytest.mark.django_db
def test_invalid_template_rejects_dispatch(draft_change, operation_profile):
    operation_profile.verification_plan_template = {
        "checks": [
            {
                "key": "bad-check",
                "name": "Bad check",
                "type": "unknown",
                "required": True,
            }
        ]
    }
    operation_profile.save(update_fields=["verification_plan_template", "updated_at"])
    change = _approve_without_plan(draft_change)

    with pytest.raises(DomainValidationError) as exc_info:
        change_services.make_dispatchable(change=change, actor=_actor())

    assert exc_info.value.code == "verification_plan_template_invalid"
    assert not VerificationPlan.objects.filter(change_record=change).exists()


@pytest.mark.django_db
def test_missing_plan_blocks_dispatch_bind(draft_change):
    from apps.approvals import services as approval_services

    change = change_services.submit_change_record(change=draft_change, actor=_actor())
    approval_services.decide_approval(
        approval_request=change.approval_request,
        decision="approved",
        actor=_actor(),
    )
    change.refresh_from_db()
    dispatchable_change = change

    plan = dispatchable_change.verification_plan
    plan.delete()

    binding, claim_token = _claim_dispatch_execution(dispatchable_change)

    with pytest.raises(DomainConflictError) as exc_info:
        change_services.bind_execution(
            change_id=str(dispatchable_change.id),
            runner_id="verification-runner",
            claim_token=claim_token,
            execution_id=str(binding.execution_id),
            dispatch_token=change_services.generate_dispatch_token(binding),
            requested_inputs_sha256=binding.requested_inputs_sha256,
            operation_profile_key=binding.operation_profile_key,
        )

    assert exc_info.value.code == "verification_plan_missing"


@pytest.mark.django_db
def test_preflight_blocks_missing_verification_plan(draft_change):
    change = _approve_without_plan(draft_change)

    check = change_services.run_dispatch_preflight(change=change, actor=_actor())

    assert check.result == check.Result.FAILED
    verification_check = next(
        c for c in check.checks if c["name"] == "verification_plan"
    )
    assert verification_check["ok"] is False
    assert check.conflicts[0]["type"] == "verification_plan"


@pytest.mark.django_db
def test_already_generated_plan_is_reused_safely(draft_change, operation_profile):
    change = _approve_without_plan(draft_change)
    first = change_services.ensure_verification_plan(
        change=change,
        actor=_actor(),
        activate=False,
    )

    operation_profile.verification_plan_template = {
        "checks": [
            {
                "key": "new-check",
                "name": "New check",
                "type": "manual_attestation",
                "required": True,
            }
        ]
    }
    operation_profile.save(update_fields=["verification_plan_template", "updated_at"])

    second = change_services.ensure_verification_plan(
        change=change,
        actor=_actor(),
        activate=True,
    )

    assert second.id == first.id
    assert second.checks.count() == 1
    assert second.checks.get().key == "runner-health-check"
    assert second.status == VerificationPlan.Status.ACTIVE


@pytest.mark.django_db
def test_verification_plan_audit_metadata_contains_no_sensitive_payloads(draft_change):
    change = _approve_without_plan(draft_change)

    plan = change_services.ensure_verification_plan(
        change=change,
        actor=_actor(),
        activate=True,
    )

    events = AuditEvent.objects.filter(
        object_type=AuditEvent.ObjectType.CHANGE_RECORD,
        object_id=change.id,
        event_type__in=[
            "change.verification_plan_generated",
            "change.verification_plan_activated",
        ],
    )
    assert events.count() == 2

    payload = json.dumps([event.metadata for event in events], sort_keys=True)
    assert str(plan.id) in payload
    assert "postdeploy.health.ok" not in payload
    assert "source_step_key" not in payload
    assert "verification_plan_template" not in payload
    assert "requested_inputs" not in payload
