"""
卡片构建层 card_builder
负责把分析结果组装成飞书卡片 JSON。
"""
from .notifier import FeishuNotifier

__all__ = ["FeishuNotifier"]