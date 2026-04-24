from fastapi import APIRouter

router = APIRouter()


@router.post("/failure")
def summarize_failure():
    return {"status": "ok", "message": "summarize endpoint placeholder"}
