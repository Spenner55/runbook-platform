import json
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditEvent


@dataclass(frozen=True)
class AuditActor:
    actor_type: str
    actor_id: str = ""
    actor_label: str = ""


FORBIDDEN_METADATA_KEYS = {
    "api_key",
    "api_token",
    "apikey",
    "apitoken",
    "auth",
    "auth_header",
    "authorization",
    "bearer",
    "bearer_token",
    "change_dispatch_token",
    "claim_token",
    "command",
    "cookie",
    "dispatch_token",
    "dispatch_token_hash",
    "headers",
    "password",
    "private_key",
    "raw_command_output",
    "request_body",
    "request_snapshot",
    "requested_inputs",
    "secret",
    "session",
    "session_token",
    "token",
    "webhook_url",
    "workflow_snapshot",
    "x_api_key",
}

REJECTED_METADATA_KEYS = {
    "change_dispatch_token",
    "dispatch_token",
    "dispatch_token_hash",
    "requested_inputs",
    "request_snapshot",
}

MAX_METADATA_BYTES = 16 * 1024


def actor_from_request(request) -> AuditActor:
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        label = getattr(user, "get_username", lambda: "")() or str(user.pk)
        return AuditActor(
            actor_type=AuditEvent.ActorType.USER,
            actor_id=str(user.pk),
            actor_label=label,
        )
    return AuditActor(
        actor_type=AuditEvent.ActorType.UNKNOWN,
        actor_label="Unauthenticated public API",
    )


def actor_from_runner(runner_id: str) -> AuditActor:
    return AuditActor(
        actor_type=AuditEvent.ActorType.RUNNER,
        actor_id=runner_id,
        actor_label=runner_id,
    )


def system_actor(label: str = "Django system") -> AuditActor:
    return AuditActor(actor_type=AuditEvent.ActorType.SYSTEM, actor_label=label)


class AuditService:
    @staticmethod
    def emit(
        *,
        organization_id,
        actor_type: str,
        event_type: str,
        object_type: str,
        object_id,
        actor_id: str = "",
        actor_label: str = "",
        metadata: dict | None = None,
        occurred_at=None,
    ) -> AuditEvent:
        _validate_choice("actor_type", actor_type, AuditEvent.ActorType.values)
        _validate_choice("object_type", object_type, AuditEvent.ObjectType.values)
        _validate_uuid("organization_id", organization_id)
        _validate_uuid("object_id", object_id)
        _validate_event_type(event_type)

        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValidationError("Audit metadata must be a JSON object.")

        scrubbed_metadata = _scrub_metadata(metadata)
        _validate_metadata_size(scrubbed_metadata)

        return AuditEvent.objects.create(
            organization_id=organization_id,
            actor_type=actor_type,
            actor_id=actor_id or "",
            actor_label=actor_label or "",
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            metadata=scrubbed_metadata,
            occurred_at=occurred_at or timezone.now(),
        )


def _validate_choice(field_name: str, value: str, choices) -> None:
    if value not in choices:
        raise ValidationError(f"Invalid {field_name}: {value}.")


def _validate_uuid(field_name: str, value) -> None:
    if value in (None, ""):
        raise ValidationError(f"{field_name} is required.")
    try:
        UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a UUID.") from exc


def _validate_event_type(event_type: str) -> None:
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValidationError("event_type is required.")
    if len(event_type) > 128:
        raise ValidationError("event_type must be 128 characters or fewer.")


def _scrub_metadata(metadata: dict) -> dict:
    safe = {}
    for key, value in metadata.items():
        key_text = str(key)
        if key_text.lower() in REJECTED_METADATA_KEYS:
            raise ValidationError(
                f"Audit metadata contains forbidden key '{key_text}'."
            )
        if key_text.lower() in FORBIDDEN_METADATA_KEYS:
            continue
        safe[key_text] = _scrub_value(value)
    return safe


def _scrub_value(value):
    if isinstance(value, dict):
        return _scrub_metadata(value)
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    return value


def _validate_metadata_size(metadata: dict) -> None:
    try:
        encoded = json.dumps(metadata)
    except TypeError as exc:
        raise ValidationError("Audit metadata must be JSON serializable.") from exc
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValidationError("Audit metadata must be smaller than 16 KB.")


def emit(*args, **kwargs) -> AuditEvent:
    return AuditService.emit(*args, **kwargs)
