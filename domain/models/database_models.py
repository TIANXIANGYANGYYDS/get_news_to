from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.models.analysis_models import LLMAnalysisResult
from domain.models.news_models import NewsEvent
from shared.base.model import ModelBase


@dataclass
class NewsDocument(ModelBase):
    event_id: str
    source_type: str
    title: str
    content: str
    published_at: datetime
    publish_ts: int
    publish_time: str | None = None
    subject_names: list[str] = field(default_factory=list)
    analysis: LLMAnalysisResult | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def from_news_event(cls, event: NewsEvent) -> "NewsDocument":
        return cls(
            event_id=event.event_id,
            source_type=event.source.value,
            title=event.title,
            content=event.content,
            published_at=event.published_at,
            publish_ts=event.publish_ts,
            publish_time=event.publish_time,
            subject_names=event.subject_names,
        )


@dataclass
class MarketAnalysisReportDocument(ModelBase):
    report_id: str
    report_type: str
    analysis_date: str
    trade_date: str
    source_type: str
    content: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class KlineSnapshotDocument(ModelBase):
    snapshot_id: str
    trade_date: str
    symbol: str
    name: str
    close_price: float
    change_percent: float
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SectorHeatDocument(ModelBase):
    date_key: str
    sector_name: str
    heat_score: float
    event_count: int
    updated_at: datetime = field(default_factory=datetime.utcnow)
