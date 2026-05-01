"""Typed request/response schemas for the runner <-> Django API contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RunnerSettings(BaseModel):
    api_base_url: str
    runner_id: str
    runner_version: str = "0.1.0"
    registration_token: str = ""
    api_retries_enabled: bool = True
    poll_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 10
    fake_step_delay_seconds: float = 1.0
    log_level: str = "INFO"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def validate_registration_token(self) -> RunnerSettings:
        if self.registration_token.strip() in {"", "change-me"}:
            raise ValueError(
                "RUNNER_REGISTRATION_TOKEN must be set to a non-placeholder value."
            )
        return self

    def validate_for_startup(self) -> None:
        """Raise SystemExit(1) with clear messages if required config is missing."""
        import sys

        errors: list[str] = []
        if not self.api_base_url.strip():
            errors.append("API_BASE_URL is empty — set it to the Django API base URL")
        if not self.runner_id.strip():
            errors.append("RUNNER_ID is empty — set it to a unique runner identifier")
        if self.registration_token.strip() in {"", "change-me"}:
            errors.append(
                "RUNNER_REGISTRATION_TOKEN must not be empty or the placeholder 'change-me'"
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

        return cls(
            api_base_url=os.environ.get("API_BASE_URL", "http://api:8000"),
            runner_id=os.environ.get(
                "RUNNER_ID", os.environ.get("HOSTNAME", "runner-dev")
            ),
            runner_version=os.environ.get("RUNNER_VERSION", "0.1.0"),
            registration_token=os.environ.get("RUNNER_REGISTRATION_TOKEN", ""),
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
        )


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
    # Change binding fields — present only when the execution is change-bound
    change_record_id: UUID | None = None
    dispatch_token: str | None = None
    requested_inputs_sha256: str | None = None
    operation_profile_key: str | None = None

    model_config = ConfigDict(extra="ignore")

    @property
    def is_change_bound(self) -> bool:
        return self.change_record_id is not None


class ClaimNextResponse(BaseModel):
    execution: ClaimedExecution | None
    claim_token: UUID | None = None
    poll_after_seconds: int

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

    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------------------
# Step update
# ---------------------------------------------------------------------------


class StepUpdateRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    status: Literal["running", "succeeded", "failed", "skipped"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str = ""

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
    final_status: Literal["succeeded", "failed"]
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
    dispatch_token: str
    requested_inputs_sha256: str
    operation_profile_key: str
    sent_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class BindChangeExecutionResponse(BaseModel):
    change_record_id: UUID
    execution_id: UUID
    bound_at: datetime | None = None

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
