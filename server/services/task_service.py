from __future__ import annotations

from datetime import datetime

from domain.models.pipeline_models import TaskCreateRequest
from domain.models.scheduler_models import TaskRecord
from infrastructure.repositories.scheduler_task_repository import SchedulerTaskRepository


class TaskService:
    def __init__(self, repository: SchedulerTaskRepository, *, max_retry_count: int, default_timeout_seconds: int):
        self.repository = repository
        self.max_retry_count = max_retry_count
        self.default_timeout_seconds = default_timeout_seconds

    async def create_task(self, request: TaskCreateRequest, source: str = "api") -> TaskRecord:
        idempotency_key = request.payload.get("idempotency_key") or f"manual::{request.task_name}::{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        return await self.repository.create_task_if_absent(
            task_name=request.task_name,
            task_type=request.task_type,
            payload=request.payload,
            idempotency_key=idempotency_key,
            source=source,
            timeout_seconds=self.default_timeout_seconds,
            max_retry_count=self.max_retry_count,
        )
