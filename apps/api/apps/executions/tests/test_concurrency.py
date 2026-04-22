import pytest

from apps.executions import services
from apps.executions.models import Execution
from apps.runbooks import services as runbook_services
from apps.workflows import services as workflow_services


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Claim Test", slug="claim-test", raw_content=""
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow_from_runbook(runbook=runbook)
    return workflow_services.publish_workflow(workflow=wf)


@pytest.mark.django_db(transaction=True)
def test_claim_next_returns_execution_and_marks_claimed(published_workflow):
    services.create_execution_from_workflow(workflow=published_workflow)

    result = services.claim_next_execution(runner_id="runner-1")

    assert result is not None
    execution = result["execution"]
    assert execution.status == Execution.Status.CLAIMED
    assert execution.claimed_by_runner_id == "runner-1"
    assert execution.claim_token is not None
    assert "steps" in result


@pytest.mark.django_db(transaction=True)
def test_second_claim_returns_none_when_queue_empty(published_workflow):
    services.create_execution_from_workflow(workflow=published_workflow)

    result1 = services.claim_next_execution(runner_id="runner-1")
    assert result1 is not None

    result2 = services.claim_next_execution(runner_id="runner-2")
    assert result2 is None


@pytest.mark.django_db(transaction=True)
def test_claim_next_returns_none_on_empty_queue(org):
    result = services.claim_next_execution(runner_id="runner-1")
    assert result is None
