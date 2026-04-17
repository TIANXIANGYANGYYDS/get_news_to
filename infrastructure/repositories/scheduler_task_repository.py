from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from pymongo import ReturnDocument

from domain.enums.tasks import TaskStatus, TaskType
from domain.models.scheduler_models import TaskRecord
from shared.base.repository import BaseMongoRepository


class SchedulerTaskRepository(BaseMongoRepository):
    collection_name = "scheduler_tasks"

    async def ensure_indexes(self):
        await self.collection.create_index("task_id", unique=True, name="uk_task_id")
        await self.collection.create_index([("status", 1), ("next_run_at", 1)], name="idx_status_next_run_at")
        await self.collection.create_index("lease_until", name="idx_lease_until")
        await self.collection.create_index("idempotency_key", unique=True, sparse=True, name="uk_idempotency_key")
        await self.collection.create_index([("task_name", 1), ("scheduled_for", 1)], name="idx_task_schedule")

    async def create_task(self, task: TaskRecord) -> TaskRecord:
        await self.upsert_one({"task_id": task.task_id}, task.to_dict())
        return task

    async def create_task_if_absent(
        self,
        *,
        task_name: str,
        task_type: TaskType,
        payload: dict,
        idempotency_key: str,
        source: str,
        timeout_seconds: int,
        max_retry_count: int,
        scheduled_for: datetime | None = None,
        parent_task_id: str | None = None,
    ) -> TaskRecord:
        now = datetime.utcnow()
        task_id = str(uuid4())
        doc = {
            "task_id": task_id,
            "task_name": task_name,
            "task_type": task_type.value,
            "status": TaskStatus.PENDING.value,
            "payload": payload,
            "source": source,
            "idempotency_key": idempotency_key,
            "retry_count": 0,
            "max_retry_count": max_retry_count,
            "recovery_count": 0,
            "max_recovery_count": 2,
            "timeout_seconds": timeout_seconds,
            "created_at": now,
            "next_run_at": now,
            "scheduled_for": scheduled_for,
            "parent_task_id": parent_task_id,
        }
        inserted = await self.collection.find_one_and_update(
            {"idempotency_key": idempotency_key},
            {"$setOnInsert": doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return TaskRecord.from_dict(inserted)

    async def claim_next_task(self, *, worker_id: str, lease_seconds: int) -> TaskRecord | None:
        now = datetime.utcnow()
        lease_until = now + timedelta(seconds=lease_seconds)
        claimed = await self.collection.find_one_and_update(
            {
                "$and": [
                    {"status": {"$in": [TaskStatus.PENDING.value, TaskStatus.QUEUED.value, TaskStatus.RETRYING.value]}},
                    {"$or": [{"next_run_at": None}, {"next_run_at": {"$lte": now}}]},
                ]
            },
            {
                "$set": {
                    "status": TaskStatus.RUNNING.value,
                    "started_at": now,
                    "heartbeat_at": now,
                    "lease_until": lease_until,
                    "worker_id": worker_id,
                    "error_message": None,
                }
            },
            sort=[("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        return TaskRecord.from_dict(claimed) if claimed else None

    async def heartbeat(self, *, task_id: str, worker_id: str, lease_seconds: int):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"task_id": task_id, "worker_id": worker_id, "status": TaskStatus.RUNNING.value},
            {"$set": {"heartbeat_at": now, "lease_until": now + timedelta(seconds=lease_seconds)}},
        )

    async def mark_succeeded(self, *, task_id: str, worker_id: str, duration_ms: int, payload: dict | None = None):
        now = datetime.utcnow()
        update = {
            "status": TaskStatus.SUCCEEDED.value,
            "finished_at": now,
            "duration_ms": duration_ms,
            "lease_until": None,
            "worker_id": worker_id,
            "heartbeat_at": now,
        }
        if payload is not None:
            update["result_payload"] = payload
        await self.collection.update_one({"task_id": task_id}, {"$set": update})

    async def mark_retrying(self, *, task: TaskRecord, error_message: str, next_run_at: datetime):
        await self.collection.update_one(
            {"task_id": task.task_id},
            {
                "$set": {
                    "status": TaskStatus.RETRYING.value,
                    "next_run_at": next_run_at,
                    "error_message": error_message,
                    "lease_until": None,
                    "worker_id": None,
                },
                "$inc": {"retry_count": 1},
            },
        )

    async def mark_failed(self, *, task: TaskRecord, status: TaskStatus, error_message: str):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"task_id": task.task_id},
            {
                "$set": {
                    "status": status.value,
                    "finished_at": now,
                    "error_message": error_message,
                    "lease_until": None,
                    "worker_id": None,
                }
            },
        )

    async def mark_dead_letter(self, *, task: TaskRecord, reason: str):
        now = datetime.utcnow()
        await self.collection.update_one(
            {"task_id": task.task_id},
            {
                "$set": {
                    "status": TaskStatus.DEAD_LETTER.value,
                    "finished_at": now,
                    "dead_letter_reason": reason,
                    "error_message": reason,
                    "lease_until": None,
                    "worker_id": None,
                }
            },
        )

    async def recover_stale_running_tasks(self, *, now: datetime) -> list[TaskRecord]:
        cursor = self.collection.find({"status": TaskStatus.RUNNING.value, "lease_until": {"$lt": now}})
        stale = [TaskRecord.from_dict(doc) async for doc in cursor]

        for task in stale:
            if task.recovery_count >= task.max_recovery_count:
                await self.mark_dead_letter(task=task, reason="lease expired and recovery limit reached")
            else:
                await self.collection.update_one(
                    {"task_id": task.task_id},
                    {
                        "$set": {
                            "status": TaskStatus.QUEUED.value,
                            "next_run_at": now,
                            "worker_id": None,
                            "lease_until": None,
                            "heartbeat_at": now,
                            "error_message": "recovered from stale running",
                        },
                        "$inc": {"recovery_count": 1},
                    },
                )
        return stale

    async def create_compensation_task(self, *, failed_task: TaskRecord, reason: str) -> TaskRecord:
        return await self.create_task_if_absent(
            task_name=failed_task.task_name,
            task_type=TaskType.COMPENSATION,
            payload={"compensate_for": failed_task.task_id, "reason": reason, **failed_task.payload},
            idempotency_key=f"compensate::{failed_task.task_id}",
            source="scheduler_recovery",
            timeout_seconds=failed_task.timeout_seconds,
            max_retry_count=max(1, failed_task.max_retry_count),
            parent_task_id=failed_task.task_id,
        )

    async def list_dead_letters(self, *, limit: int = 100) -> list[TaskRecord]:
        cursor = self.collection.find({"status": TaskStatus.DEAD_LETTER.value}).sort("finished_at", -1).limit(limit)
        return [TaskRecord.from_dict(doc) async for doc in cursor]
