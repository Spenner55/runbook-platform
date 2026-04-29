from pydantic import BaseModel


class ExecutionStepSummary(BaseModel):
    step_id: str
    name: str
    status: str
    output: str | None = None


class ExecutionSummarizeRequest(BaseModel):
    request_id: str
    execution_id: str
    workflow_title: str
    status: str
    steps: list[ExecutionStepSummary]


class ExecutionSummarizeResponse(BaseModel):
    request_id: str
    summary: str
    key_outcomes: list[str]
