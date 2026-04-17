from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from domain.models.pipeline_models import MorningReadingPayload
from shared.base.crawler import BaseCrawler


class MorningReadingCrawler(BaseCrawler):
    source_name = "morning_reading"

    def fetch(self, limit: int = 0, date: str | None = None) -> MorningReadingPayload:
        date_key = date or datetime.now().strftime("%Y%m%d")
        url = f"https://stock.10jqka.com.cn/zaopan/{date_key}.shtml"
        response = self.request("GET", url, headers={"User-Agent": "Mozilla/5.0"})
        response.encoding = "gbk"
        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        date_matches = re.findall(r'Global\.date\s*=\s*"(\d{8})"', html)
        parsed_date = date_matches[-1] if date_matches else date_key
        display_date = f"{parsed_date[:4]}-{parsed_date[4:6]}-{parsed_date[6:8]}"

        main_block = soup.find("div", id="block_2125")
        raw_content = main_block.get_text("\n", strip=True) if main_block else ""
        sections = self._split_sections(raw_content)

        return MorningReadingPayload(
            date=display_date,
            source_type=self.source_name,
            raw_content=raw_content,
            sections=sections,
        )

    @staticmethod
    def _split_sections(content: str) -> dict[str, str]:
        title_mapping = {
            "【隔夜海外行情动态】": "overseas",
            "【昨日国内行情回顾】": "domestic",
            "【重大新闻汇总】": "major_news",
            "【公司公告】": "company_announcements",
            "【券商观点】": "broker_views",
            "【今日重点关注的财经数据与事件】": "calendar",
        }
        result = {
            "head": [],
            "overseas": [],
            "domestic": [],
            "major_news": [],
            "company_announcements": [],
            "broker_views": [],
            "calendar": [],
        }
        current_key = "head"

        for line in content.splitlines():
            clean = line.strip()
            if not clean:
                continue
            for title, key in title_mapping.items():
                if title in clean:
                    current_key = key
                    break
            else:
                result[current_key].append(clean)

        return {key: "\n".join(value).strip() for key, value in result.items()}
