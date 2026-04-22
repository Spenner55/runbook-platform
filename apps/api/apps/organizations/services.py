from apps.organizations.models import Organization


def create_organization(*, name: str, slug: str) -> Organization:
    """Create a new organization."""
    return Organization.objects.create(name=name, slug=slug)
