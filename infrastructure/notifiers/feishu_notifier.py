from __future__ import annotations

from typing import Any

import httpx

from shared.base.notifier import BaseNotifier


class FeishuCardBuilder:
    def build_text_card(self, title: str, content: str) -> dict[str, Any]:
        return {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": content}],
            },
        }


class FeishuNotifier(BaseNotifier):
    def __init__(self, *, app_id: str, app_secret: str, chat_id: str, bot_name: str, card_builder: FeishuCardBuilder | None = None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.bot_name = bot_name
        self.card_builder = card_builder or FeishuCardBuilder()

    async def send(self, title: str, content: str, extra: dict[str, Any] | None = None) -> None:
        if not self.chat_id:
            return
        # lightweight/no-auth webhook-style placeholder for integration point
        payload = self.card_builder.build_text_card(title=title, content=content)
        if extra:
            payload["extra"] = extra
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post("https://open.feishu.cn/open-apis/im/v1/messages", json=payload)
