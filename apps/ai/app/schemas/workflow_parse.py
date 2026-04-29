from pydantic import BaseModel


class RunbookInput(BaseModel):
    id: str
    title: str
    raw_content: str


class ParseRunbookRequest(BaseModel):
    request_id: str
    runbook: RunbookInput


class WorkflowCandidateStep(BaseModel):
    step_key: str
    name: str
    step_type: str
    risk_level: str
    requires_approval: bool
    command: str | None = None


class ParseRunbookResponse(BaseModel):
    request_id: str
    workflow_title: str
    steps: list[WorkflowCandidateStep]
    warnings: list[str]
