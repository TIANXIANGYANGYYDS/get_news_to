from enum import Enum


class TaskType(str, Enum):
    SCHEDULED = "scheduled"
    ON_DEMAND = "on_demand"
    COMPENSATION = "compensation"
    MANUAL = "manual"
    AGGREGATION = "aggregation"
    NOTIFICATION = "notification"
    BACKFILL = "backfill"


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    DEAD_LETTER = "dead_letter"
