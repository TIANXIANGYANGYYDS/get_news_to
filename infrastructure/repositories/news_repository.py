from __future__ import annotations

from datetime import datetime

from domain.models.database_models import NewsDocument
from shared.base.repository import BaseMongoRepository


class NewsRepository(BaseMongoRepository):
    collection_name = "news_events"

    async def ensure_indexes(self):
        await self.collection.create_index("event_id", unique=True, name="uk_event_id")
        await self.collection.create_index([("source_type", 1), ("publish_ts", -1)], name="idx_source_publish_ts")
        await self.collection.create_index("published_at", name="idx_published_at")
        await self.collection.create_index("idempotency_key", unique=True, sparse=True, name="uk_idempotency_key")

    async def upsert_news_document(self, news_document: NewsDocument):
        payload = news_document.to_dict()
        payload["updated_at"] = datetime.utcnow()
        payload["idempotency_key"] = f"news::{news_document.event_id}"
        return await self.upsert_one({"event_id": news_document.event_id}, payload)

    async def list_latest(self, *, source_type: str | None = None, limit: int = 100) -> list[NewsDocument]:
        query = {"source_type": source_type} if source_type else {}
        cursor = self.collection.find(query).sort("publish_ts", -1).limit(limit)
        return [NewsDocument.from_dict(doc) async for doc in cursor]

    async def get_existing_event_ids(self, event_ids: list[str]) -> set[str]:
        if not event_ids:
            return set()
        cursor = self.collection.find({"event_id": {"$in": event_ids}}, projection={"event_id": 1, "_id": 0})
        return {doc["event_id"] async for doc in cursor if doc.get("event_id")}

    async def has_event(self, event_id: str) -> bool:
        return await self.find_one({"event_id": event_id}, projection={"_id": 1}) is not None
