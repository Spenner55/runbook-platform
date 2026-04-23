from django.db import IntegrityError, transaction

from apps.common.exceptions import DomainConflictError, InvalidStateTransitionError
from apps.runbooks.models import Runbook


def create_runbook(*, organization, title: str, slug: str, raw_content: str) -> Runbook:
    try:
        with transaction.atomic():
            return Runbook.objects.create(
                organization=organization,
                title=title,
                slug=slug,
                raw_content=raw_content,
                status=Runbook.Status.DRAFT,
            )
    except IntegrityError as exc:
        raise DomainConflictError(
            code="runbook_slug_conflict",
            detail="A runbook with this slug already exists in the organization.",
            attr="slug",
        ) from exc


def mark_runbook_ready(*, runbook: Runbook) -> Runbook:
    """Transition a draft runbook to ready."""
    if runbook.status != Runbook.Status.DRAFT:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot mark runbook ready with status '{runbook.status}', expected 'draft'.",
        )
    runbook.status = Runbook.Status.READY
    runbook.save(update_fields=["status", "updated_at"])
    return runbook


def archive_runbook(*, runbook: Runbook) -> Runbook:
    """Transition a draft or ready runbook to archived."""
    allowed = {Runbook.Status.DRAFT, Runbook.Status.READY}
    if runbook.status not in allowed:
        raise InvalidStateTransitionError(
            code="invalid_state_transition",
            detail=f"Cannot archive runbook with status '{runbook.status}'.",
        )
    runbook.status = Runbook.Status.ARCHIVED
    runbook.save(update_fields=["status", "updated_at"])
    return runbook
