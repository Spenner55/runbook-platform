import pytest
from unittest.mock import patch

from apps.runbooks import services as runbook_services
from apps.workflows import services
from apps.workflows.internal_clients import WorkflowCandidate, WorkflowCandidateStep
from apps.workflows.models import Workflow


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Deploy Service", slug="deploy-service", raw_content=""
    )


def _make_candidate(title: str = "Deploy Service") -> WorkflowCandidate:
    """Return a minimal valid WorkflowCandidate for service tests."""
    return WorkflowCandidate(
        request_id="test-req-id",
        workflow_title=title,
        steps=[
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
        ],
    )


@pytest.fixture(autouse=True)
def mock_ai_client():
    """Prevent tests from making real HTTP calls to the AI service."""
    with patch(
        "apps.workflows.services.parse_runbook_to_workflow_candidate",
        return_value=_make_candidate(),
    ) as mock:
        yield mock


@pytest.mark.django_db
def test_create_workflow_assigns_version_1(runbook):
    workflow = services.create_workflow_from_runbook(runbook=runbook)
    assert workflow.version == 1


@pytest.mark.django_db
def test_create_workflow_increments_version(runbook):
    v1 = services.create_workflow_from_runbook(runbook=runbook)
    v2 = services.create_workflow_from_runbook(runbook=runbook)
    assert v1.version == 1
    assert v2.version == 2


@pytest.mark.django_db
def test_create_workflow_creates_definition(runbook):
    workflow = services.create_workflow_from_runbook(runbook=runbook)
    assert workflow.definition is not None
    assert "steps" in workflow.definition
    assert len(workflow.definition["steps"]) > 0
    assert workflow.status == Workflow.Status.DRAFT
    assert workflow.name == runbook.title


@pytest.mark.django_db
def test_publish_workflow_transitions_status(runbook):
    workflow = services.create_workflow_from_runbook(runbook=runbook)
    published = services.publish_workflow(workflow=workflow)
    assert published.status == Workflow.Status.PUBLISHED


@pytest.mark.django_db
def test_publish_workflow_rejects_non_draft(runbook):
    workflow = services.create_workflow_from_runbook(runbook=runbook)
    services.publish_workflow(workflow=workflow)
    with pytest.raises(ValueError, match="draft"):
        services.publish_workflow(workflow=workflow)


@pytest.mark.django_db
def test_ai_failure_does_not_create_partial_workflow(runbook):
    """If the AI client raises, no Workflow row should be persisted."""
    from apps.workflows.internal_clients import AiServiceUnavailableError

    with patch(
        "apps.workflows.services.parse_runbook_to_workflow_candidate",
        side_effect=AiServiceUnavailableError("service down"),
    ):
        with pytest.raises(AiServiceUnavailableError):
            services.create_workflow_from_runbook(runbook=runbook)

    assert Workflow.objects.filter(runbook=runbook).count() == 0


@pytest.mark.django_db
def test_ai_client_called_with_runbook_data(runbook, mock_ai_client):
    """Verify the AI client receives the correct runbook fields."""
    services.create_workflow_from_runbook(runbook=runbook)
    mock_ai_client.assert_called_once()
    call_kwargs = mock_ai_client.call_args.kwargs
    assert call_kwargs["runbook_id"] == str(runbook.id)
    assert call_kwargs["runbook_title"] == runbook.title
    assert call_kwargs["raw_content"] == runbook.raw_content


@pytest.mark.django_db
def test_definition_maps_candidate_fields(runbook, mock_ai_client):
    """Candidate fields must be mapped to the canonical definition shape."""
    workflow = services.create_workflow_from_runbook(runbook=runbook)
    step = workflow.definition["steps"][0]
    assert step["id"] == "step-1"
    assert step["type"] == "manual"
    assert step["risk"] == "low"
    assert "requiresApproval" in step
