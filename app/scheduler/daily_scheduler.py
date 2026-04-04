from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.logger import get_logger


logger = get_logger("scheduler.daily")


class DailyScheduler:
    def __init__(self, hour: int, minute: int, timezone: str, task_callable):
        self.hour = hour
        self.minute = minute
        self.timezone = timezone
        self.task_callable = task_callable
        self._task: asyncio.Task | None = None
        self._next_run_time: datetime | None = None

    def get_next_run_time(self) -> datetime:
        tz = ZoneInfo(self.timezone)
        now = datetime.now(tz)

        next_run = now.replace(
            hour=self.hour,
            minute=self.minute,
            second=0,
            microsecond=0,
        )

        if next_run <= now:
            next_run += timedelta(days=1)

        return next_run

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def next_run_at(self) -> datetime | None:
        return self._next_run_time

    @property
    def next_run_at_iso(self) -> str | None:
        if self._next_run_time is None:
            return None
        return self._next_run_time.isoformat()

    async def startup(self):
        if self.is_running:
            return

        self._task = asyncio.create_task(
            self.run_forever(),
            name="daily-market-analysis-scheduler",
        )

    async def start(self):
        await self.startup()

    async def shutdown(self):
        if self._task is None:
            return

        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

        self._task = None
        self._next_run_time = None

    async def stop(self):
        await self.shutdown()

    async def run_forever(self):
        while True:
            next_run = self.get_next_run_time()
            self._next_run_time = next_run
            now = datetime.now(ZoneInfo(self.timezone))
            wait_seconds = (next_run - now).total_seconds()

            logger.info(
                f"next run at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
                f"waiting {int(wait_seconds)} seconds"
            )

            await asyncio.sleep(wait_seconds)

            try:
                logger.info("daily task started")
                await self.task_callable()
                logger.info("daily task finished")
            except Exception as e:
                logger.exception(f"daily task failed: {e}")
