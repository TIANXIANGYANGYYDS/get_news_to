from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from domain.enums.tasks import TaskType
from domain.models.scheduler_models import ScheduledJob
from infrastructure.repositories.scheduler_task_repository import SchedulerTaskRepository
from scheduler.core.dispatcher import TaskDispatcher


class SchedulerEngine:
    def __init__(
        self,
        repository: SchedulerTaskRepository,
        dispatcher: TaskDispatcher,
        *,
        scheduled_jobs: list[ScheduledJob],
        tick_seconds: int = 2,
        default_timeout_seconds: int = 120,
        default_max_retry_count: int = 3,
    ):
        self.repository = repository
        self.dispatcher = dispatcher
        self.scheduled_jobs = scheduled_jobs
        self.tick_seconds = tick_seconds
        self.default_timeout_seconds = default_timeout_seconds
        self.default_max_retry_count = default_max_retry_count
        self._task: asyncio.Task | None = None
        self._last_schedule_cursor: dict[str, datetime] = {}

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self):
        if self.is_running:
            return
        self._task = asyncio.create_task(self._run_loop(), name="scheduler-engine")

    async def stop(self):
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self):
        while True:
            now = datetime.utcnow()
            await self._materialize_scheduled_tasks(now=now)
            await self.dispatcher.recover_stale_tasks(now=now)
            await asyncio.sleep(self.tick_seconds)

    async def _materialize_scheduled_tasks(self, *, now: datetime):
        for job in self.scheduled_jobs:
            if not job.enabled:
                continue

            last_cursor = self._last_schedule_cursor.get(job.task_name)
            if last_cursor is None:
                last_cursor = now - timedelta(seconds=job.interval_seconds)

            next_due = last_cursor + timedelta(seconds=job.interval_seconds)
            catchup_start = max(next_due, now - timedelta(seconds=job.catchup_window_seconds or 0))

            due_points: list[datetime] = []
            cursor = catchup_start
            while cursor <= now:
                due_points.append(cursor)
                cursor += timedelta(seconds=job.interval_seconds)

            for due_time in due_points:
                idempotency_key = f"scheduled::{job.task_name}::{due_time.strftime('%Y%m%d%H%M%S')}"
                await self.repository.create_task_if_absent(
                    task_name=job.task_name,
                    task_type=TaskType.BACKFILL if due_time < now else TaskType.SCHEDULED,
                    payload={"scheduled_for": due_time.isoformat(), "is_backfill": due_time < now},
                    idempotency_key=idempotency_key,
                    source="scheduler",
                    timeout_seconds=self.default_timeout_seconds,
                    max_retry_count=self.default_max_retry_count,
                    scheduled_for=due_time,
                )

            if due_points:
                self._last_schedule_cursor[job.task_name] = due_points[-1]
