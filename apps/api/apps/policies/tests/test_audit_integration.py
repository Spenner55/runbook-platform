import pytest

from apps.audit.models import AuditEvent
from apps.executions import services as execution_services
from apps.policies import services as policy_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def execution_and_step(org):
    runbook = runbook_services.create_runbook(
        organization=org,
        title="Policy Audit",
        slug="policy-audit",
        raw_content="Deploy\nVerify",
    )
    workflow = workflow_services.publish_workflow(
        workflow=workflow_services.create_workflow(
            runbook=runbook, transform_client=StubWorkflowTransformClient()
        )
    )
    execution = execution_services.create_execution(workflow=workflow)
    return execution, execution.steps.order_by("position").first()


@pytest.mark.django_db
def test_policy_crud_and_evaluation_emit_audit_events(org, execution_and_step):
    execution, step = execution_and_step
    policy = policy_services.create_policy(organization=org, name="Safety")
    rule = policy_services.create_rule(
        policy=policy,
        name="High risk",
        priority=10,
        condition_type="risk_level",
        condition_params={"operator": "in", "values": ["high"]},
        outcome="approval_required",
    )
    policy_services.update_policy(policy=policy, description="Updated")
    policy_services.deactivate_rule(rule=rule)
    evaluation = policy_services.evaluate_step_policy(execution=execution, step=step)

    event_types = set(AuditEvent.objects.values_list("event_type", flat=True))
    assert {
        "policy.created",
        "policy_rule.created",
        "policy.updated",
        "policy_rule.deactivated",
        "policy.evaluated",
    }.issubset(event_types)

    evaluation_event = AuditEvent.objects.get(
        event_type="policy.evaluated", object_id=evaluation.id
    )
    assert evaluation_event.metadata["execution_id"] == str(execution.id)
    assert "condition_params" not in evaluation_event.metadata
