from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.llm.k_line_analysis_llm import analyze_buy_point
from app.logger import get_logger


logger = get_logger("services.daily_stock_tech")


@dataclass
class DailyStockTechRunStats:
    target_trade_date: str
    total: int = 0
    pre_skipped_succeeded: int = 0
    to_process: int = 0
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_data_insufficient: int = 0
    skipped_by_other_worker: int = 0


class DailyStockTechnicalAnalysisService:
    """每日盘前个股纯技术分析服务（独立模块）。"""

    def __init__(
        self,
        *,
        daily_market_analysis_repository,
        daily_kline_snapshot_repository,
        technical_result_repository,
        resolve_target_trade_date: Callable[[], str],
        worker_concurrency: int = 6,
        running_timeout_minutes: int = 10,
    ):
        self.daily_market_analysis_repository = daily_market_analysis_repository
        self.daily_kline_snapshot_repository = daily_kline_snapshot_repository
        self.technical_result_repository = technical_result_repository
        self.resolve_target_trade_date = resolve_target_trade_date
        self.worker_concurrency = min(max(worker_concurrency, 4), 8)
        self.running_timeout_minutes = running_timeout_minutes

    async def run_once(self) -> DailyStockTechRunStats:
        # target_trade_date 统一作为全链路查库/跳过判断依据
        target_trade_date = self.resolve_target_trade_date()
        stats = DailyStockTechRunStats(target_trade_date=target_trade_date)

        stock_pool = await self._load_stock_pool(target_trade_date)
        stats.total = len(stock_pool)

        if not stock_pool:
            logger.info("stock pool is empty, target_trade_date=%s", target_trade_date)
            return stats

        stock_codes = [item["stock_code"] for item in stock_pool]
        existing_map = await self.technical_result_repository.get_batch_by_trade_date_stock_codes(
            target_trade_date,
            stock_codes,
        )

        succeeded_codes = {
            code
            for code, row in existing_map.items()
            if (row.get("analysis_status") or "") == "succeeded"
        }
        stats.pre_skipped_succeeded = len(succeeded_codes)

        if len(succeeded_codes) == len(stock_pool):
            logger.info(
                "all stocks already succeeded, skip whole batch, target_trade_date=%s, total=%s",
                target_trade_date,
                len(stock_pool),
            )
            return stats

        to_process = [item for item in stock_pool if item["stock_code"] not in succeeded_codes]
        stats.to_process = len(to_process)

        logger.info(
            "daily stock technical analysis start, target_trade_date=%s, total=%s, pre_skipped_succeeded=%s, to_process=%s, worker_concurrency=%s",
            target_trade_date,
            stats.total,
            stats.pre_skipped_succeeded,
            stats.to_process,
            self.worker_concurrency,
        )

        semaphore = asyncio.Semaphore(self.worker_concurrency)

        async def _run_one(stock_item: dict[str, Any]) -> None:
            async with semaphore:
                await self._process_one_stock(
                    target_trade_date=target_trade_date,
                    stock_item=stock_item,
                    stats=stats,
                )

        await asyncio.gather(*[_run_one(item) for item in to_process])

        logger.info(
            "daily stock technical analysis finished, target_trade_date=%s, total=%s, pre_skipped_succeeded=%s, to_process=%s, claimed=%s, succeeded=%s, failed=%s, skipped_data_insufficient=%s, skipped_by_other_worker=%s",
            target_trade_date,
            stats.total,
            stats.pre_skipped_succeeded,
            stats.to_process,
            stats.claimed,
            stats.succeeded,
            stats.failed,
            stats.skipped_data_insufficient,
            stats.skipped_by_other_worker,
        )

        return stats

    async def _load_stock_pool(self, target_trade_date: str) -> list[dict[str, Any]]:
        raw_date = target_trade_date.replace("-", "")
        doc = await self.daily_market_analysis_repository.get_by_trade_date(raw_date)
        if not doc:
            return []

        result: list[dict[str, Any]] = []
        sector_top_stocks = doc.get("sector_top_stocks") or []
        for sector_item in sector_top_stocks:
            sector_name = (sector_item.get("sector_name") or "").strip()
            if not sector_name:
                continue
            sector_rank = sector_item.get("rank")

            for idx, stock in enumerate(sector_item.get("stocks") or [], start=1):
                code = (stock.get("code") or "").strip()
                if not code:
                    continue
                result.append(
                    {
                        "sector_name": sector_name,
                        "sector_rank": sector_rank,
                        "stock_code": code,
                        "stock_name": (stock.get("name") or "").strip(),
                        "stock_rank_in_sector": idx,
                    }
                )
        return result

    async def _process_one_stock(
        self,
        *,
        target_trade_date: str,
        stock_item: dict[str, Any],
        stats: DailyStockTechRunStats,
    ) -> None:
        now = datetime.utcnow()
        claim_result = await self.technical_result_repository.try_claim_running(
            trade_date=target_trade_date,
            stock=stock_item,
            now=now,
            running_timeout_minutes=self.running_timeout_minutes,
        )

        if not claim_result.claimed:
            stats.skipped_by_other_worker += 1
            return

        stats.claimed += 1

        try:
            raw_bars = await self.daily_kline_snapshot_repository.get_recent_bars(
                symbol=stock_item["stock_code"],
                end_trade_date=target_trade_date,
                limit=30,
            )

            bars = [self._to_llm_bar(row) for row in raw_bars]
            bars = [row for row in bars if row is not None]

            if len(bars) < 20:
                stats.skipped_data_insufficient += 1
                await self.technical_result_repository.mark_skipped_data_insufficient(
                    trade_date=target_trade_date,
                    stock_code=stock_item["stock_code"],
                    now=datetime.utcnow(),
                    error_message=f"kline bars insufficient, need >=20, got {len(bars)}",
                    context_fields=self._build_context_fields(stock_item=stock_item, bars=bars),
                )
                return

            context_fields = self._build_context_fields(stock_item=stock_item, bars=bars)
            result = await asyncio.to_thread(
                analyze_buy_point,
                stock_item["stock_code"],
                bars,
                "日线",
                context_fields.get("recent_high"),
                context_fields.get("recent_low"),
            )

            llm_fields = result.llm_analysis.model_dump()
            await self.technical_result_repository.mark_succeeded(
                trade_date=target_trade_date,
                stock_code=stock_item["stock_code"],
                now=datetime.utcnow(),
                context_fields=context_fields,
                llm_fields=llm_fields,
            )
            stats.succeeded += 1
        except Exception as e:
            stats.failed += 1
            await self.technical_result_repository.mark_failed(
                trade_date=target_trade_date,
                stock_code=stock_item["stock_code"],
                now=datetime.utcnow(),
                error_message=str(e),
            )

    @staticmethod
    def _to_llm_bar(row: dict[str, Any]) -> dict[str, Any] | None:
        trade_date = row.get("trade_date")
        open_price = row.get("open_price")
        high_price = row.get("high_price")
        low_price = row.get("low_price")
        close_price = row.get("close_price")

        if (
            not trade_date
            or open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
        ):
            return None

        return {
            "trade_date": trade_date,
            "open_price": float(open_price),
            "high_price": float(high_price),
            "low_price": float(low_price),
            "close_price": float(close_price),
        }

    @staticmethod
    def _build_context_fields(*, stock_item: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
        bars_count = len(bars)
        current_price = bars[-1]["close_price"] if bars else None
        recent_high = max((x["high_price"] for x in bars), default=None)
        recent_low = min((x["low_price"] for x in bars), default=None)
        return {
            "analysis_time": datetime.utcnow().replace(microsecond=0),
            "sector_name": stock_item.get("sector_name"),
            "sector_rank": stock_item.get("sector_rank"),
            "stock_name": stock_item.get("stock_name"),
            "stock_rank_in_sector": stock_item.get("stock_rank_in_sector"),
            "bars_count": bars_count,
            "kline_trade_date_start": bars[0]["trade_date"] if bars else None,
            "kline_trade_date_end": bars[-1]["trade_date"] if bars else None,
            "current_price": current_price,
            "recent_high": recent_high,
            "recent_low": recent_low,
            "input_bars": bars,
        }
