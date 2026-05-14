import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def find_pool_for_change(change) -> tuple:
    """Match all targets on a change to a pool via TargetConnectivityRoute.

    Returns (pool, reason) where pool=None means no match.
    Rules:
    - All targets must map to routes with the same pool (Phase C: single-pool dispatch).
    - At least one active runner in the pool must have last_heartbeat_at within RUNNER_ONLINE_SECONDS.
    - The pool must be active.
    """
    from apps.runners.models import Runner, RunnerPool, TargetConnectivityRoute

    targets = list(change.targets.all())
    if not targets:
        return None, "no_targets"

    online_threshold = timezone.now() - timezone.timedelta(
        seconds=getattr(settings, "RUNNER_ONLINE_SECONDS", 30)
    )

    # If the organization has no routes at all, return ok (no routing policy configured).
    any_org_routes = TargetConnectivityRoute.objects.filter(
        organization=change.organization, is_active=True
    ).exists()
    if not any_org_routes:
        return None, "no_routes_configured"

    matched_pools: list = []
    for target in targets:
        routes = (
            TargetConnectivityRoute.objects.filter(
                organization=change.organization,
                environment=target.environment if hasattr(target, "environment") else "production",
                is_active=True,
            )
            .filter(
                # Match by exact target_type or wildcard
                target_type__in=[target.target_type, "*"]
            )
            .filter(
                # Match by exact normalized_identifier_pattern or wildcard
                normalized_identifier_pattern__in=[
                    target.normalized_identifier if hasattr(target, "normalized_identifier") else "",
                    "*",
                ]
            )
            .select_related("pool")
            .order_by("priority", "id")  # deterministic tie-break on same priority
        )

        route = routes.first()
        if route is None:
            logger.debug(
                "No connectivity route found for target %s:%s",
                target.target_type,
                getattr(target, "normalized_identifier", ""),
            )
            return None, "route_miss"

        # Route's required_capabilities must be covered by the matched pool's capabilities.
        if route.required_capabilities:
            pool_caps = set(route.pool.capabilities or [])
            missing = [c for c in route.required_capabilities if c not in pool_caps]
            if missing:
                logger.debug(
                    "Pool '%s' missing required capabilities for route: %s",
                    route.pool.key,
                    missing,
                )
                return None, "missing_required_capability"

        matched_pools.append(route.pool)

    # All targets must map to the same pool.
    pool_ids = {p.id for p in matched_pools}
    if len(pool_ids) > 1:
        return None, "multi_pool_unsupported"

    pool = matched_pools[0]

    if pool.status == RunnerPool.Status.DRAINING:
        return None, "pool_draining"
    if pool.status == RunnerPool.Status.DISABLED:
        return None, "pool_disabled"
    if pool.status != RunnerPool.Status.ACTIVE:
        return None, f"pool_{pool.status}"

    # Operation-profile required capabilities must be covered by the pool.
    op_profile = getattr(change, "operation_profile", None)
    if op_profile is not None:
        op_required = list(getattr(op_profile, "required_runner_capabilities", None) or [])
        if op_required:
            pool_caps = set(pool.capabilities or [])
            missing = [c for c in op_required if c not in pool_caps]
            if missing:
                logger.debug(
                    "Pool '%s' missing operation-profile required capabilities: %s",
                    pool.key,
                    missing,
                )
                return None, "missing_required_capability"

    # Require at least one online runner in the pool.
    has_online_runner = Runner.objects.filter(
        pool=pool,
        status=Runner.Status.ACTIVE,
        last_heartbeat_at__gte=online_threshold,
    ).exists()

    if not has_online_runner:
        return None, "no_online_runner"

    return pool, "ok"
