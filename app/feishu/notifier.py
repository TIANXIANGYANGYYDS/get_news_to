import json
import time
from typing import Any, Optional

import aiohttp

from app.logger import get_logger


logger = get_logger("feishu.notifier")


class FeishuNotifier:
    TENANT_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MESSAGE_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

    def __init__(self, app_id: str, app_secret: str, chat_id: str, bot_name: str = "daily_pe_reporter"):
        if not app_id:
            raise ValueError("FEISHU_APP_ID is empty")
        if not app_secret:
            raise ValueError("FEISHU_APP_SECRET is empty")
        if not chat_id:
            raise ValueError("FEISHU_CHAT_ID is empty")

        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.bot_name = bot_name

        self._session: Optional[aiohttp.ClientSession] = None
        self._tenant_access_token: Optional[str] = None
        self._token_expire_at: float = 0.0

    async def startup(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
            logger.info("feishu session started")

    async def shutdown(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("feishu session closed")

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            await self.startup()
        assert self._session is not None
        return self._session

    def _is_token_valid(self) -> bool:
        if not self._tenant_access_token:
            return False
        return time.time() < self._token_expire_at

    async def get_tenant_access_token(self) -> str:
        if self._is_token_valid():
            return self._tenant_access_token  # type: ignore[return-value]

        session = await self._ensure_session()

        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8"
        }

        async with session.post(self.TENANT_ACCESS_TOKEN_URL, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"get tenant_access_token http failed: status={resp.status}, body={text}")

            data = json.loads(text)

        if data.get("code") != 0:
            raise RuntimeError(f"get tenant_access_token failed: {data}")

        token = data["tenant_access_token"]
        expire = int(data.get("expire", 7200))

        self._tenant_access_token = token
        self._token_expire_at = time.time() + max(expire - 60, 60)

        logger.info("feishu tenant_access_token refreshed")
        return token

    @staticmethod
    def _dump_compact_json(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    async def send_text(self, text: str) -> dict:
        token = await self.get_tenant_access_token()
        session = await self._ensure_session()

        payload = {
            "receive_id": self.chat_id,
            "msg_type": "text",
            "content": self._dump_compact_json({"text": text}),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        async with session.post(self.MESSAGE_SEND_URL, json=payload, headers=headers) as resp:
            text_body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"send text http failed: status={resp.status}, body={text_body}")

            data = json.loads(text_body)

        if data.get("code") != 0:
            raise RuntimeError(f"send text failed: {data}")

        logger.info("feishu text sent")
        return data

    async def send_card(self, card_json: dict) -> dict:
        token = await self.get_tenant_access_token()
        session = await self._ensure_session()

        payload = {
            "receive_id": self.chat_id,
            "msg_type": "interactive",
            "content": self._dump_compact_json(card_json),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        logger.info("sending feishu interactive card")

        async with session.post(self.MESSAGE_SEND_URL, json=payload, headers=headers) as resp:
            text_body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"send card http failed: status={resp.status}, body={text_body}")

            data = json.loads(text_body)

        if data.get("code") != 0:
            raise RuntimeError(f"send card failed: {data}")

        logger.info("feishu card sent successfully")
        return data