"""Typed request/response schemas for the runner <-> Django API contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class RunnerSettings(BaseModel):
    api_base_url: str
    runner_id: str
    runner_version: str = "0.1.0"
    registration_token: str = ""
    poll_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 10
    fake_step_delay_seconds: float = 1.0
    log_level: str = "INFO"

    model_config = ConfigDict(extra="forbid", frozen=True)

    @classmethod
    def from_env(cls) -> "RunnerSettings":
        import os
        return cls(
            api_base_url=os.environ.get("API_BASE_URL", "http://api:8000"),
            runner_id=os.environ.get("RUNNER_ID", os.environ.get("HOSTNAME", "runner-dev")),
            runner_version=os.environ.get("RUNNER_VERSION", "0.1.0"),
            registration_token=os.environ.get("RUNNER_REGISTRATION_TOKEN", ""),
            poll_interval_seconds=int(os.environ.get("RUNNER_POLL_INTERVAL_SECONDS", "5")),
            heartbeat_interval_seconds=int(os.environ.get("RUNNER_HEARTBEAT_INTERVAL_SECONDS", "10")),
            fake_step_delay_seconds=float(os.environ.get("RUNNER_FAKE_STEP_DELAY_SECONDS", "1.0")),
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
    status: Literal["pending", "running", "succeeded", "failed", "skipped"]

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

    model_config = ConfigDict(extra="ignore")


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
