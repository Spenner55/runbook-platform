"""Tests for RunnerPool, Runner, RunnerRegistrationToken, TargetConnectivityRoute,
and ExecutionLease model constraints and tenant boundaries."""

import pytest
from django.db import IntegrityError

from apps.runners.models import Runner, RunnerPool, TargetConnectivityRoute
from apps.runners.tests.conftest import make_runner


@pytest.mark.django_db
class TestRunnerPoolConstraints:
    def test_pool_key_unique_per_org(self, org, pool):
        with pytest.raises(IntegrityError):
            RunnerPool.objects.create(
                organization=org,
                key="prod-pool",  # duplicate
                name="Duplicate",
                status=RunnerPool.Status.ACTIVE,
            )

    def test_same_key_allowed_in_different_org(self, org2, pool):
        # Same key in another org must succeed
        other = RunnerPool.objects.create(
            organization=org2,
            key="prod-pool",
            name="Other org pool",
            status=RunnerPool.Status.ACTIVE,
        )
        assert other.pk is not None

    def test_pool_str(self, pool):
        assert "prod-pool" in str(pool)
        assert "active" in str(pool)


@pytest.mark.django_db
class TestRunnerModel:
    def test_runner_belongs_to_pool_org(self, pool, runner):
        assert runner.organization_id == pool.organization_id

    def test_runner_str(self, runner):
        assert "active" in str(runner)

    def test_revoked_runner_status(self, pool):
        r = make_runner(pool, status=Runner.Status.REVOKED)
        r.refresh_from_db()
        assert r.status == Runner.Status.REVOKED

    def test_runner_initial_status_registered(self, pool):
        from apps.runners.services import generate_runner_token
        _, h = generate_runner_token()
        r = Runner.objects.create(
            organization=pool.organization,
            pool=pool,
            display_name="new-runner",
            status=Runner.Status.REGISTERED,
            token_hash=h,
        )
        assert r.status == Runner.Status.REGISTERED


@pytest.mark.django_db
class TestTargetConnectivityRoute:
    def test_create_route(self, org, pool):
        route = TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            required_capabilities=["action.shell_command"],
            priority=10,
            is_active=True,
        )
        assert route.pk is not None

    def test_wildcard_route(self, org, pool):
        route = TargetConnectivityRoute.objects.create(
            organization=org,
            environment="production",
            target_type="*",
            normalized_identifier_pattern="*",
            pool=pool,
            is_active=True,
        )
        assert route.target_type == "*"
