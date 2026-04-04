from __future__ import annotations

from datetime import datetime
from math import exp, log, tanh
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.results import UpdateResult


class SectorMarketHeatRankingRepository:
    """
    市场热度排行榜 repository

    说明：
    1. 源数据来自 cls_telegraphs
    2. 目标表为 sector_market_heat_rankings
    3. 每天只有一条数据（biz_date 唯一）
    4. 每次调度完成后，重算“当前时刻往前72小时”窗口内的版块热度排行，并覆盖当天这条记录
    5. 计算口径：
       - 不使用单条新闻 score
       - 只使用新闻数量 + 时间衰减
       - 18小时内不衰减；18小时后开始衰减
       - 更偏实时热点
       - 最终总分范围：[0, 100]
    """

    source_collection_name = "cls_telegraphs"
    target_collection_name = "sector_market_heat_rankings"

    def __init__(self, db, timezone: str = "Asia/Shanghai"):
        self.db = db
        self.source_collection = db[self.source_collection_name]
        self.target_collection = db[self.target_collection_name]
        self.timezone = timezone

    async def create_indexes(self):
        await self.target_collection.create_index("biz_date", unique=True, name="uk_biz_date")
        await self.target_collection.create_index("updated_at_ts", name="idx_updated_at_ts")
        await self.target_collection.create_index("window_end_ts", name="idx_window_end_ts")

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

    async def rebuild_realtime_ranking(
        self,
        now_ts: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """
        重建当天“市场热度排行榜”
        统计窗口：当前时刻往前72小时（滚动窗口）
        """
        current_now_ts = now_ts or self._now_ts()
        biz_date = self._biz_date(current_now_ts)
        window_start_ts = current_now_ts - 72 * 3600
        window_end_ts = current_now_ts

        rows = await self._load_window_rows(
            start_ts=window_start_ts,
            end_ts=window_end_ts,
        )
        sector_rankings = self._build_sector_rankings(
            rows=rows,
            now_ts=current_now_ts,
        )

        if limit is not None and limit > 0:
            sector_rankings = sector_rankings[:limit]
            for idx, item in enumerate(sector_rankings, start=1):
                item["rank"] = idx

        doc = {
            "biz_date": biz_date,
            "ranking_type": "sector_market_heat",
            "window_type": "rolling_72h",
            "window_hours": 72,
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "formula_version": "v1_realtime_count_time_only",
            "formula_config": {
                "time_rule": "18h no decay, then exponential decay",
                "half_life_hours": 18,
                "count_score": "100 * tanh(effective_news_count / 6)",
                "time_score": "100 * (effective_news_count / news_count)",
                "final_score": "clip(0.75*count_score + 0.25*time_score, 0, 100)",
            },
            "sector_count": len(sector_rankings),
            "total_news_count": len(rows),
            "sector_rankings": sector_rankings,
        }

        await self.upsert_one(doc)
        return doc

    async def _load_window_rows(self, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
        """
        从 cls_telegraphs 取窗口内新闻明细，保留：
        - event_id
        - publish_ts
        - llm_analysis.sectors

        规则：
        1. 统计 publish_ts 落在 [start_ts, end_ts] 内的数据
        2. 一条新闻命中多个版块，则分别参与对应版块计算
        3. 同一条新闻内部若 sectors 重复，先去重
        4. sectors 为空/null/非数组，则忽略
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
                "event_id": 1,
                "publish_ts": 1,
                "llm_analysis.sectors": 1,
            },
        )

        docs = await cursor.to_list(length=None)

        rows: list[dict[str, Any]] = []
        for doc in docs:
            publish_ts = self._safe_int(doc.get("publish_ts"))
            if publish_ts is None:
                continue

            llm_analysis = doc.get("llm_analysis") or {}
            sectors = self._normalize_sectors(llm_analysis.get("sectors"))

            if not sectors:
                continue

            rows.append(
                {
                    "event_id": doc.get("event_id"),
                    "publish_ts": publish_ts,
                    "sectors": sectors,
                }
            )

        return rows

    def _build_sector_rankings(
        self,
        rows: list[dict[str, Any]],
        now_ts: int,
    ) -> list[dict[str, Any]]:
        sector_news_map: dict[str, list[dict[str, Any]]] = {}

        for row in rows:
            publish_ts = int(row["publish_ts"])
            age_hours = max((now_ts - publish_ts) / 3600.0, 0.0)
            time_decay = self._time_decay(age_hours=age_hours)

            news_fact = {
                "event_id": row.get("event_id"),
                "publish_ts": publish_ts,
                "age_hours": age_hours,
                "time_decay": time_decay,
            }

            for sector in row["sectors"]:
                sector_news_map.setdefault(sector, []).append(news_fact)

        rankings = [
            self._build_single_sector_ranking(sector=sector, news_items=news_items)
            for sector, news_items in sector_news_map.items()
        ]

        rankings.sort(
            key=lambda x: (
                -x["final_score"],
                -x["count_score"],
                -x["time_score"],
                -x["effective_news_count"],
                -x["news_count"],
                x["sector"],
            )
        )

        for idx, item in enumerate(rankings, start=1):
            item["rank"] = idx

        return rankings

    def _build_single_sector_ranking(
        self,
        sector: str,
        news_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        news_count = len(news_items)
        recent_news_count = sum(1 for item in news_items if item["age_hours"] <= 18.0)

        effective_news_count = sum(item["time_decay"] for item in news_items)

        count_raw = effective_news_count
        count_score = 100.0 * tanh(count_raw / 6.0)

        time_raw = effective_news_count / max(news_count, 1)
        time_score = 100.0 * time_raw

        final_score = self._clip(
            0.75 * count_score + 0.25 * time_score,
            0.0,
            100.0,
        )

        latest_publish_ts = max((item["publish_ts"] for item in news_items), default=None)

        dominant_news = sorted(
            news_items,
            key=lambda x: (x["age_hours"], -x["publish_ts"]),
        )[:5]

        return {
            "sector": sector,
            "rank": 0,
            "final_score": self._round(final_score),
            "count_score": self._round(count_score),
            "time_score": self._round(time_score),
            "count_raw": self._round(count_raw, 4),
            "time_raw": self._round(time_raw, 4),
            "news_count": news_count,
            "recent_news_count": recent_news_count,
            "effective_news_count": self._round(effective_news_count, 4),
            "latest_publish_ts": latest_publish_ts,
            "dominant_event_ids": [item.get("event_id") for item in dominant_news if item.get("event_id")],
        }

    def _time_decay(self, age_hours: float) -> float:
        effective_age_hours = max(age_hours - 18.0, 0.0)
        if effective_age_hours <= 0:
            return 1.0

        half_life_hours = 18.0
        return exp(-log(2.0) * effective_age_hours / half_life_hours)

    @staticmethod
    def _normalize_sectors(sectors: Any) -> list[str]:
        if not isinstance(sectors, list):
            return []

        seen = set()
        result: list[str] = []
        for item in sectors:
            text = str(item).strip() if item is not None else ""
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _safe_int(value: Any, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clip(value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    @staticmethod
    def _round(value: float | None, digits: int = 2) -> float | None:
        if value is None:
            return None
        return round(float(value), digits)

    def _now_ts(self) -> int:
        return int(datetime.now(ZoneInfo(self.timezone)).timestamp())

    def _biz_date(self, ts: int) -> str:
        return datetime.fromtimestamp(ts, ZoneInfo(self.timezone)).date().isoformat()

    def build_llm_ranking_payload(
        self,
        doc: dict | None,
        limit: int | None = None,
    ) -> dict | None:
        """
        构造提供给 LLM 的精简排行结果。

        仅保留：
        - sector: 板块
        - rank: 排名
        - final_score: 得分
        - news_count: 新闻数量
        """
        if not doc:
            return None

        return {
            "biz_date": doc.get("biz_date"),
            "ranking_type": doc.get("ranking_type") or "sector_market_heat",
            "sector_rankings": self._simplify_sector_rankings(
                doc.get("sector_rankings"),
                limit=limit,
            ),
        }

    def _simplify_sector_rankings(
        self,
        sector_rankings: Any,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(sector_rankings, list):
            return []

        simplified: list[dict[str, Any]] = []
        for idx, item in enumerate(sector_rankings, start=1):
            if not isinstance(item, dict):
                continue

            sector = str(item.get("sector") or "").strip()
            if not sector:
                continue

            rank = self._safe_positive_int(item.get("rank"), default=idx)
            news_count = self._safe_non_negative_int(item.get("news_count"), default=0)

            simplified.append(
                {
                    "sector": sector,
                    "rank": rank,
                    "final_score": self._round(self._safe_float(item.get("final_score"), 0.0)),
                    "news_count": news_count,
                }
            )

        simplified.sort(key=lambda x: (x["rank"], -x["final_score"], x["sector"]))

        if limit is not None and limit > 0:
            return simplified[:limit]
        return simplified

    @staticmethod
    def _safe_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _safe_non_negative_int(value: Any, default: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(parsed, 0)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    async def get_market_heat_ranking(
        self,
        biz_date: str,
        limit: int | None = None,
    ) -> dict | None:
        """
        获取指定日期的市场热度排行榜（LLM精简字段）。
        """
        doc = await self.get_by_biz_date(biz_date)
        return self.build_llm_ranking_payload(doc, limit=limit)
