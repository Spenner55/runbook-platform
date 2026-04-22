from django.db import IntegrityError, transaction

from apps.common.exceptions import DomainConflictError
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
