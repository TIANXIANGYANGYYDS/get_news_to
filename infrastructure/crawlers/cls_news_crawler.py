from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from domain.enums.news import NewsSource
from domain.models.news_models import NewsEvent
from shared.base.crawler import BaseNewsCrawler


CN_TZ = timezone(timedelta(hours=8))


class CLSNewsCrawler(BaseNewsCrawler):
    source_name = NewsSource.CLS.value
    base_url = "https://www.cls.cn/nodeapi/telegraphList"

    def _build_params(self, limit: int) -> dict[str, Any]:
        return {
            "app": "CailianpressWeb",
            "os": "web",
            "refresh_type": "1",
            "rn": str(limit),
        }

    def fetch(self, limit: int = 20) -> list[NewsEvent]:
        response = self.request("GET", self.base_url, params=self._build_params(limit), headers={"User-Agent": "Mozilla/5.0"})
        payload = response.json()
        items = payload.get("data", {}).get("roll_data", [])
        events: list[NewsEvent] = []

        for item in items:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            publish_ts, publish_time = self.parse_timestamp(item.get("ctime") or item.get("time"))
            if not publish_ts:
                continue
            event_id = str(item.get("id") or self.deduplicate_key(publish_ts, item.get("title") or "", content))
            published_at = datetime.fromtimestamp(publish_ts, tz=CN_TZ)
            events.append(
                NewsEvent(
                    event_id=event_id,
                    source=NewsSource.CLS,
                    title=(item.get("title") or "").strip(),
                    content=content,
                    published_at=published_at,
                    publish_ts=publish_ts,
                    publish_time=publish_time,
                    subject_names=[x.get("subject_name") for x in (item.get("subjects") or []) if x.get("subject_name")],
                )
            )

        return events
