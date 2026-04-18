import asyncio
import contextlib
import inspect
import os
import re
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
from app.llm.Moring_Reading_llm import analyze_morning_data, extract_mainline_sectors
from app.crawlers.Get_fupan import fetch_fupan_full_visible_text, build_fupan_url
from app.llm.cls_telegraph_llm import analyze_cls_telegraph
from app.repo import (
    CLSTelegraphRepository,
    DailyMarketAnalysisRepository,
    Sector3DDailySummaryRepository,
    SectorInvestmentPreferenceRankingRepository,
    SectorMarketHeatRankingRepository,
    DailyKLineSnapshotRepository,
    DailyStockTechnicalAnalysisResultRepository,
)
from app.crawlers.Get_cls_telegraph import (
    fetch_latest_telegraphs as fetch_latest_cls_telegraphs,
)
from app.crawlers.Get_jin10_telegraph import (
    fetch_latest_telegraphs as fetch_latest_jin10_telegraphs,
)
from app.crawlers.Get_10jqka_telegraph import (
    fetch_latest_telegraphs as fetch_latest_10jqka_telegraphs,
)
from app.crawlers.Get_10jqka_sector_top_stocks import fetch_sector_top_stocks_by_name
from app.model import CLSTelegraph, CLSTelegraphLLMAnalysis
from app.services import DailyStockTechnicalAnalysisService

from datetime import datetime, timedelta, time as dt_time
from app.crawlers.Get_Daily_K_line_data import (
    EastmoneyAShareCrawler,
    ShanchenProxyProvider,
)
from app.crawlers.proxy_provider import NoProxyProvider

logger = get_logger("bootstrap")

# A 股主板日历，这里使用上交所交易日历即可覆盖常见 A 股交易日判断逻辑
XSHG = xcals.get_calendar("XSHG")

# 中国时区，所有交易日、盘前逻辑、业务日期计算都统一按这个时区处理
CN_TZ = ZoneInfo("Asia/Shanghai")


class Application:

    def __init__(self):
        """
        应用主入口对象。

        职责：
        1. 初始化飞书通知组件
        2. 初始化每日调度器
        3. 管理 Mongo 连接与各类 repository
        4. 管理市场资讯轮询任务（当前来源：CLS + Jin10 + 10jqka）
        5. 管理市场资讯异步消费队列（5 个 worker）
        """
        # 飞书通知器：负责把卡片实际发送到飞书群
        self.notifier = FeishuNotifier(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            chat_id=settings.feishu_chat_id,
            bot_name=settings.feishu_bot_name,
        )

        # 卡片构建器：负责把业务数据组装成飞书卡片 JSON
        self.card_builder = CardBuilder()

        # -----------------------------
        # 每日调度器
        # -----------------------------
        # 每日盘前分析调度器
        self.market_analysis_scheduler = DailyScheduler(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone=settings.timezone,
            task_callable=self.send_daily_market_analysis_card,
            task_name="market-analysis-scheduler",
        )

        # 每日 A 股日快照调度器（固定 15:40，中国时区）
        self.daily_kline_snapshot_scheduler = DailyScheduler(
            hour=15,
            minute=40,
            timezone="Asia/Shanghai",
            task_callable=self.sync_daily_kline_snapshot_once,
            task_name="daily-kline-snapshot-scheduler",
        )

        # -----------------------------
        # Mongo 相关对象
        # -----------------------------
        self.mongo_client = None
        self.db = None

        # 统一资讯原始表 repository（CLS + Jin10 + 10jqka 共用）
        self.cls_telegraph_repository = None

        # 三日内版块汇总表 repository
        self.sector_3d_daily_summary_repository = None

        # 市场投资倾向排行榜 repository
        self.sector_investment_preference_ranking_repository = None

        # 市场热度排行榜 repository
        self.sector_market_heat_ranking_repository = None

        # 每日盘前分析表 repository
        self.daily_market_analysis_repository = None

        # A 股日快照 repository
        self.daily_kline_snapshot_repository = None

        # 每日个股技术分析结果 repository
        self.daily_stock_technical_analysis_result_repository = None

        # 每日个股技术分析服务
        self.daily_stock_technical_analysis_service = None
        self.daily_stock_technical_analysis_task = None

        # 轮询任务句柄
        self.cls_telegraph_polling_task = None

        # -----------------------------
        # 市场资讯异步消费队列
        # -----------------------------
        # 去重完成后的资讯统一入这个队列，由 worker 并发消费
        self.market_telegraph_queue: asyncio.Queue = asyncio.Queue(maxsize=2000)

        # 固定 5 个 worker
        self.market_telegraph_worker_count = 5
        self.market_telegraph_worker_tasks: list[asyncio.Task] = []

        # 正在队列中 / 正在 worker 处理中但尚未写库完成的 event_id
        # 作用：避免“尚未入库完成前，被下一轮轮询再次抓到并重复入队”
        self.pending_event_ids: set[str] = set()
        self.pending_event_ids_lock = asyncio.Lock()

        # 版块衍生视图刷新事件 + 后台刷新任务
        # worker 处理完后只打事件，不在每条上直接重刷，避免太重
        self.sector_views_refresh_event = asyncio.Event()
        self.sector_views_refresh_task = None


    def get_a_share_trade_dates(self, now: datetime | None = None) -> tuple[str, str]:
        """
        获取当前业务对应的 A 股“今日交易日”和“前一交易日”。

        规则：
        1. 如果当前时间 >= 上午 9 点，则优先认为今天是候选交易日
        2. 如果当前时间 < 上午 9 点，则候选日期往前退一天
        3. 若候选日期不是交易日，则回退到最近一个交易日
        4. 再基于该交易日获取前一个交易日

        返回：
        - today_trade_date: 当前业务交易日，格式 YYYYMMDD
        - prev_trade_date: 前一个交易日，格式 YYYYMMDD
        """
        now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)

        # 9 点前默认还处于“前一个交易日夜间/盘前准备阶段”
        candidate_date = now.date() if now.hour >= 9 else (now - timedelta(days=1)).date()
        candidate = pd.Timestamp(candidate_date)

        if XSHG.is_session(candidate):
            today_trade_day = candidate
        else:
            # 非交易日时不能直接传给 previous_session，否则 exchange_calendars 会报 NotSessionError
            today_trade_day = XSHG.date_to_session(candidate, direction="previous")

        prev_trade_day = XSHG.previous_session(today_trade_day)

        return today_trade_day.strftime("%Y%m%d"), prev_trade_day.strftime("%Y%m%d")

    def resolve_target_trade_date(self, now: datetime | None = None) -> str:
        """
        解析本次任务 target_trade_date：
        - 交易日：今天
        - 非交易日：回退到上一个交易日

        复用项目里现有交易日判断与前一交易日函数。
        """
        current = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
        today_trade_date, prev_trade_date = self.get_a_share_trade_dates(current)

        if self.is_a_share_trade_day(current):
            return self._format_trade_date(today_trade_date)

        return self._format_trade_date(prev_trade_date)

    @staticmethod
    def _format_trade_date(trade_date: str) -> str:
        """
        交易日格式标准化：
        把 YYYYMMDD 转成 YYYY-MM-DD。

        用途：
        - 早盘数据里的日期字段有时直接是 YYYYMMDD
        - 卡片展示和入库时更适合统一成 YYYY-MM-DD
        """
        trade_date = (trade_date or "").strip()
        if len(trade_date) == 8 and trade_date.isdigit():
            return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        return trade_date

    def _build_daily_market_analysis_doc(
        self,
        *,
        analysis_date: str,
        trade_date: str,
        prev_trade_date: str,
        morning_data: dict,
        prev_day_review: str,
        analysis_text: str,
        mainline_sectors: list[dict] | None = None,
        sector_top_stocks: list[dict] | None = None,
    ) -> dict:
        """
        构造“盘前主线分析”入库文档。

        说明：
        - analysis_date 是唯一键语义，同一天只保留一条
        - 如果当天重复执行，会通过 upsert 覆盖更新，而不是新增多条
        """
        return {
            "analysis_date": analysis_date,
            "trade_date": trade_date,
            "prev_trade_date": prev_trade_date,
            "source": morning_data.get("source"),
            "morning_data": morning_data,
            "prev_day_review": prev_day_review,
            "analysis_text": analysis_text,
            "mainline_sectors": mainline_sectors or [],
            "sector_top_stocks": sector_top_stocks or [],
        }

    async def _maybe_await(self, result):
        """
        兼容同步返回值与 awaitable 返回值。

        用途：
        - scheduler 的 startup()/start()/shutdown()/stop() 可能是同步，也可能是异步
        - 这里统一做兼容，避免上层重复写判断
        """
        if inspect.isawaitable(result):
            return await result
        return result

    async def _start_scheduler(self, scheduler: DailyScheduler | None, scheduler_name: str):
        """
        启动某个每日调度器。

        兼容两种方法名：
        - startup()
        - start()
        """
        if scheduler is None:
            return

        for method_name in ("startup", "start"):
            method = getattr(scheduler, method_name, None)
            if callable(method):
                await self._maybe_await(method())
                logger.info("%s started by %s()", scheduler_name, method_name)
                return

        logger.warning("%s has no startup()/start() method, skip starting", scheduler_name)


    async def _stop_scheduler(self, scheduler: DailyScheduler | None, scheduler_name: str):
        """
        停止某个每日调度器。

        兼容两种方法名：
        - shutdown()
        - stop()
        """
        if scheduler is None:
            return

        for method_name in ("shutdown", "stop"):
            method = getattr(scheduler, method_name, None)
            if callable(method):
                await self._maybe_await(method())
                logger.info("%s stopped by %s()", scheduler_name, method_name)
                return

        logger.warning("%s has no shutdown()/stop() method, skip stopping", scheduler_name)

    @staticmethod
    def _normalize_dedup_text(text: str) -> str:
        """
        文本归一化，用于跨平台内容去重。

        处理目标：
        1. 去站点来源前后缀
        2. 去日期来源口径差异
        3. 去空白、换行、标点差异
        4. 尽量把“同一条资讯的不同平台文案包装”压缩到相近形式
        """
        text = (text or "").strip()

        if not text:
            return ""

        # 去来源前缀 / 口径差异
        text = re.sub(r"财联社\d{1,2}月\d{1,2}日电[，,:：]?", "", text)
        text = re.sub(r"金十数据\d{1,2}月\d{1,2}日讯[，,:：]?", "", text)
        text = re.sub(r"^\[?金十数据\]?[，,:：]?", "", text)
        text = re.sub(r"^\[?财联社\]?[，,:：]?", "", text)

        # 去尾部站点标识
        text = re.sub(r"\s*[-—]\s*金十数据\s*$", "", text)
        text = re.sub(r"\s*[-—]\s*财联社\s*$", "", text)
        text = re.sub(r"\s*金十数据\s*$", "", text)
        text = re.sub(r"\s*财联社\s*$", "", text)

        text = re.sub(r"同花顺\d{1,2}月\d{1,2}日讯[，,:：]?", "", text)
        text = re.sub(r"^\[?同花顺\]?[，,:：]?", "", text)
        text = re.sub(r"\s*[-—]\s*同花顺\s*$", "", text)
        text = re.sub(r"\s*同花顺\s*$", "", text)
        text = re.sub(r"[（(]同花顺[）)]\s*$", "", text)

        # 去引号、括号、标点差异
        text = re.sub(r"[“”\"'`‘’]", "", text)
        text = re.sub(r"[，。；：！？、】【（）()、,.;:!?·\-—\[\]]", "", text)

        # 去空白
        text = re.sub(r"\s+", "", text)

        return text.lower()

    @staticmethod
    def _is_valid_dedup_title(title: str) -> bool:
        """
        判断标题是否适合用来做去重。

        规则：
        - 太短的不算
        - 太模板化、太泛化的不算
        - 这些情况退回按内容去重更稳
        """
        title = (title or "").strip()
        if not title:
            return False

        if len(title) < 6:
            return False

        bad_patterns = [
            r"^金十图示",
            r"^新闻联播今日要点",
            r"^今日要点$",
            r"^金十数据$",
            r"^财联社$",
            r"^快讯$",
        ]

        for pattern in bad_patterns:
            if re.search(pattern, title):
                return False

        return True

    @staticmethod
    def _strip_title_from_content(content: str, title: str) -> str:
        """
        如果正文开头就是标题，则把标题从正文前缀剥掉。

        作用：
        - 有的平台是“标题 + 正文”
        - 有的平台只有“正文”
        - 去掉标题后，更容易让两边内容 key 对齐
        """
        content = (content or "").strip()
        title = (title or "").strip()

        if not content or not title:
            return content

        # 兼容：
        # 1. 标题 正文
        # 2. 【标题】正文
        # 3. 标题：正文
        pattern = rf"^\s*[【\[]?{re.escape(title)}[】\]]?\s*[-—:：，,\s]*"
        stripped = re.sub(pattern, "", content, count=1)

        return stripped.strip() or content

    def _build_cross_source_dedup_keys(self, row: CLSTelegraph) -> set[str]:
        """
        为单条资讯构造“跨平台去重 key 集合”。

        设计思想：
        - 不是只生成一个 key，而是生成一组 key
        - 这样能处理：
          1. 一边有标题、一边没标题
          2. 一边正文里带标题、一边正文不带标题
          3. 来源包装口径不同但本质是同一条消息

        规则：
        - 有有效标题时：加入 title key
        - 同时始终加入 content key
        - 如果标题存在，还会再生成一个“去掉标题前缀后的 content key”
        """
        keys = set()

        title = (row.title or "").strip()
        content = (row.content or "").strip()

        if self._is_valid_dedup_title(title):
            norm_title = self._normalize_dedup_text(title)
            if norm_title:
                keys.add(f"title::{norm_title}")

        norm_content = self._normalize_dedup_text(content)
        if len(norm_content) >= 12:
            keys.add(f"content::{norm_content}")

        if title:
            stripped_content = self._strip_title_from_content(content, title)
            norm_stripped_content = self._normalize_dedup_text(stripped_content)
            if len(norm_stripped_content) >= 12:
                keys.add(f"content::{norm_stripped_content}")

        return keys

    @staticmethod
    def _build_duplicate_preference_score(row: CLSTelegraph) -> tuple:
        """
        当两条资讯被判定为重复时，决定保留哪一条。

        当前偏好：
        1. 正文更长的优先（信息量更大）
        2. subjects 更多的优先
        3. 有标题的优先
        4. CLS 略微优先（因为你原始链路就是从 CLS 起家的）
        5. publish_ts 更新的优先
        """
        return (
            len((row.content or "").strip()),
            len(row.subjects or []),
            1 if (row.title or "").strip() else 0,
            1 if row.source == "cls" else 0,
            row.publish_ts or 0,
        )

    def _pick_better_duplicate_row(
        self,
        old_row: CLSTelegraph,
        new_row: CLSTelegraph,
    ) -> CLSTelegraph:
        """
        在两条重复资讯里挑一条更适合保留的。
        """
        old_score = self._build_duplicate_preference_score(old_row)
        new_score = self._build_duplicate_preference_score(new_row)

        return new_row if new_score > old_score else old_row

    def _dedup_rows_in_batch(self, rows: list[CLSTelegraph]) -> list[CLSTelegraph]:
        """
        对“本轮合并后的 CLS + Jin10 批次”做内容级去重。

        逻辑：
        - 先按 dedup key 集合判断是否重复
        - 如果重复，保留信息更完整的一条
        - 这样能拦住“同一轮里两个平台同时抓到同一条资讯”的情况
        """
        if not rows:
            return rows

        deduped_rows: list[CLSTelegraph] = []
        deduped_keys: list[set[str]] = []

        for row in rows:
            row_keys = self._build_cross_source_dedup_keys(row)

            if not row_keys:
                deduped_rows.append(row)
                deduped_keys.append(set())
                continue

            matched_index = None
            for idx, existing_keys in enumerate(deduped_keys):
                if row_keys & existing_keys:
                    matched_index = idx
                    break

            if matched_index is None:
                deduped_rows.append(row)
                deduped_keys.append(set(row_keys))
                continue

            kept_row = deduped_rows[matched_index]
            better_row = self._pick_better_duplicate_row(kept_row, row)

            deduped_rows[matched_index] = better_row
            deduped_keys[matched_index] = deduped_keys[matched_index] | row_keys

        deduped_rows.sort(key=lambda x: x.publish_ts or 0)

        removed_count = len(rows) - len(deduped_rows)
        if removed_count > 0:
            logger.info("batch cross-source dedup removed %s duplicate rows", removed_count)

        return deduped_rows


    def is_a_share_trade_day(self, now: datetime | None = None) -> bool:
        """
        判断当前日期是否为 A 股交易日（中国时区）
        """
        now = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
        candidate = pd.Timestamp(now.date())
        return bool(XSHG.is_session(candidate))


    async def sync_daily_kline_snapshot_once(self) -> None:
        """
        每天 15:40 执行一次：
        1. 仅在 A 股交易日执行
        2. 先检查库里是否已有当前业务交易日的数据
        3. 若没有，再爬取东方财富 A 股列表快照
        4. 按 trade_date + symbol 去重 upsert 入库
        5. 成功后删除当日 checkpoint
        """
        if self.daily_kline_snapshot_repository is None:
            logger.warning("daily_kline_snapshot_repository is not initialized")
            return

        checkpoint_file: str | None = None

        try:
            now = datetime.now(CN_TZ)

            # # 非交易日直接跳过
            # if not self.is_a_share_trade_day(now):
            #     logger.info(
            #         "skip daily kline snapshot because today is not a-share trading day, now=%s",
            #         now.isoformat(),
            #     )
            #     return

            # 这里的“当天”按业务交易日定义：
            # 9点前属于上一个交易日；9点后属于当天交易日（若非交易日则回退最近交易日）
            today_trade_date, _ = self.get_a_share_trade_dates(now)
            trade_date = self._format_trade_date(today_trade_date)

            # 先查库：如果当天交易日数据已经存在，就不再启动爬虫
            already_exists = await self.daily_kline_snapshot_repository.has_trade_date_data(trade_date)
            if already_exists:
                logger.info(
                    "skip daily kline snapshot because trade_date=%s already exists in db",
                    trade_date,
                )
                return

            proxy_api_url = (
                "https://sch.shanchendaili.com/api.html"
                "?action=get_ip"
                f"&key={settings.proxy_api_key}"
                "&time=1"
                "&count=1"
                "&type=json"
                "&only=0"
            )

            provider = ShanchenProxyProvider(
                api_url=proxy_api_url,
                timeout=10,
                scheme="http",
            )

            checkpoint_file = f"eastmoney_a_share_checkpoint_{trade_date}.json"

            crawler = EastmoneyAShareCrawler(
                page_size=100,
                timeout=20,
                page_retry=8,
                min_sleep=0.0,
                max_sleep=0.0,
                batch_pages=0,
                batch_sleep_min=0.0,
                batch_sleep_max=0.0,
                checkpoint_file=checkpoint_file,
                proxy_provider=provider,
            )

            raw_rows, _display_rows = await asyncio.to_thread(
                crawler.fetch_all,
                80,
                True,
                False,
            )

            if not raw_rows:
                logger.warning("daily kline snapshot fetched empty, trade_date=%s", trade_date)
                return

            result = await self.daily_kline_snapshot_repository.bulk_upsert(
                rows=raw_rows,
                trade_date=trade_date,
            )

            if result is None:
                logger.warning("daily kline snapshot bulk_upsert not executed, trade_date=%s", trade_date)
                return

            logger.info(
                "daily kline snapshot synced successfully, trade_date=%s, total_rows=%s, matched=%s, modified=%s, upserted=%s",
                trade_date,
                len(raw_rows),
                result.matched_count,
                result.modified_count,
                len(result.upserted_ids),
            )

            # 成功入库后删除当日 checkpoint
            if checkpoint_file and os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
                logger.info("daily kline snapshot checkpoint removed: %s", checkpoint_file)

        except Exception as e:
            logger.exception("sync_daily_kline_snapshot_once failed: %s", e)



    async def _try_register_pending_event_id(self, event_id: str) -> bool:
        """
        尝试把 event_id 注册到“待处理集合”中。

        返回：
        - True：本次成功注册，可以入队
        - False：为空或已在待处理集合中，跳过，避免重复入队
        """
        if not event_id:
            return False

        async with self.pending_event_ids_lock:
            if event_id in self.pending_event_ids:
                return False
            self.pending_event_ids.add(event_id)
            return True

    async def _unregister_pending_event_id(self, event_id: str):
        """
        从待处理集合中移除 event_id。
        """
        if not event_id:
            return

        async with self.pending_event_ids_lock:
            self.pending_event_ids.discard(event_id)

    async def _enqueue_market_telegraphs(
        self,
        rows: list[CLSTelegraph],
        send_insert_card: bool,
    ) -> int:
        """
        将去重后的资讯批量加入队列。

        注意：
        - 这里只负责入队，不做 LLM 分析
        - send_insert_card 也随任务一起进入队列，兼容 startup 首次灌库不发卡
        """
        if not rows:
            return 0

        enqueued_count = 0

        for row in rows:
            can_enqueue = await self._try_register_pending_event_id(row.event_id)
            if not can_enqueue:
                logger.info(
                    "skip enqueue duplicated pending telegraph, source=%s, event_id=%s",
                    row.source,
                    row.event_id,
                )
                continue

            try:
                await self.market_telegraph_queue.put((row, send_insert_card))
                enqueued_count += 1
            except Exception:
                await self._unregister_pending_event_id(row.event_id)
                raise

        return enqueued_count

    async def analyze_single_telegraph(
        self,
        row: CLSTelegraph,
    ) -> tuple[CLSTelegraphLLMAnalysis | dict, bool]:
        """
        对单条资讯执行 LLM 分析。

        说明：
        - 现在 CLS 和 Jin10 都统一成 CLSTelegraph
        - 因此这里复用同一套单条分析逻辑
        - 后续如果 Jin10 想做 source 定制 prompt，也只需要在这里扩展

        返回：
        - analysis: 标准化后的 LLM 分析结果
        - is_success: 本次 LLM 分析是否成功
        """
        content = (row.content or "").strip()
        subjects = row.subjects or []

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
                "telegraph llm analyzed successfully, source=%s, event_id=%s, score=%s",
                row.source,
                row.event_id,
                analysis.score,
            )
            return analysis, True

        except Exception as e:
            logger.exception(
                "telegraph llm analyze failed, source=%s, event_id=%s, error=%s",
                row.source,
                row.event_id,
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

    async def _market_telegraph_worker(self, worker_no: int):
        """
        市场资讯 worker。

        职责：
        1. 从队列取出去重后的单条资讯
        2. 执行 LLM 分析
        3. 回填 llm_analysis 并 upsert 入库
        4. 若为新插入且允许发卡，则发送飞书卡片
        5. 触发版块衍生视图刷新事件
        """
        while True:
            got_item = False
            row = None
            send_insert_card = True

            try:
                row, send_insert_card = await self.market_telegraph_queue.get()
                got_item = True

                llm_analysis, llm_ok = await self.analyze_single_telegraph(row)
                row.llm_analysis = llm_analysis

                update_result = await self.cls_telegraph_repository.upsert_one(row)
                is_new_insert = bool(getattr(update_result, "upserted_id", None))

                card_ok = None
                if is_new_insert and send_insert_card:
                    card_ok = await self.send_cls_telegraph_insert_card(row)

                logger.info(
                    "market telegraph processed by worker, worker=%s, source=%s, event_id=%s, "
                    "llm_ok=%s, is_new_insert=%s, card_ok=%s, queue_size=%s",
                    worker_no,
                    row.source,
                    row.event_id,
                    llm_ok,
                    is_new_insert,
                    card_ok,
                    self.market_telegraph_queue.qsize(),
                )

                # 有新处理完成的数据后，通知后台统一刷新衍生视图
                self.sector_views_refresh_event.set()

            except asyncio.CancelledError:
                logger.info("market telegraph worker cancelled, worker=%s", worker_no)
                raise
            except Exception as e:
                logger.exception(
                    "market telegraph worker failed, worker=%s, source=%s, event_id=%s, error=%s",
                    worker_no,
                    getattr(row, "source", None),
                    getattr(row, "event_id", None),
                    e,
                )
            finally:
                if row is not None:
                    await self._unregister_pending_event_id(row.event_id)

                if got_item:
                    self.market_telegraph_queue.task_done()

    async def _refresh_sector_3d_daily_summary(self):
        """
        重建“当天实时三日内版块汇总”。

        说明：
        - 该方法只负责触发 repository 重算并记录日志
        - 失败只记日志，不影响资讯主同步链路
        - 即使没有新增新闻，只要窗口右移，也有必要重建
        """
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
        """
        重建“当天市场投资倾向排行榜”。

        说明：
        - 基于 cls_telegraphs 已入库并已完成 llm_analysis 的数据进行重算
        - 失败只记日志，不影响主流程
        """
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
        """
        重建“当天市场热度排行榜”。

        说明：
        - 基于 cls_telegraphs 已入库的数据进行重算
        - 只使用数量 + 时间，不使用单条新闻 score
        - 失败只记日志，不影响主流程
        """
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

    async def _refresh_sector_views(self):
        """
        统一刷新所有基于 cls_telegraphs 的版块衍生视图。

        当前包括：
        1. 实时三日内版块汇总
        2. 市场投资倾向排行榜
        3. 市场热度排行榜

        设计目的：
        - 让同步入口只调一个刷新方法
        - 避免多处出口漏刷新
        """
        await self._refresh_sector_3d_daily_summary()
        await self._refresh_sector_investment_preference_ranking()
        await self._refresh_sector_market_heat_ranking()

    async def _sector_views_refresh_loop(self):
        """
        版块衍生视图后台刷新循环。

        设计：
        - worker 每处理完一条只 set event
        - 这里统一做一个轻微 debounce，再批量刷新
        - 避免 5 个 worker 每条都直接触发全量重算
        """
        while True:
            try:
                await self.sector_views_refresh_event.wait()

                # 简单 debounce：等几秒，尽量合并一批已完成处理的结果
                await asyncio.sleep(5)

                self.sector_views_refresh_event.clear()
                await self._refresh_sector_views()

            except asyncio.CancelledError:
                logger.info("sector views refresh loop cancelled")
                raise
            except Exception as e:
                logger.exception("sector views refresh loop failed: %s", e)

    async def fetch_new_cls_telegraphs(
        self,
        latest_ts: int | None,
        rn: int = 20,
    ) -> list[CLSTelegraph]:
        """
        抓取最新一批 CLS 电报候选数据。

        规则：
        1. 每次只抓最新 rn 条
        2. 不分页
        3. 不做停机期间历史缺失数据回补
        4. 只保留 event_id 和 content 都存在的有效数据
        5. 按 event_id 去重
        6. 若 latest_ts 不为空，则过滤掉时间更早的数据
        7. 最终按 publish_ts 升序返回，方便后续顺序处理

        说明：
        - 这里 latest_ts 是 CLS 自己的最新时间，不是全局最新时间
        """
        batch = await asyncio.to_thread(fetch_latest_cls_telegraphs, rn)

        if not batch:
            logger.info("no cls telegraphs fetched")
            return []

        batch = [row for row in batch if row.event_id and row.content]
        if not batch:
            logger.info("empty valid cls telegraph batch")
            return []

        rows = []
        seen_event_ids = set()

        for row in batch:
            event_id = row.event_id
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)

            row_ts = row.publish_ts or 0

            # 保留“同秒数据”，只过滤更早的数据
            # 同秒重复由后面的 event_id 去重兜底
            if latest_ts is not None and row_ts < latest_ts:
                continue

            rows.append(row)

        rows.sort(key=lambda x: x.publish_ts or 0)
        return rows

    async def fetch_new_jin10_telegraphs(
        self,
        latest_ts: int | None,
        limit: int = 20,
        detail_limit: int = 10,
        sleep_seconds: float = 0.2,
    ) -> list[CLSTelegraph]:
        """
        抓取最新一批 Jin10 电报候选数据。

        规则与 CLS 基本一致：
        1. 只保留 event_id 和 content 都存在的有效数据
        2. 按 event_id 去重
        3. latest_ts 按 Jin10 自己的 source 游标过滤
        4. 最终按 publish_ts 升序返回
        """
        batch = await asyncio.to_thread(
            fetch_latest_jin10_telegraphs,
            limit,
            detail_limit,
            sleep_seconds,
        )

        if not batch:
            logger.info("no jin10 telegraphs fetched")
            return []

        batch = [row for row in batch if row.event_id and row.content]
        if not batch:
            logger.info("empty valid jin10 telegraph batch")
            return []

        rows = []
        seen_event_ids = set()

        for row in batch:
            event_id = row.event_id
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)

            row_ts = row.publish_ts or 0

            # 同样只过滤更早的数据，同秒重复交给 event_id 去重
            if latest_ts is not None and row_ts < latest_ts:
                continue

            rows.append(row)

        rows.sort(key=lambda x: x.publish_ts or 0)
        return rows

    async def fetch_new_10jqka_telegraphs(
        self,
        latest_ts: int | None,
        rn: int = 20,
    ) -> list[CLSTelegraph]:
        """
        抓取最新一批 10jqka 快讯候选数据。

        规则与 CLS / Jin10 基本一致：
        1. 只保留 event_id 和 content 都存在的有效数据
        2. 按 event_id 去重
        3. latest_ts 按 10jqka 自己的 source 游标过滤
        4. 最终按 publish_ts 升序返回
        """
        batch = await asyncio.to_thread(fetch_latest_10jqka_telegraphs, rn)

        if not batch:
            logger.info("no 10jqka telegraphs fetched")
            return []

        batch = [row for row in batch if row.event_id and row.content]
        if not batch:
            logger.info("empty valid 10jqka telegraph batch")
            return []

        rows = []
        seen_event_ids = set()

        for row in batch:
            event_id = row.event_id
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)

            row_ts = row.publish_ts or 0

            # 同样只过滤更早的数据，同秒重复交给 event_id 去重
            if latest_ts is not None and row_ts < latest_ts:
                continue

            rows.append(row)

        rows.sort(key=lambda x: x.publish_ts or 0)
        return rows

    async def fetch_new_market_telegraphs(self) -> list[CLSTelegraph]:
        """
        统一抓取市场资讯（CLS + Jin10 + 10jqka）。

        核心逻辑：
        1. 各 source 分别获取自己的最新时间游标
        2. 分别抓取各自增量
        3. 合并成一个统一待处理列表
        4. 按时间升序返回，供后续统一分析

        这样做的好处：
        - 后面的 LLM、入库、衍生视图逻辑都不需要拆成三套
        """
        if self.cls_telegraph_repository is None:
            logger.warning("cls_telegraph_repository is not initialized")
            return []

        cls_latest_ts = await self.cls_telegraph_repository.get_latest_publish_ts_by_source("cls")
        jin10_latest_ts = await self.cls_telegraph_repository.get_latest_publish_ts_by_source("jin10")
        jqka_latest_ts = await self.cls_telegraph_repository.get_latest_publish_ts_by_source("10jqka")

        cls_rows = await self.fetch_new_cls_telegraphs(
            latest_ts=cls_latest_ts,
            rn=20,
        )

        jin10_rows = await self.fetch_new_jin10_telegraphs(
            latest_ts=jin10_latest_ts,
            limit=20,
            detail_limit=10,
            sleep_seconds=0.2,
        )

        jqka_rows = await self.fetch_new_10jqka_telegraphs(
            latest_ts=jqka_latest_ts,
            rn=20,
        )

        rows = cls_rows + jin10_rows + jqka_rows
        rows.sort(key=lambda x: x.publish_ts or 0)
        return rows
    
    async def sync_cls_telegraphs_once(self, send_insert_card: bool = True):
        """
        执行一轮市场资讯同步。

        注意：
        - 为了尽量少改现有主流程，这里保留原方法名 sync_cls_telegraphs_once
        - 但当前实际同步来源已经扩展为：CLS + Jin10

        完整流程：
        1. 分别按 source 获取 CLS / Jin10 各自最新 publish_ts
        2. 分别抓取 CLS / Jin10 候选数据
        3. 合并为统一待分析列表
        4. 先按 event_id 过滤一次，避免同 id 重复
        5. 再做批次内跨平台内容去重
        6. 去重后的 rows 不再串行执行 LLM，而是统一加入队列
        7. 由 5 个 worker 并发完成：LLM -> upsert -> 发卡
        8. 版块衍生视图由后台刷新任务统一节流刷新

        参数：
        - send_insert_card:
          True  -> 新插入资讯发送飞书卡
          False -> 常用于 startup 首次灌库，避免一次性刷屏
        """
        if self.cls_telegraph_repository is None:
            logger.warning("cls_telegraph_repository is not initialized")
            return

        rows = await self.fetch_new_market_telegraphs()

        if not rows:
            logger.info("no candidate market telegraphs after fetch")
            return

        # 第一步：按 event_id 过滤一次，避免同 id 重复进入队列
        event_ids = [row.event_id for row in rows if row.event_id]
        existing_event_ids = await self.cls_telegraph_repository.get_existing_event_ids(event_ids)
        rows = [row for row in rows if row.event_id not in existing_event_ids]

        if not rows:
            logger.info("no new market telegraphs after event_id dedup")
            return

        # 第二步：批次内跨平台去重
        rows = self._dedup_rows_in_batch(rows)

        if not rows:
            logger.info("no new market telegraphs after batch cross-source dedup")
            return

        # 升序处理，保证入队和日志顺序更接近真实发布时间顺序
        rows.sort(key=lambda x: x.publish_ts or 0)

        cls_count = sum(1 for row in rows if row.source == "cls")
        jin10_count = sum(1 for row in rows if row.source == "jin10")
        jqka_count = sum(1 for row in rows if row.source == "10jqka")

        enqueued_count = await self._enqueue_market_telegraphs(
            rows=rows,
            send_insert_card=send_insert_card,
        )

        if enqueued_count <= 0:
            logger.info(
                "no market telegraphs enqueued after pending-event dedup, "
                "cls_count=%s, jin10_count=%s, jqka_count=%s, queue_size=%s",
                cls_count,
                jin10_count,
                jqka_count,
                self.market_telegraph_queue.qsize(),
            )
            return

        max_ts = max((row.publish_ts or 0) for row in rows)
        logger.info(
            "market telegraphs enqueued successfully, enqueue_count=%s, cls_count=%s, "
            "jin10_count=%s, jqka_count=%s, latest_publish_ts=%s, "
            "send_insert_card=%s, queue_size=%s",
            enqueued_count,
            cls_count,
            jin10_count,
            jqka_count,
            max_ts,
            send_insert_card,
            self.market_telegraph_queue.qsize(),
        )

    async def cls_telegraph_polling_loop(self):
        """
        市场资讯轮询主循环。

        注意：
        - 为尽量少改动旧代码，方法名仍然保留 cls_telegraph_polling_loop
        - 当前轮询实际已经覆盖 CLS + Jin10 两个来源

        行为：
        - 应用启动后常驻运行
        - 每隔 5 分钟执行一次同步
        - CancelledError 需要继续抛出，确保任务能被正常停止
        - 其他异常只记录日志，避免轮询任务整体退出
        """
        while True:
            try:
                await asyncio.sleep(300)
                await self.sync_cls_telegraphs_once(send_insert_card=True)
            except asyncio.CancelledError:
                logger.info("market telegraph polling loop cancelled")
                raise
            except Exception as e:
                logger.exception("market telegraph polling loop failed: %s", e)

    @staticmethod
    def _extract_ranking_rows(ranking_data):
        if not ranking_data:
            return []

        if isinstance(ranking_data, list):
            return ranking_data

        if isinstance(ranking_data, dict):
            for key in ("sector_rankings", "rankings", "rows", "items", "data", "list"):
                value = ranking_data.get(key)
                if isinstance(value, list):
                    return value

        return []
    
    async def _load_card_top5_rankings(self) -> tuple[list, list]:
        """
        加载卡片展示用的两个榜单 Top5。
        这里按当前业务交易日对应的 analysis_date 去取。
        """
        investment_top5 = []
        heat_top5 = []

        try:
            ## 目前直接用当前日期的分析结果，后续如果需要更精确的“资讯发布时间对应的分析结果”，可以改成根据资讯 publish_ts 去找对应的 analysis_date
            # today_trade_date, _ = self.get_a_share_trade_dates()
            # analysis_date = self._format_trade_date(today_trade_date)
            analysis_date = datetime.now(CN_TZ).date().isoformat()
        except Exception as e:
            logger.exception("resolve card analysis_date failed: %s", e)
            return investment_top5, heat_top5

        if self.sector_investment_preference_ranking_repository is not None:
            try:
                ranking_data = await self.sector_investment_preference_ranking_repository.get_investment_preference_ranking(
                    analysis_date,
                    limit=5,
                )
                investment_top5 = self._extract_ranking_rows(ranking_data)[:5]
            except Exception as e:
                logger.exception(
                    "load investment preference top5 failed, analysis_date=%s, err=%s",
                    analysis_date,
                    e,
                )
        else:
            logger.warning("sector_investment_preference_ranking_repository is not initialized")

        if self.sector_market_heat_ranking_repository is not None:
            try:
                ranking_data = await self.sector_market_heat_ranking_repository.get_market_heat_ranking(
                    analysis_date,
                    limit=5,
                )
                heat_top5 = self._extract_ranking_rows(ranking_data)[:5]
            except Exception as e:
                logger.exception(
                    "load market heat top5 failed, analysis_date=%s, err=%s",
                    analysis_date,
                    e,
                )
        else:
            logger.warning("sector_market_heat_ranking_repository is not initialized")

        return investment_top5, heat_top5


    async def send_cls_telegraph_insert_card(self, row: CLSTelegraph) -> bool:
        try:
            investment_top5, heat_top5 = await self._load_card_top5_rankings()

            card = self.card_builder.build_cls_telegraph_insert_card(
                row=row,
                investment_top5=investment_top5,
                heat_top5=heat_top5,
            )

            await self.notifier.send_card(card)

            logger.info(
                "telegraph insert card sent successfully, source=%s, event_id=%s, investment_top5_count=%s, heat_top5_count=%s",
                row.source,
                row.event_id,
                len(investment_top5),
                len(heat_top5),
            )
            return True
        except Exception as e:
            logger.exception(
                "send telegraph insert card failed, source=%s, event_id=%s, error=%s",
                row.source,
                row.event_id,
                e,
            )
            return False

    async def startup(self):
        """
        应用启动流程。

        顺序：
        1. 启动飞书 notifier
        2. 建立 Mongo 连接
        3. 初始化各 repository 并建索引
        4. 启动每日调度器（盘前分析 + A股日快照）
        5. 启动 5 个市场资讯 worker
        6. 启动版块衍生视图后台刷新任务
        7. 启动时先同步一次市场资讯
        8. 创建常驻轮询后台任务
        """
        await self.notifier.startup()

        # 建立 Mongo 客户端与数据库对象
        self.mongo_client = AsyncIOMotorClient(settings.mongo_uri)
        self.db = self.mongo_client[settings.mongo_db_name]

        # 初始化统一资讯原始表 repository
        self.cls_telegraph_repository = CLSTelegraphRepository(self.db)
        await self.cls_telegraph_repository.create_indexes()

        # 初始化三日版块汇总 repository
        self.sector_3d_daily_summary_repository = Sector3DDailySummaryRepository(
            self.db,
            timezone="Asia/Shanghai",
        )
        await self.sector_3d_daily_summary_repository.create_indexes()

        # 初始化市场投资倾向排行榜 repository
        self.sector_investment_preference_ranking_repository = SectorInvestmentPreferenceRankingRepository(
            self.db,
            timezone="Asia/Shanghai",
        )
        await self.sector_investment_preference_ranking_repository.create_indexes()

        # 初始化市场热度排行榜 repository
        self.sector_market_heat_ranking_repository = SectorMarketHeatRankingRepository(
            self.db,
            timezone="Asia/Shanghai",
        )
        await self.sector_market_heat_ranking_repository.create_indexes()

        # 初始化每日盘前分析 repository
        self.daily_market_analysis_repository = DailyMarketAnalysisRepository(self.db)
        await self.daily_market_analysis_repository.create_indexes()

        # 初始化 A 股日快照 repository
        self.daily_kline_snapshot_repository = DailyKLineSnapshotRepository(self.db)
        await self.daily_kline_snapshot_repository.create_indexes()

        # 初始化每日个股技术分析结果 repository
        self.daily_stock_technical_analysis_result_repository = DailyStockTechnicalAnalysisResultRepository(self.db)
        await self.daily_stock_technical_analysis_result_repository.create_indexes()

        # 初始化每日个股技术分析服务
        self.daily_stock_technical_analysis_service = DailyStockTechnicalAnalysisService(
            daily_market_analysis_repository=self.daily_market_analysis_repository,
            daily_kline_snapshot_repository=self.daily_kline_snapshot_repository,
            technical_result_repository=self.daily_stock_technical_analysis_result_repository,
            resolve_target_trade_date=self.resolve_target_trade_date,
            worker_concurrency=settings.stock_tech_analysis_worker_concurrency,
            running_timeout_minutes=settings.stock_tech_analysis_running_timeout_minutes,
        )


        # 启动时主动检查一次 A 股日快照：
        # - 非交易日会自动跳过
        # - 当天交易日已有数据会自动跳过
        # - 当天交易日还没有数据则补抓一次
        try:
            await self.sync_daily_kline_snapshot_once()
        except Exception as e:
            logger.warning("startup daily kline snapshot skipped: %s", e)

        # 启动每日盘前分析调度器
        try:
            await self._start_scheduler(
                self.market_analysis_scheduler,
                "market_analysis_scheduler",
            )
        except Exception as e:
            logger.exception("start market_analysis_scheduler failed: %s", e)

        # 启动每日 A 股日快照调度器（15:40）
        try:
            await self._start_scheduler(
                self.daily_kline_snapshot_scheduler,
                "daily_kline_snapshot_scheduler",
            )
        except Exception as e:
            logger.exception("start daily_kline_snapshot_scheduler failed: %s", e)

        # 启动市场资讯 worker 池
        self.market_telegraph_worker_tasks = [
            asyncio.create_task(self._market_telegraph_worker(i + 1))
            for i in range(self.market_telegraph_worker_count)
        ]

        # 启动版块衍生视图后台刷新任务
        self.sector_views_refresh_task = asyncio.create_task(
            self._sector_views_refresh_loop()
        )

        # 启动时先同步一次市场资讯
        try:
            await self.sync_cls_telegraphs_once(send_insert_card=True)
        except Exception as e:
            logger.exception("initial market telegraph sync failed: %s", e)

        # 创建常驻轮询任务：之后每 5 分钟自动拉取一次市场资讯
        self.cls_telegraph_polling_task = asyncio.create_task(
            self.cls_telegraph_polling_loop()
        )


    async def shutdown(self):
        """
        应用关闭流程。

        顺序：
        1. 取消轮询任务
        2. 取消版块衍生视图刷新任务
        3. 取消 worker 池
        4. 停止每日调度器（盘前分析 + A股日快照）
        5. 关闭 Mongo 连接
        6. 关闭飞书 notifier
        """
        if self.daily_stock_technical_analysis_task is not None:
            self.daily_stock_technical_analysis_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.daily_stock_technical_analysis_task
            self.daily_stock_technical_analysis_task = None

        if self.cls_telegraph_polling_task is not None:
            self.cls_telegraph_polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.cls_telegraph_polling_task
            self.cls_telegraph_polling_task = None

        if self.sector_views_refresh_task is not None:
            self.sector_views_refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.sector_views_refresh_task
            self.sector_views_refresh_task = None

        if self.market_telegraph_worker_tasks:
            for task in self.market_telegraph_worker_tasks:
                task.cancel()

            for task in self.market_telegraph_worker_tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            self.market_telegraph_worker_tasks = []

        try:
            await self._stop_scheduler(
                self.market_analysis_scheduler,
                "market_analysis_scheduler",
            )
        except Exception as e:
            logger.exception("stop market_analysis_scheduler failed: %s", e)

        try:
            await self._stop_scheduler(
                self.daily_kline_snapshot_scheduler,
                "daily_kline_snapshot_scheduler",
            )
        except Exception as e:
            logger.exception("stop daily_kline_snapshot_scheduler failed: %s", e)

        if self.mongo_client is not None:
            self.mongo_client.close()

        await self.notifier.shutdown()

    def _trigger_daily_stock_technical_analysis_background(self, analysis_trade_date: str | None = None):
        """
        非阻塞触发每日个股技术分析：
        - 盘前主流程不等待该任务完成
        - 已有同类任务在跑时不重复创建
        """
        if self.daily_stock_technical_analysis_service is None:
            logger.warning("daily_stock_technical_analysis_service is not initialized")
            return

        if self.daily_stock_technical_analysis_task is not None and not self.daily_stock_technical_analysis_task.done():
            logger.info("daily stock technical analysis task already running, skip duplicate trigger")
            return

        async def _runner():
            try:
                await self.daily_stock_technical_analysis_service.run_once(analysis_trade_date=analysis_trade_date)
                logger.info("daily stock technical analysis service finished")
            except Exception as e:
                logger.exception("daily stock technical analysis service failed: %s", e)

        self.daily_stock_technical_analysis_task = asyncio.create_task(
            _runner(),
            name="daily-stock-technical-analysis",
        )
        logger.info("daily stock technical analysis service triggered in background")

    async def send_daily_test_card(self):
        """
        发送测试卡片。

        用途：
        - 验证飞书发送链路是否正常
        - 验证卡片渲染样式是否符合预期
        """
        card = self.card_builder.build_daily_test_card()
        await self.notifier.send_card(card)
        logger.info("daily test card sent")

    async def send_daily_market_analysis_card(self):
        """
        执行“盘前主线分析”全流程。

        流程：
        1. 获取当前业务交易日和前一交易日
        2. 抓取今日早盘材料
        3. 抓取前一交易日复盘内容
        4. 调用 LLM 生成盘前主线分析文本
        5. 按 analysis_date 唯一键 upsert 到 Mongo
        6. 发送飞书卡片

        注意：
        - 同一天只保留一条记录
        - 如果因为重启或重跑导致当天再次执行，会更新当天记录，不会新增第二条
        """
        try:
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

            prev_day_review = await asyncio.to_thread(
                fetch_fupan_full_visible_text,
                review_url,
            )

            logger.info(
                "previous day review fetched successfully, review_len=%s",
                len(prev_day_review or ""),
            )

            # 优先使用早盘数据中的日期；若缺失，则用当前交易日格式化结果兜底
            analysis_date = (
                (morning_data.get("date") or "").strip()
                or self._format_trade_date(today_trade_date)
            )

            investment_preference_ranking = None
            market_heat_ranking = None

            if self.sector_investment_preference_ranking_repository is not None:
                try:
                    investment_preference_ranking = await (
                        self.sector_investment_preference_ranking_repository.get_investment_preference_ranking(
                            analysis_date,
                            limit=12,
                        )
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

            mainline_sectors: list[dict] = []
            sector_top_stocks: list[dict] = []
            sector_proxy_provider = NoProxyProvider()

            if settings.proxy_api_key:
                try:
                    proxy_api_url = (
                        "https://sch.shanchendaili.com/api.html"
                        "?action=get_ip"
                        f"&key={settings.proxy_api_key}"
                        "&time=1"
                        "&count=1"
                        "&type=json"
                        "&only=0"
                    )
                    sector_proxy_provider = ShanchenProxyProvider(
                        api_url=proxy_api_url,
                        timeout=10,
                        scheme="http",
                    )
                except Exception as e:
                    logger.exception("init sector proxy provider failed, fallback local only: %s", e)
                    sector_proxy_provider = NoProxyProvider()

            try:
                mainline_sectors = extract_mainline_sectors(analysis_text, top_n=5)
            except Exception as e:
                logger.exception("extract mainline sectors failed: %s", e)
                mainline_sectors = []

            for sector in mainline_sectors:
                rank = sector.get("rank")
                sector_name = (sector.get("sector_name") or "").strip()
                if not sector_name:
                    continue

                sector_item = {
                    "rank": rank,
                    "sector_name": sector_name,
                    "sector_code": None,
                    "stocks": [],
                }
                try:
                    fetched = await asyncio.to_thread(
                        fetch_sector_top_stocks_by_name,
                        sector_name,
                        20,
                        12,
                        sector_proxy_provider,
                        1,
                    )
                    sector_item["sector_code"] = fetched.get("sector_code")
                    sector_item["stocks"] = fetched.get("stocks") or []
                except Exception as e:
                    logger.exception(
                        "fetch sector top stocks failed in bootstrap, sector_name=%s, err=%s",
                        sector_name,
                        e,
                    )
                sector_top_stocks.append(sector_item)

            # 先入库/更新，保证当天只有一条
            if self.daily_market_analysis_repository is not None:
                doc = self._build_daily_market_analysis_doc(
                    analysis_date=analysis_date,
                    trade_date=today_trade_date,
                    prev_trade_date=prev_trade_date,
                    morning_data=morning_data,
                    prev_day_review=prev_day_review,
                    analysis_text=analysis_text,
                    mainline_sectors=mainline_sectors,
                    sector_top_stocks=sector_top_stocks,
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

            # 独立模块：盘前分析完成后，后台触发每日个股纯技术分析服务（不阻塞主卡片发送）
            self._trigger_daily_stock_technical_analysis_background(analysis_trade_date=analysis_date)

            # 发送盘前主线分析飞书卡片
            card = self.card_builder.build_daily_market_analysis_card(
                date=analysis_date,
                analysis_text=analysis_text,
                morning_data=morning_data,
            )

            await self.notifier.send_card(card)
            logger.info("daily market analysis card sent")

        except Exception as e:
            logger.exception("send_daily_market_analysis_card failed: %s", e)
            raise
