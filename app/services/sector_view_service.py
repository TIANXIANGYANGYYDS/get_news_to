import asyncio

from app.logger import get_logger

logger = get_logger("sector_view_service")


class SectorViewService:
    """管理版块衍生视图刷新生命周期与节流。"""

    def __init__(
        self,
        *,
        sector_3d_daily_summary_repository,
        sector_investment_preference_ranking_repository,
        sector_market_heat_ranking_repository,
        debounce_seconds: int = 5,
    ):
        self.sector_3d_daily_summary_repository = sector_3d_daily_summary_repository
        self.sector_investment_preference_ranking_repository = sector_investment_preference_ranking_repository
        self.sector_market_heat_ranking_repository = sector_market_heat_ranking_repository
        self.debounce_seconds = debounce_seconds

        self._refresh_event = asyncio.Event()
        self._refresh_task = None

    def mark_dirty(self):
        self._refresh_event.set()

    async def startup(self):
        if self._refresh_task is None:
            self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def shutdown(self):
        if self._refresh_task is None:
            return

        self._refresh_task.cancel()
        try:
            await self._refresh_task
        except asyncio.CancelledError:
            pass
        self._refresh_task = None

    async def _refresh_sector_3d_daily_summary(self):
        if self.sector_3d_daily_summary_repository is None:
            logger.warning("sector_3d_daily_summary_repository is not initialized")
            return

        try:
            summary_doc = await self.sector_3d_daily_summary_repository.rebuild_realtime_3d_summary()
            logger.info(
                "sector 3d daily summary updated, biz_date=%s, sector_count=%s, total_news_count=%s, total_score_sum=%s",
                summary_doc.get("biz_date"),
                summary_doc.get("sector_count"),
                summary_doc.get("total_news_count"),
                summary_doc.get("total_score_sum"),
            )
        except Exception as e:
            logger.exception("refresh sector 3d daily summary failed: %s", e)

    async def _refresh_sector_investment_preference_ranking(self):
        if self.sector_investment_preference_ranking_repository is None:
            logger.warning("sector_investment_preference_ranking_repository is not initialized")
            return

        try:
            ranking_doc = await self.sector_investment_preference_ranking_repository.rebuild_realtime_ranking()
            logger.info(
                "sector investment preference ranking updated, biz_date=%s, sector_count=%s, total_news_count=%s",
                ranking_doc.get("biz_date"),
                ranking_doc.get("sector_count"),
                ranking_doc.get("total_news_count"),
            )
        except Exception as e:
            logger.exception("refresh sector investment preference ranking failed: %s", e)

    async def _refresh_sector_market_heat_ranking(self):
        if self.sector_market_heat_ranking_repository is None:
            logger.warning("sector_market_heat_ranking_repository is not initialized")
            return

        try:
            ranking_doc = await self.sector_market_heat_ranking_repository.rebuild_realtime_ranking()
            logger.info(
                "sector market heat ranking updated, biz_date=%s, sector_count=%s, total_news_count=%s",
                ranking_doc.get("biz_date"),
                ranking_doc.get("sector_count"),
                ranking_doc.get("total_news_count"),
            )
        except Exception as e:
            logger.exception("refresh sector market heat ranking failed: %s", e)

    async def refresh_sector_views(self):
        await self._refresh_sector_3d_daily_summary()
        await self._refresh_sector_investment_preference_ranking()
        await self._refresh_sector_market_heat_ranking()

    async def _refresh_loop(self):
        while True:
            try:
                await self._refresh_event.wait()
                await asyncio.sleep(self.debounce_seconds)
                self._refresh_event.clear()
                await self.refresh_sector_views()
            except asyncio.CancelledError:
                logger.info("sector views refresh loop cancelled")
                raise
            except Exception as e:
                logger.exception("sector views refresh loop failed: %s", e)
