from fastapi import APIRouter

router = APIRouter()

@router.post("/runbook")
def parse_runbook():
    return {
        "status": "ok",
        "message": "parse endpoint placeholder"
    }
