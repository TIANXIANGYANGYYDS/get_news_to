from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from domain.enums.tasks import TaskStatus, TaskType
from shared.base.model import ModelBase


@dataclass
class RetryPolicy(ModelBase):
    max_retries: int = 3
    base_backoff_seconds: int = 5
    retryable_errors: tuple[str, ...] = ("network", "timeout", "mongodb", "llm", "429", "5xx")

    def next_retry_at(self, retry_count: int, now: datetime | None = None) -> datetime:
        current = now or datetime.utcnow()
        return current + timedelta(seconds=self.base_backoff_seconds * (2 ** max(0, retry_count - 1)))


@dataclass
class ScheduledJob(ModelBase):
    task_name: str
    interval_seconds: int
    task_type: TaskType = TaskType.SCHEDULED
    enabled: bool = True
    catchup_window_seconds: int = 0


@dataclass
class TaskContext(ModelBase):
    source: str
    trigger_by: str
    trace_id: str | None = None


@dataclass
class TaskExecutionResult(ModelBase):
    status: TaskStatus
    message: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class FailureRecord(ModelBase):
    task_id: str
    error_message: str
    occurred_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TaskRecord(ModelBase):
    task_id: str
    task_name: str
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    payload: dict = field(default_factory=dict)
    source: str = "system"
    idempotency_key: str | None = None
    retry_count: int = 0
    max_retry_count: int = 3
    recovery_count: int = 0
    max_recovery_count: int = 2
    timeout_seconds: int = 120
    created_at: datetime = field(default_factory=datetime.utcnow)
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    retry_at: datetime | None = None
    next_run_at: datetime | None = None
    heartbeat_at: datetime | None = None
    lease_until: datetime | None = None
    worker_id: str | None = None
    error_message: str | None = None
    dead_letter_reason: str | None = None
    parent_task_id: str | None = None
    scheduled_for: datetime | None = None
