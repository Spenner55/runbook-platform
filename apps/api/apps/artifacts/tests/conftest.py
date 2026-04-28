import io

import pytest

from apps.executions import services as execution_services
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org,
        title="Artifact Test Runbook",
        slug="artifact-test",
        raw_content="Deploy app\nVerify health",
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
    return workflow_services.publish_workflow(workflow=wf)


@pytest.fixture
def queued_execution(published_workflow):
    return execution_services.create_execution(workflow=published_workflow)


@pytest.fixture
def claimed_result(queued_execution):
    """Returns the full claim result dict: {execution, claim_token, steps}."""
    result = execution_services.claim_next_execution(runner_id="runner-test")
    assert result is not None
    return result


@pytest.fixture
def claimed_execution(claimed_result):
    return claimed_result["execution"]


@pytest.fixture
def claim_token(claimed_result):
    return str(claimed_result["claim_token"])


@pytest.fixture
def step(claimed_execution):
    return claimed_execution.steps.first()


@pytest.fixture
def small_file():
    content = b"hello stdout\n"
    f = io.BytesIO(content)
    f.name = "stdout.txt"
    f.size = len(content)
    f.chunks = lambda: [content]
    return f


@pytest.fixture
def artifact_media_root(tmp_path, settings):
    settings.ARTIFACT_MEDIA_ROOT = str(tmp_path / "artifacts")
    return settings.ARTIFACT_MEDIA_ROOT
