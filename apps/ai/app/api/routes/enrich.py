from fastapi import APIRouter

router = APIRouter()

@router.post("/workflow")
def enrich_workflow():
    return {
        "status": "ok",
        "message": "enrich endpoint placeholder"
    }
