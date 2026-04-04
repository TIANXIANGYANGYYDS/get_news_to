from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.schemas import (
    HealthResponse,
    MorningAnalysisRequest,
    MorningAnalysisResponse,
    SyncTelegraphsRequest,
    TaskTriggerResponse,
    TelegraphAnalysisRequest,
    TelegraphAnalysisResponse,
)


router = APIRouter(prefix="/api/v1", tags=["daily-pe-reporter"])


def get_application(request: Request) -> Any:
    return request.app.state.application


@router.get("/health", response_model=HealthResponse)
async def health(application: Any = Depends(get_application)):
    polling_task = application.cls_telegraph_polling_task

    return HealthResponse(
        scheduler_running=bool(application.scheduler and application.scheduler.is_running),
        cls_telegraph_polling_running=bool(polling_task and not polling_task.done()),
        next_daily_run_at=application.scheduler.next_run_at_iso if application.scheduler else None,
        mongo_connected=application.db is not None,
    )


@router.post("/tasks/test-card", response_model=TaskTriggerResponse)
async def send_test_card(application: Any = Depends(get_application)):
    await application.send_daily_test_card()
    return TaskTriggerResponse(message="test card sent")


@router.post("/tasks/daily-market-analysis", response_model=TaskTriggerResponse)
async def send_daily_market_analysis(application: Any = Depends(get_application)):
    await application.send_daily_market_analysis_card()
    return TaskTriggerResponse(message="daily market analysis completed")


@router.post("/tasks/cls-telegraphs/sync", response_model=TaskTriggerResponse)
async def sync_cls_telegraphs(
    payload: SyncTelegraphsRequest,
    application: Any = Depends(get_application),
):
    await application.sync_cls_telegraphs_once(
        send_insert_card=payload.send_insert_card,
    )
    return TaskTriggerResponse(message="cls telegraphs sync completed")


@router.post("/analysis/cls-telegraph", response_model=TelegraphAnalysisResponse)
async def analyze_cls_telegraph_endpoint(payload: TelegraphAnalysisRequest):
    from app.llm.cls_telegraph_llm import analyze_cls_telegraph

    title = payload.title.strip()
    content = payload.content.strip()
    full_content = f"{title}\n\n{content}" if title else content

    analysis = await asyncio.to_thread(
        analyze_cls_telegraph,
        full_content,
        payload.subjects,
    )
    return TelegraphAnalysisResponse(analysis=analysis)


@router.post("/analysis/morning", response_model=MorningAnalysisResponse)
async def analyze_morning_endpoint(payload: MorningAnalysisRequest):
    from app.llm.Moring_Reading_llm import analyze_morning_data

    morning_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sections": {
            "head": payload.morning_content,
        },
    }

    analysis_text = await asyncio.to_thread(
        analyze_morning_data,
        morning_data,
        payload.review_content,
    )
    return MorningAnalysisResponse(analysis_text=analysis_text)
