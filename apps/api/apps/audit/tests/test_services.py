import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.audit.services import AuditService


@pytest.mark.django_db
def test_emit_creates_audit_event(org):
    event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={"initial_status": "queued"},
    )

    assert event.id is not None
    assert event.metadata == {"initial_status": "queued"}


@pytest.mark.django_db
def test_emit_rejects_invalid_actor_type(org):
    with pytest.raises(ValidationError):
        AuditService.emit(
            organization_id=org.id,
            actor_type="robot",
            event_type="execution.created",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=org.id,
            metadata={},
        )


@pytest.mark.django_db
def test_emit_requires_metadata_object(org):
    with pytest.raises(ValidationError):
        AuditService.emit(
            organization_id=org.id,
            actor_type=AuditEvent.ActorType.SYSTEM,
            event_type="execution.created",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=org.id,
            metadata=["not", "an", "object"],
        )


@pytest.mark.django_db
def test_emit_scrubs_sensitive_metadata_keys(org):
    event = AuditService.emit(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.RUNNER,
        actor_id="runner-1",
        actor_label="runner-1",
        event_type="execution.claimed",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={
            "previous_status": "queued",
            "claim_token": "secret",
            "authorization": "Bearer secret",
            "command": "deploy --token secret",
        },
    )

    assert event.metadata == {"previous_status": "queued"}


@pytest.mark.django_db
def test_emit_rejects_non_json_serializable_metadata(org):
    with pytest.raises(ValidationError):
        AuditService.emit(
            organization_id=org.id,
            actor_type=AuditEvent.ActorType.SYSTEM,
            event_type="execution.created",
            object_type=AuditEvent.ObjectType.EXECUTION,
            object_id=org.id,
            metadata={"when": timezone.now()},
        )
