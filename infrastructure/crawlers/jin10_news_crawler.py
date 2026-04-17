from __future__ import annotations

from datetime import datetime, timezone, timedelta
import re

from bs4 import BeautifulSoup

from domain.enums.news import NewsSource
from domain.models.news_models import NewsEvent
from shared.base.crawler import BaseNewsCrawler

CN_TZ = timezone(timedelta(hours=8))


class Jin10NewsCrawler(BaseNewsCrawler):
    source_name = NewsSource.JIN10.value
    base_url = "https://www.jin10.com/"

    def fetch(self, limit: int = 20) -> list[NewsEvent]:
        response = self.request("GET", self.base_url, headers={"User-Agent": "Mozilla/5.0"})
        response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        text = " ".join(soup.stripped_strings)
        matches = re.findall(r"(\d{2}:\d{2}:\d{2})\s+([^\n]{8,120})", text)
        events: list[NewsEvent] = []
        now = datetime.now(CN_TZ)

        for idx, (hms, content) in enumerate(matches[:limit]):
            try:
                dt = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {hms}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
            except ValueError:
                continue
            publish_ts = int(dt.timestamp())
            event_id = self.deduplicate_key(publish_ts, "", content)
            events.append(
                NewsEvent(
                    event_id=f"jin10-{idx}-{event_id}",
                    source=NewsSource.JIN10,
                    title="",
                    content=content,
                    published_at=dt,
                    publish_ts=publish_ts,
                    publish_time=hms,
                )
            )
        return events
