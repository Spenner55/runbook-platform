import hashlib
import secrets
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.organizations.models import Organization
from apps.runners.models import (
    Runner,
    RunnerPool,
    RunnerRegistrationToken,
)
from apps.runners.services import generate_runner_token


@pytest.fixture
def org2(db):
    return Organization.objects.create(name="Other Corp", slug="other-corp")


@pytest.fixture
def pool(db, org):
    return RunnerPool.objects.create(
        organization=org,
        key="prod-pool",
        name="Production Pool",
        environment="production",
        network_zone="prod-vpc-us-east-1",
        status=RunnerPool.Status.ACTIVE,
        max_concurrent_executions=2,
        capabilities=["action.shell_command", "action.http_request"],
    )


@pytest.fixture
def pool2(db, org):
    return RunnerPool.objects.create(
        organization=org,
        key="staging-pool",
        name="Staging Pool",
        environment="production",
        status=RunnerPool.Status.ACTIVE,
        max_concurrent_executions=1,
    )


@pytest.fixture
def other_org_pool(db, org2):
    return RunnerPool.objects.create(
        organization=org2,
        key="prod-pool",
        name="Other Org Pool",
        status=RunnerPool.Status.ACTIVE,
    )


def make_runner(
    pool, *, status=Runner.Status.ACTIVE, token_hash=None, fingerprint="fp-default"
):
    if token_hash is None:
        _, token_hash = generate_runner_token()
    now = timezone.now()
    return Runner.objects.create(
        organization=pool.organization,
        pool=pool,
        display_name=f"runner-{secrets.token_hex(4)}",
        status=status,
        runner_version="0.1.0",
        hostname="host-01",
        fingerprint_sha256=fingerprint,
        token_hash=token_hash,
        registered_at=now,
        last_seen_at=now,
        last_heartbeat_at=now,
    )


@pytest.fixture
def runner(db, pool):
    return make_runner(pool)


@pytest.fixture
def runner_token_clear(db, pool):
    """Returns (registration_token_clear_text, RunnerRegistrationToken)."""
    clear = secrets.token_hex(32)
    token_hash = hashlib.sha256(clear.encode()).hexdigest()
    reg_token = RunnerRegistrationToken.objects.create(
        organization=pool.organization,
        pool=pool,
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(hours=1),
        max_registrations=3,
        label_policy=["region", "environment"],
        capability_policy=["action.shell_command", "action.http_request"],
    )
    return clear, reg_token


@pytest.fixture
def runner_api_client(db, runner):
    """APIClient authenticated as an active runner via per-runner bearer token."""
    clear, hash_ = generate_runner_token()
    runner.token_hash = hash_
    runner.save(update_fields=["token_hash"])
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {clear}")
    return client, clear, runner


@pytest.fixture
def legacy_runner_client(db, settings):
    """APIClient using the legacy shared RUNNER_TOKENS mechanism."""
    settings.RUNNER_TOKENS = ["legacy-shared-token"]
    settings.RUNNER_LEGACY_TOKEN_MODE = True
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer legacy-shared-token")
    return client
