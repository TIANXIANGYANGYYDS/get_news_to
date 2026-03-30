"""
调度层 scheduler
负责每天定时触发一次任务。
不要把业务逻辑塞进 scheduler 里，scheduler 只负责“何时执行”。
"""

from .daily_scheduler import DailyScheduler

__all__ = ["DailyScheduler"]