from fastapi import APIRouter

from app.schemas.workflow_parse import ParseRunbookRequest, ParseRunbookResponse
from app.services.workflow_parser import parse_runbook_to_candidate

router = APIRouter()


@router.post("/runbook", response_model=ParseRunbookResponse)
def parse_runbook(request: ParseRunbookRequest) -> ParseRunbookResponse:
    """
    Accept a raw runbook and return a structured workflow candidate.

    Called by Django only. Must not persist anything.
    Version assignment and final persistence remain Django's responsibility.
    """
    return parse_runbook_to_candidate(request)
