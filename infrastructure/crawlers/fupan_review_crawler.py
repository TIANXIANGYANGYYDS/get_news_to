from __future__ import annotations

import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from domain.models.pipeline_models import FupanReviewPayload
from shared.base.crawler import BaseCrawler


class FupanReviewCrawler(BaseCrawler):
    source_name = "fupan_review"

    def fetch(self, limit: int = 0, date: str | None = None) -> FupanReviewPayload:
        date_key = date or (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        url = f"https://stock.10jqka.com.cn/fupan/{date_key}.shtml"
        response = self.request("GET", url, headers={"User-Agent": "Mozilla/5.0"})
        response.encoding = response.apparent_encoding or "utf-8"
        content = self._extract_visible_text(response.text)
        return FupanReviewPayload(date=date_key, source_type=self.source_name, url=url, content=content)

    @staticmethod
    def _extract_visible_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")

        def clean_text(text: str) -> str:
            text = text.replace("\xa0", " ")
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()

        content_blocks: list[str] = []
        for selector in ["div.header", "div.container", "div.footer"]:
            node = soup.select_one(selector)
            if node:
                text = clean_text(node.get_text("\n", strip=True))
                if text:
                    content_blocks.append(text)

        deduped: list[str] = []
        seen: set[str] = set()
        for block in content_blocks:
            key = re.sub(r"\s+", " ", block)
            if key not in seen:
                seen.add(key)
                deduped.append(block)

        return "\n\n".join(deduped)
