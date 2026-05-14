import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import InvalidStateTransitionError

logger = logging.getLogger(__name__)


def _execution_eligible_for_pool(execution, pool) -> bool:
    """Return True if this execution can be claimed by pool.

    Non-change executions route to the org's default pool when one is
    configured; if none is configured any pool may claim them.
    Change-backed executions are always considered eligible here — the
    dispatch-expiry check handles their lifecycle separately, and full
    route-matching against a specific pool is deferred to a later phase.
    """
    from apps.changes.models import ChangeExecutionBinding
    from apps.runners.models import RunnerPool

    is_change_bound = ChangeExecutionBinding.objects.filter(
        execution=execution
    ).exists()
    if is_change_bound:
        routed_pool_key = execution.runner_pool_key or ""
        return not routed_pool_key or routed_pool_key == pool.key

    if pool.default_for_non_change_executions:
        return True

    # No default configured on this pool — check whether any pool in the org
    # is the configured default.  If none is, open mode: any pool may claim.
    any_default = RunnerPool.objects.filter(
        organization=pool.organization,
        status=RunnerPool.Status.ACTIVE,
        default_for_non_change_executions=True,
    ).exists()
    return not any_default


@transaction.atomic
def schedule_execution_claim(runner) -> dict | None:
    """Pool-aware execution claim for a registered runner.

    Returns a dict with 'execution', 'steps', 'claim_token', 'lease' if work
    was found; {'drain': True} if the runner/pool is draining; or None if the
    queue is empty or concurrency limits are hit.

    Must be called within a transaction — uses select_for_update to prevent
    double-claims.
    """
    from apps.executions.models import Execution
    from apps.runners.models import ExecutionLease, Runner, RunnerPool

    pool = runner.pool

    if runner.status == Runner.Status.DRAINING:
        return {"drain": True}
    if runner.status not in (Runner.Status.ACTIVE, Runner.Status.REGISTERED):
        raise InvalidStateTransitionError(
            code="runner_not_active",
            detail=f"Runner status '{runner.status}' cannot claim executions.",
        )

    # Re-fetch the pool with a row lock so that concurrent claim attempts on the
    # same pool are serialized.  This ensures the concurrency count checks below
    # are accurate under concurrent load.
    pool = RunnerPool.objects.select_for_update().get(pk=pool.pk)

    if pool.status == RunnerPool.Status.DRAINING:
        return {"drain": True}
    if pool.status != RunnerPool.Status.ACTIVE:
        raise InvalidStateTransitionError(
            code="pool_not_active",
            detail=f"Runner pool '{pool.key}' is not active (status: {pool.status}).",
        )

    # Concurrency checks (all evaluated after pool row is locked).
    runner_active_count = ExecutionLease.objects.filter(
        runner=runner, status=ExecutionLease.Status.ACTIVE
    ).count()
    if runner_active_count >= 1:
        # Pilot: one execution per runner.
        return None

    pool_active_count = ExecutionLease.objects.filter(
        pool=pool, status=ExecutionLease.Status.ACTIVE
    ).count()
    if pool_active_count >= pool.max_concurrent_executions:
        return None

    org_active_count = ExecutionLease.objects.filter(
        organization=runner.organization, status=ExecutionLease.Status.ACTIVE
    ).count()
    org_limit = getattr(settings, "RUNNER_ORG_MAX_CONCURRENT", 5)
    if org_active_count >= org_limit:
        return None

    now = timezone.now()

    from apps.executions.services import _expire_unbound_change_dispatch_if_needed

    # Find the oldest queued execution eligible for this runner's pool.
    # excluded_ids accumulates rows that were ineligible in this iteration so
    # that subsequent fetches advance to the next candidate rather than
    # re-selecting the same row.
    execution = None
    excluded_ids: set = set()
    for _ in range(50):
        candidate = (
            Execution.objects.select_for_update(skip_locked=True)
            .filter(
                status=Execution.Status.QUEUED,
                organization=runner.organization,
            )
            .exclude(pk__in=excluded_ids)
            .order_by("created_at")
            .first()
        )
        if candidate is None:
            break

        if _expire_unbound_change_dispatch_if_needed(candidate, now=now):
            # Row status changed to a terminal state; the next query will
            # naturally skip it without needing it in excluded_ids.
            continue

        if not _execution_eligible_for_pool(candidate, pool):
            excluded_ids.add(candidate.pk)
            continue

        # Capability check: if the workflow snapshot specifies requiredCapabilities,
        # verify the pool supports them all.
        required_caps = candidate.workflow_snapshot.get("requiredCapabilities", [])
        if required_caps:
            pool_caps = set(pool.capabilities or [])
            missing = [c for c in required_caps if c not in pool_caps]
            if missing:
                logger.debug(
                    "Skipping execution %s — pool missing capabilities: %s",
                    candidate.id,
                    missing,
                )
                excluded_ids.add(candidate.pk)
                continue

        execution = candidate
        break

    if execution is None:
        return None

    claim_token = uuid.uuid4()
    execution.status = Execution.Status.CLAIMED
    execution.claimed_by_runner_id = str(runner.id)
    execution.claim_token = claim_token
    execution.claimed_at = now
    execution.last_heartbeat_at = now
    execution.runner_pool_key = pool.key
    execution.save(
        update_fields=[
            "status",
            "claimed_by_runner_id",
            "claim_token",
            "claimed_at",
            "last_heartbeat_at",
            "runner_pool_key",
            "updated_at",
        ]
    )

    lease = ExecutionLease.objects.create(
        execution=execution,
        organization=runner.organization,
        runner=runner,
        pool=pool,
        status=ExecutionLease.Status.ACTIVE,
        claimed_at=now,
        last_heartbeat_at=now,
    )

    steps = list(execution.steps.order_by("position"))
    return {
        "execution": execution,
        "steps": steps,
        "claim_token": str(claim_token),
        "lease": lease,
    }
