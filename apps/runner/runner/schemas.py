"""Typed request/response schemas for the runner <-> Django API contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    model_validator,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


_VALID_EXECUTION_MODES = frozenset({"simulated", "sandboxed"})
_KNOWN_SANDBOX_PROVIDERS = frozenset({"local_process"})
_VALID_CLEANUP_POLICIES = frozenset({"always", "on_success", "never"})

_SANDBOX_NUMERIC_FIELDS: list[tuple[str, str]] = [
    ("sandbox_default_timeout_seconds", "RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS"),
    ("sandbox_stdout_max_bytes", "RUNNER_SANDBOX_STDOUT_MAX_BYTES"),
    ("sandbox_stderr_max_bytes", "RUNNER_SANDBOX_STDERR_MAX_BYTES"),
    ("sandbox_artifact_max_bytes", "RUNNER_SANDBOX_ARTIFACT_MAX_BYTES"),
    ("sandbox_max_artifacts_per_step", "RUNNER_SANDBOX_MAX_ARTIFACTS_PER_STEP"),
]


class RunnerSettings(BaseModel):
    api_base_url: str
    runner_id: str
    runner_version: str = "0.1.0"
    registration_token: str = ""
    registered_runner_id: str = ""
    runner_bearer_token: str = ""
    runner_display_name: str = ""
    runner_install_fingerprint: str = ""
    runner_state_file: str = ""
    api_retries_enabled: bool = True
    poll_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 10
    fake_step_delay_seconds: float = 1.0
    log_level: str = "INFO"

    # Sandbox settings
    execution_mode: str = "simulated"
    sandbox_provider: str = "local_process"
    sandbox_workspace_root: str = "/tmp/runner-workspaces"
    sandbox_cleanup_policy: str = "always"
    sandbox_default_timeout_seconds: int = 300
    sandbox_stdout_max_bytes: int = 5_242_880
    sandbox_stderr_max_bytes: int = 5_242_880
    sandbox_artifact_max_bytes: int = 52_428_800
    sandbox_max_artifacts_per_step: int = 10
    sandbox_allowed_env_prefixes: list[str] = []
    sandbox_allowed_env_names: list[str] = []
    sandbox_shell_path: str = "/bin/sh"
    sandbox_allow_shell: bool = False

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_registration_token(self) -> RunnerSettings:
        # Allow empty/placeholder only when runner_bearer_token is already set
        # (post-registration mode).
        if not self.runner_bearer_token and self.registration_token.strip() in {"", "change-me"}:
            raise ValueError(
                "RUNNER_REGISTRATION_TOKEN must be set to a non-placeholder value, "
                "or RUNNER_BEARER_TOKEN must be set (post-registration mode)."
            )
        return self

    def validate_for_startup(self) -> None:
        """Raise SystemExit(1) with clear messages if required config is missing."""
        import os
        import sys
        from pathlib import Path

        errors: list[str] = []

        # Core connectivity
        if not self.api_base_url.strip():
            errors.append("API_BASE_URL is empty — set it to the Django API base URL")
        if not self.runner_id.strip():
            errors.append("RUNNER_ID is empty — set it to a unique runner identifier")
        # In legacy mode: registration_token is used directly as bearer.
        # In registered mode: runner_bearer_token takes precedence.
        if not self.runner_bearer_token and self.registration_token.strip() in {"", "change-me"}:
            errors.append(
                "RUNNER_REGISTRATION_TOKEN must not be empty or the placeholder 'change-me'"
            )

        # Execution mode
        execution_mode = getattr(self, "execution_mode", "simulated")
        if execution_mode not in _VALID_EXECUTION_MODES:
            errors.append(
                f"RUNNER_EXECUTION_MODE must be one of {sorted(_VALID_EXECUTION_MODES)},"
                f" got {execution_mode!r}"
            )

        # Sandbox provider
        sandbox_provider = getattr(self, "sandbox_provider", "local_process")
        if sandbox_provider not in _KNOWN_SANDBOX_PROVIDERS:
            errors.append(
                f"RUNNER_SANDBOX_PROVIDER {sandbox_provider!r} is not known."
                f" Available: {sorted(_KNOWN_SANDBOX_PROVIDERS)}"
            )

        # Cleanup policy
        cleanup_policy = getattr(self, "sandbox_cleanup_policy", "always")
        if cleanup_policy not in _VALID_CLEANUP_POLICIES:
            errors.append(
                f"RUNNER_SANDBOX_CLEANUP_POLICY must be one of {sorted(_VALID_CLEANUP_POLICIES)},"
                f" got {cleanup_policy!r}"
            )

        # Numeric limits must be positive
        for field_name, env_name in _SANDBOX_NUMERIC_FIELDS:
            val = getattr(self, field_name, 1)
            if not isinstance(val, int) or val <= 0:
                errors.append(f"{env_name} must be a positive integer, got {val!r}")

        # Workspace root: must exist or be creatable/writable
        workspace_root_str = getattr(
            self, "sandbox_workspace_root", "/tmp/runner-workspaces"
        )
        if workspace_root_str:
            workspace_root = Path(workspace_root_str)
            if workspace_root.exists():
                if not os.access(str(workspace_root), os.W_OK):
                    errors.append(
                        f"RUNNER_SANDBOX_WORKSPACE_ROOT {workspace_root} exists but is not writable"
                    )
            else:
                try:
                    workspace_root.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    errors.append(
                        f"RUNNER_SANDBOX_WORKSPACE_ROOT {workspace_root} cannot be created: {exc}"
                    )

        # Shell path must exist when shell execution is enabled
        allow_shell = getattr(self, "sandbox_allow_shell", False)
        shell_path_str = getattr(self, "sandbox_shell_path", "/bin/sh")
        if allow_shell and shell_path_str and not Path(shell_path_str).exists():
            errors.append(
                f"RUNNER_SANDBOX_SHELL_PATH {shell_path_str!r} does not exist"
                " (required when RUNNER_SANDBOX_ALLOW_SHELL=true)"
            )

        if errors:
            for msg in errors:
                print(f"CRITICAL startup validation failed: {msg}", file=sys.stderr)
            raise SystemExit(1)

    @classmethod
    def from_env(cls) -> RunnerSettings:
        import os

        def _env_bool(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def _env_list(name: str) -> list[str]:
            raw = os.environ.get(name, "")
            if not raw.strip():
                return []
            return [item.strip() for item in raw.split(",") if item.strip()]

        return cls(
            api_base_url=os.environ.get("API_BASE_URL", "http://api:8000"),
            runner_id=os.environ.get(
                "RUNNER_ID", os.environ.get("HOSTNAME", "runner-dev")
            ),
            runner_version=os.environ.get("RUNNER_VERSION", "0.1.0"),
            registration_token=os.environ.get("RUNNER_REGISTRATION_TOKEN", ""),
            registered_runner_id=os.environ.get("RUNNER_REGISTERED_ID", ""),
            runner_bearer_token=os.environ.get("RUNNER_BEARER_TOKEN", ""),
            runner_display_name=os.environ.get("RUNNER_DISPLAY_NAME", ""),
            runner_install_fingerprint=os.environ.get("RUNNER_INSTALL_FINGERPRINT", ""),
            runner_state_file=os.environ.get("RUNNER_STATE_FILE", ""),
            api_retries_enabled=_env_bool("RUNNER_API_RETRIES_ENABLED", True),
            poll_interval_seconds=int(
                os.environ.get("RUNNER_POLL_INTERVAL_SECONDS", "5")
            ),
            heartbeat_interval_seconds=int(
                os.environ.get("RUNNER_HEARTBEAT_INTERVAL_SECONDS", "10")
            ),
            fake_step_delay_seconds=float(
                os.environ.get("RUNNER_FAKE_STEP_DELAY_SECONDS", "1.0")
            ),
            log_level=os.environ.get("RUNNER_LOG_LEVEL", "INFO"),
            execution_mode=os.environ.get("RUNNER_EXECUTION_MODE", "simulated"),
            sandbox_provider=os.environ.get("RUNNER_SANDBOX_PROVIDER", "local_process"),
            sandbox_workspace_root=os.environ.get(
                "RUNNER_SANDBOX_WORKSPACE_ROOT", "/tmp/runner-workspaces"
            ),
            sandbox_cleanup_policy=os.environ.get(
                "RUNNER_SANDBOX_CLEANUP_POLICY", "always"
            ),
            sandbox_default_timeout_seconds=int(
                os.environ.get("RUNNER_SANDBOX_DEFAULT_TIMEOUT_SECONDS", "300")
            ),
            sandbox_stdout_max_bytes=int(
                os.environ.get("RUNNER_SANDBOX_STDOUT_MAX_BYTES", str(5_242_880))
            ),
            sandbox_stderr_max_bytes=int(
                os.environ.get("RUNNER_SANDBOX_STDERR_MAX_BYTES", str(5_242_880))
            ),
            sandbox_artifact_max_bytes=int(
                os.environ.get("RUNNER_SANDBOX_ARTIFACT_MAX_BYTES", str(52_428_800))
            ),
            sandbox_max_artifacts_per_step=int(
                os.environ.get("RUNNER_SANDBOX_MAX_ARTIFACTS_PER_STEP", "10")
            ),
            sandbox_allowed_env_prefixes=_env_list(
                "RUNNER_SANDBOX_ALLOWED_ENV_PREFIXES"
            ),
            sandbox_allowed_env_names=_env_list("RUNNER_SANDBOX_ALLOWED_ENV_NAMES"),
            sandbox_shell_path=os.environ.get("RUNNER_SANDBOX_SHELL_PATH", "/bin/sh"),
            sandbox_allow_shell=_env_bool("RUNNER_SANDBOX_ALLOW_SHELL", False),
        )


# ---------------------------------------------------------------------------
# Step action / metadata sub-models (v2 workflow definitions)
# ---------------------------------------------------------------------------


class RetrySpec(BaseModel):
    max_attempts: int = Field(alias="maxAttempts")
    backoff_seconds: int = Field(0, alias="backoffSeconds")
    retry_on: list[str] = Field(default_factory=list, alias="retryOn")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class IdempotencySpec(BaseModel):
    mode: str
    key: str = ""
    reason: str = ""

    model_config = ConfigDict(extra="ignore")


class ArtifactDeclaration(BaseModel):
    key: str
    name: str = ""
    path: str = ""
    kind: str = ""
    mime_type: str = Field("", alias="mimeType")
    required: bool = False
    max_bytes: int | None = Field(None, alias="maxBytes")
    content_disposition: str = Field("", alias="contentDisposition")
    evidence_role: str = Field("", alias="evidenceRole")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ActionSnapshot(BaseModel):
    type: str
    version: str = ""
    params: dict[str, Any] = {}
    inputs: dict[str, Any] = {}
    outputs: dict[str, Any] = {}

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


class ClaimNextRequest(BaseModel):
    runner_id: str
    runner_version: str = "0.1.0"
    requested_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class ClaimedStep(BaseModel):
    id: UUID
    position: int
    step_key: str
    name: str
    step_type: str
    risk_level: str
    command: str = ""
    requires_approval: bool = False
    status: Literal[
        "pending", "waiting_for_approval", "running", "succeeded", "failed", "skipped"
    ]
    step_snapshot: dict[str, Any] = {}
    # v2 action fields — None for v1 steps
    action_snapshot: ActionSnapshot | None = None
    timeout_seconds: int | None = None
    retry: RetrySpec | None = None
    idempotency: IdempotencySpec | None = None
    artifacts: list[ArtifactDeclaration] = []
    secret_keys: list[str] = []

    model_config = ConfigDict(extra="ignore")


class ClaimedVerificationKey(BaseModel):
    check_key: str
    verification_key: str = ""
    step_key: str = ""
    check_type: str = ""

    model_config = ConfigDict(extra="ignore")


class BreakglassSessionFacts(BaseModel):
    """Informational breakglass facts included in claimed execution payloads.

    These are scope and expiry observations only.  The runner must not treat
    them as credentials or use them to skip Django step-start gate calls.
    """

    breakglass_session_id: UUID
    scope_sha256: str
    scope_summary: str = ""
    started_at: datetime
    expires_at: datetime
    review_due_at: datetime

    model_config = ConfigDict(extra="ignore")


class ClaimedExecution(BaseModel):
    id: UUID
    status: Literal["claimed", "running"]
    workflow_id: UUID
    organization_id: UUID
    workflow_version: int
    workflow_snapshot: dict[str, Any]
    claimed_by_runner_id: str = ""
    claimed_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    steps: list[ClaimedStep]
    execution_mode: str = "live"
    # Change binding fields — present only when the execution is change-bound
    change_record_id: UUID | None = None
    dispatch_token: SecretStr | None = None
    requested_inputs_sha256: str | None = None
    operation_profile_key: str | None = None
    verification_plan_id: UUID | None = None
    verification_keys: list[ClaimedVerificationKey] = []
    # Optional breakglass facts — informational only; no local privilege changes
    breakglass: BreakglassSessionFacts | None = None

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def validate_change_fields_complete(self) -> ClaimedExecution:
        change_fields = {
            "change_record_id": self.change_record_id,
            "dispatch_token": self.dispatch_token,
            "requested_inputs_sha256": self.requested_inputs_sha256,
            "operation_profile_key": self.operation_profile_key,
        }
        present = {k for k, v in change_fields.items() if v is not None}
        if present and present != set(change_fields):
            missing = set(change_fields) - present
            raise ValueError(
                f"Change-bound execution is missing required fields: {sorted(missing)}. "
                "All change fields must be present together."
            )
        return self

    @property
    def is_change_bound(self) -> bool:
        return self.change_record_id is not None


class ClaimNextResponse(BaseModel):
    execution: ClaimedExecution | None
    claim_token: UUID | None = None
    poll_after_seconds: int
    runner_action: str = "continue"  # "continue" | "drain"
    drain_reason: str = ""

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class HeartbeatRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    observed_status: Literal["claimed", "running"] = "claimed"
    sent_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class HeartbeatResponse(BaseModel):
    execution_id: UUID | None = None
    status: str
    last_heartbeat_at: datetime | None = None
    cancel_requested: bool = False
    cancel_reason: str = ""

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Step update
# ---------------------------------------------------------------------------


class StepUpdateRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    status: Literal["succeeded", "failed", "skipped"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str = ""
    failure_kind: str = ""
    timed_out: bool = False
    cancelled: bool = False
    sandbox_provider: str = ""
    sandbox_run_id: str = ""

    model_config = ConfigDict(extra="forbid")


class StepUpdateStepDetail(BaseModel):
    id: UUID
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str = ""

    model_config = ConfigDict(extra="ignore")


class StepUpdateResponse(BaseModel):
    execution_id: UUID
    step: StepUpdateStepDetail
    execution_status: str

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Complete execution
# ---------------------------------------------------------------------------


class CompleteExecutionRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    final_status: Literal["succeeded", "failed", "cancelled"]
    finished_at: datetime | None = None
    error_message: str = ""

    model_config = ConfigDict(extra="forbid")


class CompleteExecutionResponse(BaseModel):
    id: UUID
    status: str
    finished_at: datetime | None = None

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Step start
# ---------------------------------------------------------------------------


class StepStartRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    sent_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class ApprovalRequestDetail(BaseModel):
    id: UUID
    status: str
    requested_at: datetime | None = None
    timeout_seconds: int | None = None
    expires_at: datetime | None = None
    resolved_at: datetime | None = None

    model_config = ConfigDict(extra="ignore")


class StepStartResponse(BaseModel):
    execution_id: UUID
    execution_status: str
    step: dict[str, Any]
    runner_action: Literal["run", "wait_for_approval", "blocked"]
    poll_after_seconds: int
    approval_request: ApprovalRequestDetail | None = None

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Approval status polling
# ---------------------------------------------------------------------------


class ApprovalStatusRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    observed_step_status: str = "waiting_for_approval"
    sent_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class ApprovalStatusResponse(BaseModel):
    execution_id: UUID
    execution_status: str
    step_id: UUID
    step_status: str
    approval_request: ApprovalRequestDetail | None = None
    runner_action: Literal["wait", "run", "fail"]
    poll_after_seconds: int

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Local runtime result models
# ---------------------------------------------------------------------------


class StepRunResult(BaseModel):
    status: Literal["succeeded", "failed"]
    exit_code: int
    error_message: str = ""

    model_config = ConfigDict(extra="forbid")


class ExecutionRunSummary(BaseModel):
    final_status: Literal["succeeded", "failed"]
    failed_step_id: UUID | None = None
    error_message: str = ""

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Change binding
# ---------------------------------------------------------------------------


class BindChangeExecutionRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    execution_id: UUID
    dispatch_token: SecretStr
    requested_inputs_sha256: str
    operation_profile_key: str
    sent_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")

    @field_serializer("dispatch_token", when_used="json")
    def _serialize_dispatch_token(self, v: SecretStr) -> str:
        return v.get_secret_value()


class BindChangeExecutionResponse(BaseModel):
    change_record_id: UUID
    execution_id: UUID
    bound_at: datetime | None = None

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Breakglass heartbeat (optional, change-bound only)
# ---------------------------------------------------------------------------


class BreakglassHeartbeatRequest(BaseModel):
    """Runner -> Django: report observation of an active breakglass session."""

    runner_id: str
    claim_token: UUID
    breakglass_session_id: UUID
    scope_sha256: str
    observed_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class BreakglassHeartbeatResponse(BaseModel):
    """Django -> runner: current authoritative breakglass status."""

    status: str
    expires_at: datetime | None = None
    server_time: datetime

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Execution timing callbacks (change-bound only)
# ---------------------------------------------------------------------------


class ExecutionTimingCallbackRequest(BaseModel):
    runner_id: str
    execution_id: UUID
    observed_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class ExecutionStartedResponse(BaseModel):
    change_record_id: UUID
    execution_started_at: datetime | None = None

    model_config = ConfigDict(extra="ignore")


class ExecutionFinishedResponse(BaseModel):
    change_record_id: UUID
    execution_finished_at: datetime | None = None
    locks_released: int = 0

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Verification callbacks (change-bound only)
# ---------------------------------------------------------------------------


class VerificationResultRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    execution_id: UUID
    check_key: str
    verification_key: str = ""
    outcome: Literal["passed", "failed"]
    step_key: str = ""
    artifact_ids: list[UUID] = []
    artifact_checksums: dict[str, str] = {}
    observed_value: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    sent_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class VerificationResultResponse(BaseModel):
    result_id: UUID
    check_id: UUID
    validation_status: str
    validation_errors: list[dict[str, Any]] = []
    check_status: str
    plan_status: str
    change_status: str
    accepted: bool = False
    artifact_ids: list[UUID] = []

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Artifact upload
# ---------------------------------------------------------------------------


class ArtifactUploadResponse(BaseModel):
    id: UUID
    execution_id: UUID
    step_id: UUID | None = None
    kind: str
    name: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    uploaded_by_runner_id: str
    uploaded_at: datetime | None = None

    model_config = ConfigDict(extra="ignore")
