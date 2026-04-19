from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dashboard_schemas import DashboardResponse
from app.services.dashboard_query_service import DashboardQueryService


router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


def get_application(request: Request) -> Any:
    return request.app.state.application


@router.get("/major-indices", response_model=DashboardResponse)
async def get_major_indices(application: Any = Depends(get_application)):
    service = DashboardQueryService(application)
    data = await service.get_major_indices()
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/overview", response_model=DashboardResponse)
async def get_overview(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = DashboardQueryService(application)
    data = await service.get_overview(trade_date=trade_date)
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/mainline-sectors", response_model=DashboardResponse)
async def get_mainline_sectors(
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = DashboardQueryService(application)
    data = await service.get_mainline_sectors(trade_date=trade_date)
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/sectors/{sector_name}", response_model=DashboardResponse)
async def get_sector_detail(
    sector_name: str,
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = DashboardQueryService(application)
    data = await service.get_sector_detail(sector_name=sector_name, trade_date=trade_date)
    if not data:
        return DashboardResponse(ok=True, data=None, message="sector not found")
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/stocks/{stock_code}/technical", response_model=DashboardResponse)
async def get_stock_technical(
    stock_code: str,
    trade_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = DashboardQueryService(application)
    data = await service.get_stock_technical(stock_code=stock_code, trade_date=trade_date)
    if not data:
        return DashboardResponse(ok=True, data=None, message="technical result not found")
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/news-feed", response_model=DashboardResponse)
async def get_news_feed(
    trade_date: str | None = Query(default=None),
    sector: str | None = Query(default=None),
    source: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    application: Any = Depends(get_application),
):
    service = DashboardQueryService(application)
    data = await service.get_news_feed(
        trade_date=trade_date,
        sector=sector,
        source=source,
        keyword=keyword,
        min_score=min_score,
        page=page,
        page_size=page_size,
    )
    return DashboardResponse(ok=True, data=data, message="")


@router.get("/rankings", response_model=DashboardResponse)
async def get_rankings(
    biz_date: str | None = Query(default=None),
    application: Any = Depends(get_application),
):
    service = DashboardQueryService(application)
    data = await service.get_rankings(biz_date=biz_date)
    return DashboardResponse(ok=True, data=data, message="")
