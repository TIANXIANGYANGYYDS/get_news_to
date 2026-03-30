import asyncio

from app.config import settings
from app.feishu import FeishuNotifier
from app.feishu.card_builder import CardBuilder
from app.logger import get_logger
from app.scheduler import DailyScheduler
from app.crawlers.Get_Morning_Reading import fetch_and_split_morning_data
from app.llm.Moring_Reading_llm import analyze_morning_data
from app.crawlers.Get_fupan import fetch_fupan_full_visible_text, build_fupan_url
import pandas as pd
import exchange_calendars as xcals
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = get_logger("bootstrap")

# A 股主板日历，上海交易所日历即可
XSHG = xcals.get_calendar("XSHG")
CN_TZ = ZoneInfo("Asia/Shanghai")

class Application:
    def __init__(self):
        self.notifier = FeishuNotifier(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            chat_id=settings.feishu_chat_id,
            bot_name=settings.feishu_bot_name,
        )
        self.card_builder = CardBuilder()

        self.scheduler = DailyScheduler(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone=settings.timezone,
            task_callable=self.send_daily_market_analysis_card,
        )


    def get_a_share_trade_dates(self, now: datetime | None = None) -> tuple[str, str]:
        """
        返回:
        - today_trade_date: 当前业务交易日
        - prev_trade_date: 前一个交易日

        规则:
        1. 使用北京时间
        2. 如果当前时间 < 09:00，则先按前一天算
        3. 如果该日不是 A 股交易日，则回退到最近一个交易日
        4. 再取它的前一个交易日
        5. 返回格式: YYYYMMDD
        """
        now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)

        # 9点前按前一天
        candidate_date = now.date() if now.hour >= 9 else (now - timedelta(days=1)).date()
        candidate = pd.Timestamp(candidate_date)

        # 修正到最近一个交易日
        if XSHG.is_session(candidate):
            today_trade_day = candidate
        else:
            today_trade_day = XSHG.previous_session(candidate)

        # 取前一个交易日
        prev_trade_day = XSHG.previous_session(today_trade_day)

        return today_trade_day.strftime("%Y%m%d"), prev_trade_day.strftime("%Y%m%d")

    async def startup(self):
        await self.notifier.startup()

    async def shutdown(self):
        await self.notifier.shutdown()

    async def send_daily_test_card(self):
        card = self.card_builder.build_daily_test_card()
        await self.notifier.send_card(card)
        logger.info("daily test card sent")

    async def send_daily_market_analysis_card(self):
        try:
            logger.info("start fetching morning market data")
            morning_data = fetch_and_split_morning_data(self.get_a_share_trade_dates()[0])

            if not morning_data:
                logger.warning("morning_data is empty")
                return

            logger.info(
                "morning data fetched successfully, date=%s, raw_content_len=%s",
                morning_data.get("date"),
                len(morning_data.get("raw_content", "")),
            )

            logger.info("start fetching previous day review")
            review_url = build_fupan_url(self.get_a_share_trade_dates()[1])

            prev_day_review = await asyncio.to_thread(
                fetch_fupan_full_visible_text,
                review_url,
            )

            logger.info(
                "previous day review fetched successfully, review_len=%s",
                len(prev_day_review or ""),
            )

            logger.info("start llm analysis for morning market data")
            analysis_text = await asyncio.to_thread(
                analyze_morning_data,
                morning_data,
                prev_day_review,
            )

            if not analysis_text:
                logger.warning("analysis_text is empty")
                return

            logger.info("llm analysis finished, analysis_len=%s", len(analysis_text))

            card = self.card_builder.build_daily_market_analysis_card(
                date=morning_data.get("date"),
                analysis_text=analysis_text,
                morning_data=morning_data,
            )

            await self.notifier.send_card(card)
            logger.info("daily market analysis card sent")

        except Exception as e:
            logger.exception("send_daily_market_analysis_card failed: %s", e)
            raise