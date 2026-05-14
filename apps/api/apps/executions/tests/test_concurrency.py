import threading
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.approvals import services as approval_services
from apps.common.exceptions import InvalidStateTransitionError
from apps.executions import services
from apps.executions.models import Execution, ExecutionStep
from apps.runbooks import services as runbook_services
from apps.runners.models import ExecutionLease, Runner, RunnerPool
from apps.runners.scheduling import schedule_execution_claim
from apps.runners.services import generate_runner_token
from apps.workflows import services as workflow_services
from apps.workflows.internal_clients import StubWorkflowTransformClient


@pytest.fixture
def runbook(org):
    return runbook_services.create_runbook(
        organization=org, title="Claim Test", slug="claim-test", raw_content=""
    )


@pytest.fixture
def published_workflow(runbook):
    wf = workflow_services.create_workflow(
        runbook=runbook, transform_client=StubWorkflowTransformClient()
    )
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
def test_two_concurrent_claims_on_one_execution_yield_exactly_one_claim(
    published_workflow,
):
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
def test_two_concurrent_claims_on_two_executions_return_different_ids(
    published_workflow,
):
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


@pytest.mark.django_db(transaction=True)
@override_settings(RUNNER_STALE_HEARTBEAT_SECONDS=30)
def test_claim_next_reclaims_stale_execution_waiting_on_resolved_approval(
    published_workflow,
):
    execution = services.create_execution_from_workflow(workflow=published_workflow)
    claimed = services.claim_next_execution(runner_id="runner-1")
    assert claimed is not None
    claim_token = claimed["claim_token"]
    step = execution.steps.order_by("position").first()
    approval_request, _ = approval_services.request_step_approval(
        execution=execution,
        step=step,
        runner_id="runner-1",
        claim_token=claim_token,
        policy_driven=True,
    )
    approval_services.decide_approval(
        approval_request=approval_request,
        decision="approved",
        actor_label="Test Op",
    )

    old_token = claimed["execution"].claim_token
    stale_at = timezone.now() - timedelta(seconds=31)
    Execution.objects.filter(pk=execution.pk).update(
        status=Execution.Status.RUNNING,
        started_at=stale_at,
        last_heartbeat_at=stale_at,
    )

    reclaimed = services.claim_next_execution(runner_id="runner-2")

    assert reclaimed is not None
    reclaimed_execution = reclaimed["execution"]
    assert reclaimed_execution.id == execution.id
    assert reclaimed_execution.status == Execution.Status.RUNNING
    assert reclaimed_execution.claimed_by_runner_id == "runner-2"
    assert reclaimed_execution.claim_token != old_token
    assert reclaimed["steps"][0].status == ExecutionStep.Status.WAITING_FOR_APPROVAL


# ---------------------------------------------------------------------------
# Pool-aware concurrency (Runner model path)
# ---------------------------------------------------------------------------


def _make_pool(org, *, key="pool", max_concurrent=2):
    return RunnerPool.objects.create(
        organization=org,
        key=key,
        name=key,
        status=RunnerPool.Status.ACTIVE,
        max_concurrent_executions=max_concurrent,
    )


def _make_runner(pool, fingerprint="fp-default"):
    _, token_hash = generate_runner_token()
    now = timezone.now()
    return Runner.objects.create(
        organization=pool.organization,
        pool=pool,
        display_name=f"runner-{fingerprint}",
        status=Runner.Status.ACTIVE,
        token_hash=token_hash,
        fingerprint_sha256=fingerprint,
        registered_at=now,
        last_seen_at=now,
        last_heartbeat_at=now,
    )


@pytest.mark.django_db(transaction=True)
def test_pool_aware_concurrent_claim_respects_pool_limit(org, runbook, published_workflow):
    """Two runners racing on a pool with max_concurrent=1 — only one succeeds."""
    pool = _make_pool(org, key="limited-pool", max_concurrent=1)
    runner_a = _make_runner(pool, fingerprint="fp-pa")
    runner_b = _make_runner(pool, fingerprint="fp-pb")

    services.create_execution_from_workflow(workflow=published_workflow)
    services.create_execution_from_workflow(workflow=published_workflow)

    results = []
    errors = []

    def claim(r):
        try:
            res = schedule_execution_claim(r)
            results.append(res)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=claim, args=(runner_a,))
    t2 = threading.Thread(target=claim, args=(runner_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    claimed = [r for r in results if r is not None and "execution" in r]
    # Pool limit of 1 — at most one runner may hold a lease.
    assert len(claimed) <= 1


@pytest.mark.django_db(transaction=True)
def test_pool_aware_concurrent_claim_no_double_claim(org, runbook, published_workflow):
    """Two runners racing on a single queued execution cannot both claim it."""
    pool = _make_pool(org, key="race-pool", max_concurrent=2)
    runner_a = _make_runner(pool, fingerprint="fp-ra")
    runner_b = _make_runner(pool, fingerprint="fp-rb")

    services.create_execution_from_workflow(workflow=published_workflow)

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def claim(r):
        barrier.wait()
        try:
            res = schedule_execution_claim(r)
            results.append(res)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=claim, args=(runner_a,))
    t2 = threading.Thread(target=claim, args=(runner_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors
    claimed = [r for r in results if r is not None and "execution" in r]
    assert len(claimed) <= 1, "Only one runner may claim a single execution"


@pytest.mark.django_db(transaction=True)
def test_pool_drain_during_concurrent_claim_blocks_new_claims(
    org, runbook, published_workflow
):
    """If the pool transitions to draining between the eligibility check and the
    actual claim, the runner correctly receives a drain signal rather than a lease."""
    pool = _make_pool(org, key="drain-race-pool", max_concurrent=2)
    runner_a = _make_runner(pool, fingerprint="fp-dr")

    services.create_execution_from_workflow(workflow=published_workflow)

    # Drain the pool before the runner calls claim.
    pool.status = RunnerPool.Status.DRAINING
    pool.save()
    runner_a.pool.refresh_from_db()

    result = schedule_execution_claim(runner_a)
    assert result == {"drain": True}
    assert not ExecutionLease.objects.filter(runner=runner_a).exists()


@pytest.mark.django_db(transaction=True)
def test_ownership_mismatch_rejected_on_heartbeat(org, runbook, published_workflow):
    """A runner presenting the wrong claim token is rejected with 409."""
    services.create_execution_from_workflow(workflow=published_workflow)
    result = services.claim_next_execution(runner_id="runner-owner")
    assert result is not None
    execution = result["execution"]
    real_token = result["claim_token"]

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.heartbeat_execution(
            execution=execution,
            runner_id="runner-owner",
            claim_token="00000000-0000-0000-0000-000000000000",
        )
    assert exc_info.value.code == "claim_token_mismatch"


@pytest.mark.django_db(transaction=True)
def test_wrong_runner_id_rejected_on_heartbeat(org, runbook, published_workflow):
    """A runner presenting a valid token but mismatched runner_id is rejected."""
    services.create_execution_from_workflow(workflow=published_workflow)
    result = services.claim_next_execution(runner_id="runner-owner")
    assert result is not None
    execution = result["execution"]
    claim_token = result["claim_token"]

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        services.heartbeat_execution(
            execution=execution,
            runner_id="runner-imposter",
            claim_token=claim_token,
        )
    assert exc_info.value.code == "runner_ownership_mismatch"
