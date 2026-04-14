from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from pymongo import ASCENDING, UpdateOne

from app.model import DailyKLineSnapshot


CN_TZ = ZoneInfo("Asia/Shanghai")


class DailyKLineSnapshotRepository:
    """
    A 股日度快照 Repo
    collection: daily_kline_snapshots
    唯一键：trade_date + symbol
    """

    def __init__(self, db):
        self.collection = db["daily_kline_snapshots"]

    async def create_indexes(self) -> None:
        await self.collection.create_index(
            [("trade_date", ASCENDING), ("symbol", ASCENDING)],
            unique=True,
            name="uniq_trade_date_symbol",
        )
        await self.collection.create_index(
            [("trade_date", ASCENDING)],
            name="idx_trade_date",
        )
        await self.collection.create_index(
            [("symbol", ASCENDING)],
            name="idx_symbol",
        )

    @staticmethod
    def _build_model(row: Dict[str, Any], trade_date: str) -> DailyKLineSnapshot:
        now = datetime.now(CN_TZ)
        return DailyKLineSnapshot.from_raw_row(
            raw_row=row,
            trade_date=trade_date,
            now=now,
        )

    async def upsert_one(self, row: Dict[str, Any], trade_date: str):
        snapshot = self._build_model(row=row, trade_date=trade_date)
        doc = snapshot.to_mongo_dict()

        result = await self.collection.update_one(
            {
                "trade_date": doc["trade_date"],
                "symbol": doc["symbol"],
            },
            {
                "$set": {
                    "name": doc["name"],
                    "open_price": doc["open_price"],
                    "close_price": doc["close_price"],
                    "high_price": doc["high_price"],
                    "low_price": doc["low_price"],
                    "prev_close_price": doc["prev_close_price"],
                    "change_percent": doc["change_percent"],
                    "change_amount": doc["change_amount"],
                    "speed_percent": doc["speed_percent"],
                    "turnover_percent": doc["turnover_percent"],
                    "volume_ratio": doc["volume_ratio"],
                    "amplitude_percent": doc["amplitude_percent"],
                    "turnover_amount_yuan": doc["turnover_amount_yuan"],
                    "float_shares": doc["float_shares"],
                    "float_market_cap_yuan": doc["float_market_cap_yuan"],
                    "total_market_cap_yuan": doc["total_market_cap_yuan"],
                    "pe_ratio": doc["pe_ratio"],
                    "updated_at": doc["updated_at"],
                },
                "$setOnInsert": {
                    "id": doc["id"],
                    "trade_date": doc["trade_date"],
                    "symbol": doc["symbol"],
                    "created_at": doc["created_at"],
                },
            },
            upsert=True,
        )
        return result

    async def bulk_upsert(self, rows: List[Dict[str, Any]], trade_date: str):
        if not rows:
            return None

        operations = []

        for row in rows:
            try:
                snapshot = self._build_model(row=row, trade_date=trade_date)
                doc = snapshot.to_mongo_dict()
            except Exception as e:
                print(f"[入库] 跳过非法数据: {repr(e)} | row={row}")
                continue

            operations.append(
                UpdateOne(
                    {
                        "trade_date": doc["trade_date"],
                        "symbol": doc["symbol"],
                    },
                    {
                        "$set": {
                            "name": doc["name"],
                            "open_price": doc["open_price"],
                            "close_price": doc["close_price"],
                            "high_price": doc["high_price"],
                            "low_price": doc["low_price"],
                            "prev_close_price": doc["prev_close_price"],
                            "change_percent": doc["change_percent"],
                            "change_amount": doc["change_amount"],
                            "speed_percent": doc["speed_percent"],
                            "turnover_percent": doc["turnover_percent"],
                            "volume_ratio": doc["volume_ratio"],
                            "amplitude_percent": doc["amplitude_percent"],
                            "turnover_amount_yuan": doc["turnover_amount_yuan"],
                            "float_shares": doc["float_shares"],
                            "float_market_cap_yuan": doc["float_market_cap_yuan"],
                            "total_market_cap_yuan": doc["total_market_cap_yuan"],
                            "pe_ratio": doc["pe_ratio"],
                            "updated_at": doc["updated_at"],
                        },
                        "$setOnInsert": {
                            "id": doc["id"],
                            "trade_date": doc["trade_date"],
                            "symbol": doc["symbol"],
                            "created_at": doc["created_at"],
                        },
                    },
                    upsert=True,
                )
            )

        if not operations:
            return None

        return await self.collection.bulk_write(operations, ordered=False)
    
    async def has_trade_date_data(self, trade_date: str) -> bool:
        """
        判断某个交易日是否已经存在至少一条日快照数据
        """
        doc = await self.collection.find_one(
            {"trade_date": trade_date},
            projection={"_id": 1},
        )
        return doc is not None