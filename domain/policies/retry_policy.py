from domain.models.scheduler_models import RetryPolicy


def should_retry(error_message: str, retry_count: int, policy: RetryPolicy) -> bool:
    lowered = (error_message or "").lower()
    if retry_count >= policy.max_retries:
        return False
    return any(keyword in lowered for keyword in policy.retryable_errors)
