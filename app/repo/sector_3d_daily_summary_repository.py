from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.results import UpdateResult


class Sector3DDailySummaryRepository:
    """
    每日实时三日内版块信息表 repository

    说明：
    1. 源数据来自 cls_telegraphs
    2. 目标表为 sector_3d_daily_summaries
    3. 每天只有一条数据（biz_date 唯一）
    4. 每次调度完成后，重算“当前时刻往前72小时”窗口内的版块聚合，并覆盖当天这条记录
    """

    source_collection_name = "cls_telegraphs"
    target_collection_name = "sector_3d_daily_summaries"

    def __init__(self, db, timezone: str = "Asia/Shanghai"):
        self.db = db
        self.source_collection = db[self.source_collection_name]
        self.target_collection = db[self.target_collection_name]
        self.timezone = timezone

    async def create_indexes(self):
        await self.target_collection.create_index("biz_date", unique=True, name="uk_biz_date")
        await self.target_collection.create_index("updated_at_ts", name="idx_updated_at_ts")

    async def get_by_biz_date(self, biz_date: str) -> dict | None:
        return await self.target_collection.find_one({"biz_date": biz_date})

    async def upsert_one(self, data: dict) -> UpdateResult:
        now_ts = int(datetime.utcnow().timestamp())
        return await self.target_collection.update_one(
            {"biz_date": data["biz_date"]},
            {
                "$set": {
                    **data,
                    "updated_at_ts": now_ts,
                },
                "$setOnInsert": {
                    "created_at_ts": now_ts,
                },
            },
            upsert=True,
        )

    async def rebuild_realtime_3d_summary(self, now_ts: int | None = None) -> dict[str, Any]:
        """
        重建当天“实时三日内版块信息表”
        统计窗口：当前时刻往前 72 小时（滚动窗口）
        """

        current_now_ts = now_ts or self._now_ts()
        biz_date = self._biz_date(current_now_ts)
        window_start_ts = current_now_ts - 72 * 3600
        window_end_ts = current_now_ts

        sector_stats = await self._aggregate_sector_stats(
            start_ts=window_start_ts,
            end_ts=window_end_ts,
        )

        total_news_count = sum(item["news_count"] for item in sector_stats)
        total_score_sum = sum(item["score_sum"] for item in sector_stats)

        doc = {
            "biz_date": biz_date,
            "window_type": "rolling_72h",
            "window_hours": 72,
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "sector_count": len(sector_stats),
            "total_news_count": total_news_count,
            "total_score_sum": total_score_sum,
            "sector_stats": sector_stats,
        }

        await self.upsert_one(doc)
        return doc

    async def _aggregate_sector_stats(self, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
        """
        从 cls_telegraphs 聚合版块统计

        规则：
        1. 统计 publish_ts 落在 [start_ts, end_ts] 内的数据
        2. 版块来源字段：llm_analysis.sectors
        3. 分数字段：llm_analysis.score
        4. 一条新闻命中多个版块，则每个版块各记 1 次
        5. 同一条新闻内部若 sectors 重复，先去重
        6. sectors 为空/null/非数组，则忽略
        """

        pipeline = [
            {
                "$match": {
                    "publish_ts": {
                        "$gte": start_ts,
                        "$lte": end_ts,
                    }
                }
            },
            {
                "$project": {
                    "score": {"$ifNull": ["$llm_analysis.score", 0]},
                    "sectors": {
                        "$cond": [
                            {"$isArray": "$llm_analysis.sectors"},
                            {"$setUnion": ["$llm_analysis.sectors", []]},
                            [],
                        ]
                    },
                }
            },
            {"$unwind": "$sectors"},
            {
                "$project": {
                    "score": 1,
                    "sector": {
                        "$trim": {
                            "input": {"$ifNull": ["$sectors", ""]}
                        }
                    },
                }
            },
            {
                "$match": {
                    "sector": {"$ne": ""}
                }
            },
            {
                "$group": {
                    "_id": "$sector",
                    "news_count": {"$sum": 1},
                    "score_sum": {"$sum": "$score"},
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "sector": "$_id",
                    "news_count": 1,
                    "score_sum": 1,
                }
            },
            {
                "$sort": {
                    "news_count": -1,
                    "score_sum": -1,
                    "sector": 1,
                }
            },
        ]

        return await self.source_collection.aggregate(pipeline).to_list(length=None)

    def _now_ts(self) -> int:
        return int(datetime.now(ZoneInfo(self.timezone)).timestamp())

    def _biz_date(self, ts: int) -> str:
        return datetime.fromtimestamp(ts, ZoneInfo(self.timezone)).date().isoformat()