from __future__ import annotations

from fastapi import APIRouter

from app.api.dashboard_routes import router as dashboard_router


router = APIRouter(prefix="/api/v1", tags=["daily-pe-reporter"])

router.include_router(dashboard_router)
