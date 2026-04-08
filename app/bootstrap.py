import asyncio
import contextlib
import inspect
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings
from app.feishu import FeishuNotifier
from app.feishu.card_builder import CardBuilder
from app.logger import get_logger
from app.scheduler import DailyScheduler
from app.llm.news_pipeline_llm import analyze_cls_telegraph_v2
from app.repo import (
    CLSTelegraphRepository,
    DailyMarketAnalysisRepository,
    Sector3DDailySummaryRepository,
    SectorInvestmentPreferenceRankingRepository,
    SectorMarketHeatRankingRepository,
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
from app.model import CLSTelegraph, CLSTelegraphLLMAnalysis
from app.services.daily_market_analysis_service import DailyMarketAnalysisService
from app.services.sector_view_service import SectorViewService
from app.services.telegraph_deduplicator import TelegraphDeduplicator

logger = get_logger("bootstrap")



class Application:
    def __init__(self):
        """
        应用主入口对象。

        职责：
        1. 初始化飞书通知组件
        2. 初始化每日调度器
        3. 管理 Mongo 连接与各类 repository
        4. 管理市场资讯轮询任务（当前来源：CLS + Jin10）
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

        # 每日调度器：按配置时间触发盘前分析发送任务
        self.scheduler = DailyScheduler(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone=settings.timezone,
            task_callable=self.send_daily_market_analysis_card,
        )

        # -----------------------------
        # Mongo 相关对象
        # -----------------------------
        self.mongo_client = None
        self.db = None

        # 统一资讯原始表 repository（CLS + Jin10 共用）
        self.cls_telegraph_repository = None

        # 三日内版块汇总表 repository
        self.sector_3d_daily_summary_repository = None

        # 市场投资倾向排行榜 repository
        self.sector_investment_preference_ranking_repository = None

        # 市场热度排行榜 repository
        self.sector_market_heat_ranking_repository = None

        # 每日盘前分析表 repository
        self.daily_market_analysis_repository = None

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

        # 拆分后的独立 service
        self.telegraph_deduplicator: TelegraphDeduplicator | None = None
        self.sector_view_service: SectorViewService | None = None
        self.daily_market_analysis_service: DailyMarketAnalysisService | None = None

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

    async def _start_scheduler(self):
        """
        启动每日调度器。

        兼容两种方法名：
        - startup()
        - start()

        任意命中一个即可启动，否则只记录 warning，不中断主流程。
        """
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
        """
        停止每日调度器。

        兼容两种方法名：
        - shutdown()
        - stop()

        任意命中一个即可停止，否则只记录 warning，不中断主流程。
        """
        if self.scheduler is None:
            return

        for method_name in ("shutdown", "stop"):
            method = getattr(self.scheduler, method_name, None)
            if callable(method):
                await self._maybe_await(method())
                logger.info("daily scheduler stopped by %s()", method_name)
                return

        logger.warning("daily scheduler has no shutdown()/stop() method, skip stopping")

    def _dedup_rows_in_batch(self, rows: list[CLSTelegraph]) -> list[CLSTelegraph]:
        if self.telegraph_deduplicator is None:
            logger.warning("telegraph_deduplicator is not initialized")
            return rows

        deduped_rows = self.telegraph_deduplicator.dedup_rows_in_batch(rows)
        removed_count = len(rows) - len(deduped_rows)
        if removed_count > 0:
            logger.info("batch cross-source dedup removed %s duplicate rows", removed_count)

        return deduped_rows

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
                analyze_cls_telegraph_v2,
                content,
                subjects,
                title=row.title,
                publish_time=row.publish_time,
                source=row.source,
                event_id=row.event_id,
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
                if self.sector_view_service is not None:
                    self.sector_view_service.mark_dirty()

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
            analysis_date = datetime.now().date().isoformat()
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
        4. 启动每日调度器
        5. 启动 5 个市场资讯 worker
        6. 启动版块衍生视图后台刷新任务
        7. 启动时先同步一次市场资讯（首次不发入库卡，防止刷屏）
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

        # 初始化 service（第一阶段：拆去重、衍生视图、盘前分析）
        self.telegraph_deduplicator = TelegraphDeduplicator()
        self.sector_view_service = SectorViewService(
            sector_3d_daily_summary_repository=self.sector_3d_daily_summary_repository,
            sector_investment_preference_ranking_repository=self.sector_investment_preference_ranking_repository,
            sector_market_heat_ranking_repository=self.sector_market_heat_ranking_repository,
        )
        self.daily_market_analysis_service = DailyMarketAnalysisService(
            notifier=self.notifier,
            card_builder=self.card_builder,
            daily_market_analysis_repository=self.daily_market_analysis_repository,
            sector_investment_preference_ranking_repository=self.sector_investment_preference_ranking_repository,
            sector_market_heat_ranking_repository=self.sector_market_heat_ranking_repository,
        )

        # 启动每日盘前调度器
        try:
            await self._start_scheduler()
        except Exception as e:
            logger.exception("start daily scheduler failed: %s", e)

        # 启动市场资讯 worker 池
        self.market_telegraph_worker_tasks = [
            asyncio.create_task(self._market_telegraph_worker(i + 1))
            for i in range(self.market_telegraph_worker_count)
        ]

        # 启动版块衍生视图后台刷新任务
        if self.sector_view_service is not None:
            await self.sector_view_service.startup()

        # 启动时先同步一次市场资讯，但首次灌库不发入库卡，避免群里刷屏
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
        4. 停止每日调度器
        5. 关闭 Mongo 连接
        6. 关闭飞书 notifier
        """
        if self.cls_telegraph_polling_task is not None:
            self.cls_telegraph_polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.cls_telegraph_polling_task
            self.cls_telegraph_polling_task = None

        if self.sector_view_service is not None:
            await self.sector_view_service.shutdown()

        if self.market_telegraph_worker_tasks:
            for task in self.market_telegraph_worker_tasks:
                task.cancel()

            for task in self.market_telegraph_worker_tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            self.market_telegraph_worker_tasks = []

        try:
            await self._stop_scheduler()
        except Exception as e:
            logger.exception("stop daily scheduler failed: %s", e)

        if self.mongo_client is not None:
            self.mongo_client.close()

        await self.notifier.shutdown()

    async def send_daily_test_card(self):
        """
        发送测试卡片。

        用途：
        - 验证飞书发送链路是否正常
        - 验证卡片渲染样式是否符合预期
        """
        if self.daily_market_analysis_service is None:
            logger.warning("daily_market_analysis_service is not initialized")
            return
        await self.daily_market_analysis_service.send_daily_test_card()

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
        if self.daily_market_analysis_service is None:
            logger.warning("daily_market_analysis_service is not initialized")
            return
        try:
            await self.daily_market_analysis_service.send_daily_market_analysis_card()
        except Exception as e:
            logger.exception("send_daily_market_analysis_card failed: %s", e)
            raise
