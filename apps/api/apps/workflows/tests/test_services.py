import pytest

from apps.runbooks import services as runbook_services
from apps.workflows import services
from apps.workflows.models import Workflow


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Deploy Service", slug="deploy-service", raw_content=""
    )


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
