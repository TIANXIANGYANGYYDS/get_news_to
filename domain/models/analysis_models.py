from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from shared.base.model import ModelBase


@dataclass
class LLMAnalysisRequest(ModelBase):
    event_id: str
    content: str
    title: str = ""
    subject_names: list[str] = field(default_factory=list)


@dataclass
class LLMAnalysisResult(ModelBase):
    score: int = 0
    reason: str = ""
    sector_names: list[str] = field(default_factory=list)
    company_names: list[str] = field(default_factory=list)
    is_fallback: bool = False
    error_message: str | None = None
    token_usage: int | None = None
    latency_ms: int | None = None


@dataclass
class NewsAnalysisRecord(ModelBase):
    event_id: str
    result: LLMAnalysisResult
    analyzed_at: datetime = field(default_factory=datetime.utcnow)
