"""
Action catalog lookup for the pilot workflow engine.

The catalog maps action types to their schema locations and runner requirements.
lookup_action_contract fails closed: unknown type or version raises DomainValidationError.
"""

import json
from functools import lru_cache

from apps.common.exceptions import DomainValidationError
from apps.workflows.schema_loader import _find_schema_dir

_CATALOG_FILES = {
    "pilot.v1": "action-catalog.pilot.v1.json",
}


@lru_cache(maxsize=4)
def _load_catalog(catalog_version: str) -> dict:
    filename = _CATALOG_FILES.get(catalog_version)
    if filename is None:
        raise ValueError(f"Unknown action catalog version: {catalog_version!r}")
    path = _find_schema_dir() / filename
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_action_contract(action_type: str, action_version: str) -> dict:
    """Return the catalog entry for the given action type and catalog version.

    Raises DomainValidationError for any unknown type or version so callers
    cannot silently proceed with an unregistered action.
    """
    try:
        catalog = _load_catalog(action_version)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise DomainValidationError(
            code="unknown_action_catalog_version",
            detail=f"No action catalog registered for version {action_version!r}.",
        ) from exc

    for entry in catalog.get("actions", []):
        if entry.get("type") == action_type:
            return entry

    raise DomainValidationError(
        code="unknown_action_type",
        detail=(
            f"Action type {action_type!r} is not registered in catalog "
            f"version {action_version!r}."
        ),
    )
