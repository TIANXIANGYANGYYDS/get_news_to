from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.enums.tasks import TaskType
from shared.base.model import ModelBase


@dataclass
class TaskCreateRequest(ModelBase):
    task_name: str
    task_type: TaskType = TaskType.MANUAL
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationPayload(ModelBase):
    title: str
    content: str
    channels: list[str] = field(default_factory=lambda: ["feishu"])


@dataclass
class MorningReadingPayload(ModelBase):
    date: str
    source_type: str
    raw_content: str
    sections: dict[str, str]


@dataclass
class FupanReviewPayload(ModelBase):
    date: str
    source_type: str
    url: str
    content: str


@dataclass
class KlineSnapshotRow(ModelBase):
    symbol: str
    name: str
    close_price: float
    change_percent: float
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class KlineSnapshotBatch(ModelBase):
    trade_date: str
    source_type: str
    rows: list[KlineSnapshotRow]
    fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MorningAnalysisOutput(ModelBase):
    summary_text: str
    key_sectors: list[str] = field(default_factory=list)


@dataclass
class TaskExecutionPayload(ModelBase):
    task_name: str
    data: dict[str, Any] = field(default_factory=dict)
