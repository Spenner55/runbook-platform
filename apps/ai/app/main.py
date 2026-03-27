from fastapi import FastAPI
from app.api.routes.health import router as health_router
from app.api.routes.parse import router as parse_router
from app.api.routes.enrich import router as enrich_router
from app.api.routes.summarize import router as summarize_router

app = FastAPI(title="Runbook Platform AI Service")

app.include_router(health_router)
app.include_router(parse_router, prefix="/parse", tags=["parse"])
app.include_router(enrich_router, prefix="/enrich", tags=["enrich"])
app.include_router(summarize_router, prefix="/summarize", tags=["summarize"])
