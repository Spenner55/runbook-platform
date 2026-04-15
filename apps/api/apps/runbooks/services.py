from apps.runbooks.models import Runbook


def create_runbook(*, organization, title: str, slug: str, raw_content: str) -> Runbook:
    """Create a new runbook in draft status."""
    return Runbook.objects.create(
        organization=organization,
        title=title,
        slug=slug,
        raw_content=raw_content,
        status=Runbook.Status.DRAFT,
    )
