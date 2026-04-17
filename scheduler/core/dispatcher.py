from __future__ import annotations

from datetime import datetime

from infrastructure.repositories.scheduler_task_repository import SchedulerTaskRepository


class TaskDispatcher:
    def __init__(self, repository: SchedulerTaskRepository):
        self.repository = repository

    async def recover_stale_tasks(self, *, now: datetime):
        await self.repository.recover_stale_running_tasks(now=now)
