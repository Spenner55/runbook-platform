from pydantic import BaseModel

from app.schemas.workflow_parse import WorkflowCandidateStep


class WorkflowEnrichRequest(BaseModel):
    request_id: str
    workflow_title: str
    steps: list[WorkflowCandidateStep]
    raw_content: str | None = None


class WorkflowEnrichResponse(BaseModel):
    request_id: str
    steps: list[WorkflowCandidateStep]
    warnings: list[str]
