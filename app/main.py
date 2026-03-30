import asyncio

from app.bootstrap import Application
from app.config import settings
from app.logger import get_logger


logger = get_logger("main")


async def main():
    app = Application()
    await app.startup()

    try:
        if settings.run_on_startup:
            # logger.info("run startup test task once")
            # await app.send_daily_test_card()   #发送测试卡
            logger.info("run startup market analysis task once")
            await app.send_daily_market_analysis_card()

        logger.info("scheduler started")
        await app.scheduler.run_forever()
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())