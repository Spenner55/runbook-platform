"""Tests for public runner management API endpoints."""

import hashlib
import secrets
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.organizations.models import Membership, MembershipRole, Organization
from apps.runners.models import (
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
    TargetConnectivityRoute,
)
from apps.runners.tests.conftest import make_runner
from apps.users.models import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(email_prefix, org, role=MembershipRole.OPERATOR):
    user = User.objects.create_user(
        email=f"{email_prefix}-{secrets.token_hex(4)}@example.com",
        password="s3cr3tpass!",
    )
    Membership.objects.create(organization=org, user=user, role=role)
    return user


def _client_for(user, org):
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return client


def _make_reg_token(pool, *, max_registrations=1, hours=1):
    clear = secrets.token_hex(32)
    token_hash = hashlib.sha256(clear.encode()).hexdigest()
    reg_token = RunnerRegistrationToken.objects.create(
        organization=pool.organization,
        pool=pool,
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(hours=hours),
        max_registrations=max_registrations,
    )
    return reg_token, clear


# ---------------------------------------------------------------------------
# Pool tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunnerPoolList:
    def test_member_can_list_pools(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-pools/")
        assert resp.status_code == 200
        assert any(p["id"] == str(pool.id) for p in resp.data)

    def test_unauthenticated_rejected(self, org, pool):
        client = APIClient()
        client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)
        resp = client.get("/api/v1/runner-pools/")
        assert resp.status_code in (401, 403)

    def test_cross_org_pools_not_visible(self, org, pool):
        org2 = Organization.objects.create(name="Other", slug="other-x1")
        other_pool = RunnerPool.objects.create(
            organization=org2,
            key="other-pool",
            name="Other",
            status=RunnerPool.Status.ACTIVE,
        )
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-pools/")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.data]
        assert str(other_pool.id) not in ids

    def test_list_includes_health_state(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-pools/")
        assert resp.status_code == 200
        p = next(p for p in resp.data if p["id"] == str(pool.id))
        assert "active_runner_count" in p
        assert "active_execution_count" in p
        assert "capacity_summary" in p
        assert "drain_requested_at" in p
        assert "disabled_at" in p


@pytest.mark.django_db
class TestRunnerPoolDetail:
    def test_member_can_retrieve(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get(f"/api/v1/runner-pools/{pool.id}/")
        assert resp.status_code == 200
        assert resp.data["id"] == str(pool.id)

    def test_cross_org_access_rejected(self, org, pool):
        org2 = Organization.objects.create(name="Other", slug="other-x2")
        user2 = _make_user("viewer", org2, MembershipRole.VIEWER)
        client = _client_for(user2, org2)
        resp = client.get(f"/api/v1/runner-pools/{pool.id}/")
        assert resp.status_code == 404

    def test_no_secrets_in_response(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get(f"/api/v1/runner-pools/{pool.id}/")
        assert resp.status_code == 200
        raw = str(resp.data)
        assert "token_hash" not in raw


@pytest.mark.django_db
class TestRunnerPoolCreate:
    def test_admin_can_create(self, org):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(
            "/api/v1/runner-pools/",
            {"key": "new-pool", "name": "New Pool", "max_concurrent_executions": 2},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["key"] == "new-pool"
        assert "capacity_summary" in resp.data

    def test_member_cannot_create(self, org):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(
            "/api/v1/runner-pools/",
            {"key": "new-pool2", "name": "New Pool 2"},
            format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestRunnerPoolDrain:
    def test_admin_can_drain_active_pool(self, org, pool):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/drain/")
        assert resp.status_code == 200
        assert resp.data["status"] == "draining"
        assert resp.data["drain_requested_at"] is not None

    def test_draining_already_draining_pool_returns_409(self, org, pool):
        pool.status = RunnerPool.Status.DRAINING
        pool.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/drain/")
        assert resp.status_code == 409

    def test_draining_disabled_pool_returns_409(self, org, pool):
        pool.status = RunnerPool.Status.DISABLED
        pool.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/drain/")
        assert resp.status_code == 409

    def test_member_cannot_drain(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/drain/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestRunnerPoolDisable:
    def test_admin_can_disable(self, org, pool):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/disable/")
        assert resp.status_code == 200
        assert resp.data["status"] == "disabled"
        assert resp.data["disabled_at"] is not None

    def test_disabling_already_disabled_returns_409(self, org, pool):
        pool.status = RunnerPool.Status.DISABLED
        pool.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/disable/")
        assert resp.status_code == 409


@pytest.mark.django_db
class TestRunnerPoolReactivate:
    def test_admin_can_reactivate_disabled_pool(self, org, pool):
        pool.status = RunnerPool.Status.DISABLED
        pool.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/reactivate/")
        assert resp.status_code == 200
        assert resp.data["status"] == "active"

    def test_admin_can_reactivate_draining_pool(self, org, pool):
        pool.status = RunnerPool.Status.DRAINING
        pool.drain_requested_at = timezone.now()
        pool.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/reactivate/")
        assert resp.status_code == 200
        assert resp.data["status"] == "active"
        assert resp.data["drain_requested_at"] is None

    def test_reactivating_active_pool_returns_409(self, org, pool):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/reactivate/")
        assert resp.status_code == 409

    def test_member_cannot_reactivate(self, org, pool):
        pool.status = RunnerPool.Status.DISABLED
        pool.save()
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-pools/{pool.id}/reactivate/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunnerList:
    def test_member_can_list_runners(self, org, pool, runner):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runners/")
        assert resp.status_code == 200
        assert any(r["id"] == str(runner.id) for r in resp.data)

    def test_cross_org_runners_not_visible(self, org, pool, runner):
        org2 = Organization.objects.create(name="Other", slug="other-r1")
        pool2 = RunnerPool.objects.create(
            organization=org2, key="p2", name="P2", status=RunnerPool.Status.ACTIVE
        )
        other_runner = make_runner(pool2)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runners/")
        ids = [r["id"] for r in resp.data]
        assert str(other_runner.id) not in ids

    def test_no_token_hash_in_response(self, org, pool, runner):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runners/")
        assert resp.status_code == 200
        raw = str(resp.data)
        assert "token_hash" not in raw

    def test_list_includes_health_state(self, org, pool, runner):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runners/")
        assert resp.status_code == 200
        r = next(r for r in resp.data if r["id"] == str(runner.id))
        assert "last_seen_at" in r
        assert "last_heartbeat_at" in r
        assert "active_execution_count" in r


@pytest.mark.django_db
class TestRunnerDetail:
    def test_cross_org_access_rejected(self, org, pool, runner):
        org2 = Organization.objects.create(name="Other", slug="other-r2")
        user2 = _make_user("viewer", org2, MembershipRole.VIEWER)
        client = _client_for(user2, org2)
        resp = client.get(f"/api/v1/runners/{runner.id}/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestRunnerDrain:
    def test_admin_can_drain_active_runner(self, org, pool, runner):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/drain/")
        assert resp.status_code == 200
        assert resp.data["status"] == "draining"

    def test_draining_disabled_runner_returns_409(self, org, pool):
        runner = make_runner(pool, status=Runner.Status.DISABLED)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/drain/")
        assert resp.status_code == 409

    def test_draining_revoked_runner_returns_409(self, org, pool):
        runner = make_runner(pool, status=Runner.Status.REVOKED)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/drain/")
        assert resp.status_code == 409


@pytest.mark.django_db
class TestRunnerDisable:
    def test_admin_can_disable_runner(self, org, pool, runner):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/disable/")
        assert resp.status_code == 200
        assert resp.data["status"] == "disabled"

    def test_disabling_revoked_runner_returns_409(self, org, pool):
        runner = make_runner(pool, status=Runner.Status.REVOKED)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/disable/")
        assert resp.status_code == 409


@pytest.mark.django_db
class TestRunnerRevoke:
    def test_admin_can_revoke_runner(self, org, pool, runner):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/revoke/")
        assert resp.status_code == 200
        assert resp.data["status"] == "revoked"
        assert resp.data.get("token_hash") is None  # never returned

    def test_revoking_already_revoked_returns_409(self, org, pool):
        runner = make_runner(pool, status=Runner.Status.REVOKED)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/revoke/")
        assert resp.status_code == 409

    def test_member_cannot_revoke(self, org, pool, runner):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runners/{runner.id}/revoke/")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Registration token tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRegistrationTokenCreate:
    def test_admin_can_create_token(self, org, pool):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        expires_at = (timezone.now() + timedelta(hours=2)).isoformat()
        resp = client.post(
            f"/api/v1/runner-pools/{pool.id}/registration-tokens/",
            {"expires_at": expires_at, "max_registrations": 3},
            format="json",
        )
        assert resp.status_code == 201
        assert "token" in resp.data
        assert len(resp.data["token"]) > 0
        assert "token_hash" not in resp.data
        # Clear token returned only in create response
        assert "id" in resp.data

    def test_create_token_does_not_expose_hash(self, org, pool):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        expires_at = (timezone.now() + timedelta(hours=2)).isoformat()
        resp = client.post(
            f"/api/v1/runner-pools/{pool.id}/registration-tokens/",
            {"expires_at": expires_at},
            format="json",
        )
        assert resp.status_code == 201
        raw = str(resp.data)
        assert "token_hash" not in raw

    def test_member_cannot_create_token(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        expires_at = (timezone.now() + timedelta(hours=2)).isoformat()
        resp = client.post(
            f"/api/v1/runner-pools/{pool.id}/registration-tokens/",
            {"expires_at": expires_at},
            format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestRegistrationTokenList:
    def test_member_can_list_tokens(self, org, pool):
        reg_token, _ = _make_reg_token(pool)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-registration-tokens/")
        assert resp.status_code == 200
        assert any(t["id"] == str(reg_token.id) for t in resp.data)

    def test_list_never_exposes_clear_token_or_hash(self, org, pool):
        _make_reg_token(pool)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-registration-tokens/")
        assert resp.status_code == 200
        raw = str(resp.data)
        assert "token_hash" not in raw
        # No field called "token" in list response
        for t in resp.data:
            assert "token" not in t

    def test_cross_org_tokens_not_visible(self, org, pool):
        org2 = Organization.objects.create(name="Other", slug="other-t1")
        pool2 = RunnerPool.objects.create(
            organization=org2, key="p2", name="P2", status=RunnerPool.Status.ACTIVE
        )
        other_token, _ = _make_reg_token(pool2)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-registration-tokens/")
        ids = [t["id"] for t in resp.data]
        assert str(other_token.id) not in ids

    def test_list_includes_status_flags(self, org, pool):
        reg_token, _ = _make_reg_token(pool)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/runner-registration-tokens/")
        assert resp.status_code == 200
        t = next(t for t in resp.data if t["id"] == str(reg_token.id))
        assert "is_revoked" in t
        assert "is_expired" in t
        assert "is_exhausted" in t
        assert t["is_revoked"] is False


@pytest.mark.django_db
class TestRegistrationTokenRevoke:
    def test_admin_can_revoke_token(self, org, pool):
        reg_token, _ = _make_reg_token(pool)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-registration-tokens/{reg_token.id}/revoke/")
        assert resp.status_code == 200
        assert resp.data["is_revoked"] is True
        assert "token_hash" not in resp.data
        assert "token" not in resp.data

    def test_revoking_already_revoked_returns_409(self, org, pool):
        reg_token, _ = _make_reg_token(pool)
        reg_token.revoked_at = timezone.now()
        reg_token.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-registration-tokens/{reg_token.id}/revoke/")
        assert resp.status_code == 409

    def test_member_cannot_revoke(self, org, pool):
        reg_token, _ = _make_reg_token(pool)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/runner-registration-tokens/{reg_token.id}/revoke/")
        assert resp.status_code == 403

    def test_cross_org_revoke_rejected(self, org, pool):
        reg_token, _ = _make_reg_token(pool)
        org2 = Organization.objects.create(name="Other", slug="other-t2")
        user2 = _make_user("admin", org2, MembershipRole.ADMIN)
        client = _client_for(user2, org2)
        resp = client.post(f"/api/v1/runner-registration-tokens/{reg_token.id}/revoke/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Target connectivity route tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRouteList:
    def test_member_can_list_routes(self, org, pool):
        route = TargetConnectivityRoute.objects.create(
            organization=org,
            pool=pool,
            environment="production",
            target_type="host",
            normalized_identifier_pattern="*.prod.example.com",
        )
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/target-connectivity-routes/")
        assert resp.status_code == 200
        assert any(r["id"] == str(route.id) for r in resp.data)

    def test_cross_org_routes_not_visible(self, org, pool):
        org2 = Organization.objects.create(name="Other", slug="other-cr1")
        pool2 = RunnerPool.objects.create(
            organization=org2, key="p2", name="P2", status=RunnerPool.Status.ACTIVE
        )
        other_route = TargetConnectivityRoute.objects.create(
            organization=org2,
            pool=pool2,
            environment="production",
            target_type="host",
            normalized_identifier_pattern="other.example.com",
        )
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.get("/api/v1/target-connectivity-routes/")
        ids = [r["id"] for r in resp.data]
        assert str(other_route.id) not in ids


@pytest.mark.django_db
class TestRouteCreate:
    def test_admin_can_create_route(self, org, pool):
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(
            "/api/v1/target-connectivity-routes/",
            {
                "pool": str(pool.id),
                "environment": "production",
                "target_type": "host",
                "normalized_identifier_pattern": "*.prod.example.com",
                "priority": 50,
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["target_type"] == "host"
        assert resp.data["is_active"] is True

    def test_cross_org_pool_rejected(self, org, pool):
        org2 = Organization.objects.create(name="Other", slug="other-cr2")
        pool2 = RunnerPool.objects.create(
            organization=org2, key="p2", name="P2", status=RunnerPool.Status.ACTIVE
        )
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(
            "/api/v1/target-connectivity-routes/",
            {
                "pool": str(pool2.id),
                "environment": "production",
                "target_type": "host",
                "normalized_identifier_pattern": "*.prod.example.com",
            },
            format="json",
        )
        assert resp.status_code == 404

    def test_member_cannot_create_route(self, org, pool):
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(
            "/api/v1/target-connectivity-routes/",
            {
                "pool": str(pool.id),
                "environment": "production",
                "target_type": "host",
                "normalized_identifier_pattern": "*.prod.example.com",
            },
            format="json",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestRouteDeactivateReactivate:
    def _make_route(self, org, pool, *, is_active=True):
        return TargetConnectivityRoute.objects.create(
            organization=org,
            pool=pool,
            environment="production",
            target_type="host",
            normalized_identifier_pattern="*.prod.example.com",
            is_active=is_active,
        )

    def test_admin_can_deactivate_route(self, org, pool):
        route = self._make_route(org, pool)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/deactivate/")
        assert resp.status_code == 200
        assert resp.data["is_active"] is False

    def test_deactivating_already_inactive_returns_409(self, org, pool):
        route = self._make_route(org, pool, is_active=False)
        # Bypass clean() which validates pool status for active routes
        TargetConnectivityRoute.objects.filter(pk=route.pk).update(is_active=False)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/deactivate/")
        assert resp.status_code == 409

    def test_admin_can_reactivate_route(self, org, pool):
        route = self._make_route(org, pool)
        TargetConnectivityRoute.objects.filter(pk=route.pk).update(is_active=False)
        route.refresh_from_db()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/reactivate/")
        assert resp.status_code == 200
        assert resp.data["is_active"] is True

    def test_reactivating_active_route_returns_409(self, org, pool):
        route = self._make_route(org, pool)
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/reactivate/")
        assert resp.status_code == 409

    def test_reactivating_route_with_disabled_pool_returns_409(self, org, pool):
        route = self._make_route(org, pool)
        TargetConnectivityRoute.objects.filter(pk=route.pk).update(is_active=False)
        pool.status = RunnerPool.Status.DISABLED
        pool.save()
        user = _make_user("admin", org, MembershipRole.ADMIN)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/reactivate/")
        assert resp.status_code == 409
        assert resp.data["code"] == "pool_not_active"

    def test_member_cannot_deactivate(self, org, pool):
        route = self._make_route(org, pool)
        user = _make_user("viewer", org, MembershipRole.VIEWER)
        client = _client_for(user, org)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/deactivate/")
        assert resp.status_code == 403

    def test_cross_org_deactivate_rejected(self, org, pool):
        route = self._make_route(org, pool)
        org2 = Organization.objects.create(name="Other", slug="other-dr1")
        user2 = _make_user("admin", org2, MembershipRole.ADMIN)
        client = _client_for(user2, org2)
        resp = client.post(f"/api/v1/target-connectivity-routes/{route.id}/deactivate/")
        assert resp.status_code == 404
