from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.logger import get_logger


logger = get_logger("daily_analysis_task_service")


class DailyAnalysisTaskService:
    """
    每日盘前分析任务执行服务。

    关键能力：
    1. 创建幂等任务
    2. 业务层指数退避重试
    3. 发送卡片幂等（card_sent 防重）
    """

    def __init__(
        self,
        *,
        task_repository,
        market_analysis_service,
        notifier,
        card_builder,
    ):
        self.task_repository = task_repository
        self.market_analysis_service = market_analysis_service
        self.notifier = notifier
        self.card_builder = card_builder

    async def ensure_today_task_exists(self) -> dict[str, Any]:
        today_trade_date, _ = self.market_analysis_service.get_a_share_trade_dates()
        biz_date = self.market_analysis_service.format_trade_date(today_trade_date)
        task, created = await self.task_repository.ensure_task(biz_date=biz_date)
        logger.info(
            "daily analysis task ensured, biz_date=%s, task_id=%s, created=%s, status=%s",
            biz_date,
            task.get("_id"),
            created,
            task.get("status"),
        )
        return task

    @staticmethod
    def _classify_error(error: Exception) -> str:
        text = f"{type(error).__name__}: {error}".lower()
        if "apitimeouterror" in text or "readtimeout" in text or "timeout" in text:
            return "timeout"
        if "ratelimit" in text or "429" in text:
            return "rate_limit"
        if "5xx" in text or "status code 5" in text:
            return "server_error"
        if "parse" in text:
            return "parse_error"
        if "validation" in text or "business" in text:
            return "business_validation_error"
        return "unknown_error"

    @staticmethod
    def _calc_backoff_seconds(retry_count: int) -> int:
        # 指数退避：30s, 60s, 120s, ...，最大 15 分钟
        return min(30 * (2 ** max(0, retry_count - 1)), 900)

    async def execute_claimed_task(self, task: dict[str, Any]) -> None:
        task_id = task.get("_id")
        biz_date = task.get("biz_date")
        retry_count = int(task.get("retry_count") or 0)
        max_retry_count = int(task.get("max_retry_count") or 8)

        logger.info(
            "daily analysis task claimed, task_id=%s, biz_date=%s, retry_count=%s, max_retry_count=%s",
            task_id,
            biz_date,
            retry_count,
            max_retry_count,
        )

        try:
            analysis_text = task.get("analysis_text")
            morning_data = None

            # 如果还没有分析结果，先生成分析文本
            if not analysis_text:
                logger.info("start generate analysis text, task_id=%s, biz_date=%s", task_id, biz_date)
                payload = await self.market_analysis_service.prepare_daily_analysis_payload()
                morning_data = payload["morning_data"]
                analysis_text = await asyncio.to_thread(
                    self.market_analysis_service.generate_analysis_text,
                    payload,
                )
                await self.task_repository.save_analysis_text(
                    task_id=task_id,
                    analysis_text=analysis_text,
                )
                logger.info(
                    "analysis text generated and saved, task_id=%s, biz_date=%s, text_len=%s",
                    task_id,
                    biz_date,
                    len(analysis_text or ""),
                )
            else:
                logger.info("analysis text already exists, skip regeneration, task_id=%s", task_id)

            # 卡片发送幂等：card_sent=True 时直接成功结束，不重复发
            if task.get("card_sent"):
                await self.task_repository.mark_card_sent(task_id=task_id)
                logger.info(
                    "card already sent before, mark succeeded directly, task_id=%s, biz_date=%s",
                    task_id,
                    biz_date,
                )
                return

            if morning_data is None:
                morning_data = {"source": "unknown"}

            card = self.card_builder.build_daily_market_analysis_card(
                date=biz_date,
                analysis_text=analysis_text,
                morning_data=morning_data,
            )
            await self.notifier.send_card(card)
            logger.info("daily analysis feishu card sent, task_id=%s, biz_date=%s", task_id, biz_date)

            await self.task_repository.mark_card_sent(task_id=task_id)
            logger.info("daily analysis task succeeded, task_id=%s, biz_date=%s", task_id, biz_date)
        except Exception as error:
            error_type = self._classify_error(error)
            retry_count += 1
            logger.exception(
                "daily analysis task failed, task_id=%s, biz_date=%s, retry=%s, error_type=%s, error=%s",
                task_id,
                biz_date,
                retry_count,
                error_type,
                error,
            )

            if retry_count >= max_retry_count:
                await self.task_repository.mark_failed(
                    task_id=task_id,
                    retry_count=retry_count,
                    error_type=error_type,
                    error_message=str(error),
                )
                logger.error(
                    "daily analysis task reached max retries and marked failed, task_id=%s, biz_date=%s",
                    task_id,
                    biz_date,
                )
                return

            backoff = self._calc_backoff_seconds(retry_count)
            next_retry_at = datetime.utcnow() + timedelta(seconds=backoff)
            await self.task_repository.mark_retry(
                task_id=task_id,
                retry_count=retry_count,
                next_retry_at=next_retry_at,
                error_type=error_type,
                error_message=str(error),
            )
            logger.warning(
                "daily analysis task scheduled retry, task_id=%s, biz_date=%s, retry=%s, backoff_seconds=%s, next_retry_at=%s",
                task_id,
                biz_date,
                retry_count,
                backoff,
                next_retry_at.isoformat(),
            )
