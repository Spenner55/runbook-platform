import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit.models import AuditEvent


@pytest.mark.django_db
def test_audit_event_cannot_be_updated(org):
    event = AuditEvent.objects.create(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={},
        occurred_at=timezone.now(),
    )

    event.actor_label = "changed"
    with pytest.raises(ValidationError):
        event.save()


@pytest.mark.django_db
def test_audit_event_cannot_be_deleted(org):
    event = AuditEvent.objects.create(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={},
        occurred_at=timezone.now(),
    )

    with pytest.raises(ValidationError):
        event.delete()


@pytest.mark.django_db
def test_audit_event_queryset_cannot_be_deleted(org):
    AuditEvent.objects.create(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={},
        occurred_at=timezone.now(),
    )

    with pytest.raises(ValidationError):
        AuditEvent.objects.all().delete()


@pytest.mark.django_db
def test_audit_event_queryset_cannot_be_updated(org):
    AuditEvent.objects.create(
        organization_id=org.id,
        actor_type=AuditEvent.ActorType.SYSTEM,
        event_type="execution.created",
        object_type=AuditEvent.ObjectType.EXECUTION,
        object_id=org.id,
        metadata={},
        occurred_at=timezone.now(),
    )

    with pytest.raises(ValidationError):
        AuditEvent.objects.all().update(actor_label="tampered")
