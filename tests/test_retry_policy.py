from domain.models.scheduler_models import RetryPolicy
from domain.policies.retry_policy import should_retry


def test_should_retry_retryable_network_error():
    policy = RetryPolicy(max_retries=3)
    assert should_retry("network timeout from upstream", retry_count=1, policy=policy)


def test_should_not_retry_when_limit_reached():
    policy = RetryPolicy(max_retries=1)
    assert not should_retry("network timeout", retry_count=1, policy=policy)
