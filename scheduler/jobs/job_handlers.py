from __future__ import annotations

from domain.enums.tasks import TaskStatus
from domain.models.pipeline_models import NotificationPayload
from domain.models.scheduler_models import TaskExecutionResult, TaskRecord
from server.services.task_orchestration_service import TaskOrchestrationService


class JobHandlers:
    def __init__(self, orchestration_service: TaskOrchestrationService):
        self.orchestration_service = orchestration_service

    async def crawl_news(self, task: TaskRecord) -> TaskExecutionResult:
        result = await self.orchestration_service.run_news_ingestion(limit=50)
        return TaskExecutionResult(status=TaskStatus.SUCCEEDED, payload=result)

    async def aggregate_sector(self, task: TaskRecord) -> TaskExecutionResult:
        result = await self.orchestration_service.run_sector_aggregation()
        return TaskExecutionResult(status=TaskStatus.SUCCEEDED, payload=result)

    async def notify_digest(self, task: TaskRecord) -> TaskExecutionResult:
        notification_payload = NotificationPayload.from_dict(task.payload)
        await self.orchestration_service.run_notification(notification_payload)
        return TaskExecutionResult(status=TaskStatus.SUCCEEDED)

    async def morning_analysis(self, task: TaskRecord) -> TaskExecutionResult:
        result = await self.orchestration_service.run_morning_analysis()
        return TaskExecutionResult(status=TaskStatus.SUCCEEDED, payload=result)

    async def fupan_review(self, task: TaskRecord) -> TaskExecutionResult:
        result = await self.orchestration_service.run_fupan_review()
        return TaskExecutionResult(status=TaskStatus.SUCCEEDED, payload=result)

    async def kline_snapshot(self, task: TaskRecord) -> TaskExecutionResult:
        result = await self.orchestration_service.run_kline_snapshot()
        return TaskExecutionResult(status=TaskStatus.SUCCEEDED, payload=result)
