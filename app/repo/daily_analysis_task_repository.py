from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pymongo import ReturnDocument


class DailyAnalysisTaskRepository:
    """
    每日盘前分析任务仓储。

    说明：
    - 所有任务状态都持久化到 Mongo，支持重启恢复。
    - 同一个 biz_date + task_type 只允许一条有效任务，保证幂等。
    """

    collection_name = "daily_analysis_tasks"

    def __init__(self, db):
        self.collection = db[self.collection_name]

    async def create_indexes(self):
        await self.collection.create_index(
            [("task_type", 1), ("biz_date", 1)],
            unique=True,
            name="uk_task_type_biz_date",
        )
        await self.collection.create_index(
            "idempotency_key",
            unique=True,
            name="uk_idempotency_key",
        )
        await self.collection.create_index(
            [("status", 1), ("next_retry_at", 1)],
            name="idx_status_next_retry_at",
        )
        await self.collection.create_index(
            [("status", 1), ("lock_until", 1)],
            name="idx_status_lock_until",
        )

    async def ensure_task(
        self,
        *,
        biz_date: str,
        task_type: str = "daily_market_analysis",
        max_retry_count: int = 8,
    ) -> tuple[dict[str, Any], bool]:
        """
        确保任务存在（幂等）。
        返回：(task_doc, created_new)
        """
        now = datetime.utcnow()
        idempotency_key = f"{task_type}:{biz_date}"
        result = await self.collection.find_one_and_update(
            {"task_type": task_type, "biz_date": biz_date},
            {
                "$setOnInsert": {
                    "task_type": task_type,
                    "biz_date": biz_date,
                    "status": "pending",
                    "retry_count": 0,
                    "max_retry_count": max_retry_count,
                    "next_retry_at": now,
                    "lock_owner": None,
                    "lock_until": None,
                    "idempotency_key": idempotency_key,
                    "analysis_text": None,
                    "card_sent": False,
                    "card_sent_at": None,
                    "last_error": None,
                    "last_error_type": None,
                    "create_time": now,
                    "update_time": now,
                },
                "$set": {
                    "update_time": now,
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        created_new = result.get("create_time") == result.get("update_time")
        return result, created_new

    async def claim_next_runnable_task(
        self,
        *,
        lock_owner: str,
        lock_seconds: int = 180,
        task_type: str = "daily_market_analysis",
    ) -> dict[str, Any] | None:
        """
        领取可执行任务：
        - pending/retrying 且到达 next_retry_at
        - running 但 lock_until 已过期（支持恢复）
        """
        now = datetime.utcnow()
        lock_until = now + timedelta(seconds=lock_seconds)
        query = {
            "task_type": task_type,
            "$or": [
                {"status": {"$in": ["pending", "retrying"]}, "next_retry_at": {"$lte": now}},
                {"status": "running", "lock_until": {"$lte": now}},
            ],
        }
        update = {
            "$set": {
                "status": "running",
                "lock_owner": lock_owner,
                "lock_until": lock_until,
                "update_time": now,
            }
        }
        return await self.collection.find_one_and_update(
            query,
            update,
            sort=[("next_retry_at", 1), ("create_time", 1)],
            return_document=ReturnDocument.AFTER,
        )

    async def mark_retry(
        self,
        *,
        task_id: Any,
        retry_count: int,
        next_retry_at: datetime,
        error_type: str,
        error_message: str,
    ):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "status": "retrying",
                    "retry_count": retry_count,
                    "next_retry_at": next_retry_at,
                    "last_error_type": error_type,
                    "last_error": error_message,
                    "lock_owner": None,
                    "lock_until": None,
                    "update_time": now,
                }
            },
        )

    async def mark_failed(
        self,
        *,
        task_id: Any,
        retry_count: int,
        error_type: str,
        error_message: str,
    ):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "status": "failed",
                    "retry_count": retry_count,
                    "last_error_type": error_type,
                    "last_error": error_message,
                    "lock_owner": None,
                    "lock_until": None,
                    "update_time": now,
                }
            },
        )

    async def save_analysis_text(self, *, task_id: Any, analysis_text: str):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "analysis_text": analysis_text,
                    "last_error": None,
                    "last_error_type": None,
                    "update_time": now,
                }
            },
        )

    async def mark_card_sent(self, *, task_id: Any):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "card_sent": True,
                    "card_sent_at": now,
                    "status": "succeeded",
                    "lock_owner": None,
                    "lock_until": None,
                    "last_error": None,
                    "last_error_type": None,
                    "update_time": now,
                }
            },
        )
