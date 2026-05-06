import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.audit.services import AuditActor
from apps.changes import services as change_services
from apps.changes.models import OperationProfile
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
        verification_plan_template={
            "checks": [
                {
                    "key": "runner-health-check",
                    "name": "Runner health check completed",
                    "type": "runner_step",
                    "required": True,
                    "source_step_key": "health-check",
                    "verification_key": "postdeploy.health.ok",
                }
            ]
        },
        approval_ttl_seconds=3600,
        dispatch_ttl_seconds=900,
        allowed_target_types=["server"],
    )
    profile.allowed_workflows.add(published_workflow)
    return profile


@pytest.fixture
def org_factory():
    from apps.organizations.models import Organization

    def _make(slug):
        return Organization.objects.create(name=slug, slug=slug)

    return _make


@pytest.fixture
def org_user(org, db):
    from apps.users.models import User

    return User.objects.create_user(
        email="org-user@example.com",
        password="s3cr3tpass!",
    )


@pytest.fixture
def draft_change(org, operation_profile, published_workflow):
    # Create via service directly to avoid HTTP overhead in non-API tests
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
