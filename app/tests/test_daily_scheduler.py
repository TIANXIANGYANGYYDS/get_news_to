import asyncio
import unittest

from app.scheduler.daily_scheduler import DailyScheduler


class DailySchedulerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_and_shutdown_manage_background_task(self):
        started = asyncio.Event()

        async def fake_run_forever():
            started.set()
            await asyncio.Event().wait()

        scheduler = DailyScheduler(
            hour=9,
            minute=0,
            timezone="Asia/Shanghai",
            task_callable=lambda: None,
        )
        scheduler.run_forever = fake_run_forever  # type: ignore[assignment]

        await scheduler.startup()

        await asyncio.wait_for(started.wait(), timeout=1)
        self.assertTrue(scheduler.is_running)

        await scheduler.shutdown()

        self.assertFalse(scheduler.is_running)
        self.assertIsNone(scheduler.next_run_at)
