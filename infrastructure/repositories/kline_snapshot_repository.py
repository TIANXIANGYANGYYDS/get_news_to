from __future__ import annotations

from datetime import datetime

from domain.models.database_models import KlineSnapshotDocument
from shared.base.repository import BaseMongoRepository


class KlineSnapshotRepository(BaseMongoRepository):
    collection_name = "kline_snapshots"

    async def ensure_indexes(self):
        await self.collection.create_index([("trade_date", 1), ("symbol", 1)], unique=True, name="uk_trade_symbol")
        await self.collection.create_index("trade_date", name="idx_trade_date")

    async def upsert_snapshot(self, document: KlineSnapshotDocument):
        payload = document.to_dict()
        payload["updated_at"] = datetime.utcnow()
        return await self.upsert_one({"trade_date": document.trade_date, "symbol": document.symbol}, payload)
