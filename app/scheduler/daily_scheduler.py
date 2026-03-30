import asyncio
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

    async def run_forever(self):
        while True:
            next_run = self.get_next_run_time()
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