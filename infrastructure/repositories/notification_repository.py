from __future__ import annotations

from datetime import datetime

from shared.base.repository import BaseMongoRepository


class NotificationRepository(BaseMongoRepository):
    collection_name = "notification_records"

    async def ensure_indexes(self):
        await self.collection.create_index("notification_key", unique=True, name="uk_notification_key")
        await self.collection.create_index("created_at", name="idx_created_at")

    async def reserve_notification(self, notification_key: str, payload: dict) -> bool:
        now = datetime.utcnow()
        result = await self.collection.update_one(
            {"notification_key": notification_key},
            {"$setOnInsert": {"notification_key": notification_key, "payload": payload, "created_at": now}},
            upsert=True,
        )
        return result.upserted_id is not None
