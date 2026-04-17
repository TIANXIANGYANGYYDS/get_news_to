class AppError(Exception):
    pass


class RetryableError(AppError):
    pass


class NonRetryableError(AppError):
    pass


class TimeoutError(AppError):
    pass
