from unittest.mock import patch

import pytest

from apps.common.exceptions import (
    DomainValidationError,
    InvalidStateTransitionError,
    InvalidWorkflowDefinitionError,
)
from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


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
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def draft_workflow(runbook):
    return workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )


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


# ---------------------------------------------------------------------------
# Integration notifications
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_execution_completion_triggers_notify(published_workflow):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]

    with patch("apps.executions.services.IntegrationService.notify") as notify:
        completed = services.complete_execution(
            execution=execution,
            runner_id="runner-1",
            claim_token=claimed["claim_token"],
            outcome=Execution.Status.SUCCEEDED,
        )

    notify.assert_called_once()
    kwargs = notify.call_args.kwargs
    assert kwargs["event_type"] == "execution.completed"
    assert kwargs["organization"] == completed.organization
    assert kwargs["context"]["event_type"] == "execution.completed"
    assert kwargs["context"]["execution_id"] == str(completed.id)
    assert kwargs["context"]["workflow_id"] == str(completed.workflow_id)


@pytest.mark.django_db
def test_execution_failure_triggers_notify_and_excludes_secrets_and_output(
    published_workflow,
):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]

    with patch("apps.executions.services.IntegrationService.notify") as notify:
        failed = services.complete_execution(
            execution=execution,
            runner_id="runner-1",
            claim_token=claimed["claim_token"],
            outcome=Execution.Status.FAILED,
        )

    kwargs = notify.call_args.kwargs
    assert kwargs["event_type"] == "execution.failed"
    assert kwargs["context"]["event_type"] == "execution.failed"
    assert kwargs["context"]["execution_id"] == str(failed.id)
    payload_text = str(kwargs["context"])
    assert str(claimed["claim_token"]) not in payload_text
    assert "raw_output" not in payload_text
    assert "command" not in payload_text


@pytest.mark.django_db
def test_notify_failure_does_not_fail_execution_completion(published_workflow):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]

    with patch(
        "apps.executions.services.IntegrationService.notify",
        side_effect=RuntimeError("dispatch unavailable"),
    ):
        completed = services.complete_execution(
            execution=execution,
            runner_id="runner-1",
            claim_token=claimed["claim_token"],
            outcome=Execution.Status.SUCCEEDED,
        )

    completed.refresh_from_db()
    assert completed.status == Execution.Status.SUCCEEDED


@pytest.mark.django_db
def test_step_failure_triggers_notify_with_step_identifiers(published_workflow):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]
    step = execution.steps.order_by("position").first()

    with patch("apps.executions.services.IntegrationService.notify") as notify:
        updated = services.update_execution_step(
            execution=execution,
            step_id=str(step.id),
            runner_id="runner-1",
            claim_token=claimed["claim_token"],
            new_status=ExecutionStep.Status.FAILED,
            error_message="raw output should stay out",
        )

    kwargs = notify.call_args.kwargs
    assert kwargs["event_type"] == "execution_step.failed"
    assert kwargs["context"]["event_type"] == "execution_step.failed"
    assert kwargs["context"]["execution_id"] == str(execution.id)
    assert kwargs["context"]["step_id"] == str(updated.id)
    assert "raw output should stay out" not in str(kwargs["context"])
