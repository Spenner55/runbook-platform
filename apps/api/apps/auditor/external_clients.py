"""External reference refresh boundary.

Search and detail selectors must not import this module.  It exists only for
explicit refresh service calls where an operator has requested a fresh snapshot.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExternalSnapshot:
    snapshot: dict
    external_key: str = ""
    external_url: str = ""
    display_label: str = ""


class ExternalReferenceClient(Protocol):
    def fetch_snapshot(self, *, reference) -> ExternalSnapshot:
        """Return a bounded snapshot for an existing external reference."""


class ExternalReferenceRefreshUnavailable(Exception):
    """Raised when no explicit refresh client is configured for the reference."""


def get_refresh_client(*, system: str) -> ExternalReferenceClient:
    raise ExternalReferenceRefreshUnavailable(
        f"No external reference refresh client configured for {system}."
    )
