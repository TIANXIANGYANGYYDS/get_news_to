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
        2. 版块来源字段：llm_analysis.sector_analyses[].sector
        3. 分数字段：llm_analysis.sector_analyses[].score
        4. 一条新闻命中多个版块，则每个版块各记 1 次
        5. 同一条新闻内部若 sector 重复，先去重
        6. sector_analyses 为空/null/非数组，则忽略
        """
        cursor = self.source_collection.find(
            {
                "publish_ts": {
                    "$gte": start_ts,
                    "$lte": end_ts,
                }
            },
            projection={
                "_id": 0,
                "llm_analysis.sector_analyses": 1,
                "llm_analysis.score": 1,   # 历史兼容
                "llm_analysis.sectors": 1,  # 历史兼容
            },
        )

        docs = await cursor.to_list(length=None)
        stats_map: dict[str, dict[str, Any]] = {}

        for doc in docs:
            llm_analysis = doc.get("llm_analysis") or {}
            normalized_items = self._normalize_sector_items(llm_analysis)
            for item in normalized_items:
                sector = item["sector"]
                score = item["score"]
                if sector not in stats_map:
                    stats_map[sector] = {"sector": sector, "news_count": 0, "score_sum": 0.0}
                stats_map[sector]["news_count"] += 1
                stats_map[sector]["score_sum"] += score

        result = list(stats_map.values())
        result.sort(key=lambda x: (-x["news_count"], -x["score_sum"], x["sector"]))
        return result

    @staticmethod
    def _normalize_sector_items(llm_analysis: dict[str, Any]) -> list[dict[str, Any]]:
        seen = set()
        result: list[dict[str, Any]] = []

        sector_analyses = llm_analysis.get("sector_analyses")
        if isinstance(sector_analyses, list):
            for item in sector_analyses:
                if not isinstance(item, dict):
                    continue
                sector = str(item.get("sector") or "").strip()
                if not sector or sector in seen:
                    continue
                seen.add(sector)
                score = item.get("score", 0)
                try:
                    score = float(score)
                except (TypeError, ValueError):
                    score = 0.0
                result.append({"sector": sector, "score": score})

        # 历史兼容
        if result:
            return result

        legacy_score = llm_analysis.get("score", 0)
        try:
            legacy_score = float(legacy_score)
        except (TypeError, ValueError):
            legacy_score = 0.0

        legacy_sectors = llm_analysis.get("sectors")
        if not isinstance(legacy_sectors, list):
            return []

        for item in legacy_sectors:
            sector = str(item).strip() if item is not None else ""
            if not sector or sector in seen:
                continue
            seen.add(sector)
            result.append({"sector": sector, "score": legacy_score})

        return result

    def _now_ts(self) -> int:
        return int(datetime.now(ZoneInfo(self.timezone)).timestamp())

    def _biz_date(self, ts: int) -> str:
        return datetime.fromtimestamp(ts, ZoneInfo(self.timezone)).date().isoformat()
