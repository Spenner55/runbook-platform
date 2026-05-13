"""Tests for internal runner API endpoints:
POST /api/v1/internal/runners/register/ and POST /api/v1/internal/runners/heartbeat/"""

import hashlib
import secrets
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.runners.models import Runner, RunnerRegistrationToken
from apps.runners.services import generate_runner_token
from apps.runners.tests.conftest import make_runner


def _make_reg_token(pool, *, max_reg=1, extra_seconds=3600):
    clear = secrets.token_hex(32)
    token_hash = hashlib.sha256(clear.encode()).hexdigest()
    RunnerRegistrationToken.objects.create(
        organization=pool.organization,
        pool=pool,
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(seconds=extra_seconds),
        max_registrations=max_reg,
    )
    return clear


@pytest.fixture
def legacy_client(settings):
    settings.RUNNER_TOKENS = ["reg-test-token"]
    settings.RUNNER_LEGACY_TOKEN_MODE = True
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer reg-test-token")
    return client


@pytest.mark.django_db
class TestRunnerRegisterView:
    def test_register_returns_runner_id_and_token(self, pool):
        clear = _make_reg_token(pool)
        client = APIClient()
        resp = client.post(
            "/api/v1/internal/runners/register/",
            {
                "registration_token": clear,
                "organization_id": str(pool.organization_id),
                "pool_key": pool.key,
                "display_name": "prod-runner-01",
                "runner_version": "0.2.0",
                "fingerprint_sha256": "fp-test",
                "hostname": "host-01",
                "labels": {},
                "capabilities": [],
            },
            format="json",
        )
        assert resp.status_code == 201, resp.data
        data = resp.data
        assert "runner_id" in data
        assert "runner_bearer_token" in data
        assert "pool_key" in data
        assert data["pool_key"] == pool.key

    def test_register_with_invalid_token_returns_400(self, pool):
        client = APIClient()
        resp = client.post(
            "/api/v1/internal/runners/register/",
            {
                "registration_token": "not-valid",
                "display_name": "r",
                "runner_version": "0.1.0",
                "fingerprint_sha256": "fp",
                "hostname": "h",
                "labels": {},
                "capabilities": [],
            },
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["code"] == "invalid_registration_token"

    def test_register_uses_bootstrap_token_without_runner_auth(self, pool):
        clear = _make_reg_token(pool)
        client = APIClient()
        resp = client.post(
            "/api/v1/internal/runners/register/",
            {"registration_token": clear, "display_name": "r", "runner_version": "0.1.0",
             "fingerprint_sha256": "fp", "hostname": "h", "labels": {}, "capabilities": []},
            format="json",
        )
        assert resp.status_code == 201

    def test_register_wrong_pool_scope_returns_400(self, pool, pool2):
        clear = _make_reg_token(pool)
        client = APIClient()
        resp = client.post(
            "/api/v1/internal/runners/register/",
            {
                "registration_token": clear,
                "pool_key": pool2.key,
                "display_name": "r",
                "runner_version": "0.1.0",
                "fingerprint_sha256": "fp",
                "hostname": "h",
                "labels": {},
                "capabilities": [],
            },
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["code"] == "registration_scope_mismatch"

    def test_register_wrong_organization_scope_returns_400(self, pool, org2):
        clear = _make_reg_token(pool)
        client = APIClient()
        resp = client.post(
            "/api/v1/internal/runners/register/",
            {
                "registration_token": clear,
                "organization_id": str(org2.id),
                "display_name": "r",
                "runner_version": "0.1.0",
                "fingerprint_sha256": "fp",
                "hostname": "h",
                "labels": {},
                "capabilities": [],
            },
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["code"] == "registration_scope_mismatch"


@pytest.mark.django_db
class TestRunnerHeartbeatView:
    def test_heartbeat_updates_liveness(self, pool):
        clear, h = generate_runner_token()
        runner = make_runner(pool, token_hash=h)
        old_heartbeat = runner.last_heartbeat_at

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {"runner_version": "0.2.0", "hostname": "new-host", "current_execution_count": 0,
             "observed_pool_key": pool.key, "capabilities_checksum": "abc"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["runner_id"] == str(runner.id)
        assert resp.data["runner_action"] == "continue"
        runner.refresh_from_db()
        assert runner.last_heartbeat_at > old_heartbeat
        assert runner.last_seen_at > old_heartbeat

    def test_heartbeat_rejects_body_runner_id_mismatch(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {"runner_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert resp.status_code == 403

    def test_heartbeat_rejects_header_runner_id_mismatch(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h)

        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {clear}",
            HTTP_X_RUNNER_ID="00000000-0000-0000-0000-000000000000",
        )
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {},
            format="json",
        )
        assert resp.status_code == 403

    def test_heartbeat_drain_response_for_draining_runner(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h, status=Runner.Status.DRAINING)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {"runner_version": "0.1.0", "hostname": "h", "current_execution_count": 1},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["runner_action"] == "drain"

    def test_heartbeat_drain_response_for_draining_pool(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h)
        pool.status = "draining"
        pool.save()

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {"runner_version": "0.1.0", "hostname": "h", "current_execution_count": 0},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["runner_action"] == "drain"

    def test_heartbeat_with_legacy_auth_returns_400(self, settings):
        settings.RUNNER_TOKENS = ["shared-hb-token"]
        settings.RUNNER_LEGACY_TOKEN_MODE = True
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer shared-hb-token")
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {"runner_version": "0.1.0", "hostname": "h", "current_execution_count": 0},
            format="json",
        )
        # Legacy auth doesn't resolve a runner_id — should return 400
        assert resp.status_code == 400
