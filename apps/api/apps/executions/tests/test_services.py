import pytest

from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Deploy Service", slug="deploy-service", raw_content=""
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow_from_runbook(runbook=runbook)
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def draft_workflow(runbook):
    return workflow_services.create_workflow_from_runbook(runbook=runbook)


@pytest.mark.django_db
def test_create_execution_creates_execution_and_steps(published_workflow):
    execution = services.create_execution_from_workflow(workflow=published_workflow)

    assert execution.status == Execution.Status.QUEUED
    expected_step_count = len(published_workflow.definition["steps"])
    assert ExecutionStep.objects.filter(execution=execution).count() == expected_step_count


@pytest.mark.django_db
def test_create_execution_requires_published_workflow(draft_workflow):
    with pytest.raises(ValueError, match="published"):
        services.create_execution_from_workflow(workflow=draft_workflow)


@pytest.mark.django_db
def test_create_execution_materializes_steps_in_order(published_workflow):
    execution = services.create_execution_from_workflow(workflow=published_workflow)
    steps = list(execution.steps.order_by("position"))

    positions = [s.position for s in steps]
    assert positions == list(range(1, len(steps) + 1))

    expected_names = [s["name"] for s in published_workflow.definition["steps"]]
    assert [s.name for s in steps] == expected_names


@pytest.mark.django_db
def test_create_execution_is_atomic(published_workflow, monkeypatch):
    original_create = ExecutionStep.objects.create
    calls = []

    def fail_on_second(**kwargs):
        calls.append(1)
        if len(calls) >= 2:
            raise RuntimeError("forced mid-creation failure")
        return original_create(**kwargs)

    monkeypatch.setattr(ExecutionStep.objects, "create", fail_on_second)

    with pytest.raises(RuntimeError):
        services.create_execution_from_workflow(workflow=published_workflow)

    assert Execution.objects.count() == 0


@pytest.mark.django_db
def test_cancel_execution_transitions_to_cancelled(published_workflow):
    execution = services.create_execution_from_workflow(workflow=published_workflow)
    cancelled = services.cancel_execution(execution=execution)
    assert cancelled.status == Execution.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_non_queued_execution_raises(published_workflow):
    execution = services.create_execution_from_workflow(workflow=published_workflow)
    services.cancel_execution(execution=execution)
    with pytest.raises(ValueError, match="queued"):
        services.cancel_execution(execution=execution)
