from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardResponse(BaseModel):
    ok: bool = True
    data: Any = None
    message: str = ""


class MajorIndexItem(BaseModel):
    name: str
    code: str
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None


class MajorIndicesData(BaseModel):
    trade_date: str
    updated_at: str
    indices: list[MajorIndexItem]


class Pagination(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    total: int = Field(default=0, ge=0)


class PagedItemsData(BaseModel):
    items: list[dict[str, Any]]
    pagination: Pagination
