import threading

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


@pytest.mark.django_db(transaction=True)
def test_claim_next_does_not_claim_non_queued_rows(published_workflow):
    """Executions not in QUEUED status must never be claimed."""
    execution = services.create_execution_from_workflow(workflow=published_workflow)
    # Cancel it so it is no longer queued
    services.cancel_execution(execution=execution)

    result = services.claim_next_execution(runner_id="runner-1")
    assert result is None


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_claims_on_one_execution_yield_exactly_one_claim(published_workflow):
    """
    Two threads racing to claim the same single queued execution must produce
    exactly one claimed result and one no-work result.

    Uses select_for_update(skip_locked=True) to guarantee this. Requires a
    real PostgreSQL transaction per thread (not SQLite) because SQLite does not
    implement skip_locked.
    """
    services.create_execution_from_workflow(workflow=published_workflow)

    results: list = [None, None]
    barrier = threading.Barrier(2)

    def claim(index: int, runner_id: str) -> None:
        barrier.wait()  # both threads start at the same time
        results[index] = services.claim_next_execution(runner_id=runner_id)

    t1 = threading.Thread(target=claim, args=(0, "runner-A"))
    t2 = threading.Thread(target=claim, args=(1, "runner-B"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    claimed = [r for r in results if r is not None]
    empty = [r for r in results if r is None]
    assert len(claimed) == 1, "Exactly one runner should have claimed the execution"
    assert len(empty) == 1, "Exactly one runner should have received no-work"


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_claims_on_two_executions_return_different_ids(published_workflow):
    """Two queued executions can each be independently claimed by different runners."""
    exe1 = services.create_execution_from_workflow(workflow=published_workflow)
    exe2 = services.create_execution_from_workflow(workflow=published_workflow)

    r1 = services.claim_next_execution(runner_id="runner-1")
    r2 = services.claim_next_execution(runner_id="runner-2")

    assert r1 is not None
    assert r2 is not None
    assert r1["execution"].id != r2["execution"].id
    claimed_ids = {r1["execution"].id, r2["execution"].id}
    assert claimed_ids == {exe1.id, exe2.id}
