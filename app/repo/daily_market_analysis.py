from datetime import datetime
from pymongo.results import UpdateResult


class DailyMarketAnalysisRepository:
    collection_name = "daily_market_analysis"

    def __init__(self, db):
        self.collection = db[self.collection_name]

    async def create_indexes(self):
        await self.collection.create_index(
            "analysis_date",
            unique=True,
            name="uk_analysis_date",
        )
        await self.collection.create_index(
            "trade_date",
            name="idx_trade_date",
        )
        await self.collection.create_index(
            "updated_at",
            name="idx_updated_at",
        )

    async def upsert_one(self, data: dict) -> UpdateResult:
        """
        按 analysis_date 唯一更新/插入。
        同一天只保留一条记录：
        - 第一次分析：插入
        - 重启服务后再次分析：更新当天记录
        """
        analysis_date = (data.get("analysis_date") or "").strip()
        if not analysis_date:
            raise ValueError("analysis_date is required")

        now = datetime.utcnow()

        payload = dict(data)
        payload["updated_at"] = now

        return await self.collection.update_one(
            {"analysis_date": analysis_date},
            {
                "$set": payload,
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def get_by_analysis_date(self, analysis_date: str) -> dict | None:
        return await self.collection.find_one(
            {"analysis_date": analysis_date},
            projection={"_id": 0},
        )
    async def get_by_trade_date(self, trade_date: str) -> dict | None:
        return await self.collection.find_one(
            {"trade_date": trade_date},
            projection={"_id": 0},
            sort=[("updated_at", -1)],
        )
