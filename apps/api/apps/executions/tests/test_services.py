from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from prometheus_client import REGISTRY

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
    before = (
        REGISTRY.get_sample_value(
            "runbook_executions_total",
            {"event": "created", "status": Execution.Status.QUEUED},
        )
        or 0
    )

    execution = services.create_execution(workflow=published_workflow)

    assert Execution.objects.filter(pk=execution.pk).exists()
    assert execution.status == Execution.Status.QUEUED
    after = REGISTRY.get_sample_value(
        "runbook_executions_total",
        {"event": "created", "status": Execution.Status.QUEUED},
    )
    assert after > before


@pytest.mark.django_db
def test_create_execution_creates_correct_step_count(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    expected = len(published_workflow.definition["steps"])
    assert ExecutionStep.objects.filter(execution=execution).count() == expected


@pytest.mark.django_db
def test_terminal_step_update_records_step_duration_metric(published_workflow):
    execution = services.create_execution(workflow=published_workflow)
    claim = services.claim_next_execution(runner_id="runner-1")
    assert claim is not None
    claim_token = claim["claim_token"]
    step = execution.steps.order_by("position").first()
    labels = {
        "step_type": step.step_type or "unknown",
        "risk_level": step.risk_level or "unknown",
        "outcome": ExecutionStep.Status.SUCCEEDED,
    }
    before = (
        REGISTRY.get_sample_value("runbook_step_duration_seconds_count", labels) or 0
    )

    started_at = timezone.now() - timedelta(seconds=2)
    services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-1",
        claim_token=claim_token,
        new_status=ExecutionStep.Status.RUNNING,
        started_at=started_at,
        _allow_running=True,
    )
    services.update_execution_step(
        execution=execution,
        step_id=str(step.id),
        runner_id="runner-1",
        claim_token=claim_token,
        new_status=ExecutionStep.Status.SUCCEEDED,
        finished_at=timezone.now(),
    )

    after = REGISTRY.get_sample_value("runbook_step_duration_seconds_count", labels)
    assert after > before


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


@pytest.mark.django_db
def test_create_execution_rejects_requires_review_workflow(draft_workflow):
    draft_workflow.status = "published"
    draft_workflow.requires_review = True
    draft_workflow.save(update_fields=["status", "requires_review", "updated_at"])

    with pytest.raises(DomainValidationError) as exc_info:
        services.create_execution(workflow=draft_workflow)
    assert exc_info.value.code == "workflow_requires_review"


@pytest.mark.django_db
def test_rejected_review_workflow_cannot_be_executed(draft_workflow):
    draft_workflow.requires_review = True
    draft_workflow.parse_source = "ai_parse"
    draft_workflow.save(update_fields=["requires_review", "parse_source", "updated_at"])
    workflow_services.reject_review(workflow=draft_workflow)

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
def test_execution_completion_triggers_notify(
    published_workflow, django_capture_on_commit_callbacks
):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]

    with patch("apps.executions.services.IntegrationService.notify") as notify:
        with django_capture_on_commit_callbacks(execute=True):
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
    assert kwargs["context"]["workflow_name"] == completed.workflow_snapshot["name"]


@pytest.mark.django_db
def test_execution_failure_triggers_notify_and_excludes_secrets_and_output(
    published_workflow, django_capture_on_commit_callbacks
):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]

    with patch("apps.executions.services.IntegrationService.notify") as notify:
        with django_capture_on_commit_callbacks(execute=True):
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
    assert kwargs["context"]["workflow_name"] == failed.workflow_snapshot["name"]
    payload_text = str(kwargs["context"])
    assert str(claimed["claim_token"]) not in payload_text
    assert "raw_output" not in payload_text
    assert "command" not in payload_text


@pytest.mark.django_db
def test_notify_failure_does_not_fail_execution_completion(
    published_workflow, django_capture_on_commit_callbacks
):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]

    with patch(
        "apps.executions.services.IntegrationService.notify",
        side_effect=RuntimeError("dispatch unavailable"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            completed = services.complete_execution(
                execution=execution,
                runner_id="runner-1",
                claim_token=claimed["claim_token"],
                outcome=Execution.Status.SUCCEEDED,
            )

    completed.refresh_from_db()
    assert completed.status == Execution.Status.SUCCEEDED


@pytest.mark.django_db
def test_step_failure_triggers_notify_with_step_identifiers(
    published_workflow, django_capture_on_commit_callbacks
):
    services.create_execution(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    execution = claimed["execution"]
    step = execution.steps.order_by("position").first()

    with patch("apps.executions.services.IntegrationService.notify") as notify:
        with django_capture_on_commit_callbacks(execute=True):
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
    assert kwargs["context"]["step_name"] == updated.name
    assert kwargs["context"]["step_position"] == updated.position
    assert "raw output should stay out" not in str(kwargs["context"])


# ---------------------------------------------------------------------------
# B5: complete_execution re-raises hook failure for change-bound executions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_complete_execution_reraises_hook_failure_for_change_bound(
    monkeypatch, published_workflow
):
    """If the change completion hook fails, complete_execution must re-raise for change-bound executions."""
    from unittest.mock import MagicMock, patch

    from apps.executions import services as execution_services

    _ = execution_services.create_execution(workflow=published_workflow)
    result = execution_services.claim_next_execution(runner_id="runner-b5-test")
    assert result is not None
    claimed = result["execution"]
    claim_token = result["claim_token"]

    def failing_hook(*args, **kwargs):
        raise RuntimeError("simulated hook failure")

    monkeypatch.setattr(
        "apps.changes.services.handle_bound_execution_completed",
        failing_hook,
    )

    # Make the ChangeExecutionBinding queryset report this execution as change-bound
    mock_qs = MagicMock()
    mock_qs.exists.return_value = True
    mock_filter = MagicMock(return_value=mock_qs)

    with patch("apps.changes.models.ChangeExecutionBinding.objects.filter", mock_filter):
        with pytest.raises(RuntimeError, match="simulated hook failure"):
            execution_services.complete_execution(
                execution=claimed,
                runner_id="runner-b5-test",
                claim_token=str(claim_token),
                outcome="succeeded",
            )


@pytest.mark.django_db
def test_complete_execution_swallows_hook_failure_for_non_change_execution(
    monkeypatch, published_workflow
):
    """For non-change-bound executions, hook failure must still be swallowed."""
    from apps.executions import services as execution_services

    _ = execution_services.create_execution(workflow=published_workflow)
    result = execution_services.claim_next_execution(runner_id="runner-nc-test")
    assert result is not None
    claim_token = result["claim_token"]
    claimed = result["execution"]

    def failing_hook(*args, **kwargs):
        raise RuntimeError("non-change hook failure")

    monkeypatch.setattr(
        "apps.changes.services.handle_bound_execution_completed",
        failing_hook,
    )

    result_exec = execution_services.complete_execution(
        execution=claimed,
        runner_id="runner-nc-test",
        claim_token=str(claim_token),
        outcome="succeeded",
    )
    assert result_exec.status == "succeeded"
