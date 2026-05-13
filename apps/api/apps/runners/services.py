import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService, system_actor
from apps.common.exceptions import DomainValidationError


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_runner_token() -> tuple[str, str]:
    """Return (clear_token, hash). Clear token shown once."""
    clear = secrets.token_hex(32)
    return clear, _hash_token(clear)


@transaction.atomic
def register_runner(
    *,
    registration_token: str,
    display_name: str,
    runner_version: str,
    fingerprint_sha256: str,
    hostname: str,
    labels: dict,
    capabilities: list,
) -> tuple:
    """Validate the registration token, create or reactivate a Runner, rotate its bearer token.

    Returns (runner, clear_bearer_token).
    Raises DomainValidationError on invalid/expired/revoked token.
    """
    from apps.runners.models import Runner, RunnerRegistrationToken

    now = timezone.now()
    token_hash = _hash_token(registration_token)

    try:
        reg_token = RunnerRegistrationToken.objects.select_for_update().select_related(
            "pool", "organization"
        ).get(token_hash=token_hash)
    except RunnerRegistrationToken.DoesNotExist:
        raise DomainValidationError(
            code="invalid_registration_token",
            detail="Registration token is invalid.",
        )

    if reg_token.revoked_at is not None:
        raise DomainValidationError(
            code="registration_token_revoked",
            detail="Registration token has been revoked.",
        )
    if reg_token.expires_at < now:
        raise DomainValidationError(
            code="registration_token_expired",
            detail="Registration token has expired.",
        )
    if reg_token.used_count >= reg_token.max_registrations:
        raise DomainValidationError(
            code="registration_token_exhausted",
            detail="Registration token has reached its maximum use count.",
        )

    pool = reg_token.pool
    if pool.status != "active":
        raise DomainValidationError(
            code="pool_not_active",
            detail=f"Runner pool '{pool.key}' is not active (status: {pool.status}).",
        )

    # Filter labels and capabilities to only allowed values (silently drop extras).
    allowed_labels_keys = set(reg_token.label_policy) if reg_token.label_policy else None
    if allowed_labels_keys is not None:
        accepted_labels = {k: v for k, v in labels.items() if k in allowed_labels_keys}
    else:
        accepted_labels = labels

    allowed_caps = set(reg_token.capability_policy) if reg_token.capability_policy else None
    if allowed_caps is not None:
        accepted_capabilities = [c for c in capabilities if c in allowed_caps]
    else:
        accepted_capabilities = capabilities

    clear_token, new_token_hash = generate_runner_token()

    # Check for existing runner with same fingerprint in same pool.
    existing = None
    if fingerprint_sha256:
        existing = (
            Runner.objects.filter(
                pool=pool,
                fingerprint_sha256=fingerprint_sha256,
            )
            .exclude(status=Runner.Status.REVOKED)
            .first()
        )

    if existing is not None:
        existing.status = Runner.Status.ACTIVE
        existing.token_hash = new_token_hash
        existing.runner_version = runner_version
        existing.hostname = hostname
        existing.display_name = display_name
        existing.last_seen_at = now
        existing.last_heartbeat_at = now
        existing.save(
            update_fields=[
                "status",
                "token_hash",
                "runner_version",
                "hostname",
                "display_name",
                "last_seen_at",
                "last_heartbeat_at",
                "updated_at",
            ]
        )
        runner = existing
    else:
        runner = Runner.objects.create(
            organization=reg_token.organization,
            pool=pool,
            display_name=display_name,
            status=Runner.Status.ACTIVE,
            runner_version=runner_version,
            hostname=hostname,
            fingerprint_sha256=fingerprint_sha256,
            token_hash=new_token_hash,
            registered_at=now,
            last_seen_at=now,
            last_heartbeat_at=now,
            metadata={"accepted_labels": accepted_labels, "accepted_capabilities": accepted_capabilities},
        )

    reg_token.used_count += 1
    reg_token.save(update_fields=["used_count", "updated_at"])

    actor = system_actor("Runner registration")
    AuditService.emit(
        organization_id=reg_token.organization_id,
        actor_type=AuditEvent.ActorType.RUNNER,
        actor_id=str(runner.id),
        actor_label=runner.display_name,
        event_type="runner.registered",
        object_type=AuditEvent.ObjectType.RUNNER,
        object_id=runner.id,
        metadata={
            "pool_key": pool.key,
            "pool_id": str(pool.id),
            "runner_version": runner_version,
            "hostname": hostname,
        },
    )

    return runner, clear_token


def update_runner_heartbeat(
    *,
    runner,
    runner_version: str = "",
    hostname: str = "",
    current_execution_count: int = 0,
    observed_pool_key: str = "",
    capabilities_checksum: str = "",
):
    """Update runner liveness fields. Does not extend execution leases."""
    from apps.runners.models import Runner

    now = timezone.now()
    update_fields = ["last_heartbeat_at", "last_seen_at", "updated_at"]

    runner.last_heartbeat_at = now
    runner.last_seen_at = now

    if runner_version and runner_version != runner.runner_version:
        runner.runner_version = runner_version
        update_fields.append("runner_version")

    if hostname and hostname != runner.hostname:
        runner.hostname = hostname
        update_fields.append("hostname")

    if runner.status == Runner.Status.REGISTERED:
        runner.status = Runner.Status.ACTIVE
        update_fields.append("status")

    runner.save(update_fields=update_fields)
    return runner
