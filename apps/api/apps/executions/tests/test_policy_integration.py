"""
Integration tests: policy evaluation wired into ExecutionStepStartView.

Covers all three effective outcomes, the requiresApproval floor, idempotency,
failure paths, and no-policy fallback.
"""

import pytest
from django.test import Client

from apps.approvals.models import ApprovalRequest
from apps.executions import services as exec_services
from apps.executions.models import ExecutionStep
from apps.organizations.models import Organization
from apps.policies import services as policy_services
from apps.policies.models import PolicyEvaluation
from apps.runbooks import services as runbook_services
from apps.workflows import services as wf_services
from apps.workflows.internal_clients import StubWorkflowTransformClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Policy Integration Runbook",
        slug="policy-integration",
        raw_content="Deploy\nVerify",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = wf_services.create_workflow(runbook=runbook, transform_client=StubWorkflowTransformClient())
    return wf_services.publish_workflow(workflow=wf)


@pytest.fixture
def claimed(published_workflow):
    exec_services.create_execution(workflow=published_workflow)
    return exec_services.claim_next_execution(runner_id="runner-1")


def _step_start(execution_id, step_id, claim_token):
    c = Client()
    return c.post(
        f"/api/v1/internal/executions/{execution_id}/steps/{step_id}/start/",
        data={"runner_id": "runner-1", "claim_token": str(claim_token)},
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# auto_approve path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_policy_requires_approval_false_returns_run(claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.requires_approval = False
    step.save(update_fields=["requires_approval", "updated_at"])

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["runner_action"] == "run"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.RUNNING


@pytest.mark.django_db
def test_auto_approve_policy_returns_run(org, claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "low"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="AutoApprove Policy")
    policy_services.create_rule(
        policy=policy, name="Auto low", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["low"]},
        outcome="auto_approve",
    )

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.json()["runner_action"] == "run"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.RUNNING


# ---------------------------------------------------------------------------
# approval_required path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_policy_requires_approval_true_returns_wait(claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.status_code in (200, 201)
    assert resp.json()["runner_action"] == "wait_for_approval"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL
    assert ApprovalRequest.objects.filter(step=step).exists()


@pytest.mark.django_db
def test_approval_required_policy_on_no_requires_approval_step_creates_request(org, claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="Approval Policy")
    policy_services.create_rule(
        policy=policy, name="High risk gate", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="approval_required",
    )

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.json()["runner_action"] == "wait_for_approval"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL
    assert ApprovalRequest.objects.filter(step=step).exists()


@pytest.mark.django_db
def test_auto_approve_policy_on_requires_approval_true_step_applies_floor(org, claimed):
    """Policy says auto_approve but requiresApproval=True floor forces approval."""
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "high"
    step.requires_approval = True
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="AutoApprove Policy")
    policy_services.create_rule(
        policy=policy, name="Auto high", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="auto_approve",
    )

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.json()["runner_action"] == "wait_for_approval"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.WAITING_FOR_APPROVAL

    evaluation = PolicyEvaluation.objects.filter(step=step).order_by("-evaluated_at").first()
    assert evaluation.outcome == "auto_approve"
    assert evaluation.effective_outcome == "approval_required"


# ---------------------------------------------------------------------------
# block path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_block_policy_transitions_step_to_failed(org, claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "critical"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="Block Policy")
    policy_services.create_rule(
        policy=policy, name="Block critical", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "equals", "value": "critical"},
        outcome="block",
        reason="Critical steps are always blocked.",
    )

    resp = _step_start(execution.id, step.id, claim_token)
    body = resp.json()

    assert body["runner_action"] == "blocked"
    assert body["policy_evaluation"]["outcome"] == "block"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.FAILED
    assert step.error_message == "policy_blocked"
    assert not ApprovalRequest.objects.filter(step=step).exists()


@pytest.mark.django_db
def test_block_policy_overrides_requires_approval(org, claimed):
    """Block always wins even when step has requiresApproval=True."""
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "critical"
    step.requires_approval = True
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="Block Policy")
    policy_services.create_rule(
        policy=policy, name="Block all critical", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "equals", "value": "critical"},
        outcome="block",
    )

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.json()["runner_action"] == "blocked"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.FAILED


@pytest.mark.django_db
def test_unexpected_policy_exception_persists_error_evaluation(monkeypatch, claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()

    def raise_policy_error(*args, **kwargs):
        raise RuntimeError("policy backend unavailable")

    monkeypatch.setattr(policy_services, "evaluate_step_policy", raise_policy_error)

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.status_code == 200
    assert resp.json()["runner_action"] == "blocked"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.FAILED
    assert step.error_message == "policy_evaluation_error"

    evaluation = PolicyEvaluation.objects.get(step=step)
    assert evaluation.error_code == "policy_evaluation_error"
    assert evaluation.effective_outcome == "block"


@pytest.mark.django_db
def test_policy_evaluation_history_requires_organization_id(claimed):
    execution = claimed["execution"]
    c = Client()

    resp = c.get(f"/api/v1/executions/{execution.id}/policy-evaluations/")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_policy_evaluation_history_rejects_wrong_organization(claimed):
    execution = claimed["execution"]
    other_org = Organization.objects.create(name="Other Org", slug="other-org")
    c = Client()

    resp = c.get(
        f"/api/v1/executions/{execution.id}/policy-evaluations/"
        f"?organization_id={other_org.id}"
    )

    assert resp.status_code == 404


@pytest.mark.django_db
def test_policy_evaluation_history_returns_scoped_results(claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()

    start_resp = _step_start(execution.id, step.id, claim_token)
    assert start_resp.status_code == 200

    c = Client()
    resp = c.get(
        f"/api/v1/executions/{execution.id}/policy-evaluations/"
        f"?organization_id={execution.organization_id}"
    )

    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_idempotent_waiting_for_approval_returns_existing_request(claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])

    resp1 = _step_start(execution.id, step.id, claim_token)
    assert resp1.json()["runner_action"] == "wait_for_approval"

    resp2 = _step_start(execution.id, step.id, claim_token)
    assert resp2.json()["runner_action"] == "wait_for_approval"
    assert ApprovalRequest.objects.filter(step=step).count() == 1


# ---------------------------------------------------------------------------
# Priority ordering end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lower_priority_rule_wins_end_to_end(org, claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="Multi Rule Policy")
    policy_services.create_rule(
        policy=policy, name="Block first", priority=1,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )
    policy_services.create_rule(
        policy=policy, name="Approve second", priority=2,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="auto_approve",
    )

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.json()["runner_action"] == "blocked"
    step.refresh_from_db()
    assert step.status == ExecutionStep.Status.FAILED


# ---------------------------------------------------------------------------
# Deactivate policy restores workflow default
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deactivated_policy_falls_back_to_workflow_default(org, claimed):
    execution = claimed["execution"]
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = policy_services.create_policy(organization=org, name="Block Policy", is_active=False)
    policy_services.create_rule(
        policy=policy, name="Block high", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )

    resp = _step_start(execution.id, step.id, claim_token)

    assert resp.json()["runner_action"] == "run"
