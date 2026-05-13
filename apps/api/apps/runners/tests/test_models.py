"""Tests for RunnerPool, Runner, RunnerRegistrationToken, TargetConnectivityRoute,
and ExecutionLease model constraints and tenant boundaries."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.runners.models import (
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
    TargetConnectivityRoute,
)
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

    def test_only_one_default_non_change_pool_per_org(self, org, pool):
        pool.default_for_non_change_executions = True
        pool.save(update_fields=["default_for_non_change_executions"])

        with pytest.raises(IntegrityError):
            RunnerPool.objects.create(
                organization=org,
                key="prod-pool-2",
                name="Second default",
                default_for_non_change_executions=True,
            )

    def test_default_non_change_pool_allowed_in_different_org(self, org2, pool):
        pool.default_for_non_change_executions = True
        pool.save(update_fields=["default_for_non_change_executions"])

        other = RunnerPool.objects.create(
            organization=org2,
            key="prod-pool-2",
            name="Other org default",
            default_for_non_change_executions=True,
        )
        assert other.pk is not None

    def test_pool_metadata_rejects_secret_like_keys(self, pool):
        pool.metadata = {"token": "not allowed"}
        with pytest.raises(ValidationError):
            pool.full_clean()


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

    def test_runner_pool_must_match_organization(self, org2, pool):
        runner = make_runner(pool)
        runner.organization = org2
        with pytest.raises(ValidationError):
            runner.full_clean()

    def test_runner_token_hash_unique(self, pool):
        runner = make_runner(pool, fingerprint="fp-token-a")
        with pytest.raises(IntegrityError):
            make_runner(
                pool,
                token_hash=runner.token_hash,
                fingerprint="fp-token-b",
            )

    def test_runner_metadata_rejects_secret_like_keys(self, runner):
        runner.metadata = {"facts": {"password": "not allowed"}}
        with pytest.raises(ValidationError):
            runner.full_clean()


@pytest.mark.django_db
class TestRunnerRegistrationToken:
    def test_registration_token_pool_must_match_organization(self, org2, runner_token_clear):
        _, token = runner_token_clear
        token.organization = org2
        with pytest.raises(ValidationError):
            token.full_clean()

    def test_registration_usage_cannot_exceed_max(self, runner_token_clear):
        _, token = runner_token_clear
        token.used_count = token.max_registrations + 1
        with pytest.raises(ValidationError):
            token.full_clean()

    def test_registration_usage_db_constraint(self, runner_token_clear):
        _, token = runner_token_clear
        token.used_count = token.max_registrations + 1
        with pytest.raises(IntegrityError):
            token.save(update_fields=["used_count"])

    def test_registration_token_hash_unique(self, pool, runner_token_clear):
        _, token = runner_token_clear
        with pytest.raises(IntegrityError):
            RunnerRegistrationToken.objects.create(
                organization=pool.organization,
                pool=pool,
                token_hash=token.token_hash,
                expires_at=token.expires_at,
                max_registrations=1,
            )


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

    def test_route_pool_must_match_organization(self, org2, pool):
        route = TargetConnectivityRoute(
            organization=org2,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        with pytest.raises(ValidationError):
            route.full_clean()

    def test_active_route_requires_active_pool(self, org, pool):
        pool.status = RunnerPool.Status.DRAINING
        pool.save(update_fields=["status"])
        route = TargetConnectivityRoute(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=True,
        )
        with pytest.raises(ValidationError):
            route.full_clean()

    def test_inactive_route_can_reference_draining_pool(self, org, pool):
        pool.status = RunnerPool.Status.DRAINING
        pool.save(update_fields=["status"])
        route = TargetConnectivityRoute(
            organization=org,
            environment="production",
            target_type="server",
            normalized_identifier_pattern="web-01.prod",
            pool=pool,
            is_active=False,
        )
        route.full_clean()
