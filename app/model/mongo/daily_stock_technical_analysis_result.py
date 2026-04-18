from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DailyStockTechnicalAnalysisResult(BaseModel):
    """每日个股技术分析结果模型（单表）。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid4()))
    trade_date: str
    analysis_time: datetime

    sector_name: str
    sector_rank: int | None = None
    stock_code: str
    stock_name: str | None = None
    stock_rank_in_sector: int | None = None

    bars_count: int | None = None
    kline_trade_date_start: str | None = None
    kline_trade_date_end: str | None = None
    current_price: float | None = None
    recent_high: float | None = None
    recent_low: float | None = None
    input_bars: list[dict[str, Any]] = Field(default_factory=list)

    analysis_status: str
    error_message: str | None = None

    conclusion: str | None = None
    current_channel: str | None = None
    channel_support_buy: str | None = None
    current_pattern: str | None = None
    pattern_allowed_type: str | None = None
    key_candle: str | None = None
    has_follow_through: str | None = None
    can_trigger_buy: str | None = None
    expected_entry: str | None = None
    trigger_condition: str | None = None
    buy_price: str | None = None
    stop_loss: str | None = None
    take_profit: str | None = None
    reason: str | None = None

    created_at: datetime
    updated_at: datetime

    def to_mongo_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=False)
