"""Typed request/response schemas for the runner <-> Django API contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class ClaimNextRequest(BaseModel):
    runner_id: str


class ClaimedStep(BaseModel):
    id: UUID
    position: int
    step_key: str
    name: str
    step_type: str
    risk_level: str
    command: str
    requires_approval: bool
    status: str


class ClaimedExecution(BaseModel):
    id: UUID
    status: str
    workflow_id: UUID
    organization_id: UUID
    workflow_version: int
    workflow_snapshot: dict[str, Any]
    claim_token: UUID
    steps: list[ClaimedStep]


class ClaimNextResponse(BaseModel):
    execution: ClaimedExecution | None
    poll_after_seconds: int


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    runner_id: str
    claim_token: UUID


class HeartbeatResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Step update
# ---------------------------------------------------------------------------

class StepUpdateRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    error_message: str = ""


class StepUpdateResponse(BaseModel):
    id: UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    error_message: str


# ---------------------------------------------------------------------------
# Complete execution
# ---------------------------------------------------------------------------

class CompleteExecutionRequest(BaseModel):
    runner_id: str
    claim_token: UUID
    outcome: str  # "succeeded" | "failed"


class CompleteExecutionResponse(BaseModel):
    id: UUID
    status: str
    started_at: datetime | None
    finished_at: datetime | None
