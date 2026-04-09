from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SectorRankingItem(BaseModel):
    sector: str = Field(..., min_length=1)
    rank: int = 0
    final_score: float | None = None
    event_score: float | None = None
    count_score: float | None = None
    time_score: float | None = None
    news_count: int = 0


class SectorInvestmentPreferenceRankingDoc(BaseModel):
    biz_date: str
    ranking_type: Literal["sector_investment_preference"] = "sector_investment_preference"
    window_type: str
    window_hours: int
    window_start_ts: int
    window_end_ts: int
    formula_version: str
    formula_config: dict[str, Any]
    sector_count: int = 0
    total_news_count: int = 0
    sector_rankings: list[dict[str, Any]] = Field(default_factory=list)
    updated_at_ts: int | None = None
    created_at_ts: int | None = None


class SectorMarketHeatRankingDoc(BaseModel):
    biz_date: str
    ranking_type: Literal["sector_market_heat"] = "sector_market_heat"
    window_type: str
    window_hours: int
    window_start_ts: int
    window_end_ts: int
    formula_version: str
    formula_config: dict[str, Any]
    sector_count: int = 0
    total_news_count: int = 0
    sector_rankings: list[dict[str, Any]] = Field(default_factory=list)
    updated_at_ts: int | None = None
    created_at_ts: int | None = None


class Sector3DDailySummaryDoc(BaseModel):
    biz_date: str
    window_type: str
    window_hours: int
    window_start_ts: int
    window_end_ts: int
    sector_count: int = 0
    total_news_count: int = 0
    total_score_sum: float = 0.0
    sector_stats: list[dict[str, Any]] = Field(default_factory=list)
    updated_at_ts: int | None = None
    created_at_ts: int | None = None


class DailyMarketAnalysisDoc(BaseModel):
    analysis_date: str
    trade_date: str
    prev_trade_date: str
    source: str | None = None
    morning_data: dict[str, Any] = Field(default_factory=dict)
    prev_day_review: str = ""
    analysis_text: str
    updated_at: datetime | None = None
    created_at: datetime | None = None
