"""Tests for find_pool_for_change: route miss, online-runner check,
multi-pool rejection, draining/disabled pool, no-routes bypass,
capability checks, inactive-wildcard rejection, and priority tie-breaking."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.runners.models import Runner, TargetConnectivityRoute
from apps.runners.route_matching import find_pool_for_change
from apps.runners.tests.conftest import make_runner


def _mock_target(org, target_type="server", normalized_id="web-01.prod", environment="production"):
    t = MagicMock()
    t.target_type = target_type
    t.normalized_identifier = normalized_id
    t.environment = environment
    return t


def _mock_change(org, targets):
    change = MagicMock()
    change.organization = org
    change.targets.all.return_value = targets
    return change


@pytest.mark.django_db
class TestFindPoolForChange:
    def test_returns_none_ok_when_no_routes_configured(self, org, pool):
        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        # No routes configured → non-blocking bypass
        assert pool_result is None
        assert reason == "no_routes_configured"

    def test_returns_pool_when_exact_route_matches(self, org, pool):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        # Ensure at least one online runner
        make_runner(pool, fingerprint="fp-route-1")

        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is not None
        assert pool_result.pk == pool.pk
        assert reason == "ok"

    def test_wildcard_route_matches_any_target(self, org, pool):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="*",
            normalized_identifier_pattern="*",
            pool=pool,
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-wc")
        change = _mock_change(org, [_mock_target(org, target_type="database", normalized_id="db-01")])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is not None
        assert reason == "ok"

    def test_route_miss_returns_none(self, org, pool):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="other-host.prod",
            pool=pool,
            is_active=True,
        )
        change = _mock_change(org, [_mock_target(org, normalized_id="web-01.prod")])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "route_miss"

    def test_no_online_runner_returns_none(self, org, pool):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        # Create a runner that is stale (last heartbeat > RUNNER_ONLINE_SECONDS ago)
        stale_runner = make_runner(pool, fingerprint="fp-stale")
        stale_runner.last_heartbeat_at = timezone.now() - timedelta(seconds=200)
        stale_runner.save()

        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "no_online_runner"

    def test_disabled_pool_returns_pool_disabled(self, org, pool):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        pool.status = "disabled"
        pool.save()

        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "pool_disabled"

    def test_draining_pool_returns_pool_draining(self, org, pool):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        pool.status = "draining"
        pool.save()

        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "pool_draining"

    def test_multi_pool_unsupported(self, org, pool, pool2):
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="database",
            normalized_identifier_pattern="db-01.prod",
            pool=pool2,
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-mp1")
        make_runner(pool2, fingerprint="fp-mp2")

        targets = [
            _mock_target(org, target_type="server", normalized_id="web-01.prod"),
            _mock_target(org, target_type="database", normalized_id="db-01.prod"),
        ]
        change = _mock_change(org, targets)
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "multi_pool_unsupported"

    def test_no_targets_returns_no_targets(self, org):
        change = _mock_change(org, [])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "no_targets"

    def test_inactive_wildcard_does_not_match(self, org, pool):
        """An inactive wildcard route must not route traffic even when it covers all targets."""
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="*",
            normalized_identifier_pattern="*",
            pool=pool,
            is_active=False,  # explicitly inactive
        )
        make_runner(pool, fingerprint="fp-inactive-wc")
        change = _mock_change(org, [_mock_target(org)])
        # The org has no active routes → non-blocking bypass (not a route miss).
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "no_routes_configured"

    def test_priority_tie_breaker_is_deterministic(self, org, pool, pool2):
        """When two routes share the same priority the one with the lower DB id wins."""
        # Both routes are wildcards so they both match the same target type/pattern.
        route_a = TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            priority=50,
            is_active=True,
        )
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="*",
            pool=pool2,
            priority=50,
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-tie-a")
        make_runner(pool2, fingerprint="fp-tie-b")

        change = _mock_change(org, [_mock_target(org)])
        results = [find_pool_for_change(change) for _ in range(5)]
        # All runs must agree on the same pool (lower id → route_a → pool).
        pool_ids = {r[0].pk for r in results if r[0] is not None}
        assert len(pool_ids) == 1
        assert pool_ids.pop() == pool.pk  # route_a was created first, so it has the smaller id

    def test_route_required_capability_missing_from_pool_fails(self, org, pool):
        """Route with required_capabilities that the pool lacks → missing_required_capability."""
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            required_capabilities=["action.database_query"],  # pool doesn't have this
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-cap-miss")

        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "missing_required_capability"

    def test_route_required_capability_present_in_pool_passes(self, org, pool):
        """Route with required_capabilities fully covered by pool → ok."""
        # pool fixture already has capabilities=["action.shell_command", "action.http_request"]
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            required_capabilities=["action.shell_command"],
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-cap-ok")

        change = _mock_change(org, [_mock_target(org)])
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is not None
        assert reason == "ok"

    def test_operation_profile_required_capability_missing_fails(self, org, pool):
        """OperationProfile.required_runner_capabilities not in pool → missing_required_capability."""
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            required_capabilities=[],  # route itself requires nothing
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-op-cap")

        op_profile = MagicMock()
        op_profile.required_runner_capabilities = ["action.database_query"]

        change = _mock_change(org, [_mock_target(org)])
        change.operation_profile = op_profile

        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "missing_required_capability"

    def test_two_targets_same_pool_passes(self, org, pool):
        """Two targets that route to the same pool → ok (single-pool constraint satisfied)."""
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="*",
            pool=pool,
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-same-pool")

        targets = [
            _mock_target(org, normalized_id="web-01.prod"),
            _mock_target(org, normalized_id="web-02.prod"),
        ]
        change = _mock_change(org, targets)
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is not None
        assert pool_result.pk == pool.pk
        assert reason == "ok"

    def test_two_targets_different_pools_fails(self, org, pool, pool2):
        """Two targets routing to different pools → multi_pool_unsupported (fails closed)."""
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-02.prod",
            pool=pool2,
            is_active=True,
        )
        make_runner(pool, fingerprint="fp-diff-a")
        make_runner(pool2, fingerprint="fp-diff-b")

        targets = [
            _mock_target(org, normalized_id="web-01.prod"),
            _mock_target(org, normalized_id="web-02.prod"),
        ]
        change = _mock_change(org, targets)
        pool_result, reason = find_pool_for_change(change)
        assert pool_result is None
        assert reason == "multi_pool_unsupported"
