from fastapi import APIRouter, HTTPException

from app.schemas.workflow_enrich import WorkflowEnrichRequest, WorkflowEnrichResponse
from app.services.workflow_enricher import enrich_workflow_candidate

router = APIRouter()


@router.post("/workflow", response_model=WorkflowEnrichResponse)
def enrich_workflow(request: WorkflowEnrichRequest) -> WorkflowEnrichResponse:
    """
    Accept a parsed workflow candidate and return enriched steps with risk
    classification and approval requirements.

    Called by Django only. Must not persist anything.
    """
    try:
        return enrich_workflow_candidate(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
