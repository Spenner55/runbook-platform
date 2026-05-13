import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import InvalidStateTransitionError

logger = logging.getLogger(__name__)


@transaction.atomic
def schedule_execution_claim(runner) -> dict | None:
    """Pool-aware execution claim for a registered runner.

    Returns a dict with 'execution', 'steps', 'claim_token', 'lease' if work
    was found; {'drain': True} if the runner/pool is draining; or None if the
    queue is empty or concurrency limits are hit.

    Must be called within a transaction — uses select_for_update to prevent
    double-claims.
    """
    from apps.executions.models import Execution, ExecutionStep
    from apps.runners.models import ExecutionLease, Runner, RunnerPool

    pool = runner.pool

    if runner.status == Runner.Status.DRAINING:
        return {"drain": True}
    if runner.status not in (Runner.Status.ACTIVE, Runner.Status.REGISTERED):
        raise InvalidStateTransitionError(
            code="runner_not_active",
            detail=f"Runner status '{runner.status}' cannot claim executions.",
        )

    if pool.status == RunnerPool.Status.DRAINING:
        return {"drain": True}
    if pool.status != RunnerPool.Status.ACTIVE:
        raise InvalidStateTransitionError(
            code="pool_not_active",
            detail=f"Runner pool '{pool.key}' is not active (status: {pool.status}).",
        )

    # Concurrency checks.
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

    # Find the oldest queued execution in this runner's organization.
    execution = None
    for _ in range(50):
        candidate = (
            Execution.objects.select_for_update(skip_locked=True)
            .filter(
                status=Execution.Status.QUEUED,
                organization=runner.organization,
            )
            .order_by("created_at")
            .first()
        )
        if candidate is None:
            break

        if _expire_unbound_change_dispatch_if_needed(candidate, now=now):
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
                break

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
