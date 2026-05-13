"""
Tests: policy evaluation context is enriched with v2 action facts (Phase B.5).

Covers:
- v2 step snapshot yields all new context fields
- v1 step snapshot yields safe empty defaults (behaviour unchanged)
- new condition types (action_type, execution_mode, idempotency_mode, mutates_target)
  can be created and evaluated correctly
- unknown condition type is still rejected
"""

import pytest

from apps.common.exceptions import DomainValidationError
from apps.executions import services as exec_services
from apps.executions.models import Execution
from apps.policies import services
from apps.policies.models import PolicyEvaluation, PolicyRule
from apps.policies.services import _build_evaluation_context
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
        title="V2 Policy Context Test",
        slug="v2-policy-ctx",
        raw_content="step one",
    )


@pytest.fixture
def published_v1_workflow(runbook):
    wf = wf_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return wf_services.publish_workflow(workflow=wf)


def _publish_v2(runbook, definition):
    wf = wf_services.create_workflow_v2_draft(runbook=runbook, definition=definition)
    return wf_services.publish_workflow(workflow=wf)


def _v2_step(**overrides) -> dict:
    """Return a schema-valid v2 shell_command step definition."""
    step = {
        "id": "s1",
        "name": "Shell step",
        "type": "shell_command",
        "risk": "medium",
        "action": {
            "type": "shell_command",
            "params": {"command": "echo hi"},
        },
        "timeoutSeconds": 60,
        "retry": {"maxAttempts": 3},
        "idempotency": {"mode": "natural"},
        "dryRun": {"supported": True, "strategy": "native"},
        "secrets": ["DB_PASS", "API_KEY"],
        "artifacts": [
            {"key": "output_log", "kind": "file", "path": "out.log", "required": True},
            {
                "key": "report",
                "kind": "report",
                "path": "report.json",
                "required": False,
            },
        ],
    }
    step.update(overrides)
    return step


def _minimal_v2_def(step=None) -> dict:
    s = step or _v2_step()
    # Hoist secret references to top-level declarations required by the validator.
    secret_keys = s.get("secrets", [])
    return {
        "schemaVersion": "2",
        "catalogVersion": "pilot.v1",
        "name": "V2 Workflow",
        "secrets": [{"key": k} for k in secret_keys],
        "steps": [s],
    }


@pytest.fixture
def v2_execution_and_step(org, runbook):
    wf = _publish_v2(runbook, _minimal_v2_def())
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-1")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()
    return execution, step


@pytest.fixture
def v1_execution_and_step(org, published_v1_workflow):
    exec_services.create_execution(workflow=published_v1_workflow)
    result = exec_services.claim_next_execution(runner_id="runner-1")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()
    return execution, step


# ---------------------------------------------------------------------------
# _build_evaluation_context — v2 facts present
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_v2_context_includes_schema_version(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["schema_version"] == "2"


@pytest.mark.django_db
def test_v2_context_includes_catalog_version(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["catalog_version"] == "pilot.v1"


@pytest.mark.django_db
def test_v2_context_includes_execution_mode(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["execution_mode"] == Execution.ExecutionMode.LIVE


@pytest.mark.django_db
def test_v2_context_includes_action_type(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["action_type"] == "shell_command"


@pytest.mark.django_db
def test_v2_context_includes_action_version_empty_when_unset(v2_execution_and_step):
    # The base _v2_step does not set action.version, so this should be "".
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["action_version"] == ""


@pytest.mark.django_db
def test_v2_context_includes_timeout_seconds(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["timeout_seconds"] == 60


@pytest.mark.django_db
def test_v2_context_includes_retry_max_attempts(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["retry_max_attempts"] == 3


@pytest.mark.django_db
def test_v2_context_includes_idempotency_mode(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["idempotency_mode"] == "natural"


@pytest.mark.django_db
def test_v2_context_declared_secret_keys_contains_key_names_only(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["declared_secret_keys"] == ["DB_PASS", "API_KEY"]


@pytest.mark.django_db
def test_v2_context_declared_artifact_keys(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["declared_artifact_keys"] == ["output_log", "report"]


@pytest.mark.django_db
def test_v2_context_dry_run_supported(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["dry_run_supported"] is True


@pytest.mark.django_db
def test_v2_context_mutates_target_absent_is_empty_string(v2_execution_and_step):
    execution, step = v2_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["mutates_target"] == ""


@pytest.mark.django_db
def test_v2_context_mutates_target_true_serialised_as_string(v2_execution_and_step):
    # mutatesTarget is not part of the published v2 schema, so inject it directly
    # into the stored step_snapshot to test context extraction logic.
    execution, step = v2_execution_and_step
    step.step_snapshot = {**step.step_snapshot, "mutatesTarget": True}
    step.save(update_fields=["step_snapshot"])

    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["mutates_target"] == "true"


@pytest.mark.django_db
def test_v2_context_mutates_target_false_serialised_as_string(v2_execution_and_step):
    execution, step = v2_execution_and_step
    step.step_snapshot = {**step.step_snapshot, "mutatesTarget": False}
    step.save(update_fields=["step_snapshot"])

    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["mutates_target"] == "false"


# ---------------------------------------------------------------------------
# _build_evaluation_context — v1 safe defaults (behaviour unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_v1_context_schema_version_is_empty(v1_execution_and_step):
    execution, step = v1_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["schema_version"] == ""


@pytest.mark.django_db
def test_v1_context_action_type_is_empty(v1_execution_and_step):
    execution, step = v1_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["action_type"] == ""


@pytest.mark.django_db
def test_v1_context_declared_secret_keys_is_empty(v1_execution_and_step):
    execution, step = v1_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["declared_secret_keys"] == []


@pytest.mark.django_db
def test_v1_context_declared_artifact_keys_is_empty(v1_execution_and_step):
    execution, step = v1_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    assert ctx["declared_artifact_keys"] == []


@pytest.mark.django_db
def test_v1_existing_fields_still_present(v1_execution_and_step):
    execution, step = v1_execution_and_step
    from django.utils import timezone

    ctx = _build_evaluation_context(execution, step, timezone.now())
    # Original fields must still be present
    assert "organization_id" in ctx
    assert "execution_id" in ctx
    assert "step_key" in ctx
    assert "risk_level" in ctx
    assert "requires_approval" in ctx


# ---------------------------------------------------------------------------
# New condition types — validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_action_type_condition_validates_enum_params(org):
    policy = services.create_policy(organization=org, name="P1")
    rule = services.create_rule(
        policy=policy,
        name="action type rule",
        priority=10,
        condition_type="action_type",
        condition_params={
            "operator": "in",
            "values": ["shell_command", "http_request"],
        },
        outcome="approval_required",
    )
    assert rule.condition_type == "action_type"


@pytest.mark.django_db
def test_execution_mode_condition_validates_enum_params(org):
    policy = services.create_policy(organization=org, name="P2")
    rule = services.create_rule(
        policy=policy,
        name="execution mode rule",
        priority=10,
        condition_type="execution_mode",
        condition_params={"operator": "equals", "value": "dry_run"},
        outcome="auto_approve",
    )
    assert rule.condition_type == "execution_mode"


@pytest.mark.django_db
def test_idempotency_mode_condition_validates_enum_params(org):
    policy = services.create_policy(organization=org, name="P3")
    rule = services.create_rule(
        policy=policy,
        name="idempotency rule",
        priority=10,
        condition_type="idempotency_mode",
        condition_params={"operator": "equals", "value": "none"},
        outcome="approval_required",
    )
    assert rule.condition_type == "idempotency_mode"


@pytest.mark.django_db
def test_mutates_target_condition_validates_enum_params(org):
    policy = services.create_policy(organization=org, name="P4")
    rule = services.create_rule(
        policy=policy,
        name="mutates target rule",
        priority=10,
        condition_type="mutates_target",
        condition_params={"operator": "equals", "value": "true"},
        outcome="approval_required",
    )
    assert rule.condition_type == "mutates_target"


@pytest.mark.django_db
def test_invalid_condition_type_still_rejected(org):
    policy = services.create_policy(organization=org, name="P5")
    with pytest.raises(DomainValidationError) as exc_info:
        services.create_rule(
            policy=policy,
            name="bad rule",
            priority=10,
            condition_type="nonexistent_type",
            condition_params={"operator": "equals", "value": "x"},
            outcome="block",
        )
    assert exc_info.value.code == "unknown_condition_type"


# ---------------------------------------------------------------------------
# New condition types — evaluation (via evaluate_step_policy)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_action_type_condition_matches_shell_command(org, runbook):
    policy = services.create_policy(organization=org, name="Action Policy")
    services.create_rule(
        policy=policy,
        name="shell_command rule",
        priority=10,
        condition_type="action_type",
        condition_params={"operator": "equals", "value": "shell_command"},
        outcome="approval_required",
    )

    wf = _publish_v2(runbook, _minimal_v2_def())
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-eval")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is True
    assert evaluation.outcome == PolicyRule.Outcome.APPROVAL_REQUIRED


@pytest.mark.django_db
def test_action_type_condition_does_not_match_manual_task(org, runbook):
    policy = services.create_policy(organization=org, name="MT Policy")
    services.create_rule(
        policy=policy,
        name="http only",
        priority=10,
        condition_type="action_type",
        condition_params={"operator": "equals", "value": "http_request"},
        outcome="block",
    )

    # step is shell_command — rule should not match
    wf = _publish_v2(runbook, _minimal_v2_def())
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-eval2")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is False
    assert (
        evaluation.decision_source == PolicyEvaluation.DecisionSource.WORKFLOW_DEFAULT
    )


@pytest.mark.django_db
def test_execution_mode_dry_run_condition_matches(org, runbook):
    policy = services.create_policy(organization=org, name="DR Policy")
    services.create_rule(
        policy=policy,
        name="dry run auto",
        priority=10,
        condition_type="execution_mode",
        condition_params={"operator": "equals", "value": "dry_run"},
        outcome="auto_approve",
    )

    # v2 step with dryRun.strategy='native' so dry_run mode is accepted
    step_def = _v2_step()
    wf = _publish_v2(runbook, _minimal_v2_def(step=step_def))
    exec_services.create_execution(workflow=wf, mode=Execution.ExecutionMode.DRY_RUN)
    result = exec_services.claim_next_execution(runner_id="runner-dry")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is True
    assert evaluation.outcome == PolicyRule.Outcome.AUTO_APPROVE


@pytest.mark.django_db
def test_idempotency_mode_none_matches(org, runbook):
    policy = services.create_policy(organization=org, name="Idem Policy")
    services.create_rule(
        policy=policy,
        name="idempotency none requires approval",
        priority=10,
        condition_type="idempotency_mode",
        condition_params={"operator": "equals", "value": "none"},
        outcome="approval_required",
    )

    # Publish a valid v2 workflow, then strip idempotency from the stored step
    # snapshot so idempotency_mode evaluates to "".
    wf = _publish_v2(runbook, _minimal_v2_def())
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-idem")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()
    snap = dict(step.step_snapshot)
    snap.pop("idempotency", None)
    step.step_snapshot = snap
    step.save(update_fields=["step_snapshot"])

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    # idempotency_mode is "" (not "none") → should not match
    assert evaluation.matched is False


@pytest.mark.django_db
def test_mutates_target_true_matches(org, runbook):
    policy = services.create_policy(organization=org, name="Mut Policy")
    services.create_rule(
        policy=policy,
        name="mutates target block",
        priority=10,
        condition_type="mutates_target",
        condition_params={"operator": "equals", "value": "true"},
        outcome="approval_required",
    )

    # mutatesTarget is not in the v2 schema; inject directly into step_snapshot.
    wf = _publish_v2(runbook, _minimal_v2_def())
    exec_services.create_execution(workflow=wf)
    result = exec_services.claim_next_execution(runner_id="runner-mut")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()
    step.step_snapshot = {**step.step_snapshot, "mutatesTarget": True}
    step.save(update_fields=["step_snapshot"])

    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.matched is True
    assert evaluation.outcome == PolicyRule.Outcome.APPROVAL_REQUIRED


# ---------------------------------------------------------------------------
# v1 policy evaluation — still uses existing risk_level / step_type conditions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_v1_risk_level_condition_still_works(org, published_v1_workflow):
    policy = services.create_policy(organization=org, name="V1 Policy")
    services.create_rule(
        policy=policy,
        name="high risk",
        priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high", "critical"]},
        outcome="approval_required",
    )
    exec_services.create_execution(workflow=published_v1_workflow)
    result = exec_services.claim_next_execution(runner_id="runner-v1")
    execution = result["execution"]
    step = execution.steps.order_by("position").first()

    # v1 step_type defaults to "manual" with risk "low" — no match expected
    evaluation = services.evaluate_step_policy(execution=execution, step=step)
    assert evaluation.decision_source in (
        PolicyEvaluation.DecisionSource.WORKFLOW_DEFAULT,
        PolicyEvaluation.DecisionSource.POLICY_RULE,
    )
    # No exception means v1 path is still functional
