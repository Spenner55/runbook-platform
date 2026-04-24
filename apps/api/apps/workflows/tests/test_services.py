import pytest
from django.db import IntegrityError
from unittest.mock import MagicMock, patch

from apps.common.exceptions import ConcurrencyConflictError, InvalidStateTransitionError, InvalidWorkflowDefinitionError
from apps.runbooks import services as runbook_services
from apps.workflows import services
from apps.workflows.internal_clients import (
    StubWorkflowTransformClient,
    WorkflowCandidate,
    WorkflowCandidateStep,
)
from apps.workflows.models import Workflow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub():
    return StubWorkflowTransformClient()


def _fixed_client(candidate: WorkflowCandidate):
    """Return a transform client that always returns the given candidate."""
    mock = MagicMock()
    mock.transform_runbook.return_value = candidate
    return mock


def _candidate(steps=None, title="Deploy Service"):
    if steps is None:
        steps = [
            WorkflowCandidateStep(
                step_key="step-1",
                name="Verify prerequisites",
                step_type="manual",
                risk_level="low",
                requires_approval=False,
            ),
            WorkflowCandidateStep(
                step_key="step-2",
                name="Execute main task",
                step_type="manual",
                risk_level="medium",
                requires_approval=False,
            ),
        ]
    return WorkflowCandidate(request_id="test", workflow_title=title, steps=steps)


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Deploy Service", slug="deploy-service", raw_content="Do step one"
    )


# ---------------------------------------------------------------------------
# Version assignment
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_workflow_assigns_version_1(runbook):
    workflow = services.create_workflow(runbook=runbook, transform_client=_stub())
    assert workflow.version == 1


@pytest.mark.django_db
def test_create_workflow_increments_version(runbook):
    v1 = services.create_workflow(runbook=runbook, transform_client=_stub())
    v2 = services.create_workflow(runbook=runbook, transform_client=_stub())
    assert v1.version == 1
    assert v2.version == 2


@pytest.mark.django_db
def test_create_workflow_versions_are_independent_per_runbook(org):
    rb1 = runbook_services.create_runbook(
        organization=org, title="RB1", slug="rb1", raw_content="step"
    )
    rb2 = runbook_services.create_runbook(
        organization=org, title="RB2", slug="rb2", raw_content="step"
    )
    wf1 = services.create_workflow(runbook=rb1, transform_client=_stub())
    wf2 = services.create_workflow(runbook=rb2, transform_client=_stub())
    assert wf1.version == 1
    assert wf2.version == 1


# ---------------------------------------------------------------------------
# Definition and status
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_workflow_status_is_draft(runbook):
    workflow = services.create_workflow(runbook=runbook, transform_client=_stub())
    assert workflow.status == Workflow.Status.DRAFT


@pytest.mark.django_db
def test_create_workflow_name_matches_runbook_title(runbook):
    workflow = services.create_workflow(runbook=runbook, transform_client=_stub())
    assert workflow.name == runbook.title


@pytest.mark.django_db
def test_create_workflow_definition_has_steps(runbook):
    workflow = services.create_workflow(runbook=runbook, transform_client=_stub())
    assert "steps" in workflow.definition
    assert len(workflow.definition["steps"]) > 0


@pytest.mark.django_db
def test_definition_maps_candidate_fields(runbook):
    """Candidate step fields must be mapped to the canonical definition shape."""
    client = _fixed_client(_candidate())
    workflow = services.create_workflow(runbook=runbook, transform_client=client)
    step = workflow.definition["steps"][0]
    assert step["id"] == "step-1"
    assert step["name"] == "Verify prerequisites"
    assert step["type"] == "manual"
    assert step["risk"] == "low"
    assert "requiresApproval" in step


# ---------------------------------------------------------------------------
# Transform client boundary
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_transform_client_receives_correct_runbook_fields(runbook):
    client = _fixed_client(_candidate())
    services.create_workflow(runbook=runbook, transform_client=client)
    client.transform_runbook.assert_called_once_with(
        runbook_title=runbook.title,
        runbook_slug=runbook.slug,
        raw_content=runbook.raw_content,
    )


@pytest.mark.django_db
def test_transform_failure_leaves_no_workflow_row(runbook):
    """If the transform client raises, no Workflow row must be persisted."""
    client = MagicMock()
    client.transform_runbook.side_effect = RuntimeError("transform failed")

    with pytest.raises(RuntimeError):
        services.create_workflow(runbook=runbook, transform_client=client)

    assert Workflow.objects.filter(runbook=runbook).count() == 0


# ---------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_empty_steps_raises_invalid_definition_error(runbook):
    client = _fixed_client(_candidate(steps=[]))
    with pytest.raises(InvalidWorkflowDefinitionError) as exc_info:
        services.create_workflow(runbook=runbook, transform_client=client)
    assert exc_info.value.code == "invalid_workflow_definition"


@pytest.mark.django_db
def test_duplicate_step_key_raises_invalid_definition_error(runbook):
    steps = [
        WorkflowCandidateStep(step_key="dup", name="Step A", step_type="manual", risk_level="low", requires_approval=False),
        WorkflowCandidateStep(step_key="dup", name="Step B", step_type="manual", risk_level="low", requires_approval=False),
    ]
    client = _fixed_client(_candidate(steps=steps))
    with pytest.raises(InvalidWorkflowDefinitionError):
        services.create_workflow(runbook=runbook, transform_client=client)


@pytest.mark.django_db
def test_step_missing_name_raises_invalid_definition_error(runbook):
    steps = [
        WorkflowCandidateStep(step_key="s1", name="", step_type="manual", risk_level="low", requires_approval=False),
    ]
    client = _fixed_client(_candidate(steps=steps))
    with pytest.raises(InvalidWorkflowDefinitionError):
        services.create_workflow(runbook=runbook, transform_client=client)


# ---------------------------------------------------------------------------
# Version conflict
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_version_conflict_raises_concurrency_error(runbook):
    with patch(
        "apps.workflows.services.Workflow.objects.create",
        side_effect=IntegrityError("unique constraint"),
    ):
        with pytest.raises(ConcurrencyConflictError) as exc_info:
            services.create_workflow(runbook=runbook, transform_client=_stub())
    assert exc_info.value.code == "workflow_version_conflict"


# ---------------------------------------------------------------------------
# publish_workflow
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_publish_workflow_transitions_status(runbook):
    workflow = services.create_workflow(runbook=runbook, transform_client=_stub())
    published = services.publish_workflow(workflow=workflow)
    assert published.status == Workflow.Status.PUBLISHED


@pytest.mark.django_db
def test_publish_workflow_rejects_non_draft(runbook):
    workflow = services.create_workflow(runbook=runbook, transform_client=_stub())
    services.publish_workflow(workflow=workflow)
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.publish_workflow(workflow=workflow)
    assert exc_info.value.code == "invalid_state_transition"


# ---------------------------------------------------------------------------
# create_workflow_from_runbook — AI boundary wiring
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_create_workflow_from_runbook_uses_http_client(runbook):
    """create_workflow_from_runbook must go through HttpWorkflowTransformClient, not the stub."""
    from unittest.mock import MagicMock, patch
    from apps.workflows.internal_clients import HttpWorkflowTransformClient, WorkflowCandidate, WorkflowCandidateStep

    fake_candidate = WorkflowCandidate(
        request_id="req-test",
        workflow_title="Deploy Service",
        steps=[
            WorkflowCandidateStep(
                step_key="step-001",
                name="Verify prerequisites",
                step_type="manual_task",
                risk_level="low",
                requires_approval=False,
            ),
        ],
    )
    mock_http_client = MagicMock(spec=HttpWorkflowTransformClient)
    mock_http_client.transform_runbook.return_value = fake_candidate

    with patch.object(HttpWorkflowTransformClient, "from_settings", return_value=mock_http_client):
        workflow = services.create_workflow_from_runbook(runbook=runbook)

    assert workflow.version == 1
    assert workflow.status == Workflow.Status.DRAFT
    mock_http_client.transform_runbook.assert_called_once_with(
        runbook_title=runbook.title,
        runbook_slug=runbook.slug,
        raw_content=runbook.raw_content,
    )
