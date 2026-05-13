"""Tests for runner registration service: valid/invalid tokens, re-registration,
label/capability policy filtering, and audit events."""

import hashlib
import secrets
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.common.exceptions import DomainValidationError
from apps.runners.models import Runner, RunnerRegistrationToken
from apps.runners.services import register_runner


def _make_reg_token(pool, *, max_reg=1, extra_seconds=3600, label_policy=None, cap_policy=None):
    clear = secrets.token_hex(32)
    token_hash = hashlib.sha256(clear.encode()).hexdigest()
    reg = RunnerRegistrationToken.objects.create(
        organization=pool.organization,
        pool=pool,
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(seconds=extra_seconds),
        max_registrations=max_reg,
        label_policy=label_policy or [],
        capability_policy=cap_policy or [],
    )
    return clear, reg


@pytest.mark.django_db
class TestRegisterRunner:
    def test_valid_registration_creates_runner(self, pool):
        clear, _ = _make_reg_token(pool)
        runner, token = register_runner(
            registration_token=clear,
            display_name="prod-runner-01",
            runner_version="0.2.0",
            fingerprint_sha256="fp-abc123",
            hostname="host-a",
            labels={"region": "us-east-1"},
            capabilities=["action.shell_command"],
        )
        assert runner.pk is not None
        assert runner.organization_id == pool.organization_id
        assert runner.pool_id == pool.pk
        assert runner.status == Runner.Status.ACTIVE
        assert runner.display_name == "prod-runner-01"
        assert len(token) > 20

    def test_registration_increments_used_count(self, pool):
        clear, reg = _make_reg_token(pool, max_reg=2)
        register_runner(
            registration_token=clear,
            display_name="r1",
            runner_version="0.1.0",
            fingerprint_sha256="fp-1",
            hostname="h1",
            labels={},
            capabilities=[],
        )
        reg.refresh_from_db()
        assert reg.used_count == 1

    def test_invalid_token_raises(self, pool):
        with pytest.raises(DomainValidationError) as exc_info:
            register_runner(
                registration_token="not-a-real-token",
                display_name="r",
                runner_version="0.1.0",
                fingerprint_sha256="fp",
                hostname="h",
                labels={},
                capabilities=[],
            )
        assert exc_info.value.code == "invalid_registration_token"

    def test_expired_token_raises(self, pool):
        clear, _ = _make_reg_token(pool, extra_seconds=-1)
        with pytest.raises(DomainValidationError) as exc_info:
            register_runner(
                registration_token=clear,
                display_name="r",
                runner_version="0.1.0",
                fingerprint_sha256="fp",
                hostname="h",
                labels={},
                capabilities=[],
            )
        assert exc_info.value.code == "registration_token_expired"

    def test_revoked_token_raises(self, pool):
        clear, reg = _make_reg_token(pool)
        reg.revoked_at = timezone.now()
        reg.save()
        with pytest.raises(DomainValidationError) as exc_info:
            register_runner(
                registration_token=clear,
                display_name="r",
                runner_version="0.1.0",
                fingerprint_sha256="fp",
                hostname="h",
                labels={},
                capabilities=[],
            )
        assert exc_info.value.code == "registration_token_revoked"

    def test_exhausted_token_raises(self, pool):
        clear, reg = _make_reg_token(pool, max_reg=1)
        reg.used_count = 1
        reg.save()
        with pytest.raises(DomainValidationError) as exc_info:
            register_runner(
                registration_token=clear,
                display_name="r",
                runner_version="0.1.0",
                fingerprint_sha256="fp",
                hostname="h",
                labels={},
                capabilities=[],
            )
        assert exc_info.value.code == "registration_token_exhausted"

    def test_disabled_pool_raises(self, pool):
        pool.status = "disabled"
        pool.save()
        clear, _ = _make_reg_token(pool)
        with pytest.raises(DomainValidationError) as exc_info:
            register_runner(
                registration_token=clear,
                display_name="r",
                runner_version="0.1.0",
                fingerprint_sha256="fp",
                hostname="h",
                labels={},
                capabilities=[],
            )
        assert exc_info.value.code == "pool_not_active"

    def test_label_policy_filters_unknown_labels(self, pool):
        clear, _ = _make_reg_token(pool, label_policy=["region"])
        runner, _ = register_runner(
            registration_token=clear,
            display_name="r",
            runner_version="0.1.0",
            fingerprint_sha256="fp-lp",
            hostname="h",
            labels={"region": "us-east-1", "secret_tag": "forbidden"},
            capabilities=[],
        )
        assert "secret_tag" not in runner.metadata.get("accepted_labels", {})
        assert runner.metadata["accepted_labels"].get("region") == "us-east-1"

    def test_capability_policy_filters_unknown_capabilities(self, pool):
        clear, _ = _make_reg_token(pool, cap_policy=["action.shell_command"])
        runner, _ = register_runner(
            registration_token=clear,
            display_name="r",
            runner_version="0.1.0",
            fingerprint_sha256="fp-cap",
            hostname="h",
            labels={},
            capabilities=["action.shell_command", "tool.kubectl"],
        )
        accepted = runner.metadata.get("accepted_capabilities", [])
        assert "action.shell_command" in accepted
        assert "tool.kubectl" not in accepted

    def test_re_registration_reactivates_existing_runner(self, pool):
        clear, reg = _make_reg_token(pool, max_reg=2)
        runner1, _ = register_runner(
            registration_token=clear,
            display_name="r1",
            runner_version="0.1.0",
            fingerprint_sha256="fp-reuse",
            hostname="h1",
            labels={},
            capabilities=[],
        )
        runner1.status = Runner.Status.OFFLINE
        runner1.save()

        # New token for re-registration
        clear2, _ = _make_reg_token(pool, max_reg=1)
        runner2, new_token = register_runner(
            registration_token=clear2,
            display_name="r1-updated",
            runner_version="0.2.0",
            fingerprint_sha256="fp-reuse",  # same fingerprint
            hostname="h1-new",
            labels={},
            capabilities=[],
        )
        assert runner2.pk == runner1.pk
        assert runner2.status == Runner.Status.ACTIVE
        assert runner2.runner_version == "0.2.0"
        # Token must be rotated
        assert runner2.token_hash != runner1.token_hash

    def test_registration_emits_audit_event(self, pool):
        clear, _ = _make_reg_token(pool)
        runner, _ = register_runner(
            registration_token=clear,
            display_name="r-audit",
            runner_version="0.1.0",
            fingerprint_sha256="fp-audit",
            hostname="h",
            labels={},
            capabilities=[],
        )
        event = AuditEvent.objects.filter(
            object_type=AuditEvent.ObjectType.RUNNER,
            event_type="runner.registered",
            object_id=runner.id,
        ).first()
        assert event is not None
        assert event.metadata["pool_key"] == pool.key
