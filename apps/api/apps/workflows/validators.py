"""
Workflow definition validators, branched by definition_schema_version.

Public API
----------
validate_workflow_definition(definition, schema_version)
    Validates *definition* according to *schema_version*.
    Raises InvalidWorkflowDefinitionError on any structural or semantic failure.
    Fails closed for unknown schema versions.

v1 path: delegates to the existing services-layer validators (unchanged).
v2 path: structural JSON-schema check + comprehensive semantic validation.
"""

import re

import jsonschema

from apps.common.exceptions import InvalidWorkflowDefinitionError
from apps.workflows.schema_loader import load_action_schema, load_workflow_schema

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUPPORTED_CATALOG_VERSIONS = frozenset({"pilot.v1"})
_DEFAULT_CATALOG_VERSION = "pilot.v1"

# Control-plane-only action types that never touch a runner target.
_CONTROL_PLANE_ONLY = frozenset({"manual_task", "approval_gate"})

# Heuristic patterns that suggest a raw secret value rather than a safe string.
# Conservative: we only match patterns that are very unlikely to appear in
# legitimate non-secret strings.
_SECRET_PATTERNS = re.compile(
    r"(?x)"
    r"(?:"
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"  # Bearer <token>
    r"|Token\s+[A-Za-z0-9\-._~+/]+=*"  # Token <token>
    r"|ghp_[A-Za-z0-9]{36}"  # GitHub personal access token
    r"|ghs_[A-Za-z0-9]{36}"  # GitHub server-to-server token
    r"|sk-[A-Za-z0-9]{48}"  # OpenAI API key
    r"|xox[bpoa]-[0-9]+-[A-Za-z0-9\-]+"  # Slack token
    r"|ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r")"
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def validate_workflow_definition(definition: dict, schema_version: str) -> None:
    """
    Validate *definition* for the given *schema_version*.

    schema_version values accepted:
        "workflow.schema.v1" — delegates to existing v1 validators
        "workflow.schema.v2" — new structural + semantic v2 checks
        anything else        — fails closed with InvalidWorkflowDefinitionError
    """
    if schema_version == "workflow.schema.v1":
        _validate_v1(definition)
    elif schema_version == "workflow.schema.v2":
        _validate_v2(definition)
    else:
        raise InvalidWorkflowDefinitionError(
            code="unsupported_schema_version",
            detail=(
                f"Workflow schema version {schema_version!r} is not supported. "
                "Supported: 'workflow.schema.v1', 'workflow.schema.v2'."
            ),
        )


# ---------------------------------------------------------------------------
# v1 path (delegates; never changes)
# ---------------------------------------------------------------------------


def _validate_v1(definition: dict) -> None:
    from apps.workflows.services import _validate_workflow_definition as _v1

    _v1(definition)


# ---------------------------------------------------------------------------
# v2 path
# ---------------------------------------------------------------------------


def _validate_v2(definition: dict) -> None:
    _v2_json_schema(definition)
    _v2_semantics(definition)


def _v2_json_schema(definition: dict) -> None:
    schema = load_workflow_schema("2")
    try:
        jsonschema.Draft7Validator(schema).validate(definition)
    except jsonschema.ValidationError as exc:
        raise InvalidWorkflowDefinitionError(
            code="workflow_schema_violation",
            detail=f"Workflow v2 definition does not conform to schema: {exc.message}",
        ) from exc


def _v2_semantics(definition: dict) -> None:
    """Semantic invariants not expressible in (or not yet enforced by) the JSON schema."""
    _check_catalog_version(definition)
    step_ids = _check_steps(definition)
    _check_secret_declarations(definition, step_ids)


# ---------------------------------------------------------------------------
# Semantic sub-checks
# ---------------------------------------------------------------------------


def _check_catalog_version(definition: dict) -> None:
    catalog_version = definition.get("catalogVersion", _DEFAULT_CATALOG_VERSION)
    if catalog_version not in _SUPPORTED_CATALOG_VERSIONS:
        raise InvalidWorkflowDefinitionError(
            code="unsupported_catalog_version",
            detail=(
                f"catalogVersion {catalog_version!r} is not supported. "
                f"Supported: {sorted(_SUPPORTED_CATALOG_VERSIONS)}."
            ),
        )


def _check_steps(definition: dict) -> set[str]:
    """
    Validate all steps.  Returns the set of step IDs (already deduplication-checked).
    """
    catalog_version = definition.get("catalogVersion", _DEFAULT_CATALOG_VERSION)
    steps = definition.get("steps", [])

    seen_ids: set[str] = set()
    all_artifact_keys: set[str] = set()

    for pos, step in enumerate(steps, 1):
        step_id = step.get("id", f"<position {pos}>")

        # --- unique step IDs ---
        if step_id in seen_ids:
            raise InvalidWorkflowDefinitionError(
                code="duplicate_step_id",
                detail=f"Duplicate step id '{step_id}' in workflow definition.",
            )
        seen_ids.add(step_id)

        action = step.get("action", {})
        _check_action_type_match(step_id, step, action)
        _check_action_catalog(step_id, action, catalog_version)
        _check_action_inputs(step_id, action, catalog_version)
        _check_step_secrets(step_id, step, definition)
        _check_step_artifacts(step_id, step, all_artifact_keys)
        _check_retry_idempotency(step_id, step)
        _check_dry_run(step_id, step)
        _check_pilot_restrictions(step_id, step, action)

    return seen_ids


def _check_action_type_match(step_id: str, step: dict, action: dict) -> None:
    step_type = step.get("type", "")
    action_type = action.get("type", "")
    if step_type != action_type:
        raise InvalidWorkflowDefinitionError(
            code="action_type_mismatch",
            detail=(
                f"Step '{step_id}': step.type '{step_type}' does not match "
                f"action.type '{action_type}'."
            ),
        )


def _check_action_catalog(step_id: str, action: dict, catalog_version: str) -> None:
    """Verify action type is registered in the catalog."""
    from apps.common.exceptions import DomainValidationError
    from apps.workflows.action_catalog import lookup_action_contract

    action_type = action.get("type", "")
    action_version = action.get("version", catalog_version)

    try:
        lookup_action_contract(action_type, action_version)
    except DomainValidationError as exc:
        raise InvalidWorkflowDefinitionError(
            code=exc.code,
            detail=f"Step '{step_id}': {exc.detail}",
        ) from exc


def _check_action_inputs(step_id: str, action: dict, catalog_version: str) -> None:
    """Validate action params/inputs against the action-specific JSON schema."""
    action_type = action.get("type", "")
    action_version = action.get("version", catalog_version)

    # Support both 'params' (current format) and 'inputs' (blueprint format).
    payload = action.get("params") or action.get("inputs")
    if payload is None:
        return  # No payload to validate (e.g. manual_task with no params).

    try:
        action_schema = load_action_schema(action_type, action_version)
    except (FileNotFoundError, OSError) as exc:
        raise InvalidWorkflowDefinitionError(
            code="unknown_action_schema",
            detail=(
                f"Step '{step_id}': cannot load schema for action "
                f"'{action_type}:{action_version}'."
            ),
        ) from exc

    # Action schemas define a top-level 'params' or 'inputs' sub-schema.
    params_schema = action_schema.get("properties", {}).get(
        "params"
    ) or action_schema.get("properties", {}).get("inputs")
    if params_schema is None:
        return

    try:
        jsonschema.Draft7Validator(params_schema).validate(payload)
    except jsonschema.ValidationError as exc:
        raise InvalidWorkflowDefinitionError(
            code="action_input_invalid",
            detail=(
                f"Step '{step_id}': action '{action_type}' params/inputs "
                f"failed validation: {exc.message}."
            ),
        ) from exc


def _check_step_secrets(step_id: str, step: dict, definition: dict) -> None:
    """Step-level secret references must exist in the top-level declarations."""
    declared_keys = {s.get("key", "") for s in definition.get("secrets", [])}
    for ref in step.get("secrets", []):
        if ref not in declared_keys:
            raise InvalidWorkflowDefinitionError(
                code="unknown_secret_reference",
                detail=(
                    f"Step '{step_id}' references undeclared secret '{ref}'. "
                    "Declare it in the top-level 'secrets' array."
                ),
            )


def _check_step_artifacts(
    step_id: str, step: dict, all_artifact_keys: set[str]
) -> None:
    """Artifact keys must be unique across the workflow; paths must be safe."""
    for artifact in step.get("artifacts", []):
        key = artifact.get("key", "")
        if key in all_artifact_keys:
            raise InvalidWorkflowDefinitionError(
                code="duplicate_artifact_key",
                detail=(
                    f"Artifact key '{key}' is declared more than once "
                    "across workflow steps."
                ),
            )
        all_artifact_keys.add(key)

        kind = artifact.get("kind", "")
        path = artifact.get("path")

        # file and report artifacts require a path; stdout/stderr/log do not.
        if kind in ("file", "report") or path is not None:
            _validate_artifact_path(step_id, key, path)


def _validate_artifact_path(step_id: str, artifact_key: str, path) -> None:
    if path is None or path == "":
        raise InvalidWorkflowDefinitionError(
            code="invalid_artifact_path",
            detail=(
                f"Step '{step_id}', artifact '{artifact_key}': "
                "path is required for file/report artifacts."
            ),
        )
    path_str = str(path)
    if path_str.startswith("/"):
        raise InvalidWorkflowDefinitionError(
            code="invalid_artifact_path",
            detail=(
                f"Step '{step_id}', artifact '{artifact_key}': "
                "absolute paths are not allowed."
            ),
        )
    parts = path_str.replace("\\", "/").split("/")
    if ".." in parts:
        raise InvalidWorkflowDefinitionError(
            code="invalid_artifact_path",
            detail=(
                f"Step '{step_id}', artifact '{artifact_key}': "
                "path traversal ('..') is not allowed."
            ),
        )
    if path_str.startswith("~") or path_str.startswith("//"):
        raise InvalidWorkflowDefinitionError(
            code="invalid_artifact_path",
            detail=(
                f"Step '{step_id}', artifact '{artifact_key}': "
                f"path '{path_str}' is not allowed."
            ),
        )


def _check_retry_idempotency(step_id: str, step: dict) -> None:
    retry = step.get("retry")
    idempotency = step.get("idempotency")

    if retry is not None:
        max_attempts = retry.get("maxAttempts", 1)
        if max_attempts > 1:
            idempotency_mode = (idempotency or {}).get("mode", "none")
            if idempotency_mode == "none":
                raise InvalidWorkflowDefinitionError(
                    code="retry_requires_idempotency",
                    detail=(
                        f"Step '{step_id}': retry.maxAttempts={max_attempts} requires "
                        "idempotency.mode other than 'none'."
                    ),
                )

    if idempotency is not None:
        mode = idempotency.get("mode", "")
        if mode == "keyed" and not idempotency.get("key", ""):
            raise InvalidWorkflowDefinitionError(
                code="keyed_idempotency_requires_key",
                detail=(
                    f"Step '{step_id}': idempotency.mode='keyed' "
                    "requires a non-empty 'key'."
                ),
            )


def _check_dry_run(step_id: str, step: dict) -> None:
    dry_run = step.get("dryRun")
    if dry_run is None:
        return
    strategy = dry_run.get("strategy", "")
    valid = {"native", "validate_only", "mock", "unsupported"}
    if strategy not in valid:
        raise InvalidWorkflowDefinitionError(
            code="invalid_dry_run_strategy",
            detail=(
                f"Step '{step_id}': unknown dry-run strategy '{strategy}'. "
                f"Valid strategies: {sorted(valid)}."
            ),
        )


def _check_pilot_restrictions(step_id: str, step: dict, action: dict) -> None:
    step_type = step.get("type", "")
    params = action.get("params") or action.get("inputs") or {}

    if step_type == "shell_command":
        _check_shell_command_restrictions(step_id, params)
    elif step_type == "http_request":
        _check_http_request_restrictions(step_id, params)


def _check_shell_command_restrictions(step_id: str, params: dict) -> None:
    for env_key, env_val in params.get("environment", {}).items():
        if isinstance(env_val, str) and _looks_like_secret(env_val):
            raise InvalidWorkflowDefinitionError(
                code="raw_secret_in_environment",
                detail=(
                    f"Step '{step_id}': environment variable '{env_key}' appears "
                    "to contain a raw secret value. Use top-level secret declarations "
                    "and step-level secret references instead."
                ),
            )

    working_dir = params.get("working_directory", "")
    if working_dir:
        if working_dir.startswith("/"):
            raise InvalidWorkflowDefinitionError(
                code="invalid_working_directory",
                detail=(
                    f"Step '{step_id}': working_directory must be a relative path, "
                    "not an absolute path."
                ),
            )
        if ".." in working_dir.replace("\\", "/").split("/"):
            raise InvalidWorkflowDefinitionError(
                code="invalid_working_directory",
                detail=(f"Step '{step_id}': working_directory must not contain '..'."),
            )


def _check_http_request_restrictions(step_id: str, params: dict) -> None:
    url = params.get("url", "")
    if url and not (url.startswith("https://") or url.startswith("http://")):
        raise InvalidWorkflowDefinitionError(
            code="invalid_request_url",
            detail=(
                f"Step '{step_id}': http_request URL must be absolute "
                "(start with https:// or http://)."
            ),
        )

    for header_key, header_val in params.get("headers", {}).items():
        if isinstance(header_val, str) and _looks_like_secret(header_val):
            raise InvalidWorkflowDefinitionError(
                code="raw_secret_in_header",
                detail=(
                    f"Step '{step_id}': header '{header_key}' appears to contain "
                    "a raw secret value. Use top-level secret declarations instead."
                ),
            )


def _check_secret_declarations(definition: dict, step_ids: set[str]) -> None:
    """Top-level secret declarations must have unique keys; requiredBy must reference known steps."""
    seen_keys: set[str] = set()
    for secret in definition.get("secrets", []):
        key = secret.get("key", "")
        if key in seen_keys:
            raise InvalidWorkflowDefinitionError(
                code="duplicate_secret_key",
                detail=f"Duplicate secret key '{key}' in top-level declarations.",
            )
        seen_keys.add(key)

        for ref_step in secret.get("requiredBy", []):
            if ref_step not in step_ids:
                raise InvalidWorkflowDefinitionError(
                    code="unknown_step_reference",
                    detail=(
                        f"Secret '{key}' requiredBy references unknown step id "
                        f"'{ref_step}'."
                    ),
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _looks_like_secret(value: str) -> bool:
    """
    Heuristic: return True if *value* looks like a raw secret token.

    This is deliberately conservative to limit false positives.  Pattern-matched
    formats are chosen because they are essentially never found in safe strings:
    JWT, GitHub PATs, OpenAI keys, Slack tokens, and explicit Bearer/Token prefixes.
    """
    if len(value) < 20:
        return False
    return bool(_SECRET_PATTERNS.search(value))
