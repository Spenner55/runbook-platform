"""Tests for ExecutionLease lifecycle: release on complete, expiry on watchdog recovery."""

import pytest
from django.utils import timezone

from apps.executions.models import Execution
from apps.executions.services import (
    complete_execution,
    recover_stuck_executions,
)
from apps.runners.models import ExecutionLease
from apps.runners.scheduling import schedule_execution_claim
from apps.runners.tests.conftest import make_runner


def _published_workflow(org):
    from apps.runbooks import services as rb_services
    from apps.workflows import services as wf_services
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    rb = rb_services.create_runbook(
        organization=org, title="LT", slug=f"lt-{org.slug}", raw_content="step"
    )
    wf = wf_services.create_workflow(
        runbook=rb, transform_client=StubWorkflowTransformClient()
    )
    return wf_services.publish_workflow(workflow=wf)


def _make_execution(org, workflow):
    from apps.executions.services import create_execution

    return create_execution(workflow=workflow, _from_change_service=True)


@pytest.mark.django_db(transaction=True)
class TestLeaseReleasedOnComplete:
    def test_complete_execution_releases_lease(self, org, pool):
        runner = make_runner(pool)
        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = schedule_execution_claim(runner)
        assert result is not None
        execution = result["execution"]
        claim_token = result["claim_token"]

        lease = ExecutionLease.objects.get(execution=execution)
        assert lease.status == ExecutionLease.Status.ACTIVE

        complete_execution(
            execution=execution,
            runner_id=str(runner.id),
            claim_token=claim_token,
            outcome=Execution.Status.SUCCEEDED,
        )

        lease.refresh_from_db()
        assert lease.status == ExecutionLease.Status.RELEASED
        assert lease.release_reason == Execution.Status.SUCCEEDED


@pytest.mark.django_db(transaction=True)
class TestLeaseExpiredOnWatchdog:
    def test_watchdog_expires_lease(self, org, pool):
        runner = make_runner(pool)
        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = schedule_execution_claim(runner)
        execution = result["execution"]

        # Backdate heartbeat so it appears stuck
        execution.last_heartbeat_at = timezone.now() - timezone.timedelta(seconds=700)
        execution.save(update_fields=["last_heartbeat_at"])
        # Also backdate the lease
        ExecutionLease.objects.filter(execution=execution).update(
            last_heartbeat_at=timezone.now() - timezone.timedelta(seconds=700)
        )

        recovered = recover_stuck_executions(stuck_threshold_seconds=300)
        assert str(execution.id) in recovered

        lease = ExecutionLease.objects.get(execution=execution)
        assert lease.status == ExecutionLease.Status.EXPIRED
        assert lease.release_reason == "heartbeat_timeout"
