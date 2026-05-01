import pytest
from django.test import Client
from rest_framework.test import APIClient

from apps.changes.models import ChangeRecord, OperationProfile
from apps.changes import services as change_services
from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def runner_client():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer test-runner-token")
    return client


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Change Test Runbook",
        slug="change-test",
        raw_content="Run maintenance step",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook,
        transform_client=StubWorkflowTransformClient(),
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def operation_profile(org, published_workflow):
    profile = OperationProfile.objects.create(
        organization=org,
        key="prod-maintenance",
        name="Production Maintenance",
        risk_level="high",
        requires_approval=True,
        verification_required=True,
        approval_ttl_seconds=3600,
        dispatch_ttl_seconds=900,
        allowed_target_types=["server"],
    )
    profile.allowed_workflows.add(published_workflow)
    return profile


@pytest.fixture
def draft_change(org, operation_profile, published_workflow, api_client_for_org):
    client = api_client_for_org(org)
    # Create via service directly to avoid HTTP overhead in non-API tests
    from apps.audit.services import AuditActor
    from apps.audit.models import AuditEvent
    actor = AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label="test")
    return change_services.create_change_record(
        organization=org,
        operation_profile_key="prod-maintenance",
        workflow_id=str(published_workflow.id),
        title="Test Change",
        summary="A test change",
        justification="Required for maintenance",
        requested_inputs={"key": "value"},
        targets=[
            {
                "target_type": "server",
                "target_identifier": "prod-server-01",
                "environment": "production",
            }
        ],
        actor=actor,
    )
