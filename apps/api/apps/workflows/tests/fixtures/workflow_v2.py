"""Shared Pilot Phase B workflow v2 fixtures for backend tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path


def _examples_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "workflow-schema" / "examples"
        if candidate.is_dir():
            return candidate
    candidate = Path("/packages/workflow-schema/examples")
    if candidate.is_dir():
        return candidate
    raise RuntimeError("Could not locate workflow-schema examples directory")


def load_example(name: str) -> dict:
    return json.loads((_examples_dir() / name).read_text())


def valid_v2_shell_command_workflow() -> dict:
    return copy.deepcopy(load_example("workflow-v2-shell-command.valid.json"))


def valid_v2_http_request_workflow() -> dict:
    return copy.deepcopy(load_example("workflow-v2-http-request.valid.json"))


def invalid_secret_ref_workflow() -> dict:
    return copy.deepcopy(load_example("workflow-v2-invalid-secret-ref.json"))
