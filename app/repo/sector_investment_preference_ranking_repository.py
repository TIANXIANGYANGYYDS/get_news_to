from __future__ import annotations

from datetime import datetime
from math import exp, log, sqrt, tanh
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.results import UpdateResult


class SectorInvestmentPreferenceRankingRepository:
    """
    市场投资倾向排行榜 repository

    说明：
    1. 源数据来自 cls_telegraphs
    2. 目标表为 sector_investment_preference_rankings
    3. 每天只有一条数据（biz_date 唯一）
    4. 每次调度完成后，重算“当前时刻往前72小时”窗口内的版块投资倾向排行，并覆盖当天这条记录
    5. 计算口径：
       - 单条新闻强度：连续非线性公式
       - 时间规则：18小时内不衰减；18小时后开始衰减；高分衰减更慢
       - 最终总分范围：[-100, 100]
    """

    source_collection_name = "cls_telegraphs"
    target_collection_name = "sector_investment_preference_rankings"

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
        重建当天“市场投资倾向排行榜”
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
            "ranking_type": "sector_investment_preference",
            "window_type": "rolling_72h",
            "window_hours": 72,
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "formula_version": "v1_c_scheme",
            "formula_config": {
                "score_strength": "sign(score) * 100 * (abs(score)/100)^(2.6 - 1.6*(abs(score)/100))",
                "time_rule": "18h no decay, then exponential decay",
                "half_life_hours": "18 + 18 * (abs(score)/100)^1.5",
                "event_score": "100 * tanh(event_raw / 60)",
                "count_score": "100 * tanh(count_raw / 1.6)",
                "final_score": "clip(0.75*event_score + 0.08*count_score + 0.17*time_score, -100, 100)",
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
        - llm_analysis.sector_analyses

        规则：
        1. 统计 publish_ts 落在 [start_ts, end_ts] 内的数据
        2. 一条新闻命中多个版块，则分别参与对应版块计算
        3. 同一条新闻内部若 sector 重复，先去重
        4. sector_analyses 为空/null/非数组，则忽略
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
                "llm_analysis.sector_analyses": 1,
                "llm_analysis.score": 1,  # 兼容历史数据
                "llm_analysis.sectors": 1,  # 兼容历史数据
            },
        )

        docs = await cursor.to_list(length=None)

        rows: list[dict[str, Any]] = []
        for doc in docs:
            publish_ts = self._safe_int(doc.get("publish_ts"))
            if publish_ts is None:
                continue

            llm_analysis = doc.get("llm_analysis") or {}
            sector_scores = self._normalize_sector_scores(llm_analysis)
            if not sector_scores:
                continue

            rows.append(
                {
                    "event_id": doc.get("event_id"),
                    "publish_ts": publish_ts,
                    "sector_scores": sector_scores,
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
            for sector_item in row["sector_scores"]:
                score = float(sector_item["score"])
                age_hours = max((now_ts - publish_ts) / 3600.0, 0.0)
                score_strength = self._score_strength(score)
                time_decay = self._time_decay(score=score, age_hours=age_hours)
                news_effective_strength = score_strength * time_decay

                news_fact = {
                    "event_id": row.get("event_id"),
                    "publish_ts": publish_ts,
                    "score": score,
                    "age_hours": age_hours,
                    "score_strength": score_strength,
                    "time_decay": time_decay,
                    "news_effective_strength": news_effective_strength,
                }
                sector = sector_item["sector"]
                sector_news_map.setdefault(sector, []).append(news_fact)

        rankings = [
            self._build_single_sector_ranking(sector=sector, news_items=news_items)
            for sector, news_items in sector_news_map.items()
        ]

        rankings.sort(
            key=lambda x: (
                -x["final_score"],
                -x["event_score"],
                -x["count_score"],
                -x["time_score"],
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
        positive_news_count = sum(1 for item in news_items if item["score"] > 0)
        negative_news_count = sum(1 for item in news_items if item["score"] < 0)
        neutral_news_count = news_count - positive_news_count - negative_news_count

        effective_news_count = sum(item["time_decay"] for item in news_items)
        event_raw_sum = sum(item["news_effective_strength"] for item in news_items)
        event_raw = event_raw_sum / sqrt(max(effective_news_count, 1.0))
        event_score = 100.0 * tanh(event_raw / 60.0)

        positive_effective_count = sum(
            item["time_decay"] for item in news_items if item["score"] >= 20
        )
        negative_effective_count = sum(
            item["time_decay"] for item in news_items if item["score"] <= -20
        )
        count_raw = log(1.0 + positive_effective_count) - log(1.0 + negative_effective_count)
        count_score = 100.0 * tanh(count_raw / 1.6)

        positive_time_signal = max(
            (
                (abs(item["score_strength"]) / 100.0) * item["time_decay"]
                for item in news_items
                if item["score"] > 0
            ),
            default=0.0,
        )
        negative_time_signal = max(
            (
                (abs(item["score_strength"]) / 100.0) * item["time_decay"]
                for item in news_items
                if item["score"] < 0
            ),
            default=0.0,
        )
        time_raw = positive_time_signal - negative_time_signal
        time_score = 100.0 * time_raw

        final_score = self._clip(
            0.75 * event_score
            + 0.08 * count_score
            + 0.17 * time_score,
            -100.0,
            100.0,
        )

        latest_publish_ts = max((item["publish_ts"] for item in news_items), default=None)
        top_positive_score = max((item["score"] for item in news_items if item["score"] > 0), default=None)
        top_negative_score = min((item["score"] for item in news_items if item["score"] < 0), default=None)

        dominant_news = sorted(
            news_items,
            key=lambda x: abs(x["news_effective_strength"]),
            reverse=True,
        )[:5]

        return {
            "sector": sector,
            "rank": 0,
            "final_score": self._round(final_score),
            "event_score": self._round(event_score),
            "count_score": self._round(count_score),
            "time_score": self._round(time_score),
            "event_raw_sum": self._round(event_raw_sum, 4),
            "event_raw": self._round(event_raw, 4),
            "count_raw": self._round(count_raw, 4),
            "time_raw": self._round(time_raw, 4),
            "news_count": news_count,
            "positive_news_count": positive_news_count,
            "negative_news_count": negative_news_count,
            "neutral_news_count": neutral_news_count,
            "effective_news_count": self._round(effective_news_count, 4),
            "positive_effective_count": self._round(positive_effective_count, 4),
            "negative_effective_count": self._round(negative_effective_count, 4),
            "latest_publish_ts": latest_publish_ts,
            "top_positive_score": self._round(top_positive_score) if top_positive_score is not None else None,
            "top_negative_score": self._round(top_negative_score) if top_negative_score is not None else None,
            "dominant_event_ids": [item.get("event_id") for item in dominant_news if item.get("event_id")],
        }

    def _score_strength(self, score: float) -> float:
        if score == 0:
            return 0.0

        s = abs(score) / 100.0
        exponent = 2.6 - 1.6 * s
        value = 100.0 * (s ** exponent)
        return self._sign(score) * value

    def _time_decay(self, score: float, age_hours: float) -> float:
        effective_age_hours = max(age_hours - 18.0, 0.0)
        if effective_age_hours <= 0:
            return 1.0

        half_life_hours = 18.0 + 18.0 * ((abs(score) / 100.0) ** 1.5)
        return exp(-log(2.0) * effective_age_hours / half_life_hours)

    def _normalize_sector_scores(self, llm_analysis: dict[str, Any]) -> list[dict[str, float]]:
        sector_analyses = llm_analysis.get("sector_analyses")
        seen = set()
        result: list[dict[str, float]] = []

        if isinstance(sector_analyses, list):
            for item in sector_analyses:
                if not isinstance(item, dict):
                    continue
                sector = str(item.get("sector") or "").strip()
                if not sector or sector in seen:
                    continue
                seen.add(sector)
                score = self._clamp_score(self._safe_float(item.get("score", 0.0)))
                result.append({"sector": sector, "score": score})

        # 历史兼容：老结构 llm_analysis.score + llm_analysis.sectors
        if result:
            return result

        legacy_score = self._clamp_score(self._safe_float(llm_analysis.get("score", 0.0)))
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

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int | None = None) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_score(score: float) -> float:
        return max(-100.0, min(100.0, score))

    @staticmethod
    def _clip(value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(max_value, value))

    @staticmethod
    def _sign(value: float) -> float:
        if value > 0:
            return 1.0
        if value < 0:
            return -1.0
        return 0.0

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
            "ranking_type": doc.get("ranking_type") or "sector_investment_preference",
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

    async def get_investment_preference_ranking(
        self,
        biz_date: str,
        limit: int | None = None,
    ) -> dict | None:
        """
        获取指定日期的市场投资倾向排行榜（LLM精简字段）。
        """
        doc = await self.get_by_biz_date(biz_date)
        return self.build_llm_ranking_payload(doc, limit=limit)
