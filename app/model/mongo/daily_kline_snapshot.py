from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict


class DailyKLineSnapshot(BaseModel):
    """
    A 股日度快照标准模型
    用于：
    1. 规范入库数据结构
    2. 将抓取结果中的中文字段转换为英文字段
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
    )

    id: str = Field(default_factory=lambda: str(uuid4()), description="独立主键 id")
    trade_date: str = Field(..., description="交易日期，格式 YYYY-MM-DD")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    symbol: str = Field(..., alias="代码", description="股票代码")
    name: str = Field(..., alias="名称", description="股票名称")

    open_price: Optional[float] = Field(default=None, alias="开盘价", description="开盘价")
    close_price: Optional[float] = Field(default=None, alias="关盘价", description="收盘价")
    high_price: Optional[float] = Field(default=None, alias="最高价", description="最高价")
    low_price: Optional[float] = Field(default=None, alias="最低价", description="最低价")
    prev_close_price: Optional[float] = Field(default=None, alias="昨收价", description="昨收价")

    change_percent: Optional[float] = Field(default=None, alias="涨跌幅(%)", description="涨跌幅百分比")
    change_amount: Optional[float] = Field(default=None, alias="涨跌", description="涨跌额")
    speed_percent: Optional[float] = Field(default=None, alias="涨速(%)", description="涨速百分比")
    turnover_percent: Optional[float] = Field(default=None, alias="换手(%)", description="换手率")
    volume_ratio: Optional[float] = Field(default=None, alias="量比", description="量比")
    amplitude_percent: Optional[float] = Field(default=None, alias="振幅(%)", description="振幅百分比")

    turnover_amount_yuan: Optional[float] = Field(default=None, alias="成交额_元", description="成交额，单位元")
    float_shares: Optional[float] = Field(default=None, alias="流通股_股", description="流通股数")
    float_market_cap_yuan: Optional[float] = Field(default=None, alias="流通市值_元", description="流通市值，单位元")
    total_market_cap_yuan: Optional[float] = Field(default=None, alias="总市值_元", description="总市值，单位元")
    pe_ratio: Optional[float] = Field(default=None, alias="市盈率", description="市盈率")

    @classmethod
    def from_raw_row(
        cls,
        raw_row: dict[str, Any],
        trade_date: str,
        now: datetime,
    ) -> "DailyKLineSnapshot":
        """
        从抓取到的中文字段 dict 构造标准对象
        """
        payload = {
            **raw_row,
            "trade_date": trade_date,
            "created_at": now,
            "updated_at": now,
        }
        return cls.model_validate(payload)

    def to_mongo_dict(self) -> dict[str, Any]:
        """
        输出为 Mongo 入库 dict，统一使用英文字段名
        """
        return self.model_dump(by_alias=False)