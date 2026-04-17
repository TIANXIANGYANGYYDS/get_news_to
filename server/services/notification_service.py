from __future__ import annotations

import hashlib

from domain.models.pipeline_models import NotificationPayload
from infrastructure.repositories.notification_repository import NotificationRepository
from shared.base.notifier import BaseNotifier


class NotificationService:
    def __init__(self, notifier: BaseNotifier, notification_repository: NotificationRepository):
        self.notifier = notifier
        self.notification_repository = notification_repository

    async def send_message(self, payload: NotificationPayload):
        dedup_key = hashlib.md5(f"{payload.title}|{payload.content}|{','.join(payload.channels)}".encode("utf-8")).hexdigest()
        reserved = await self.notification_repository.reserve_notification(
            notification_key=f"digest::{dedup_key}",
            payload=payload.to_dict(),
        )
        if not reserved:
            return
        await self.notifier.send(title=payload.title, content=payload.content)
