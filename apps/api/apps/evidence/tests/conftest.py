import pytest

from apps.changes.models import ChangeRecord, OperationProfile
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def evidence_runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Evidence Test Runbook",
        slug="evidence-test",
        raw_content="Verify evidence foundation",
    )


@pytest.fixture
def evidence_workflow(evidence_runbook):
    workflow = workflow_services.create_workflow(
        runbook=evidence_runbook,
        transform_client=StubWorkflowTransformClient(),
    )
    return workflow_services.publish_workflow(workflow=workflow)


@pytest.fixture
def evidence_operation_profile(org, evidence_workflow):
    profile = OperationProfile.objects.create(
        organization=org,
        key="evidence-profile",
        name="Evidence Profile",
        risk_level="high",
    )
    profile.allowed_workflows.add(evidence_workflow)
    return profile


@pytest.fixture
def evidence_change(org, evidence_operation_profile, evidence_workflow):
    return ChangeRecord.objects.create(
        organization=org,
        operation_profile=evidence_operation_profile,
        workflow=evidence_workflow,
        title="Evidence change",
        summary="Evidence model tests",
        justification="Required for schema validation",
    )
