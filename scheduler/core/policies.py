from datetime import datetime

from domain.enums.tasks import TaskStatus
from domain.models.scheduler_models import RetryPolicy, TaskRecord
from domain.policies.retry_policy import should_retry


def classify_terminal_status(error_message: str) -> TaskStatus:
    lowered = (error_message or "").lower()
    if "timeout" in lowered:
        return TaskStatus.TIMED_OUT
    return TaskStatus.FAILED


def should_move_dead_letter(task: TaskRecord) -> bool:
    return task.retry_count >= task.max_retry_count


def compute_retry_at(task: TaskRecord, policy: RetryPolicy, now: datetime) -> datetime:
    return policy.next_retry_at(task.retry_count + 1, now)


def can_retry(task: TaskRecord, error_message: str, policy: RetryPolicy) -> bool:
    return should_retry(error_message, task.retry_count, policy)
