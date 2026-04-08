import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

from app.crawlers.Get_Morning_Reading import fetch_and_split_morning_data
from app.crawlers.Get_fupan import fetch_fupan_full_visible_text, build_fupan_url
from app.llm.Moring_Reading_llm import analyze_morning_data
from app.logger import get_logger

logger = get_logger("daily_market_analysis_service")
XSHG = xcals.get_calendar("XSHG")
CN_TZ = ZoneInfo("Asia/Shanghai")


class DailyMarketAnalysisService:
    def __init__(
        self,
        *,
        notifier,
        card_builder,
        daily_market_analysis_repository,
        sector_investment_preference_ranking_repository,
        sector_market_heat_ranking_repository,
    ):
        self.notifier = notifier
        self.card_builder = card_builder
        self.daily_market_analysis_repository = daily_market_analysis_repository
        self.sector_investment_preference_ranking_repository = sector_investment_preference_ranking_repository
        self.sector_market_heat_ranking_repository = sector_market_heat_ranking_repository

    def get_a_share_trade_dates(self, now: datetime | None = None) -> tuple[str, str]:
        now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
        candidate_date = now.date() if now.hour >= 9 else (now - timedelta(days=1)).date()
        candidate = pd.Timestamp(candidate_date)

        if XSHG.is_session(candidate):
            today_trade_day = candidate
        else:
            today_trade_day = XSHG.date_to_session(candidate, direction="previous")

        prev_trade_day = XSHG.previous_session(today_trade_day)
        return today_trade_day.strftime("%Y%m%d"), prev_trade_day.strftime("%Y%m%d")

    @staticmethod
    def format_trade_date(trade_date: str) -> str:
        trade_date = (trade_date or "").strip()
        if len(trade_date) == 8 and trade_date.isdigit():
            return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        return trade_date

    @staticmethod
    def build_daily_market_analysis_doc(
        *,
        analysis_date: str,
        trade_date: str,
        prev_trade_date: str,
        morning_data: dict,
        prev_day_review: str,
        analysis_text: str,
    ) -> dict:
        return {
            "analysis_date": analysis_date,
            "trade_date": trade_date,
            "prev_trade_date": prev_trade_date,
            "source": morning_data.get("source"),
            "morning_data": morning_data,
            "prev_day_review": prev_day_review,
            "analysis_text": analysis_text,
        }

    async def send_daily_test_card(self):
        card = self.card_builder.build_daily_test_card()
        await self.notifier.send_card(card)
        logger.info("daily test card sent")

    async def send_daily_market_analysis_card(self):
        today_trade_date, prev_trade_date = self.get_a_share_trade_dates()

        logger.info("start fetching morning market data")
        morning_data = fetch_and_split_morning_data(today_trade_date)
        if not morning_data:
            logger.warning("morning_data is empty")
            return

        logger.info(
            "morning data fetched successfully, date=%s, raw_content_len=%s",
            morning_data.get("date"),
            len(morning_data.get("raw_content", "")),
        )

        logger.info("start fetching previous day review")
        review_url = build_fupan_url(prev_trade_date)
        prev_day_review = await asyncio.to_thread(fetch_fupan_full_visible_text, review_url)

        logger.info("previous day review fetched successfully, review_len=%s", len(prev_day_review or ""))

        analysis_date = (morning_data.get("date") or "").strip() or self.format_trade_date(today_trade_date)

        investment_preference_ranking = None
        market_heat_ranking = None

        if self.sector_investment_preference_ranking_repository is not None:
            try:
                investment_preference_ranking = await self.sector_investment_preference_ranking_repository.get_investment_preference_ranking(
                    analysis_date,
                    limit=12,
                )
            except Exception as e:
                logger.exception(
                    "load investment preference ranking failed, analysis_date=%s, err=%s",
                    analysis_date,
                    e,
                )
        else:
            logger.warning("sector_investment_preference_ranking_repository is not initialized")

        if self.sector_market_heat_ranking_repository is not None:
            try:
                market_heat_ranking = await self.sector_market_heat_ranking_repository.get_market_heat_ranking(
                    analysis_date,
                    limit=12,
                )
            except Exception as e:
                logger.exception(
                    "load market heat ranking failed, analysis_date=%s, err=%s",
                    analysis_date,
                    e,
                )
        else:
            logger.warning("sector_market_heat_ranking_repository is not initialized")

        logger.info("start llm analysis for morning market data")
        analysis_text = await asyncio.to_thread(
            analyze_morning_data,
            morning_data,
            prev_day_review,
            investment_preference_ranking,
            market_heat_ranking,
        )

        if not analysis_text:
            logger.warning("analysis_text is empty")
            return

        logger.info("llm analysis finished, analysis_len=%s", len(analysis_text))

        if self.daily_market_analysis_repository is not None:
            doc = self.build_daily_market_analysis_doc(
                analysis_date=analysis_date,
                trade_date=today_trade_date,
                prev_trade_date=prev_trade_date,
                morning_data=morning_data,
                prev_day_review=prev_day_review,
                analysis_text=analysis_text,
            )

            update_result = await self.daily_market_analysis_repository.upsert_one(doc)
            is_new_insert = bool(getattr(update_result, "upserted_id", None))
            logger.info(
                "daily market analysis saved successfully, analysis_date=%s, action=%s",
                analysis_date,
                "insert" if is_new_insert else "update",
            )
        else:
            logger.warning("daily_market_analysis_repository is not initialized")

        card = self.card_builder.build_daily_market_analysis_card(
            date=analysis_date,
            analysis_text=analysis_text,
            morning_data=morning_data,
        )
        await self.notifier.send_card(card)
        logger.info("daily market analysis card sent")
