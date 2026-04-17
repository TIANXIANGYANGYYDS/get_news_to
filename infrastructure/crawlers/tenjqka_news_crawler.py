from __future__ import annotations

from datetime import datetime, timezone, timedelta
import re

from bs4 import BeautifulSoup

from domain.enums.news import NewsSource
from domain.models.news_models import NewsEvent
from shared.base.crawler import BaseNewsCrawler

CN_TZ = timezone(timedelta(hours=8))


class TenjqkaNewsCrawler(BaseNewsCrawler):
    source_name = NewsSource.TENJQKA.value
    base_url = "https://news.10jqka.com.cn/realtimenews.html"

    def fetch(self, limit: int = 20) -> list[NewsEvent]:
        response = self.request("GET", self.base_url, headers={"User-Agent": "Mozilla/5.0"})
        response.encoding = response.apparent_encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        tokens = [x.strip() for x in soup.stripped_strings if x.strip()]
        events: list[NewsEvent] = []
        now = datetime.now(CN_TZ)

        for idx in range(len(tokens) - 2):
            if len(events) >= limit:
                break
            if not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", tokens[idx]):
                continue
            hms = tokens[idx] if len(tokens[idx]) == 8 else f"{tokens[idx]}:00"
            title = tokens[idx + 1]
            content = tokens[idx + 2]
            try:
                dt = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {hms}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
            except ValueError:
                continue
            publish_ts = int(dt.timestamp())
            event_id = self.deduplicate_key(publish_ts, title, content)
            events.append(
                NewsEvent(
                    event_id=f"tenjqka-{idx}-{event_id}",
                    source=NewsSource.TENJQKA,
                    title=title,
                    content=content,
                    published_at=dt,
                    publish_ts=publish_ts,
                    publish_time=hms,
                )
            )
        return events
