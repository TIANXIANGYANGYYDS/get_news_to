from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.enums.news import NewsSource
from shared.base.model import ModelBase


@dataclass
class RawCrawlRecord(ModelBase):
    source: NewsSource
    payload: dict
    crawled_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NewsDedupKey(ModelBase):
    source: NewsSource
    event_id: str


@dataclass
class NewsEvent(ModelBase):
    event_id: str
    source: NewsSource
    content: str
    published_at: datetime
    publish_ts: int
    title: str = ""
    publish_time: str | None = None
    subject_names: list[str] = field(default_factory=list)


@dataclass
class CrawlFailure(ModelBase):
    source: NewsSource
    error_message: str
    occurred_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CrawlStatistics(ModelBase):
    source: NewsSource
    fetched_count: int = 0
    inserted_count: int = 0
    deduplicated_count: int = 0
    failed_count: int = 0


@dataclass
class CrawlBatchResult(ModelBase):
    source: NewsSource
    events: list[NewsEvent]
    statistics: CrawlStatistics
    failures: list[CrawlFailure] = field(default_factory=list)
