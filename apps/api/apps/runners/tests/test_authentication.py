"""Tests for RunnerBearerTokenAuthentication: per-runner DB token resolution,
legacy fallback, revoked/disabled rejection, and user JWT rejection."""

import pytest
from rest_framework.test import APIClient

from apps.runners.models import Runner
from apps.runners.services import generate_runner_token
from apps.runners.tests.conftest import make_runner


@pytest.mark.django_db
class TestPerRunnerTokenAuthentication:
    def test_valid_per_runner_token_authenticates(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")

        # Use the heartbeat endpoint as a probe (requires auth)
        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {"runner_version": "0.1.0", "hostname": "h", "current_execution_count": 0},
            format="json",
        )
        assert resp.status_code == 200

    def test_claim_next_rejects_mismatched_body_runner_id(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")

        resp = client.post(
            "/api/v1/internal/executions/claim-next/",
            {"runner_id": "00000000-0000-0000-0000-000000000000", "runner_version": "0.1.0"},
            format="json",
        )
        assert resp.status_code == 403
        assert resp.data["errors"][0]["code"] == "runner_identity_mismatch"

    def test_revoked_runner_token_returns_401(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h, status=Runner.Status.REVOKED)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")

        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {},
            format="json",
        )
        assert resp.status_code == 401

    def test_disabled_runner_token_returns_401(self, pool):
        clear, h = generate_runner_token()
        make_runner(pool, token_hash=h, status=Runner.Status.DISABLED)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")

        resp = client.post(
            "/api/v1/internal/runners/heartbeat/",
            {},
            format="json",
        )
        assert resp.status_code == 401

    def test_unknown_token_falls_back_to_legacy(self, settings):
        settings.RUNNER_TOKENS = ["known-legacy-token"]
        settings.RUNNER_LEGACY_TOKEN_MODE = True
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer known-legacy-token")

        # claim-next with legacy auth — body runner_id is trusted
        resp = client.post(
            "/api/v1/internal/executions/claim-next/",
            {"runner_id": "legacy-id", "runner_version": "0.1.0"},
            format="json",
        )
        assert resp.status_code == 200

    def test_unknown_token_without_legacy_mode_returns_401(self, settings):
        settings.RUNNER_LEGACY_TOKEN_MODE = False
        settings.RUNNER_TOKENS = []
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer bad-token-xyz")

        resp = client.post(
            "/api/v1/internal/executions/claim-next/",
            {"runner_id": "x", "runner_version": "0.1.0"},
            format="json",
        )
        assert resp.status_code == 401

    def test_missing_auth_header_returns_401(self):
        client = APIClient()
        resp = client.post(
            "/api/v1/internal/executions/claim-next/",
            {"runner_id": "x"},
            format="json",
        )
        assert resp.status_code == 401
