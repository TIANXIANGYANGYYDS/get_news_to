from __future__ import annotations

from abc import ABC
from datetime import datetime
from typing import Any, Iterable

try:
    from pymongo import UpdateOne
except Exception:
    class UpdateOne:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs



class BaseRepository(ABC):
    pass


class BaseMongoRepository(BaseRepository):
    collection_name: str = ""

    def __init__(self, db):
        self.db = db
        self.collection = db[self.collection_name]

    async def find_one(self, query: dict[str, Any], projection: dict[str, int] | None = None):
        return await self.collection.find_one(query, projection=projection)

    async def insert_one(self, document: dict[str, Any]):
        return await self.collection.insert_one(document)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], *, upsert: bool = False):
        return await self.collection.update_one(query, update, upsert=upsert)

    async def upsert_one(self, identity_query: dict[str, Any], document: dict[str, Any]):
        return await self.collection.update_one(identity_query, {"$set": document}, upsert=True)

    async def bulk_upsert(self, documents: Iterable[dict[str, Any]], *, key_field: str):
        ops = [
            UpdateOne({key_field: doc[key_field]}, {"$set": doc}, upsert=True)
            for doc in documents
            if key_field in doc
        ]
        if not ops:
            return None
        return await self.collection.bulk_write(ops, ordered=False)

    async def find_by_time_range(
        self,
        field_name: str,
        start_at: datetime,
        end_at: datetime,
        *,
        limit: int = 100,
        sort_desc: bool = True,
    ):
        direction = -1 if sort_desc else 1
        cursor = self.collection.find({field_name: {"$gte": start_at, "$lt": end_at}}).sort(field_name, direction).limit(limit)
        return [doc async for doc in cursor]
