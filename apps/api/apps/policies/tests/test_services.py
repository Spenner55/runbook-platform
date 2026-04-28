"""
Service-level tests for Phase 10.2 policies.

Covers: create/update policy/rule, condition validation, evaluation algorithm,
requiresApproval floor, inactive filtering, multi-policy ordering, and failure paths.
"""

import pytest

from apps.common.exceptions import DomainConflictError, DomainValidationError
from apps.executions import services as exec_services
from apps.policies import services
from apps.policies.models import Policy, PolicyEvaluation, PolicyRule
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
        title="Policy Test Runbook",
        slug="policy-test",
        raw_content="Deploy\nVerify",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = wf_services.create_workflow(runbook=runbook, transform_client=StubWorkflowTransformClient())
    return wf_services.publish_workflow(workflow=wf)


@pytest.fixture
def execution_and_step(org, published_workflow):
    execution = exec_services.create_execution(workflow=published_workflow)
    result = exec_services.claim_next_execution(runner_id="runner-1")
    execution = result["execution"]
    claim_token = result["claim_token"]
    step = execution.steps.order_by("position").first()
    return execution, step, claim_token


@pytest.fixture
def active_policy(org):
    return services.create_policy(organization=org, name="Test Policy")


# ---------------------------------------------------------------------------
# create_policy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_policy_success(org):
    policy = services.create_policy(organization=org, name="Safety Policy", description="Blocks risky steps.")
    assert policy.id is not None
    assert policy.is_active is True


@pytest.mark.django_db
def test_create_policy_duplicate_active_name_raises(org):
    services.create_policy(organization=org, name="Safety Policy")
    with pytest.raises(DomainConflictError) as exc_info:
        services.create_policy(organization=org, name="Safety Policy")
    assert exc_info.value.code == "duplicate_active_policy_name"


@pytest.mark.django_db
def test_create_policy_duplicate_name_allowed_when_first_inactive(org):
    services.create_policy(organization=org, name="Safety Policy", is_active=False)
    policy = services.create_policy(organization=org, name="Safety Policy", is_active=True)
    assert policy.is_active is True


# ---------------------------------------------------------------------------
# create_rule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_rule_risk_level(active_policy):
    rule = services.create_rule(
        policy=active_policy,
        name="High risk",
        priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high", "critical"]},
        outcome="approval_required",
    )
    assert rule.id is not None
    assert rule.priority == 10


@pytest.mark.django_db
def test_create_rule_duplicate_priority_raises(active_policy):
    services.create_rule(
        policy=active_policy, name="Rule A", priority=10,
        condition_type="risk_level", condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )
    with pytest.raises(DomainConflictError) as exc_info:
        services.create_rule(
            policy=active_policy, name="Rule B", priority=10,
            condition_type="risk_level", condition_params={"operator": "in", "values": ["high"]},
            outcome="block",
        )
    assert exc_info.value.code == "duplicate_rule_priority"


@pytest.mark.django_db
def test_create_rule_duplicate_name_raises(active_policy):
    services.create_rule(
        policy=active_policy, name="Rule A", priority=10,
        condition_type="risk_level", condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )
    with pytest.raises(DomainConflictError) as exc_info:
        services.create_rule(
            policy=active_policy, name="Rule A", priority=20,
            condition_type="risk_level", condition_params={"operator": "in", "values": ["high"]},
            outcome="block",
        )
    assert exc_info.value.code == "duplicate_rule_name"


@pytest.mark.django_db
def test_create_rule_zero_priority_raises(active_policy):
    with pytest.raises(DomainValidationError) as exc_info:
        services.create_rule(
            policy=active_policy, name="Bad", priority=0,
            condition_type="risk_level", condition_params={"operator": "in", "values": ["high"]},
            outcome="block",
        )
    assert exc_info.value.code == "invalid_rule_priority"


# ---------------------------------------------------------------------------
# Condition validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("params,should_raise", [
    ({"operator": "in", "values": ["high", "critical"]}, False),
    ({"operator": "equals", "value": "high"}, False),
    ({"operator": "in", "values": []}, True),
    ({"operator": "equals"}, True),
    ({"operator": "bad"}, True),
    ({"operator": "in", "values": [1, 2]}, True),
])
def test_validate_risk_level_condition(params, should_raise):
    if should_raise:
        with pytest.raises(DomainValidationError):
            services._validate_condition_params("risk_level", params)
    else:
        services._validate_condition_params("risk_level", params)


@pytest.mark.parametrize("params,should_raise", [
    ({"operator": "in", "values": ["shell", "deploy"]}, False),
    ({"operator": "equals", "value": "shell"}, False),
    ({"operator": "in", "values": []}, True),
])
def test_validate_step_type_condition(params, should_raise):
    if should_raise:
        with pytest.raises(DomainValidationError):
            services._validate_condition_params("step_type", params)
    else:
        services._validate_condition_params("step_type", params)


@pytest.mark.parametrize("params,should_raise", [
    (
        {"timezone": "America/Edmonton", "days_of_week": ["mon", "fri"],
         "start_time": "09:00", "end_time": "17:00", "match_when": "inside"},
        False,
    ),
    ({"timezone": "Invalid/Tz", "days_of_week": ["mon"], "start_time": "09:00", "end_time": "17:00", "match_when": "inside"}, True),
    ({"timezone": "UTC", "days_of_week": [], "start_time": "09:00", "end_time": "17:00", "match_when": "inside"}, True),
    ({"timezone": "UTC", "days_of_week": ["mon"], "start_time": "17:00", "end_time": "09:00", "match_when": "inside"}, True),
    ({"timezone": "UTC", "days_of_week": ["mon"], "start_time": "09:00", "end_time": "17:00", "match_when": "bad"}, True),
    ({"timezone": "UTC", "days_of_week": ["monday"], "start_time": "09:00", "end_time": "17:00", "match_when": "inside"}, True),
])
def test_validate_time_window_condition(params, should_raise):
    if should_raise:
        with pytest.raises(DomainValidationError):
            services._validate_condition_params("time_window", params)
    else:
        services._validate_condition_params("time_window", params)


def test_validate_unknown_condition_type_raises():
    with pytest.raises(DomainValidationError) as exc_info:
        services._validate_condition_params("magic_condition", {})
    assert exc_info.value.code == "unknown_condition_type"


# ---------------------------------------------------------------------------
# evaluate_step_policy — risk_level
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evaluate_risk_level_match_returns_approval_required(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Risk Policy")
    services.create_rule(
        policy=policy, name="High risk", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high", "critical"]},
        outcome="approval_required",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is True
    assert evaluation.outcome == "approval_required"
    assert evaluation.effective_outcome == "approval_required"
    assert evaluation.decision_source == "policy_rule"
    assert evaluation.policy == policy


@pytest.mark.django_db
def test_evaluate_risk_level_no_match_falls_back_to_workflow_default(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "low"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Risk Policy")
    services.create_rule(
        policy=policy, name="High risk", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high", "critical"]},
        outcome="approval_required",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is False
    assert evaluation.outcome == "auto_approve"
    assert evaluation.effective_outcome == "auto_approve"
    assert evaluation.decision_source == "workflow_default"


@pytest.mark.django_db
def test_evaluate_no_active_policies_falls_back_to_requires_approval(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.requires_approval = True
    step.save(update_fields=["requires_approval", "updated_at"])

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is False
    assert evaluation.outcome == "approval_required"
    assert evaluation.decision_source == "workflow_default"


@pytest.mark.django_db
def test_evaluate_no_active_policies_no_requires_approval(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.requires_approval = False
    step.save(update_fields=["requires_approval", "updated_at"])

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.outcome == "auto_approve"
    assert evaluation.matched is False


# ---------------------------------------------------------------------------
# requiresApproval floor
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_approve_rule_on_requires_approval_step_applies_floor(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = True
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="AutoApprove Policy")
    services.create_rule(
        policy=policy, name="Auto high", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="auto_approve",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.outcome == "auto_approve"
    assert evaluation.effective_outcome == "approval_required"
    assert evaluation.matched is True


@pytest.mark.django_db
def test_auto_approve_rule_on_non_requires_approval_step_no_floor(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="AutoApprove Policy")
    services.create_rule(
        policy=policy, name="Auto high", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="auto_approve",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.outcome == "auto_approve"
    assert evaluation.effective_outcome == "auto_approve"


# ---------------------------------------------------------------------------
# Rule priority ordering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lower_priority_number_evaluates_first(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Ordered Policy")
    services.create_rule(
        policy=policy, name="First (wins)", priority=5,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )
    services.create_rule(
        policy=policy, name="Second (ignored)", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="auto_approve",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.outcome == "block"
    assert evaluation.rule.name == "First (wins)"


@pytest.mark.django_db
def test_first_matching_rule_wins(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.step_type = "deploy"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "step_type", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Multi Rule Policy")
    services.create_rule(
        policy=policy, name="Block deploys", priority=1,
        condition_type="step_type",
        condition_params={"operator": "equals", "value": "deploy"},
        outcome="block",
    )
    services.create_rule(
        policy=policy, name="Approve high risk", priority=2,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="approval_required",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.outcome == "block"
    assert evaluation.rule.name == "Block deploys"


# ---------------------------------------------------------------------------
# Inactive filtering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_inactive_policy_excluded_from_evaluation(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Inactive Policy", is_active=False)
    services.create_rule(
        policy=policy, name="Block high", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is False
    assert evaluation.decision_source == "workflow_default"


@pytest.mark.django_db
def test_inactive_rule_excluded_from_evaluation(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Active Policy")
    services.create_rule(
        policy=policy, name="Block high", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block",
        is_active=False,
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is False


# ---------------------------------------------------------------------------
# step_type condition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evaluate_step_type_match(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.step_type = "database"
    step.requires_approval = False
    step.save(update_fields=["step_type", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="DB Policy")
    services.create_rule(
        policy=policy, name="DB block", priority=10,
        condition_type="step_type",
        condition_params={"operator": "in", "values": ["database", "deploy"]},
        outcome="block",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is True
    assert evaluation.outcome == "block"


# ---------------------------------------------------------------------------
# time_window condition
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evaluate_time_window_inside_match(org, execution_and_step):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    execution, step, _ = execution_and_step
    step.requires_approval = False
    step.save(update_fields=["requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Time Policy")
    services.create_rule(
        policy=policy, name="Business hours", priority=10,
        condition_type="time_window",
        condition_params={
            "timezone": "UTC",
            "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
            "start_time": "00:00",
            "end_time": "23:59",
            "match_when": "inside",
        },
        outcome="approval_required",
    )

    # Monday within the window
    evaluated_at = datetime(2026, 4, 27, 12, 0, 0, tzinfo=ZoneInfo("UTC"))  # Monday
    evaluation = services.evaluate_step_policy(
        execution=execution, step=step, evaluated_at=evaluated_at
    )
    assert evaluation.matched is True
    assert evaluation.outcome == "approval_required"


@pytest.mark.django_db
def test_evaluate_time_window_outside_match(org, execution_and_step):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    execution, step, _ = execution_and_step
    step.requires_approval = False
    step.save(update_fields=["requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Time Policy")
    services.create_rule(
        policy=policy, name="Weekend block", priority=10,
        condition_type="time_window",
        condition_params={
            "timezone": "UTC",
            "days_of_week": ["mon", "tue", "wed", "thu", "fri"],
            "start_time": "09:00",
            "end_time": "17:00",
            "match_when": "outside",
        },
        outcome="block",
    )

    # Saturday — outside business days
    evaluated_at = datetime(2026, 4, 25, 10, 0, 0, tzinfo=ZoneInfo("UTC"))  # Saturday
    evaluation = services.evaluate_step_policy(
        execution=execution, step=step, evaluated_at=evaluated_at
    )
    assert evaluation.matched is True
    assert evaluation.outcome == "block"


@pytest.mark.django_db
def test_time_window_uses_supplied_evaluated_at_not_wall_clock(org, execution_and_step):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    execution, step, _ = execution_and_step
    step.requires_approval = False
    step.save(update_fields=["requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Weekend Policy")
    services.create_rule(
        policy=policy,
        name="Saturday block",
        priority=10,
        condition_type="time_window",
        condition_params={
            "timezone": "UTC",
            "days_of_week": ["sat"],
            "start_time": "09:00",
            "end_time": "17:00",
            "match_when": "inside",
        },
        outcome="block",
    )

    evaluated_at = datetime(2026, 4, 25, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
    evaluation = services.evaluate_step_policy(
        execution=execution,
        step=step,
        evaluated_at=evaluated_at,
    )

    assert evaluation.matched is True
    assert evaluation.outcome == "block"
    assert evaluation.context_snapshot["evaluated_at"] == evaluated_at.isoformat()


# ---------------------------------------------------------------------------
# Failure paths (fail closed)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_persisted_condition_params_fails_closed(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Bad Params Policy")
    # Create rule directly to bypass service validation
    PolicyRule.objects.create(
        policy=policy, name="Bad rule", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "bad_operator"},
        outcome="auto_approve",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.error_code == "invalid_condition_params"
    assert evaluation.effective_outcome == "block"
    assert evaluation.matched is False


@pytest.mark.django_db
def test_unknown_condition_type_fails_closed(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.requires_approval = False
    step.save(update_fields=["requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Unknown Type Policy")
    PolicyRule.objects.create(
        policy=policy, name="Bad type", priority=10,
        condition_type="nonexistent_type",
        condition_params={},
        outcome="auto_approve",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.error_code == "invalid_condition_params"
    assert evaluation.effective_outcome == "block"


@pytest.mark.django_db
def test_unexpected_policy_load_error_persists_fail_closed_evaluation(
    org,
    execution_and_step,
    monkeypatch,
):
    execution, step, _ = execution_and_step

    def raise_policy_load_error(*args, **kwargs):
        raise RuntimeError("policy store unavailable")

    monkeypatch.setattr(services.Policy.objects, "filter", raise_policy_load_error)

    evaluation = services.evaluate_step_policy(execution=execution, step=step)

    assert evaluation.error_code == "policy_evaluation_error"
    assert evaluation.effective_outcome == "block"
    assert evaluation.policy is None
    assert evaluation.rule is None
    assert PolicyEvaluation.objects.filter(step=step, error_code="policy_evaluation_error").exists()


# ---------------------------------------------------------------------------
# Evaluation record
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evaluate_persists_context_snapshot(org, execution_and_step):
    execution, step, _ = execution_and_step
    step.risk_level = "critical"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    policy = services.create_policy(organization=org, name="Snapshot Policy")
    services.create_rule(
        policy=policy, name="Critical block", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "equals", "value": "critical"},
        outcome="block",
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.context_snapshot["risk_level"] == "critical"
    assert evaluation.context_snapshot["organization_id"] == str(org.id)
    assert evaluation.condition_params_snapshot == {"operator": "equals", "value": "critical"}


# ---------------------------------------------------------------------------
# Multi-policy cross-policy ordering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cross_policy_priority_deterministic(org, execution_and_step):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    execution, step, _ = execution_and_step
    step.risk_level = "high"
    step.requires_approval = False
    step.save(update_fields=["risk_level", "requires_approval", "updated_at"])

    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
    p1 = Policy.objects.create(
        organization=org, name="Early Policy", is_active=True,
        created_at=now,
    )
    p2 = Policy.objects.create(
        organization=org, name="Late Policy", is_active=True,
        created_at=now + timedelta(seconds=1),
    )

    # Both policies have a rule at priority 10 — p1 created_at wins
    PolicyRule.objects.create(
        policy=p1, name="P1 Rule", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="block", is_active=True,
    )
    PolicyRule.objects.create(
        policy=p2, name="P2 Rule", priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="auto_approve", is_active=True,
    )

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.policy == p1
    assert evaluation.outcome == "block"
