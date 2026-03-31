from typing import List
from pymongo.results import UpdateResult


class CLSTelegraphRepository:
    collection_name = "cls_telegraphs"

    def __init__(self, db):
        self.collection = db[self.collection_name]

    async def create_indexes(self):
        await self.collection.create_index("event_id", unique=True, name="uk_event_id")
        await self.collection.create_index("publish_ts", name="idx_publish_ts")
        await self.collection.create_index("subjects", name="idx_subjects")

    async def upsert_one(self, data: dict) -> UpdateResult:
        return await self.collection.update_one(
            {"event_id": data["event_id"]},
            {"$set": data},
            upsert=True,
        )

    async def upsert_many(self, rows: list[dict]):
        for row in rows:
            await self.upsert_one(row)

    async def get_latest_publish_ts(self) -> int | None:
        doc = await self.collection.find_one(
            {},
            sort=[("publish_ts", -1)],
            projection={"publish_ts": 1, "_id": 0},
        )
        return doc["publish_ts"] if doc else None

    async def get_existing_event_ids(self, event_ids: List[str]) -> set[str]:
        if not event_ids:
            return set()

        cursor = self.collection.find(
            {"event_id": {"$in": event_ids}},
            projection={"event_id": 1, "_id": 0},
        )

        existing = set()
        async for doc in cursor:
            event_id = doc.get("event_id")
            if event_id:
                existing.add(event_id)

        return existing