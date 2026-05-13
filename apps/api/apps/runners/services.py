import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService
from apps.common.exceptions import DomainValidationError


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_runner_token() -> tuple[str, str]:
    """Return (clear_token, hash). Clear token shown once."""
    clear = secrets.token_hex(32)
    return clear, _hash_token(clear)


def create_registration_token(
    *,
    organization,
    pool,
    expires_at,
    max_registrations: int = 1,
    label_policy: list | None = None,
    capability_policy: list | None = None,
    created_by=None,
):
    """Create a bootstrap registration token and return (token_record, clear_token)."""
    from apps.runners.models import RunnerRegistrationToken

    if pool.organization_id != organization.id:
        raise DomainValidationError(
            code="registration_scope_mismatch",
            detail="Registration token pool must belong to the supplied organization.",
        )

    clear_token, token_hash = generate_runner_token()
    registration_token = RunnerRegistrationToken.objects.create(
        organization=organization,
        pool=pool,
        token_hash=token_hash,
        expires_at=expires_at,
        max_registrations=max_registrations,
        label_policy=label_policy or [],
        capability_policy=capability_policy or [],
        created_by=created_by,
    )
    return registration_token, clear_token


@transaction.atomic
def validate_registration_token(
    *,
    registration_token: str,
    organization_id: str = "",
    pool_key: str = "",
):
    """Resolve and validate a bootstrap registration token under row lock."""
    from apps.runners.models import RunnerPool, RunnerRegistrationToken

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
    if organization_id and str(reg_token.organization_id) != str(organization_id):
        raise DomainValidationError(
            code="registration_scope_mismatch",
            detail="Registration token is not valid for this organization.",
        )
    if pool_key and reg_token.pool.key != pool_key:
        raise DomainValidationError(
            code="registration_scope_mismatch",
            detail="Registration token is not valid for this runner pool.",
        )
    if reg_token.pool.organization_id != reg_token.organization_id:
        raise DomainValidationError(
            code="registration_scope_mismatch",
            detail="Registration token pool does not belong to its organization.",
        )
    if reg_token.pool.status != RunnerPool.Status.ACTIVE:
        raise DomainValidationError(
            code="pool_not_active",
            detail=(
                f"Runner pool '{reg_token.pool.key}' is not active "
                f"(status: {reg_token.pool.status})."
            ),
        )

    return reg_token


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
    organization_id: str = "",
    pool_key: str = "",
) -> tuple:
    """Validate the registration token, create or reactivate a Runner, rotate its bearer token.

    Returns (runner, clear_bearer_token).
    Raises DomainValidationError on invalid/expired/revoked token.
    """
    from apps.runners.models import Runner

    now = timezone.now()
    reg_token = validate_registration_token(
        registration_token=registration_token,
        organization_id=organization_id,
        pool_key=pool_key,
    )
    pool = reg_token.pool

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
        existing.metadata = {
            "accepted_labels": accepted_labels,
            "accepted_capabilities": accepted_capabilities,
        }
        existing.save(
            update_fields=[
                "status",
                "token_hash",
                "runner_version",
                "hostname",
                "display_name",
                "last_seen_at",
                "last_heartbeat_at",
                "metadata",
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
