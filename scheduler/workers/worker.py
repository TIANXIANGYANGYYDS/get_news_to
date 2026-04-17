from __future__ import annotations

import asyncio

from infrastructure.repositories.scheduler_task_repository import SchedulerTaskRepository
from scheduler.core.executor import TaskExecutor


class WorkerPool:
    def __init__(
        self,
        repository: SchedulerTaskRepository,
        executor: TaskExecutor,
        *,
        worker_count: int,
        lease_seconds: int,
        poll_interval_seconds: float = 1.0,
    ):
        self.repository = repository
        self.executor = executor
        self.worker_count = worker_count
        self.lease_seconds = lease_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.tasks: list[asyncio.Task] = []

    async def start(self):
        for index in range(self.worker_count):
            self.tasks.append(asyncio.create_task(self._run_worker(index), name=f"worker-{index}"))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.tasks = []

    async def _run_worker(self, index: int):
        worker_id = f"worker-{index}"
        while True:
            task = await self.repository.claim_next_task(worker_id=worker_id, lease_seconds=self.lease_seconds)
            if task is None:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            await self.executor.execute_claimed(task, worker_id=worker_id)
