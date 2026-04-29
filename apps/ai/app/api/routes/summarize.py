from fastapi import APIRouter, HTTPException

from app.schemas.workflow_summarize import (
    ExecutionSummarizeRequest,
    ExecutionSummarizeResponse,
)
from app.services.execution_summarizer import summarize_execution_result

router = APIRouter()


@router.post("/execution", response_model=ExecutionSummarizeResponse)
def summarize_execution(request: ExecutionSummarizeRequest) -> ExecutionSummarizeResponse:
    """
    Accept execution data and return a human-readable summary.

    Called by Django only. Must not persist anything.
    """
    try:
        return summarize_execution_result(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
