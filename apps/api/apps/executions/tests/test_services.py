import pytest
from unittest.mock import patch

from apps.common.exceptions import DomainValidationError, InvalidStateTransitionError, InvalidWorkflowDefinitionError
from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Deploy Service",
        slug="deploy-service",
        raw_content="Verify prerequisites\nExecute deployment",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow_from_runbook(runbook=runbook)
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def draft_workflow(runbook):
    return workflow_services.create_workflow_from_runbook(runbook=runbook)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_execution_creates_execution_row(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    assert Execution.objects.filter(pk=execution.pk).exists()
    assert execution.status == Execution.Status.QUEUED


@pytest.mark.django_db
def test_create_execution_creates_correct_step_count(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    expected = len(published_workflow.definition["steps"])
    assert ExecutionStep.objects.filter(execution=execution).count() == expected


@pytest.mark.django_db
def test_create_execution_materializes_steps_in_order(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    steps = list(execution.steps.order_by("position"))

    assert [s.position for s in steps] == list(range(1, len(steps) + 1))
    expected_names = [s["name"] for s in published_workflow.definition["steps"]]
    assert [s.name for s in steps] == expected_names


# ---------------------------------------------------------------------------
# Immutable snapshot copy
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_execution_copies_workflow_version(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    assert execution.workflow_version == published_workflow.version


@pytest.mark.django_db
def test_create_execution_copies_workflow_snapshot(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    assert execution.workflow_snapshot == published_workflow.definition


@pytest.mark.django_db
def test_create_execution_step_snapshot_matches_definition_step(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    first_step = execution.steps.order_by("position").first()
    expected_step = published_workflow.definition["steps"][0]
    assert first_step.step_snapshot == expected_step


@pytest.mark.django_db
def test_create_execution_step_fields_copied_from_definition(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    step = execution.steps.order_by("position").first()
    definition_step = published_workflow.definition["steps"][0]
    assert step.step_key == definition_step["id"]
    assert step.name == definition_step["name"]


# ---------------------------------------------------------------------------
# Status gate
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_execution_requires_published_workflow(draft_workflow):
    with pytest.raises(DomainValidationError) as exc_info:
        services.create_execution(workflow=draft_workflow)
    assert exc_info.value.code == "workflow_not_published"


# ---------------------------------------------------------------------------
# Definition validation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_execution_rejects_empty_steps(published_workflow):
    published_workflow.definition = {"steps": []}
    published_workflow.save(update_fields=["definition"])
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        services.create_execution(workflow=published_workflow)
    assert exc_info.value.code == "workflow_has_no_steps"


@pytest.mark.django_db
def test_create_execution_rejects_missing_steps_key(published_workflow):
    published_workflow.definition = {"name": "No steps here"}
    published_workflow.save(update_fields=["definition"])
    with pytest.raises(InvalidWorkflowDefinitionError):
        services.create_execution(workflow=published_workflow)


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_execution_is_atomic(published_workflow):
    with patch(
        "apps.executions.services.ExecutionStep.objects.bulk_create",
        side_effect=RuntimeError("forced bulk_create failure"),
    ):
        with pytest.raises(RuntimeError):
            services.create_execution(workflow=published_workflow)

    assert Execution.objects.count() == 0


# ---------------------------------------------------------------------------
# cancel_execution (runner-adjacent, ValueError by design)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_cancel_execution_transitions_to_cancelled(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    cancelled = services.cancel_execution(execution=execution)
    assert cancelled.status == Execution.Status.CANCELLED


@pytest.mark.django_db
def test_cancel_non_queued_execution_raises(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    services.cancel_execution(execution=execution)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.cancel_execution(execution=execution)
    assert exc_info.value.code == "invalid_state_transition"
