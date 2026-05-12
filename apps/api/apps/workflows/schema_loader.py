"""
Load and cache JSON schemas from packages/workflow-schema.

Path resolution walks up the directory tree looking for the schema package,
then falls back to the container mount at /packages/workflow-schema.
"""

import json
from functools import lru_cache
from pathlib import Path

_WORKFLOW_SCHEMA_FILES = {
    "1": "workflow.schema.json",
    "2": "workflow.v2.schema.json",
}


@lru_cache(maxsize=1)
def _find_schema_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "workflow-schema"
        if candidate.is_dir():
            return candidate
    container = Path("/packages/workflow-schema")
    if container.is_dir():
        return container
    raise RuntimeError("Could not locate packages/workflow-schema directory")


@lru_cache(maxsize=8)
def load_workflow_schema(schema_version: str) -> dict:
    """Return the parsed JSON schema for a workflow schema version ('1' or '2')."""
    filename = _WORKFLOW_SCHEMA_FILES.get(schema_version)
    if filename is None:
        raise ValueError(
            f"Unknown workflow schema version: {schema_version!r}. "
            f"Supported: {sorted(_WORKFLOW_SCHEMA_FILES)}"
        )
    path = _find_schema_dir() / filename
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def load_action_schema(action_type: str, action_version: str) -> dict:
    """Return the parsed JSON schema for a specific action type and version.

    action_version is the catalog version string, e.g. 'pilot.v1'.
    Raises FileNotFoundError if the schema file does not exist.
    Raises json.JSONDecodeError if the schema file is malformed.
    """
    filename = f"{action_type}.{action_version}.schema.json"
    path = _find_schema_dir() / "actions" / filename
    return json.loads(path.read_text(encoding="utf-8"))
