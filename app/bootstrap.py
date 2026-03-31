import asyncio
import contextlib
import inspect
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import exchange_calendars as xcals
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.feishu import FeishuNotifier
from app.feishu.card_builder import CardBuilder
from app.logger import get_logger
from app.scheduler import DailyScheduler
from app.crawlers.Get_Morning_Reading import fetch_and_split_morning_data
from app.llm.Moring_Reading_llm import analyze_morning_data
from app.crawlers.Get_fupan import fetch_fupan_full_visible_text, build_fupan_url
from app.llm.cls_telegraph_llm import analyze_cls_telegraph
from app.repo.cls_telegraph import CLSTelegraphRepository
from app.crawlers.Get_cls_telegraph import fetch_latest_telegraphs

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

        # Mongo 相关
        self.mongo_client = None
        self.db = None
        self.cls_telegraph_repository = None

        # 财联社电报轮询任务
        self.cls_telegraph_polling_task = None

    def get_a_share_trade_dates(self, now: datetime | None = None) -> tuple[str, str]:
        """
        返回:
        - today_trade_date: 当前业务交易日
        - prev_trade_date: 前一个交易日
        """
        now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)

        candidate_date = now.date() if now.hour >= 9 else (now - timedelta(days=1)).date()
        candidate = pd.Timestamp(candidate_date)

        if XSHG.is_session(candidate):
            today_trade_day = candidate
        else:
            today_trade_day = XSHG.previous_session(candidate)

        prev_trade_day = XSHG.previous_session(today_trade_day)

        return today_trade_day.strftime("%Y%m%d"), prev_trade_day.strftime("%Y%m%d")

    async def _maybe_await(self, result):
        if inspect.isawaitable(result):
            return await result
        return result

    async def _start_scheduler(self):
        if self.scheduler is None:
            return

        for method_name in ("startup", "start"):
            method = getattr(self.scheduler, method_name, None)
            if callable(method):
                await self._maybe_await(method())
                logger.info("daily scheduler started by %s()", method_name)
                return

        logger.warning("daily scheduler has no startup()/start() method, skip starting")

    async def _stop_scheduler(self):
        if self.scheduler is None:
            return

        for method_name in ("shutdown", "stop"):
            method = getattr(self.scheduler, method_name, None)
            if callable(method):
                await self._maybe_await(method())
                logger.info("daily scheduler stopped by %s()", method_name)
                return

        logger.warning("daily scheduler has no shutdown()/stop() method, skip stopping")

    async def analyze_single_cls_telegraph(self, row: dict) -> tuple[dict, bool]:
        """
        对单条财联社电报做 LLM 分析。
        返回: (analysis_dict, is_success)
        """
        content = (row.get("content") or "").strip()
        subjects = row.get("subjects") or []

        if not content:
            return (
                {
                    "score": 0,
                    "reason": "电报内容为空，未执行有效分析。",
                    "companies": None,
                    "sectors": None,
                },
                False,
            )

        try:
            analysis = await asyncio.to_thread(
                analyze_cls_telegraph,
                content,
                subjects,
            )

            logger.info(
                "cls telegraph llm analyzed successfully, event_id=%s, score=%s",
                row.get("event_id"),
                analysis.get("score"),
            )
            return analysis, True

        except Exception as e:
            logger.exception(
                "cls telegraph llm analyze failed, event_id=%s, error=%s",
                row.get("event_id"),
                e,
            )

            return (
                {
                    "score": 0,
                    "reason": f"LLM分析失败，按中性兜底入库。错误信息：{str(e)}",
                    "companies": None,
                    "sectors": None,
                },
                False,
            )

    async def fetch_new_cls_telegraphs(
        self,
        latest_ts: int | None,
        rn: int = 20,
    ) -> list[dict]:
        """
        只抓最新 rn 条，不分页，不补历史缺失数据。
        如果服务停机期间错过了更早的数据，不回补。
        """
        batch = await asyncio.to_thread(fetch_latest_telegraphs, rn)

        if not batch:
            logger.info("no cls telegraphs fetched")
            return []

        batch = [row for row in batch if row.get("event_id") and row.get("content")]
        if not batch:
            logger.info("empty valid cls telegraph batch")
            return []

        rows = []
        seen_event_ids = set()

        for row in batch:
            event_id = row["event_id"]
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)

            row_ts = row.get("publish_ts") or 0
            if latest_ts is not None and row_ts < latest_ts:
                continue

            rows.append(row)

        rows.sort(key=lambda x: x.get("publish_ts") or 0)
        return rows

    async def sync_cls_telegraphs_once(self, send_insert_card: bool = True):
        """
        拉取最近一批财联社电报。
        对每条真正新增的数据做 LLM 分析后，再写入 Mongo。
        send_insert_card=False 时，适合首次启动灌库，避免刷屏。
        """
        if self.cls_telegraph_repository is None:
            logger.warning("cls_telegraph_repository is not initialized")
            return

        latest_ts = await self.cls_telegraph_repository.get_latest_publish_ts()
        rows = await self.fetch_new_cls_telegraphs(
            latest_ts=latest_ts,
            rn=20,
        )

        if not rows:
            logger.info("no candidate cls telegraphs after paging fetch")
            return

        # 再按 event_id 过滤，避免同秒旧消息重复做 LLM
        event_ids = [row["event_id"] for row in rows if row.get("event_id")]
        existing_event_ids = await self.cls_telegraph_repository.get_existing_event_ids(event_ids)
        rows = [row for row in rows if row.get("event_id") not in existing_event_ids]

        if not rows:
            logger.info("no new cls telegraphs to analyze and upsert")
            return

        rows.sort(key=lambda x: x.get("publish_ts") or 0)

        llm_success_count = 0
        llm_failed_count = 0
        insert_card_success_count = 0
        insert_card_failed_count = 0

        for row in rows:
            llm_analysis, llm_ok = await self.analyze_single_cls_telegraph(row)
            row["llm_analysis"] = llm_analysis

            update_result = await self.cls_telegraph_repository.upsert_one(row)
            is_new_insert = bool(getattr(update_result, "upserted_id", None))

            if llm_ok:
                llm_success_count += 1
            else:
                llm_failed_count += 1

            # 只对“本次真正新入库成功”的数据发卡
            if is_new_insert and send_insert_card:
                card_ok = await self.send_cls_telegraph_insert_card(row)
                if card_ok:
                    insert_card_success_count += 1
                else:
                    insert_card_failed_count += 1

        max_ts = max((row.get("publish_ts") or 0) for row in rows)
        logger.info(
            "cls telegraphs synced successfully, upsert_count=%s, llm_success=%s, llm_failed=%s, "
            "insert_card_success=%s, insert_card_failed=%s, latest_publish_ts=%s, send_insert_card=%s",
            len(rows),
            llm_success_count,
            llm_failed_count,
            insert_card_success_count,
            insert_card_failed_count,
            max_ts,
            send_insert_card,
        )

    async def cls_telegraph_polling_loop(self):
        """
        应用启动后，每隔 5 分钟同步一次财联社电报。
        """
        while True:
            try:
                await asyncio.sleep(300)
                await self.sync_cls_telegraphs_once(send_insert_card=True)
            except asyncio.CancelledError:
                logger.info("cls telegraph polling loop cancelled")
                raise
            except Exception as e:
                logger.exception("cls telegraph polling loop failed: %s", e)

    async def send_cls_telegraph_insert_card(self, row: dict) -> bool:
        """
        单条财联社电报入库成功后，发送飞书卡片。
        不影响主流程，发送失败返回 False。
        """
        try:
            card = self.card_builder.build_cls_telegraph_insert_card(row)
            await self.notifier.send_card(card)
            logger.info(
                "cls telegraph insert card sent successfully, event_id=%s",
                row.get("event_id"),
            )
            return True
        except Exception as e:
            logger.exception(
                "send cls telegraph insert card failed, event_id=%s, error=%s",
                row.get("event_id"),
                e,
            )
            return False

    async def startup(self):
        await self.notifier.startup()

        self.mongo_client = AsyncIOMotorClient(settings.mongo_uri)
        self.db = self.mongo_client[settings.mongo_db_name]

        self.cls_telegraph_repository = CLSTelegraphRepository(self.db)
        await self.cls_telegraph_repository.create_indexes()

        # 启动调度器
        try:
            await self._start_scheduler()
        except Exception as e:
            logger.exception("start daily scheduler failed: %s", e)

        # 启动时先同步一次，但首次灌库不发入库卡，避免刷屏
        try:
            await self.sync_cls_telegraphs_once(send_insert_card=False)
        except Exception as e:
            logger.exception("initial cls telegraph sync failed: %s", e)

        # 再启动每 5 分钟轮询
        self.cls_telegraph_polling_task = asyncio.create_task(
            self.cls_telegraph_polling_loop()
        )

    async def shutdown(self):
        if self.cls_telegraph_polling_task is not None:
            self.cls_telegraph_polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.cls_telegraph_polling_task
            self.cls_telegraph_polling_task = None

        try:
            await self._stop_scheduler()
        except Exception as e:
            logger.exception("stop daily scheduler failed: %s", e)

        if self.mongo_client is not None:
            self.mongo_client.close()

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