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
from app.repo import CLSTelegraphRepository, DailyMarketAnalysisRepository, Sector3DDailySummaryRepository, SectorInvestmentPreferenceRankingRepository, SectorMarketHeatRankingRepository
from app.crawlers.Get_cls_telegraph import fetch_latest_telegraphs

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
        4. 管理财联社电报的轮询任务
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
        # Mongo 客户端
        self.mongo_client = None
        # 当前业务数据库对象
        self.db = None

        # 财联社电报原始表 repository
        self.cls_telegraph_repository = None

        # 三日内版块汇总表 repository
        self.sector_3d_daily_summary_repository = None

        # 市场投资倾向排行榜 repository
        self.sector_investment_preference_ranking_repository = None

         # 市场热度排行榜 repository
        self.sector_market_heat_ranking_repository = None

        # 每日盘前分析表 repository
        self.daily_market_analysis_repository = None

        # 财联社电报轮询任务句柄，启动后会保存 create_task 的返回值，shutdown 时用于取消任务
        self.cls_telegraph_polling_task = None

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
    ) -> dict:
        """
        构造“盘前主线分析”入库文档。

        说明：
        - analysis_date 是唯一键语义，同一天只保留一条
        - 如果当天重复执行，会通过 upsert 覆盖更新，而不是新增多条
        """
        return {
            "analysis_date": analysis_date,   # 唯一键：同一天只保留一条
            "trade_date": trade_date,         # 当前交易日，格式 YYYYMMDD
            "prev_trade_date": prev_trade_date,  # 前一交易日，格式 YYYYMMDD
            "source": morning_data.get("source"),
            "morning_data": morning_data,
            "prev_day_review": prev_day_review,
            "analysis_text": analysis_text,
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

    async def analyze_single_cls_telegraph(self, row: dict) -> tuple[dict, bool]:
        """
        对单条财联社电报执行 LLM 分析。

        输入：
        - row: 财联社电报原始数据，至少包含 content / subjects / event_id

        返回：
        - analysis_dict: 标准化后的 LLM 分析结果
        - is_success: 本次 LLM 分析是否成功

        兜底策略：
        - 内容为空：直接返回中性结果
        - LLM 报错：记录异常，并以中性结果兜底入库，保证主流程不中断
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

    async def _refresh_sector_3d_daily_summary(self):
        """
        重建“当天实时三日内版块汇总”。

        说明：
        - 该方法只负责触发 repository 重算并记录日志
        - 失败只记日志，不影响财联社主同步链路
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
        - 与三日版块汇总并行存在，属于另一张衍生结果表
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
        - 与三日版块汇总、市场投资倾向排行并行存在，属于另一张衍生结果表
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
        - 让 sync_cls_telegraphs_once() 只调一个入口
        - 避免多个出口路径里漏掉某个衍生视图刷新
        """
        await self._refresh_sector_3d_daily_summary()
        await self._refresh_sector_investment_preference_ranking()
        await self._refresh_sector_market_heat_ranking()

    async def fetch_new_cls_telegraphs(
        self,
        latest_ts: int | None,
        rn: int = 20,
    ) -> list[dict]:
        """
        抓取最新一批财联社电报候选数据。

        规则：
        1. 每次只抓最新 rn 条
        2. 不分页
        3. 不做停机期间历史缺失数据回补
        4. 只保留 event_id 和 content 都存在的有效数据
        5. 按 event_id 去重
        6. 若 latest_ts 不为空，则过滤掉时间更早的数据
        7. 最终按 publish_ts 升序返回，方便后续顺序处理
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
        执行一轮财联社电报同步。

        完整流程：
        1. 获取库中当前最大 publish_ts
        2. 抓取最近一批候选电报
        3. 过滤掉已存在 event_id，避免重复分析
        4. 对真正新增的数据做 LLM 分析
        5. 写入 cls_telegraphs
        6. 若是本次新插入且允许发卡，则发送飞书入库卡片
        7. 本轮结束后刷新所有版块衍生视图

        参数：
        - send_insert_card:
          True  -> 新插入电报发送飞书卡
          False -> 常用于 startup 首次灌库，避免一次性刷屏

        注意：
        - 无论本次是否有新增电报，都会在结束时刷新衍生视图
        - 这样即使没有新消息，72 小时滚动窗口右移后，版块汇总与投资倾向排行也能保持最新
        """
        if self.cls_telegraph_repository is None:
            logger.warning("cls_telegraph_repository is not initialized")
            await self._refresh_sector_views()
            return

        latest_ts = await self.cls_telegraph_repository.get_latest_publish_ts()
        rows = await self.fetch_new_cls_telegraphs(
            latest_ts=latest_ts,
            rn=20,
        )

        if not rows:
            logger.info("no candidate cls telegraphs after paging fetch")
            await self._refresh_sector_views()
            return

        # 再按 event_id 过滤一次：
        # 这样可以避免“同秒旧消息”因为 publish_ts 未回退而重复做 LLM 分析
        event_ids = [row["event_id"] for row in rows if row.get("event_id")]
        existing_event_ids = await self.cls_telegraph_repository.get_existing_event_ids(event_ids)
        rows = [row for row in rows if row.get("event_id") not in existing_event_ids]

        if not rows:
            logger.info("no new cls telegraphs to analyze and upsert")
            await self._refresh_sector_views()
            return

        # 升序处理，保证写库和日志顺序更接近真实发布时间顺序
        rows.sort(key=lambda x: x.get("publish_ts") or 0)

        llm_success_count = 0
        llm_failed_count = 0
        insert_card_success_count = 0
        insert_card_failed_count = 0

        for row in rows:
            # 单条电报先跑 LLM，结果回填到 row["llm_analysis"]
            llm_analysis, llm_ok = await self.analyze_single_cls_telegraph(row)
            row["llm_analysis"] = llm_analysis

            # 再执行 upsert，确保 event_id 唯一
            update_result = await self.cls_telegraph_repository.upsert_one(row)

            # 只有 upserted_id 存在时，说明是“本次新插入”
            is_new_insert = bool(getattr(update_result, "upserted_id", None))

            if llm_ok:
                llm_success_count += 1
            else:
                llm_failed_count += 1

            # 只对“本次真正新入库成功”的数据发卡，避免更新老数据时重复发消息
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

        # 同步结束后统一刷新衍生视图
        await self._refresh_sector_views()

    async def cls_telegraph_polling_loop(self):
        """
        财联社电报轮询主循环。

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
                logger.info("cls telegraph polling loop cancelled")
                raise
            except Exception as e:
                logger.exception("cls telegraph polling loop failed: %s", e)

    async def send_cls_telegraph_insert_card(self, row: dict) -> bool:
        """
        针对单条“新插入成功”的财联社电报发送飞书卡片。

        返回：
        - True: 发送成功
        - False: 发送失败

        说明：
        - 失败不影响主流程
        - 这里只负责构建并发送“电报入库通知卡片”
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
        """
        应用启动流程。

        顺序：
        1. 启动飞书 notifier
        2. 建立 Mongo 连接
        3. 初始化各 repository 并建索引
        4. 启动每日调度器
        5. 启动时先同步一次财联社电报（首次不发入库卡，防止刷屏）
        6. 创建财联社轮询后台任务

        说明：
        - 各步骤尽量做到失败可日志化，不轻易影响整个应用启动
        """
        await self.notifier.startup()

        # 建立 Mongo 客户端与数据库对象
        self.mongo_client = AsyncIOMotorClient(settings.mongo_uri)
        self.db = self.mongo_client[settings.mongo_db_name]

        # 初始化财联社原始数据 repository
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

        # 启动每日盘前调度器
        try:
            await self._start_scheduler()
        except Exception as e:
            logger.exception("start daily scheduler failed: %s", e)

        # 启动时先同步一次财联社数据，但首次灌库不发入库卡，避免群里刷屏
        try:
            await self.sync_cls_telegraphs_once(send_insert_card=False)
        except Exception as e:
            logger.exception("initial cls telegraph sync failed: %s", e)

        # 创建常驻轮询任务：之后每 5 分钟自动拉取一次财联社电报
        self.cls_telegraph_polling_task = asyncio.create_task(
            self.cls_telegraph_polling_loop()
        )

    async def shutdown(self):
        """
        应用关闭流程。

        顺序：
        1. 取消财联社轮询任务
        2. 停止每日调度器
        3. 关闭 Mongo 连接
        4. 关闭飞书 notifier

        说明：
        - 尽量保证资源按相反顺序被正确释放
        """
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

            # 优先使用早盘数据中的日期；若缺失，则用当前交易日格式化结果兜底
            analysis_date = (
                (morning_data.get("date") or "").strip()
                or self._format_trade_date(today_trade_date)
            )

            # 先入库/更新，保证当天只有一条
            if self.daily_market_analysis_repository is not None:
                doc = self._build_daily_market_analysis_doc(
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