from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    scheduler_running: bool
    cls_telegraph_polling_running: bool
    next_daily_run_at: Optional[str] = None
    mongo_connected: bool


class TaskTriggerResponse(BaseModel):
    ok: bool = True
    message: str


class SyncTelegraphsRequest(BaseModel):
    send_insert_card: bool = True


class TelegraphAnalysisRequest(BaseModel):
    title: str = ""
    content: str = Field(..., min_length=1)
    subjects: Optional[List[str]] = None


class TelegraphAnalysisResponse(BaseModel):
    analysis: Dict[str, Any]


class MorningAnalysisRequest(BaseModel):
    morning_content: str = Field(..., min_length=1)
    review_content: str = Field(..., min_length=1)


class MorningAnalysisResponse(BaseModel):
    analysis_text: str
