from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime
from typing import Awaitable, Callable

from domain.enums.tasks import TaskStatus
from domain.models.scheduler_models import RetryPolicy, TaskExecutionResult, TaskRecord
from infrastructure.repositories.scheduler_task_repository import SchedulerTaskRepository
from scheduler.core.policies import can_retry, classify_terminal_status, compute_retry_at, should_move_dead_letter

TaskHandler = Callable[[TaskRecord], Awaitable[TaskExecutionResult]]


class TaskExecutor:
    def __init__(
        self,
        repository: SchedulerTaskRepository,
        retry_policy: RetryPolicy,
        task_handlers: dict[str, TaskHandler],
        *,
        lease_seconds: int,
        heartbeat_interval_seconds: int,
    ):
        self.repository = repository
        self.retry_policy = retry_policy
        self.task_handlers = task_handlers
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

    async def execute_claimed(self, task: TaskRecord, worker_id: str) -> TaskExecutionResult:
        started = time.perf_counter()
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(task.task_id, worker_id), name=f"heartbeat-{task.task_id}")
        try:
            handler = self.task_handlers[task.task_name]
            result = await asyncio.wait_for(handler(task), timeout=task.timeout_seconds)
            duration_ms = int((time.perf_counter() - started) * 1000)
            await self.repository.mark_succeeded(task_id=task.task_id, worker_id=worker_id, duration_ms=duration_ms, payload=result.payload)
            return result
        except asyncio.TimeoutError:
            return await self._handle_failure(task, "timeout", worker_id)
        except Exception as exc:  # noqa: PERF203
            return await self._handle_failure(task, str(exc), worker_id)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_loop(self, task_id: str, worker_id: str):
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            await self.repository.heartbeat(task_id=task_id, worker_id=worker_id, lease_seconds=self.lease_seconds)

    async def _handle_failure(self, task: TaskRecord, error_message: str, worker_id: str) -> TaskExecutionResult:
        terminal_status = classify_terminal_status(error_message)

        if can_retry(task, error_message, self.retry_policy):
            await self.repository.mark_retrying(
                task=task,
                error_message=error_message,
                next_run_at=compute_retry_at(task, self.retry_policy, now=datetime.utcnow()),
            )
            return TaskExecutionResult(status=TaskStatus.RETRYING, message=error_message)

        if should_move_dead_letter(task):
            await self.repository.mark_dead_letter(task=task, reason=error_message)
            await self.repository.create_compensation_task(failed_task=task, reason=error_message)
            return TaskExecutionResult(status=TaskStatus.DEAD_LETTER, message=error_message)

        await self.repository.mark_failed(task=task, status=terminal_status, error_message=error_message)
        await self.repository.create_compensation_task(failed_task=task, reason=error_message)
        return TaskExecutionResult(status=terminal_status, message=error_message)
