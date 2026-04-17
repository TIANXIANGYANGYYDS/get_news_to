import asyncio

from domain.enums.tasks import TaskStatus, TaskType
from domain.models.scheduler_models import RetryPolicy, TaskExecutionResult, TaskRecord
from scheduler.core.executor import TaskExecutor


class FakeRepo:
    def __init__(self):
        self.updates = []

    async def update_status(self, task_id, status, **kwargs):
        self.updates.append((task_id, status, kwargs))


def test_executor_timeout_transitions_to_retrying():
    async def _run():
        repo = FakeRepo()

        async def slow_handler(task):
            await asyncio.sleep(0.2)
            return TaskExecutionResult(status=TaskStatus.SUCCEEDED)

        executor = TaskExecutor(repo, RetryPolicy(max_retries=2, base_backoff_seconds=1), {"crawl_news": slow_handler})
        task = TaskRecord(
            task_id="t1",
            task_name="crawl_news",
            task_type=TaskType.ON_DEMAND,
            timeout_seconds=0,
        )

        result = await executor.execute(task)
        assert result.status == TaskStatus.RETRYING
        assert any(update[1] == TaskStatus.RETRYING for update in repo.updates)

    asyncio.run(_run())


def test_executor_success_to_succeeded():
    async def _run():
        repo = FakeRepo()

        async def ok_handler(task):
            return TaskExecutionResult(status=TaskStatus.SUCCEEDED)

        executor = TaskExecutor(repo, RetryPolicy(max_retries=1), {"crawl_news": ok_handler})
        task = TaskRecord(task_id="t2", task_name="crawl_news", task_type=TaskType.ON_DEMAND)

        result = await executor.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert any(update[1] == TaskStatus.SUCCEEDED for update in repo.updates)

    asyncio.run(_run())
