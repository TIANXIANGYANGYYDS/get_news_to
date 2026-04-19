from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from app.model import DailyStockTechnicalAnalysisResult


@dataclass
class ClaimResult:
    claimed: bool
    reason: str


class DailyStockTechnicalAnalysisResultRepository:
    """每日个股技术分析结果 Repo（单表）。"""

    collection_name = "daily_stock_technical_analysis_results"

    def __init__(self, db):
        self.collection = db[self.collection_name]

    async def create_indexes(self) -> None:
        await self.collection.create_index(
            [("trade_date", ASCENDING), ("stock_code", ASCENDING)],
            unique=True,
            name="uk_trade_date_stock_code",
        )
        await self.collection.create_index([("trade_date", ASCENDING)], name="idx_trade_date")
        await self.collection.create_index(
            [("trade_date", ASCENDING), ("sector_name", ASCENDING)],
            name="idx_trade_date_sector_name",
        )
        await self.collection.create_index(
            [("trade_date", ASCENDING), ("conclusion", ASCENDING)],
            name="idx_trade_date_conclusion",
        )
        await self.collection.create_index([("analysis_status", ASCENDING)], name="idx_analysis_status")

    async def get_by_trade_date_stock_code(self, trade_date: str, stock_code: str) -> dict[str, Any] | None:
        return await self.collection.find_one(
            {"trade_date": trade_date, "stock_code": stock_code},
            projection={"_id": 0},
        )

    async def get_batch_by_trade_date_stock_codes(
        self,
        trade_date: str,
        stock_codes: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not stock_codes:
            return {}

        rows = await self.collection.find(
            {
                "trade_date": trade_date,
                "stock_code": {"$in": stock_codes},
            },
            projection={"_id": 0, "stock_code": 1, "analysis_status": 1, "updated_at": 1},
        ).to_list(length=None)

        return {row["stock_code"]: row for row in rows if row.get("stock_code")}

    async def try_claim_running(
        self,
        *,
        trade_date: str,
        stock: dict[str, Any],
        now: datetime,
        running_timeout_minutes: int,
    ) -> ClaimResult:
        """
        轻量级原子抢占：
        1) failed/skipped -> running
        2) running 且过期 -> running（过期接管）
        3) 不存在 -> upsert 插入 running
        4) succeeded / running未过期 -> 跳过
        """
        stock_code = stock["stock_code"]
        stale_before = now - timedelta(minutes=running_timeout_minutes)
        claim_update_fields = self._build_running_update_fields(stock=stock, now=now)
        claim_insert_payload = self._build_running_insert_payload(trade_date=trade_date, stock=stock, now=now)

        retry_result = await self.collection.update_one(
            {
                "trade_date": trade_date,
                "stock_code": stock_code,
                "analysis_status": {"$in": ["failed", "skipped_data_insufficient"]},
            },
            {"$set": claim_update_fields},
        )
        if retry_result.modified_count > 0:
            return ClaimResult(claimed=True, reason="claimed_retry")

        takeover_result = await self.collection.update_one(
            {
                "trade_date": trade_date,
                "stock_code": stock_code,
                "analysis_status": "running",
                "updated_at": {"$lte": stale_before},
            },
            {"$set": claim_update_fields},
        )
        if takeover_result.modified_count > 0:
            return ClaimResult(claimed=True, reason="claimed_takeover")

        try:
            insert_result = await self.collection.update_one(
                {"trade_date": trade_date, "stock_code": stock_code},
                {"$setOnInsert": claim_insert_payload},
                upsert=True,
            )
            if insert_result.upserted_id is not None:
                return ClaimResult(claimed=True, reason="claimed_insert")
        except DuplicateKeyError:
            return ClaimResult(claimed=False, reason="duplicate_conflict")

        current = await self.collection.find_one(
            {"trade_date": trade_date, "stock_code": stock_code},
            projection={"_id": 0, "analysis_status": 1, "updated_at": 1},
        )

        status = (current or {}).get("analysis_status")
        if status == "succeeded":
            return ClaimResult(claimed=False, reason="already_succeeded")
        if status == "running":
            updated_at = (current or {}).get("updated_at")
            if isinstance(updated_at, datetime) and updated_at > stale_before:
                return ClaimResult(claimed=False, reason="running_by_other")

        return ClaimResult(claimed=False, reason="not_claimed")

    async def mark_succeeded(
        self,
        *,
        trade_date: str,
        stock_code: str,
        now: datetime,
        context_fields: dict[str, Any],
        llm_fields: dict[str, Any],
    ) -> None:
        await self.collection.update_one(
            {"trade_date": trade_date, "stock_code": stock_code},
            {
                "$set": {
                    **context_fields,
                    **llm_fields,
                    "analysis_status": "succeeded",
                    "error_message": None,
                    "updated_at": now,
                }
            },
            upsert=False,
        )

    async def mark_failed(
        self,
        *,
        trade_date: str,
        stock_code: str,
        now: datetime,
        error_message: str,
        context_fields: dict[str, Any] | None = None,
    ) -> None:
        await self.collection.update_one(
            {"trade_date": trade_date, "stock_code": stock_code},
            {
                "$set": {
                    **(context_fields or {}),
                    "analysis_status": "failed",
                    "error_message": error_message,
                    "updated_at": now,
                }
            },
            upsert=False,
        )

    async def mark_skipped_data_insufficient(
        self,
        *,
        trade_date: str,
        stock_code: str,
        now: datetime,
        error_message: str,
        context_fields: dict[str, Any],
    ) -> None:
        await self.collection.update_one(
            {"trade_date": trade_date, "stock_code": stock_code},
            {
                "$set": {
                    **context_fields,
                    "analysis_status": "skipped_data_insufficient",
                    "error_message": error_message,
                    "updated_at": now,
                }
            },
            upsert=False,
        )

    @staticmethod
    def _build_running_insert_payload(*, trade_date: str, stock: dict[str, Any], now: datetime) -> dict[str, Any]:
        return DailyStockTechnicalAnalysisResult(
            trade_date=trade_date,
            analysis_time=now.replace(microsecond=0),
            sector_name=stock.get("sector_name") or "",
            sector_rank=stock.get("sector_rank"),
            stock_code=stock.get("stock_code") or "",
            stock_name=stock.get("stock_name"),
            stock_rank_in_sector=stock.get("stock_rank_in_sector"),
            analysis_status="running",
            created_at=now,
            updated_at=now,
        ).to_mongo_dict()

    @staticmethod
    def _build_running_update_fields(*, stock: dict[str, Any], now: datetime) -> dict[str, Any]:
        return {
            "analysis_time": now.replace(microsecond=0),
            "sector_name": stock.get("sector_name") or "",
            "sector_rank": stock.get("sector_rank"),
            "stock_name": stock.get("stock_name"),
            "stock_rank_in_sector": stock.get("stock_rank_in_sector"),
            "analysis_status": "running",
            "updated_at": now,
        }


    async def list_by_trade_date(self, trade_date: str) -> list[dict[str, Any]]:
        rows = await self.collection.find(
            {"trade_date": trade_date},
            projection={"_id": 0},
            sort=[("sector_rank", 1), ("stock_rank_in_sector", 1), ("stock_code", 1)],
        ).to_list(length=None)
        return rows

    async def list_by_trade_date_sector(self, trade_date: str, sector_name: str) -> list[dict[str, Any]]:
        rows = await self.collection.find(
            {"trade_date": trade_date, "sector_name": sector_name},
            projection={"_id": 0},
            sort=[("stock_rank_in_sector", 1), ("stock_code", 1)],
        ).to_list(length=None)
        return rows

    async def count_grouped_by_status(self, trade_date: str) -> dict[str, int]:
        pipeline = [
            {"$match": {"trade_date": trade_date}},
            {"$group": {"_id": "$analysis_status", "count": {"$sum": 1}}},
        ]
        rows = await self.collection.aggregate(pipeline).to_list(length=None)
        result: dict[str, int] = {}
        for row in rows:
            status = str(row.get("_id") or "").strip()
            if status:
                result[status] = int(row.get("count") or 0)
        return result

    async def count_grouped_by_status_and_sector(self, trade_date: str, sector_name: str) -> dict[str, int]:
        pipeline = [
            {"$match": {"trade_date": trade_date, "sector_name": sector_name}},
            {"$group": {"_id": "$analysis_status", "count": {"$sum": 1}}},
        ]
        rows = await self.collection.aggregate(pipeline).to_list(length=None)
        result: dict[str, int] = {}
        for row in rows:
            status = str(row.get("_id") or "").strip()
            if status:
                result[status] = int(row.get("count") or 0)
        return result
