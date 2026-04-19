from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.crawlers.Get_five_major_index_crawler import FiveMajorIndexCrawler
from app.crawlers.proxy_provider import NoProxyProvider


class DashboardQueryService:
    def __init__(self, application: Any):
        self.application = application

    @staticmethod
    def _normalize_date(value: str | None) -> str | None:
        value = (value or "").strip()
        if not value:
            return None
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        return value

    def _resolve_trade_date(self, trade_date: str | None) -> str:
        normalized = self._normalize_date(trade_date)
        if normalized:
            return normalized
        return self.application.resolve_target_trade_date()

    @staticmethod
    def _safe_strip(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _reason_summary(reason: str | None, max_len: int = 100) -> str:
        content = (reason or "").strip()
        if len(content) <= max_len:
            return content
        return f"{content[:max_len].rstrip()}..."

    @staticmethod
    def _action_type_and_label(row: dict[str, Any]) -> tuple[str, str]:
        status = str(row.get("analysis_status") or "").strip()
        can_trigger_buy = str(row.get("can_trigger_buy") or "").strip().lower()

        if status == "succeeded":
            if can_trigger_buy in {"yes", "true", "1", "买", "buy"}:
                return "buy", "买"
            return "not_buy", "不买"
        if status == "running":
            return "running", "运行中"
        if status == "failed":
            return "failed", "失败"
        if status == "skipped_data_insufficient":
            return "not_buy", "不买"
        return "running", "运行中"

    async def get_major_indices(self) -> dict[str, Any]:
        crawler = FiveMajorIndexCrawler(
            proxy_provider=NoProxyProvider(),
            timeout=15,
            retry_sleep=1.0,
            max_total_attempts=3,
        )
        rows = await asyncio.to_thread(crawler.fetch)

        code_map = {
            "000001": "上证指数",
            "399001": "深证成指",
            "399006": "创业板指",
            "000300": "沪深300",
            "000688": "科创50",
        }

        source_map = {str(item.get("index_code")).zfill(6): item for item in rows}

        indices: list[dict[str, Any]] = []
        trade_date = ""
        updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

        for code, name in code_map.items():
            row = source_map.get(code) or {}
            trade_date = self._normalize_date(row.get("trade_date")) or trade_date
            crawl_time = self._safe_strip(row.get("crawl_time"))
            if crawl_time:
                updated_at = datetime.strptime(crawl_time, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=ZoneInfo("Asia/Shanghai")
                ).isoformat()

            indices.append(
                {
                    "name": name,
                    "code": code,
                    "price": row.get("latest"),
                    "change": row.get("change"),
                    "change_percent": row.get("pct_change"),
                }
            )

        return {
            "trade_date": trade_date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "updated_at": updated_at,
            "indices": indices,
        }

    async def get_overview(self, trade_date: str | None = None) -> dict[str, Any]:
        resolved_trade_date = self._resolve_trade_date(trade_date)

        dma_repo = self.application.daily_market_analysis_repository
        invest_repo = self.application.sector_investment_preference_ranking_repository
        heat_repo = self.application.sector_market_heat_ranking_repository
        tech_repo = self.application.daily_stock_technical_analysis_result_repository

        analysis_doc = await dma_repo.get_by_trade_date(resolved_trade_date)
        if not analysis_doc:
            analysis_doc = await dma_repo.get_latest()

        if analysis_doc:
            resolved_trade_date = self._normalize_date(analysis_doc.get("trade_date")) or resolved_trade_date

        investment_doc = await invest_repo.get_full_by_biz_date(resolved_trade_date)
        heat_doc = await heat_repo.get_full_by_biz_date(resolved_trade_date)
        status_count = await tech_repo.count_grouped_by_status(resolved_trade_date)

        total = sum(status_count.values())

        return {
            "trade_date": resolved_trade_date,
            "analysis_date": self._normalize_date((analysis_doc or {}).get("analysis_date")) or resolved_trade_date,
            "analysis_text": self._safe_strip((analysis_doc or {}).get("analysis_text")),
            "mainline_sectors": (analysis_doc or {}).get("mainline_sectors") or [],
            "investment_ranking_top5": ((investment_doc or {}).get("sector_rankings") or [])[:5],
            "market_heat_top5": ((heat_doc or {}).get("sector_rankings") or [])[:5],
            "stock_analysis_progress": {
                "total": total,
                "succeeded": status_count.get("succeeded", 0),
                "running": status_count.get("running", 0),
                "failed": status_count.get("failed", 0),
                "skipped_data_insufficient": status_count.get("skipped_data_insufficient", 0),
            },
            "system_status": {
                "scheduler_running": bool(
                    self.application.market_analysis_scheduler
                    and self.application.market_analysis_scheduler.is_running
                ),
                "cls_telegraph_polling_running": bool(
                    self.application.cls_telegraph_polling_task
                    and not self.application.cls_telegraph_polling_task.done()
                ),
                "mongo_connected": self.application.db is not None,
                "next_daily_run_at": (
                    self.application.market_analysis_scheduler.next_run_at_iso
                    if self.application.market_analysis_scheduler
                    else None
                ),
            },
        }

    async def get_mainline_sectors(self, trade_date: str | None = None) -> dict[str, Any]:
        resolved_trade_date = self._resolve_trade_date(trade_date)
        analysis_doc = await self.application.daily_market_analysis_repository.get_by_trade_date(resolved_trade_date)
        if not analysis_doc:
            return {"trade_date": resolved_trade_date, "items": []}

        tech_rows = await self.application.daily_stock_technical_analysis_result_repository.list_by_trade_date(
            resolved_trade_date
        )
        tech_map = {self._safe_strip(item.get("stock_code")): item for item in tech_rows}

        sector_top_stocks = analysis_doc.get("sector_top_stocks") or []
        output_items: list[dict[str, Any]] = []

        for index, sector_row in enumerate(sector_top_stocks, start=1):
            sector_name = self._safe_strip(sector_row.get("sector_name"))
            sector_code = self._safe_strip(sector_row.get("sector_code"))
            rank = sector_row.get("rank") or index

            stock_pool = sector_row.get("stocks") or []
            stocks: list[dict[str, Any]] = []
            stats = {
                "stock_count": 0,
                "completed_count": 0,
                "buy_count": 0,
                "not_buy_count": 0,
                "running_count": 0,
                "failed_count": 0,
            }

            for stock in stock_pool:
                stock_code = self._safe_strip(stock.get("stock_code") or stock.get("symbol"))
                tech = tech_map.get(stock_code, {})
                action_type, action_label = self._action_type_and_label(tech)
                analysis_status = self._safe_strip(tech.get("analysis_status"))

                stats["stock_count"] += 1
                if analysis_status in {"succeeded", "failed", "skipped_data_insufficient"}:
                    stats["completed_count"] += 1
                if action_type == "buy":
                    stats["buy_count"] += 1
                elif action_type == "not_buy":
                    stats["not_buy_count"] += 1
                elif action_type == "running":
                    stats["running_count"] += 1
                elif action_type == "failed":
                    stats["failed_count"] += 1

                stocks.append(
                    {
                        "stock_code": stock_code,
                        "stock_name": self._safe_strip(tech.get("stock_name") or stock.get("stock_name")),
                        "stock_rank_in_sector": tech.get("stock_rank_in_sector") or stock.get("rank"),
                        "analysis_status": analysis_status,
                        "conclusion": self._safe_strip(tech.get("conclusion")),
                        "can_trigger_buy": self._safe_strip(tech.get("can_trigger_buy")),
                        "buy_price": tech.get("buy_price"),
                        "stop_loss": tech.get("stop_loss"),
                        "take_profit": tech.get("take_profit"),
                        "reason_summary": self._reason_summary(tech.get("reason")),
                        "action_label": action_label,
                        "action_type": action_type,
                    }
                )

            output_items.append(
                {
                    "rank": rank,
                    "sector_name": sector_name,
                    "sector_code": sector_code,
                    "stats": stats,
                    "stocks": sorted(
                        stocks,
                        key=lambda x: (
                            x.get("stock_rank_in_sector") is None,
                            x.get("stock_rank_in_sector") or 9999,
                            x.get("stock_code") or "",
                        ),
                    ),
                }
            )

        output_items.sort(key=lambda x: (x.get("rank") or 9999, x.get("sector_name") or ""))
        return {"trade_date": resolved_trade_date, "items": output_items}

    async def get_sector_detail(self, sector_name: str, trade_date: str | None = None) -> dict[str, Any] | None:
        sector_name = self._safe_strip(sector_name)
        resolved_trade_date = self._resolve_trade_date(trade_date)

        mainline = await self.get_mainline_sectors(resolved_trade_date)
        sector_info = next((x for x in mainline.get("items", []) if x.get("sector_name") == sector_name), None)
        if not sector_info:
            return None

        invest_doc = await self.application.sector_investment_preference_ranking_repository.get_full_by_biz_date(
            resolved_trade_date
        )
        heat_doc = await self.application.sector_market_heat_ranking_repository.get_full_by_biz_date(resolved_trade_date)

        investment_item = next(
            (x for x in (invest_doc or {}).get("sector_rankings", []) if self._safe_strip(x.get("sector")) == sector_name),
            None,
        )
        heat_item = next(
            (x for x in (heat_doc or {}).get("sector_rankings", []) if self._safe_strip(x.get("sector")) == sector_name),
            None,
        )

        recent_news = await self.application.cls_telegraph_repository.list_recent_by_sector(sector_name, limit=20)

        return {
            "trade_date": resolved_trade_date,
            "sector": sector_info,
            "investment_ranking_item": investment_item,
            "market_heat_ranking_item": heat_item,
            "recent_news": recent_news,
            "summary": sector_info.get("stats") or {},
        }

    async def get_stock_technical(self, stock_code: str, trade_date: str | None = None) -> dict[str, Any] | None:
        resolved_trade_date = self._resolve_trade_date(trade_date)
        cleaned_stock_code = self._safe_strip(stock_code).zfill(6)
        row = await self.application.daily_stock_technical_analysis_result_repository.get_by_trade_date_stock_code(
            resolved_trade_date,
            cleaned_stock_code,
        )
        if not row:
            return None

        return {
            "trade_date": resolved_trade_date,
            "stock_code": cleaned_stock_code,
            "stock_name": self._safe_strip(row.get("stock_name")),
            "sector_name": self._safe_strip(row.get("sector_name")),
            "analysis": row,
        }

    async def get_news_feed(
        self,
        *,
        trade_date: str | None,
        sector: str | None,
        source: str | None,
        keyword: str | None,
        min_score: float | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), 100)
        skip = (safe_page - 1) * safe_page_size

        resolved_trade_date = self._normalize_date(trade_date)

        items = await self.application.cls_telegraph_repository.list_by_filters(
            trade_date=resolved_trade_date,
            sector=self._safe_strip(sector) or None,
            source=self._safe_strip(source) or None,
            keyword=self._safe_strip(keyword) or None,
            min_score=min_score,
            skip=skip,
            limit=safe_page_size,
        )
        total = await self.application.cls_telegraph_repository.count_by_filters(
            trade_date=resolved_trade_date,
            sector=self._safe_strip(sector) or None,
            source=self._safe_strip(source) or None,
            keyword=self._safe_strip(keyword) or None,
            min_score=min_score,
        )

        normalized_items = []
        for row in items:
            llm_analysis = row.get("llm_analysis") or {}
            normalized_items.append(
                {
                    "event_id": self._safe_strip(row.get("event_id")),
                    "source": self._safe_strip(row.get("source")),
                    "publish_ts": row.get("publish_ts"),
                    "publish_time": self._safe_strip(row.get("publish_time")),
                    "title": self._safe_strip(row.get("title")),
                    "content": self._safe_strip(row.get("content")),
                    "subjects": row.get("subjects") or [],
                    "llm_analysis": llm_analysis,
                }
            )

        return {
            "items": normalized_items,
            "pagination": {
                "page": safe_page,
                "page_size": safe_page_size,
                "total": total,
            },
        }

    async def get_rankings(self, biz_date: str | None = None) -> dict[str, Any]:
        resolved_date = self._resolve_trade_date(biz_date)
        investment_doc = await self.application.sector_investment_preference_ranking_repository.get_full_by_biz_date(
            resolved_date
        )
        heat_doc = await self.application.sector_market_heat_ranking_repository.get_full_by_biz_date(resolved_date)

        return {
            "biz_date": resolved_date,
            "investment_ranking": (investment_doc or {}).get("sector_rankings") or [],
            "market_heat_ranking": (heat_doc or {}).get("sector_rankings") or [],
        }
