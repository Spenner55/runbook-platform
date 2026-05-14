"""Tests for pool-aware execution scheduling: concurrency limits, drain mode,
org isolation, concurrent claim safety, and ExecutionLease creation."""

import threading

import pytest
from django.utils import timezone

from apps.common.exceptions import InvalidStateTransitionError
from apps.executions.models import Execution
from apps.executions.services import claim_next_execution
from apps.runners.models import ExecutionLease, Runner, RunnerPool
from apps.runners.scheduling import schedule_execution_claim
from apps.runners.tests.conftest import make_runner
from apps.workflows.models import Workflow


def _make_execution(org, workflow):
    from apps.executions.services import create_execution

    return create_execution(workflow=workflow, _from_change_service=True)


def _published_workflow(org):
    import secrets

    from apps.runbooks import services as rb_services
    from apps.workflows import services as wf_services
    from apps.workflows.internal_clients import StubWorkflowTransformClient

    slug = f"t-{secrets.token_hex(6)}"
    rb = rb_services.create_runbook(
        organization=org, title="T", slug=slug, raw_content="step"
    )
    wf = wf_services.create_workflow(
        runbook=rb, transform_client=StubWorkflowTransformClient()
    )
    return wf_services.publish_workflow(workflow=wf)


@pytest.mark.django_db(transaction=True)
class TestScheduleExecutionClaim:
    def test_active_runner_claims_queued_execution(self, org, pool, runner):
        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = schedule_execution_claim(runner)
        assert result is not None
        assert "execution" in result
        assert result["execution"].status == Execution.Status.CLAIMED
        assert result["execution"].claimed_by_runner_id == str(runner.id)
        assert result["execution"].runner_pool_key == pool.key

    def test_lease_created_atomically(self, org, pool, runner):
        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = schedule_execution_claim(runner)
        lease = ExecutionLease.objects.get(execution=result["execution"])
        assert lease.runner_id == runner.pk
        assert lease.pool_id == pool.pk
        assert lease.status == ExecutionLease.Status.ACTIVE

    def test_no_work_returns_none(self, pool, runner):
        result = schedule_execution_claim(runner)
        assert result is None

    def test_draining_runner_returns_drain(self, pool, runner):
        runner.status = Runner.Status.DRAINING
        runner.save()
        result = schedule_execution_claim(runner)
        assert result == {"drain": True}

    def test_draining_pool_returns_drain(self, org, pool, runner):
        wf = _published_workflow(org)
        _make_execution(org, wf)
        pool.status = "draining"
        pool.save()
        result = schedule_execution_claim(runner)
        assert result == {"drain": True}

    def test_runner_concurrency_limit_returns_none(self, org, pool, runner):
        wf = _published_workflow(org)
        exec1 = _make_execution(org, wf)
        exec2 = _make_execution(org, wf)

        # Manually create an active lease to simulate a running execution
        ExecutionLease.objects.create(
            execution=exec1,
            organization=org,
            runner=runner,
            pool=pool,
            status=ExecutionLease.Status.ACTIVE,
            claimed_at=timezone.now(),
        )

        result = schedule_execution_claim(runner)
        assert result is None  # runner already at limit (1)

    def test_pool_concurrency_limit_returns_none(self, org, pool, pool2):
        pool.max_concurrent_executions = 1
        pool.save()

        wf = _published_workflow(org)
        exec1 = _make_execution(org, wf)
        exec2 = _make_execution(org, wf)

        runner_a = make_runner(pool, fingerprint="fp-a")
        runner_b = make_runner(pool, fingerprint="fp-b")

        ExecutionLease.objects.create(
            execution=exec1,
            organization=org,
            runner=runner_a,
            pool=pool,
            status=ExecutionLease.Status.ACTIVE,
            claimed_at=timezone.now(),
        )

        # runner_b tries to claim — pool is full
        result = schedule_execution_claim(runner_b)
        assert result is None

    def test_org_isolation_different_org_cannot_claim(self, org, org2, pool, other_org_pool, runner):
        """Runner in org2's pool must not claim org's executions."""
        wf = _published_workflow(org)
        _make_execution(org, wf)

        other_runner = make_runner(other_org_pool, fingerprint="fp-other")
        result = schedule_execution_claim(other_runner)
        assert result is None

    def test_disabled_runner_raises(self, pool, runner):
        runner.status = Runner.Status.DISABLED
        runner.save()
        from apps.common.exceptions import InvalidStateTransitionError

        with pytest.raises(InvalidStateTransitionError):
            schedule_execution_claim(runner)

    def test_concurrent_runners_cannot_double_claim(self, org, pool):
        """Two runners racing on the same execution: only one should succeed."""
        wf = _published_workflow(org)
        _make_execution(org, wf)

        runner_a = make_runner(pool, fingerprint="fp-ca")
        runner_b = make_runner(pool, fingerprint="fp-cb")
        pool.max_concurrent_executions = 2
        pool.save()

        results = []
        errors = []

        def claim(r):
            try:
                res = schedule_execution_claim(r)
                results.append(res)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=claim, args=(runner_a,))
        t2 = threading.Thread(target=claim, args=(runner_b,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors
        non_none = [r for r in results if r is not None and "execution" in r]
        # At most one runner should have gotten the execution
        assert len(non_none) <= 1


@pytest.mark.django_db(transaction=True)
class TestScheduleEligibilityGuards:
    """Runner/pool state checks and pool-key eligibility filtering."""

    def test_revoked_runner_raises(self, pool, runner):
        runner.status = Runner.Status.REVOKED
        runner.save()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            schedule_execution_claim(runner)
        assert exc_info.value.code == "runner_not_active"

    def test_offline_runner_raises(self, pool, runner):
        runner.status = Runner.Status.OFFLINE
        runner.save()
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            schedule_execution_claim(runner)
        assert exc_info.value.code == "runner_not_active"

    def test_draining_runner_can_still_heartbeat_existing_execution(
        self, org, pool, runner
    ):
        """Drain signal blocks new claims but leaves active execution updates untouched."""
        from apps.executions.services import claim_next_execution, heartbeat_execution
        from apps.runners.services import generate_runner_token

        _, token_hash = generate_runner_token()
        runner.token_hash = token_hash
        runner.save(update_fields=["token_hash"])

        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = claim_next_execution(runner_id=str(runner.id), runner=runner)
        assert result is not None
        execution = result["execution"]
        claim_token = result["claim_token"]

        runner.status = Runner.Status.DRAINING
        runner.save()
        runner.refresh_from_db()

        # New claim returns drain signal.
        drain_result = schedule_execution_claim(runner)
        assert drain_result == {"drain": True}

        # Heartbeat on the already-owned execution must succeed.
        updated = heartbeat_execution(
            execution=execution,
            runner_id=str(runner.id),
            claim_token=claim_token,
        )
        assert updated.last_heartbeat_at is not None

    def test_non_default_pool_cannot_claim_non_change_when_default_configured(
        self, org, pool
    ):
        """When a default pool is configured in the org, non-default pools skip
        non-change executions."""
        RunnerPool.objects.create(
            organization=org,
            key="default-pool",
            name="Default Pool",
            status=RunnerPool.Status.ACTIVE,
            default_for_non_change_executions=True,
        )
        wf = _published_workflow(org)
        _make_execution(org, wf)

        non_default_runner = make_runner(pool, fingerprint="fp-nd")
        result = schedule_execution_claim(non_default_runner)
        assert result is None

    def test_default_pool_claims_non_change_execution(self, org):
        """The pool marked as default for non-change executions can claim them."""
        default_pool = RunnerPool.objects.create(
            organization=org,
            key="default-pool",
            name="Default Pool",
            status=RunnerPool.Status.ACTIVE,
            default_for_non_change_executions=True,
        )
        wf = _published_workflow(org)
        _make_execution(org, wf)

        default_runner = make_runner(default_pool, fingerprint="fp-def")
        result = schedule_execution_claim(default_runner)
        assert result is not None
        assert "execution" in result
        assert result["execution"].claimed_by_runner_id == str(default_runner.id)

    def test_no_default_configured_any_pool_can_claim(self, org, pool, pool2):
        """Without a configured default pool, any pool may claim non-change executions."""
        wf = _published_workflow(org)
        _make_execution(org, wf)

        runner_b = make_runner(pool2, fingerprint="fp-b2")
        result = schedule_execution_claim(runner_b)
        assert result is not None
        assert "execution" in result

    def test_capability_mismatch_skips_to_next_execution(self, org, pool, runner):
        """When the first queued execution requires capabilities the pool lacks,
        the scheduler skips it and claims the next eligible one."""
        wf_with_caps = _published_workflow(org)
        exec_needs_caps = _make_execution(org, wf_with_caps)
        # Inject an unsatisfied capability requirement into the snapshot.
        exec_needs_caps.workflow_snapshot["requiredCapabilities"] = ["action.exotic"]
        exec_needs_caps.save(update_fields=["workflow_snapshot"])

        wf_plain = _published_workflow(org)
        exec_plain = _make_execution(org, wf_plain)

        result = schedule_execution_claim(runner)
        assert result is not None
        assert result["execution"].id == exec_plain.id


@pytest.mark.django_db
class TestClaimNextExecutionLegacyPath:
    """Ensure the legacy (runner=None) path still works after Batch 3 changes."""

    def test_legacy_claim_works_without_runner_record(self, org, pool, settings):
        settings.RUNNER_LEGACY_TOKEN_MODE = True
        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = claim_next_execution(runner_id="legacy-runner-42")
        assert result is not None
        assert result["execution"].claimed_by_runner_id == "legacy-runner-42"

    def test_legacy_claim_sets_no_pool_key(self, org, pool, settings):
        settings.RUNNER_LEGACY_TOKEN_MODE = True
        wf = _published_workflow(org)
        _make_execution(org, wf)

        result = claim_next_execution(runner_id="legacy-runner-x")
        assert result["execution"].runner_pool_key == ""
